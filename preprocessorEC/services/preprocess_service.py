"""Preprocess service -- Phase 3 business logic.

Unified CCX duplicate detection + Infor cascading/residue matching +
3-source item labeling + buy-UOM pre-computation.

Pipeline:  SKU match -> similarity -> review -> Infor cascade ->
           Infor residue -> item labeling -> finalise.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..db import task_repo, workstate_repo
from ..db.engine import get_sqlserver_engine
from ..db.sql_loader import load_query
from ..common.utils import reduce_catalog_number
from ..state import TaskStateMachine, Phase, Status
from .scoring import (
    calculate_confidence_score,
    determine_pair_type,
    compute_similarities_batch,
    bucket_score,
)
from .llm_review import review_match_pair

logger = logging.getLogger(__name__)

# MHS org EID (matches all orgs)
MHS_ORG_EID = "105188574"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _sql_session() -> Session:
    return Session(get_sqlserver_engine())


def _determine_contract_type(items: list) -> str:
    """Heuristic: if any item has a vendor_catalog_num != mfg_catalog_num -> distributor.
    Default to MANUFACTURER."""
    for it in items:
        vpn = getattr(it, "vendor_catalog_num", None) or ""
        mfg = getattr(it, "mfg_catalog_num", None) or ""
        if vpn and mfg and vpn.strip().upper() != mfg.strip().upper():
            return "DISTRIBUTOR_PREMIER"
    return "MANUFACTURER"


# ---------------------------------------------------------------------------
# Step 1 -- CCX SKU Matching
# ---------------------------------------------------------------------------
def run_sku_matching(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Match INPUT items against CCXSyncedContractLine via reduced SKU.

    Deletes any previous match results first (supports clean reruns).
    Uses multi-factor scoring with pair-type awareness.
    Returns summary: {matched_count, total_items, contracts_found}.
    """
    state = state_machine.get_state(task_id)
    state["status"] = Status.PREPROCESSING
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.PREPROCESSING)

    # Delete previous results for a clean rerun
    task_repo.delete_match_results(task_id)

    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    if not input_items:
        return {"matched_count": 0, "total_items": 0}

    task = task_repo.get_task(task_id)
    process_type = (task.process_type or "").upper()
    is_distributor = "DISTRIBUTOR" in process_type
    precheck_mode = task.precheck_mode or "default"

    contract_type = _determine_contract_type(input_items)
    query_map = {
        "MANUFACTURER": "ccx_match_manufacturer",
        "DISTRIBUTOR_PREMIER": "ccx_match_distributor_premier",
        "DISTRIBUTOR_LOCAL": "ccx_match_distributor_local",
    }
    query_name = query_map.get(contract_type, "ccx_match_manufacturer")
    query = load_query("preprocess", "dup_detection", query=query_name)

    # all items in a task share the same org
    org_eid = getattr(input_items[0], "organization_eid", None) or MHS_ORG_EID

    all_matches = []
    with _sql_session() as sess:
        for item in input_items:
            reduced_mfg = reduce_catalog_number(item.mfg_catalog_num)
            reduced_vpn = reduce_catalog_number(item.vendor_catalog_num)

            if not reduced_mfg and not reduced_vpn:
                continue

            params = {
                "reduced_mfg_num": reduced_mfg or "",
                "reduced_vendor_num": reduced_vpn or "",
                "org_eid": org_eid,
            }
            rows = sess.execute(query, params).mappings().all()

            for row in rows:
                # Determine pair type for this match
                pt = determine_pair_type(
                    task_contract_number=task.contract_number or "",
                    task_process_type=process_type,
                    task_contract_manufacturer=task.contract_manufacturer_infor or "",
                    task_vendor_id=task.vendor_id or "",
                    match_contract_id=row.get("ContractID", ""),
                    match_contract_manufacturer=row.get("contract_manufacturer", ""),
                    match_erp_vendor_id=row.get("ERPVendorID", ""),
                )

                # Multi-factor scoring
                scores = calculate_confidence_score(
                    mfn_input=item.mfg_catalog_num or "",
                    mfn_match=row.get("mfg_catalog_num_ccx", ""),
                    desc_input=item.description or "",
                    desc_match=row.get("description_ccx", ""),
                    uom_input=item.uom or "",
                    uom_match=row.get("uom_ccx", ""),
                    qoe_input=item.qoe,
                    qoe_match=row.get("qoe_ccx", ""),
                    price_input=item.unit_price,
                    price_match=row.get("unit_price_ccx", ""),
                    vpn_input=item.vendor_catalog_num or "",
                    vpn_match=row.get("vendor_catalog_num_ccx", ""),
                    pair_type=pt,
                    precheck_mode=precheck_mode,
                    cn_input=task.contract_number or "",
                    cn_match=row.get("ContractID", ""),
                )

                # matched_item_ref: mfg+UOM for manufacturer, vendor+UOM for distributor
                if is_distributor:
                    ref = f"{row.get('vendor_catalog_num_ccx', '')}|{row.get('uom_ccx', '')}"
                else:
                    ref = f"{row.get('mfg_catalog_num_ccx', '')}|{row.get('uom_ccx', '')}"

                match_type = row.get("match_type", "REDUCED_MFG")
                bucket = scores["similarity_bucket"]

                all_matches.append({
                    "input_item_id": item.item_id,
                    "matched_source": "CCX",
                    "matched_item_ref": ref,
                    "similarity_score": scores["similarity_score"],
                    "similarity_bucket": bucket,
                    "match_status": "ACCEPTED" if bucket == "HIGH" else "PENDING",
                    "contract_number": row.get("ContractID", ""),
                    "match_type": match_type,
                    "ccx_pkid": row.get("CCX_pkid"),
                    "pair_type": pt,
                    "mfn_score": scores["mfn_score"],
                    "mfn_complexity": scores["mfn_complexity"],
                    "uom_score": scores["uom_score"],
                    "qoe_score": scores["qoe_score"],
                    "price_score": scores["price_score"],
                    "price_diff_pct": scores["price_diff_pct"],
                    "desc_score": scores["desc_score"],
                    "weighted_score": scores["weighted_score"],
                    "match_ea_price": scores["match_ea_price"],
                    "input_ea_price": scores["input_ea_price"],
                    "vendor_item_score": scores["vendor_item_score"],
                })

    if all_matches:
        task_repo.add_match_results_bulk(task_id, all_matches)

    # Store in workstate for quick access
    state["ccx_matches"] = [
        {"input_item_id": m["input_item_id"], "ccx_pkid": m["ccx_pkid"],
         "contract": m["contract_number"], "bucket": m["similarity_bucket"],
         "status": m["match_status"]}
        for m in all_matches
    ]
    state_machine.save_state(task_id, state)

    contracts = set(m["contract_number"] for m in all_matches if m["contract_number"])
    return {
        "matched_count": len(all_matches),
        "total_items": len(input_items),
        "contracts_found": len(contracts),
    }


# ---------------------------------------------------------------------------
# Step 2 -- CCX contract-level review routing
# ---------------------------------------------------------------------------
def run_contract_check(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Group CCX matches by contract for human review."""
    grouped = task_repo.get_match_results_by_contract(task_id)
    contract_summaries = []
    for contract_id, matches in grouped.items():
        if contract_id == "__no_contract__":
            continue
        n_high = sum(1 for m in matches if m.similarity_bucket == "HIGH")
        n_med = sum(1 for m in matches if m.similarity_bucket == "MED")
        n_low = sum(1 for m in matches if m.similarity_bucket == "LOW")
        contract_summaries.append({
            "contract_id": contract_id,
            "total_lines": len(matches),
            "high": n_high,
            "med": n_med,
            "low": n_low,
        })

    state = state_machine.get_state(task_id)
    state["contract_review"] = contract_summaries
    state["status"] = Status.REVIEW_CONTRACTS
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.REVIEW_CONTRACTS)

    return {"contracts": contract_summaries}


# ---------------------------------------------------------------------------
# Step 3 -- LLM review for MED/LOW matches
# ---------------------------------------------------------------------------
def run_llm_review(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Send MED/LOW CCX matches to the LLM for review.

    Updates match_status to ACCEPTED or REJECTED based on LLM verdict.
    """
    state = state_machine.get_state(task_id)
    state["status"] = Status.LLM_REVIEW
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.LLM_REVIEW)

    pending_matches = [
        m for m in task_repo.get_match_results(task_id, matched_source="CCX")
        if m.match_status == "PENDING" and m.similarity_bucket in ("MED", "LOW")
    ]

    if not pending_matches:
        return {"reviewed": 0}

    # build item lookup
    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    item_by_id = {it.item_id: it for it in input_items}

    reviewed = 0
    for match in pending_matches:
        item = item_by_id.get(match.input_item_id)
        if not item:
            continue

        input_dict = {
            "description": item.description or "",
            "mfg_catalog_num": item.mfg_catalog_num or "",
            "vendor_catalog_num": item.vendor_catalog_num or "",
            "uom": item.uom or "",
        }
        match_dict = {
            "matched_source": match.matched_source,
            "description": match.matched_item_ref or "",
            "matched_item_ref": match.matched_item_ref or "",
            "uom": "",
            "similarity_score": match.similarity_score,
        }
        result = review_match_pair(input_dict, match_dict)
        new_status = "ACCEPTED" if result["decision"] == "ACCEPT" else "REJECTED"
        task_repo.update_match_decision(match.match_id, new_status, "LLM")
        reviewed += 1

    return {"reviewed": reviewed}


# ---------------------------------------------------------------------------
# Step 4 -- Infor Cascade (via accepted CCX pkids)
# ---------------------------------------------------------------------------
def run_infor_cascade(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Fetch Infor contract lines linked to accepted CCX matches.

    Uses CCX_pkid to find corresponding Infor rows in
    InforActiveCLRefCCXSyncedCL.
    """
    state = state_machine.get_state(task_id)
    state["status"] = Status.INFOR_MATCHING
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.INFOR_MATCHING)

    accepted_pkids = task_repo.get_accepted_ccx_pkids(task_id)
    if not accepted_pkids:
        return {"infor_lines": 0}

    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    org_eid = getattr(input_items[0], "organization_eid", None) or MHS_ORG_EID if input_items else MHS_ORG_EID

    task = task_repo.get_task(task_id)
    is_distributor = "DISTRIBUTOR" in (task.process_type or "").upper()

    query = load_query("preprocess", "item_matching", query="infor_cascade_by_ccx_pkids")

    infor_matches = []
    with _sql_session() as sess:
        # SQLAlchemy text() with IN requires expanding bindparam
        from sqlalchemy import bindparam
        bound_query = query.bindparams(bindparam("ccx_pkids", expanding=True))
        rows = sess.execute(bound_query, {"ccx_pkids": accepted_pkids, "org_eid": org_eid}).mappings().all()

        # Map CCX_pkid -> input_item_id via accepted match results
        ccx_to_input = {}
        for m in task_repo.get_match_results(task_id, matched_source="CCX"):
            if m.match_status == "ACCEPTED" and m.ccx_pkid:
                ccx_to_input[m.ccx_pkid] = m.input_item_id

        for row in rows:
            input_item_id = ccx_to_input.get(row["CCX_pkid"])
            if not input_item_id:
                continue

            # matched_item_ref: mfg+UOM for manufacturer, vendor+UOM for distributor
            if is_distributor:
                ref = f"{row.get('vendor_catalog_num_infor', '')}|{row.get('uom_infor', '')}"
            else:
                ref = f"{row.get('mfg_catalog_num_infor', '')}|{row.get('uom_infor', '')}"

            infor_matches.append({
                "input_item_id": input_item_id,
                "matched_source": "INFOR_CL",
                "matched_item_ref": ref,
                "contract_number": row.get("ContractID", ""),
                "match_type": "CASCADE",
                "infor_pkid": row.get("Infor_pkid", ""),
                "ccx_pkid": row.get("CCX_pkid"),
                "match_status": "ACCEPTED",
                "similarity_score": None,
                "similarity_bucket": "HIGH",
            })

    if infor_matches:
        task_repo.add_match_results_bulk(task_id, infor_matches)

    state["infor_cl_matches"] = [
        {"input_item_id": m["input_item_id"], "infor_pkid": m["infor_pkid"],
         "contract": m["contract_number"]}
        for m in infor_matches
    ]
    state_machine.save_state(task_id, state)

    return {"infor_lines": len(infor_matches)}


# ---------------------------------------------------------------------------
# Step 5 -- Infor Residue Matching (CCX_pkid IS NULL)
# ---------------------------------------------------------------------------
def run_infor_residue(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Match INPUT items against Infor lines that have no CCX counterpart.

    These are Infor-only contract lines (CCX_pkid IS NULL).
    Uses multi-factor scoring; all Infor residue matches are pair-type D.
    """
    state = state_machine.get_state(task_id)
    state["status"] = Status.INFOR_MATCHING
    state_machine.save_state(task_id, state)

    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    if not input_items:
        return {"residue_matches": 0}

    task = task_repo.get_task(task_id)
    process_type = (task.process_type or "").upper()
    is_distributor = "DISTRIBUTOR" in process_type
    precheck_mode = task.precheck_mode or "default"

    org_eid = getattr(input_items[0], "organization_eid", None) or MHS_ORG_EID
    query = load_query("preprocess", "item_matching", query="infor_residue_match")

    residue_matches = []
    with _sql_session() as sess:
        for item in input_items:
            reduced_mfg = reduce_catalog_number(item.mfg_catalog_num)
            reduced_vpn = reduce_catalog_number(item.vendor_catalog_num)
            if not reduced_mfg and not reduced_vpn:
                continue

            params = {
                "reduced_mfg_num": reduced_mfg or "",
                "reduced_vendor_num": reduced_vpn or "",
                "org_eid": org_eid,
            }
            rows = sess.execute(query, params).mappings().all()

            if not rows:
                continue

            for row in rows:
                # All Infor residue matches are pair-type D
                scores = calculate_confidence_score(
                    mfn_input=item.mfg_catalog_num or "",
                    mfn_match=row.get("mfg_catalog_num_infor", ""),
                    desc_input=item.description or "",
                    desc_match=row.get("description", "") or "",
                    uom_input=item.uom or "",
                    uom_match=row.get("uom_infor", ""),
                    qoe_input=item.qoe,
                    qoe_match=row.get("qoe_infor", ""),
                    price_input=item.unit_price,
                    price_match=row.get("unit_price_infor", ""),
                    vpn_input=item.vendor_catalog_num or "",
                    vpn_match=row.get("vendor_catalog_num_infor", ""),
                    pair_type="D",
                    precheck_mode=precheck_mode,
                    cn_input=task.contract_number or "",
                    cn_match=row.get("ContractID", ""),
                )

                # matched_item_ref: mfg+UOM for manufacturer, vendor+UOM for distributor
                if is_distributor:
                    ref = f"{row.get('vendor_catalog_num_infor', '')}|{row.get('uom_infor', '')}"
                else:
                    ref = f"{row.get('mfg_catalog_num_infor', '')}|{row.get('uom_infor', '')}"

                bucket = scores["similarity_bucket"]
                residue_matches.append({
                    "input_item_id": item.item_id,
                    "matched_source": "INFOR_CL",
                    "matched_item_ref": ref,
                    "similarity_score": scores["similarity_score"],
                    "similarity_bucket": bucket,
                    "match_status": "ACCEPTED" if bucket == "HIGH" else "PENDING",
                    "contract_number": row.get("ContractID", ""),
                    "match_type": row.get("match_type", "REDUCED_MFG"),
                    "infor_pkid": row.get("Infor_pkid", ""),
                    "ccx_pkid": None,
                    "pair_type": "D",
                    "mfn_score": scores["mfn_score"],
                    "mfn_complexity": scores["mfn_complexity"],
                    "uom_score": scores["uom_score"],
                    "qoe_score": scores["qoe_score"],
                    "price_score": scores["price_score"],
                    "price_diff_pct": scores["price_diff_pct"],
                    "desc_score": scores["desc_score"],
                    "weighted_score": scores["weighted_score"],
                    "match_ea_price": scores["match_ea_price"],
                    "input_ea_price": scores["input_ea_price"],
                    "vendor_item_score": scores["vendor_item_score"],
                })

    if residue_matches:
        task_repo.add_match_results_bulk(task_id, residue_matches)

    state["infor_residue_matches"] = [
        {"input_item_id": m["input_item_id"], "infor_pkid": m["infor_pkid"],
         "bucket": m["similarity_bucket"], "status": m["match_status"]}
        for m in residue_matches
    ]
    state_machine.save_state(task_id, state)

    return {"residue_matches": len(residue_matches)}


# ---------------------------------------------------------------------------
# Step 6 -- LLM review for Infor residue MED/LOW
# ---------------------------------------------------------------------------
def run_infor_residue_llm_review(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Send MED/LOW Infor residue matches to LLM, same pattern as CCX LLM review."""
    pending = [
        m for m in task_repo.get_match_results(task_id, matched_source="INFOR_CL")
        if m.match_status == "PENDING" and m.similarity_bucket in ("MED", "LOW")
    ]
    if not pending:
        return {"reviewed": 0}

    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    item_by_id = {it.item_id: it for it in input_items}

    reviewed = 0
    for match in pending:
        item = item_by_id.get(match.input_item_id)
        if not item:
            continue
        input_dict = {
            "description": item.description or "",
            "mfg_catalog_num": item.mfg_catalog_num or "",
            "vendor_catalog_num": item.vendor_catalog_num or "",
            "uom": item.uom or "",
        }
        match_dict = {
            "matched_source": match.matched_source,
            "description": match.matched_item_ref or "",
            "matched_item_ref": match.matched_item_ref or "",
            "uom": "",
            "similarity_score": match.similarity_score,
        }
        result = review_match_pair(input_dict, match_dict)
        new_status = "ACCEPTED" if result["decision"] == "ACCEPT" else "REJECTED"
        task_repo.update_match_decision(match.match_id, new_status, "LLM")
        reviewed += 1

    return {"reviewed": reviewed}


# ---------------------------------------------------------------------------
# Step 7 -- 3-Source Item# Labeling + Buy UOM
# ---------------------------------------------------------------------------
def run_item_labeling(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Label each INPUT item with Infor Item# from 3 sources + buy UOM options.

    Source 1: MDM_ITEM (Manufacturer + ManufacturerNumber)
    Source 2: MDM_VENDORITEM (Vendor + VendorItem)
    Source 3: Infor CL match (from accepted INFOR_CL match results)

    If all 3 agree -> item_labeled. If conflict -> MULTI_ITEM_ERROR.
    """
    state = state_machine.get_state(task_id)
    state["status"] = Status.ITEM_LABELING
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.ITEM_LABELING)

    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    if not input_items:
        return {"labeled": 0}

    q_mdm_item = load_query("preprocess", "item_matching", query="item_label_mdm_item")
    q_mdm_vi = load_query("preprocess", "item_matching", query="item_label_mdm_vendoritem")
    q_uom = load_query("preprocess", "item_matching", query="item_uom_options")

    # Pre-build accepted INFOR_CL matches by input_item_id
    infor_matches = task_repo.get_match_results(task_id, matched_source="INFOR_CL")
    infor_items_by_input = {}
    for m in infor_matches:
        if m.match_status == "ACCEPTED" and m.matched_item_ref:
            infor_items_by_input.setdefault(m.input_item_id, []).append(m.matched_item_ref)

    labeled_count = 0
    updates = []

    with _sql_session() as sess:
        for item in input_items:
            update = {"item_id": item.item_id}

            # Source 1: MDM_ITEM
            mfg_code = item.contract_manufacturer or item.manufacturer_infor or ""
            mfg_num = item.mfg_catalog_num or ""
            if mfg_code and mfg_num:
                rows = sess.execute(q_mdm_item, {"manufacturer": mfg_code, "mfg_catalog_num": mfg_num}).mappings().all()
                if rows:
                    update["infor_item_1"] = rows[0]["Item"]
                    update["infor_item_1_active"] = rows[0]["Active"]

            # Source 2: MDM_VENDORITEM
            v_id = item.vendor_id_short or ""
            vpn = item.vendor_catalog_num or ""
            if v_id and vpn:
                rows = sess.execute(q_mdm_vi, {"vendor_id": v_id, "vendor_catalog_num": vpn}).mappings().all()
                if rows:
                    update["infor_item_2"] = rows[0]["Item"]
                    update["infor_item_2_active"] = rows[0]["Active"]

            # Source 3: Infor CL match
            infor_refs = infor_items_by_input.get(item.item_id, [])
            if infor_refs:
                unique_refs = sorted(set(infor_refs))
                update["infor_item_3"] = ", ".join(unique_refs[:5])  # cap at 5
                update["infor_item_3_active"] = "Y"  # from active CL table

            # Determine consensus
            items_found = set()
            for key in ("infor_item_1", "infor_item_2", "infor_item_3"):
                val = update.get(key)
                if val:
                    for v in val.split(", "):
                        items_found.add(v.strip())

            if len(items_found) == 0:
                update["status"] = Status.NO_MATCH
            elif len(items_found) == 1:
                final_item = items_found.pop()
                update["infor_item_number"] = final_item
                update["status"] = Status.ITEM_LABELED

                # Look up buy UOM options
                uom_rows = sess.execute(q_uom, {"item_number": final_item}).mappings().all()
                if uom_rows:
                    uom_opts = [f"{r['UOM']}*{r['UOMConversion']}" for r in uom_rows]
                    update["infor_buy_uom_options"] = ", ".join(uom_opts)
            else:
                # Multiple different Item# -- flag for human review
                update["infor_item_number"] = ", ".join(sorted(items_found))
                update["status"] = Status.MULTI_ITEM_ERROR

            updates.append(update)
            labeled_count += 1

    # Bulk update items
    if updates:
        task_repo.update_items_bulk(updates)

    state["item_labeling_done"] = True
    state_machine.save_state(task_id, state)

    return {"labeled": labeled_count}


# ---------------------------------------------------------------------------
# Full Pipeline Orchestration
# ---------------------------------------------------------------------------
def _llm_step_skipped(reason: str = "LLM review disabled") -> dict:
    return {"reviewed": 0, "skipped": True, "reason": reason}


def run_full_preprocess(
    task_id: str,
    state_machine: TaskStateMachine,
    enable_llm: bool = True,
) -> dict:
    """Run the complete preprocess pipeline.

    1. CCX SKU matching + similarity
    2. Contract-level review routing
    3. LLM review for MED/LOW CCX matches
    4. Infor cascade (via accepted CCX pkids)
    5. Infor residue matching + LLM review
    6. 3-source Item# labeling + buy UOM

    Returns aggregated results dict.
    """
    results = {}
    results["sku_matching"] = run_sku_matching(task_id, state_machine)
    results["contract_check"] = run_contract_check(task_id, state_machine)
    if enable_llm:
        results["llm_review_ccx"] = run_llm_review(task_id, state_machine)
    else:
        results["llm_review_ccx"] = _llm_step_skipped()
    results["infor_cascade"] = run_infor_cascade(task_id, state_machine)
    results["infor_residue"] = run_infor_residue(task_id, state_machine)
    if enable_llm:
        results["llm_review_infor"] = run_infor_residue_llm_review(task_id, state_machine)
    else:
        results["llm_review_infor"] = _llm_step_skipped()
    results["item_labeling"] = run_item_labeling(task_id, state_machine)
    return results


# ---------------------------------------------------------------------------
# Review decisions (human-in-the-loop)
# ---------------------------------------------------------------------------
def submit_contract_decision(
    task_id: str,
    contract_number: str,
    include: bool,
    decided_by: str,
    state_machine: TaskStateMachine,
) -> dict:
    """Accept or reject all matches under a contract."""
    grouped = task_repo.get_match_results_by_contract(task_id)
    matches = grouped.get(contract_number, [])
    decision = "ACCEPTED" if include else "REJECTED"
    for m in matches:
        task_repo.update_match_decision(m.match_id, decision, decided_by)

    state = state_machine.get_state(task_id)
    state["ccx_decisions_done"] = True
    state_machine.save_state(task_id, state)

    return {"contract_number": contract_number, "decision": decision, "affected": len(matches)}


def submit_item_decision(
    task_id: str,
    match_id: int,
    decision: str,
    decided_by: str,
    state_machine: TaskStateMachine,
) -> dict:
    """Accept, reject, or send-to-LLM for an individual match."""
    task_repo.update_match_decision(match_id, decision, decided_by)

    state = state_machine.get_state(task_id)
    state["infor_decisions_done"] = True
    state_machine.save_state(task_id, state)

    return {"match_id": match_id, "decision": decision}


def finalize_preprocess(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """Mark preprocess complete and advance to DEDUP phase."""
    state = state_machine.get_state(task_id)
    state["status"] = Status.PREPROCESSED
    state_machine.save_state(task_id, state)

    new_state = state_machine.advance(
        task_id, Phase.DEDUP, changed_by=user, notes="Preprocess complete, advancing to Dedup"
    )
    return {"phase": new_state["phase"], "status": new_state["status"]}
