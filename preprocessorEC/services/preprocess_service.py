"""Preprocess service -- Phase 3 business logic.

Unified CCX duplicate detection + Infor cascading/residue matching +
3-source item labeling + buy-UOM validation.

Pipeline:  SKU match -> similarity -> review -> Infor cascade ->
           Infor residue -> item labeling -> buy UOM -> finalise.
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
BUCKET_PRIORITY = {"HIGH": 3, "MED": 2, "LOW": 1}


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


def _row_get(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _bucket_priority(bucket: Optional[str]) -> int:
    return BUCKET_PRIORITY.get((bucket or "").upper(), 0)


def _normalize_scope_value(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def _normalize_infor_item_number(value: object) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    return text if text.isdigit() and len(text) == 6 else None


def _split_multi_value_items(value: Optional[str]) -> list[str]:
    if not value:
        return []
    items = []
    for chunk in value.split(","):
        normalized = _normalize_infor_item_number(chunk)
        if normalized:
            items.append(normalized)
    return items


def _join_multi_value_items(values: list[str] | set[str]) -> Optional[str]:
    unique_values = sorted({_normalize_infor_item_number(value) for value in values if _normalize_infor_item_number(value)})
    if not unique_values:
        return None
    return ", ".join(unique_values)


def _build_matched_snapshot(row, matched_source: str) -> dict:
    if matched_source == "CCX":
        return {
            "contract_id_matched": _row_get(row, "ContractID"),
            "organization_eid_matched": _row_get(row, "OrganizationEID"),
            "organization_matched": _row_get(row, "Organization"),
            "manufacturer_number_matched": _row_get(row, "mfg_catalog_num_ccx", "ManufacturerNumber_CCX"),
            "uom_matched": _row_get(row, "uom_ccx", "UOM_CCX"),
            "erp_vendor_id_matched": _row_get(row, "ERPVendorID"),
            "vendor_item_matched": _row_get(row, "vendor_catalog_num_ccx", "VendorItem_CCX"),
            "uom_to_match_infor_matched": _row_get(row, "uom_to_match_infor_ccx", "UOMtoMatchInfor_CCX"),
            "qoe_matched": _row_get(row, "qoe_ccx", "QOE_CCX"),
            "contract_price_matched": _row_get(row, "unit_price_ccx", "ContractPrice_CCX"),
            "item_desc_matched": _row_get(row, "description_ccx", "ItemDescription_CCX"),
        }

    return {
        "contract_id_matched": _row_get(row, "ContractID"),
        "organization_eid_matched": _row_get(row, "OrganizationEID"),
        "organization_matched": _row_get(row, "Organization"),
        "manufacturer_number_matched": _row_get(row, "mfg_catalog_num_infor", "ManufacturerNumber_Infor"),
        "uom_matched": _row_get(row, "uom_infor", "UOM_Infor"),
        "erp_vendor_id_matched": _row_get(row, "erp_vendor_id", "ERPVendorID_Infor"),
        "vendor_item_matched": _row_get(row, "vendor_catalog_num_infor", "VendorItem_Infor"),
        "uom_to_match_infor_matched": _row_get(row, "uom_infor", "UOM_Infor"),
        "qoe_matched": _row_get(row, "qoe_infor", "QOE_Infor"),
        "contract_price_matched": _row_get(row, "unit_price_infor", "ContractPrice_Infor"),
        "item_desc_matched": _row_get(row, "ItemDescription_Infor"),
    }


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
    linked_infor_query = load_query("preprocess", "item_matching", query="infor_linked_pkids_by_ccx_pkids")

    # all items in a task share the same org
    org_eid = getattr(input_items[0], "organization_eid", None) or MHS_ORG_EID

    all_matches = []
    with _sql_session() as sess:
        from sqlalchemy import bindparam

        linked_infor_query = linked_infor_query.bindparams(bindparam("ccx_pkids", expanding=True))
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
            ccx_pkids = sorted({row.get("CCX_pkid") for row in rows if row.get("CCX_pkid") is not None})
            linked_infor_by_ccx_pkid: dict[int, list[str]] = {}
            if ccx_pkids:
                linked_rows = sess.execute(linked_infor_query, {"ccx_pkids": ccx_pkids}).mappings().all()
                for linked_row in linked_rows:
                    ccx_pkid = linked_row.get("CCX_pkid")
                    infor_pkid = linked_row.get("Infor_pkid")
                    if ccx_pkid is None or not infor_pkid:
                        continue
                    linked_infor_by_ccx_pkid.setdefault(ccx_pkid, []).append(str(infor_pkid))

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
                linked_infor_pkids = sorted(set(linked_infor_by_ccx_pkid.get(row.get("CCX_pkid"), [])))

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
                    "infor_pkids_matched": ", ".join(linked_infor_pkids) or None,
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
                    **_build_matched_snapshot(row, "CCX"),
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
            "qoe": item.qoe,
            "contract_price": float(item.unit_price) if item.unit_price is not None else None,
        }
        match_dict = {
            "matched_source": match.matched_source,
            "description": match.item_desc_matched or "",
            "mfg_catalog_num": match.manufacturer_number_matched or "",
            "vendor_catalog_num": match.vendor_item_matched or "",
            "uom": match.uom_matched or "",
            "qoe": match.qoe_matched,
            "contract_price": float(match.contract_price_matched) if match.contract_price_matched is not None else None,
            "similarity_score": match.similarity_score,
        }
        result = review_match_pair(input_dict, match_dict)
        new_status = "ACCEPTED" if result["decision"] == "ACCEPT" else "REJECTED"
        task_repo.update_match_decision(
            match.match_id,
            new_status,
            "LLM",
            llm_confidence=result.get("confidence"),
            llm_reason=result.get("reason"),
        )
        reviewed += 1

    return {"reviewed": reviewed}


# ---------------------------------------------------------------------------
# Step 4 -- Infor Cascade (via CCX pkids)
# ---------------------------------------------------------------------------
def run_infor_cascade(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Fetch Infor contract lines linked to CCX matches.

    Uses CCX_pkid to find corresponding Infor rows in
    InforActiveCLRefCCXSyncedCL.
    """
    state = state_machine.get_state(task_id)
    state["status"] = Status.INFOR_MATCHING
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.INFOR_MATCHING)

    ccx_matches = [m for m in task_repo.get_match_results(task_id, matched_source="CCX") if m.ccx_pkid]
    if not ccx_matches:
        return {"infor_lines": 0}

    cascade_pkids = sorted({match.ccx_pkid for match in ccx_matches if match.ccx_pkid is not None})
    if not cascade_pkids:
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
        rows = sess.execute(bound_query, {"ccx_pkids": cascade_pkids, "org_eid": org_eid}).mappings().all()

        # Map every task CCX pkid to the task rows that matched it so a single
        # Infor line can carry all CCX source rows for the same input item.
        ccx_matches_by_pkid: dict[int, list] = {}
        for match in ccx_matches:
            ccx_matches_by_pkid.setdefault(match.ccx_pkid, []).append(match)

        relevant_infor_pkids = sorted({row.get("Infor_pkid") for row in rows if row.get("Infor_pkid")})
        lineage_by_key: dict[tuple[int, str], set[int]] = {}
        if relevant_infor_pkids and ccx_matches_by_pkid:
            lineage_rows = sess.execute(
                bound_query,
                {"ccx_pkids": sorted(ccx_matches_by_pkid.keys()), "org_eid": org_eid},
            ).mappings().all()
            for lineage_row in lineage_rows:
                infor_pkid = lineage_row.get("Infor_pkid")
                ccx_pkid = lineage_row.get("CCX_pkid")
                if not infor_pkid or not ccx_pkid or infor_pkid not in relevant_infor_pkids:
                    continue
                for source_match in ccx_matches_by_pkid.get(ccx_pkid, []):
                    lineage_by_key.setdefault((source_match.input_item_id, infor_pkid), set()).add(ccx_pkid)

        grouped_rows: dict[tuple[int, str], list] = {}
        for row in rows:
            ccx_pkid = row.get("CCX_pkid")
            if not ccx_pkid:
                continue
            for source_match in ccx_matches_by_pkid.get(ccx_pkid, []):
                infor_pkid = row.get("Infor_pkid")
                if not infor_pkid:
                    continue
                grouped_rows.setdefault((source_match.input_item_id, infor_pkid), []).append((row, source_match))

        for (input_item_id, infor_pkid), row_sources in grouped_rows.items():
            lineage_pkids = sorted(lineage_by_key.get((input_item_id, infor_pkid), set()))
            source_matches = [source_match for _row, source_match in row_sources]
            primary_match = min(
                source_matches,
                key=lambda match: ((_bucket_priority(match.similarity_bucket) or 99), match.ccx_pkid or 0, match.match_id),
            )
            primary_row = next(row for row, source_match in row_sources if source_match.match_id == primary_match.match_id)

            # matched_item_ref: mfg+UOM for manufacturer, vendor+UOM for distributor
            if is_distributor:
                ref = f"{primary_row.get('vendor_catalog_num_infor', '')}|{primary_row.get('uom_infor', '')}"
            else:
                ref = f"{primary_row.get('mfg_catalog_num_infor', '')}|{primary_row.get('uom_infor', '')}"

            infor_matches.append({
                "input_item_id": input_item_id,
                "matched_source": "INFOR_CL",
                "matched_item_ref": ref,
                "contract_number": primary_row.get("ContractID", ""),
                "match_type": "CASCADE",
                "infor_pkid": infor_pkid,
                "ccx_pkid": primary_match.ccx_pkid,
                "ccx_pkids_matched": ", ".join(str(pkid) for pkid in lineage_pkids) or None,
                "match_status": task_repo._aggregate_cascade_status(source_matches),
                "similarity_score": None,
                "similarity_bucket": task_repo._aggregate_cascade_bucket(source_matches),
                **_build_matched_snapshot(primary_row, "INFOR_CL"),
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
                    desc_match=row.get("ItemDescription_Infor", "") or "",
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
                    **_build_matched_snapshot(row, "INFOR_CL"),
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
            "qoe": item.qoe,
            "contract_price": float(item.unit_price) if item.unit_price is not None else None,
        }
        match_dict = {
            "matched_source": match.matched_source,
            "description": match.item_desc_matched or "",
            "mfg_catalog_num": match.manufacturer_number_matched or "",
            "vendor_catalog_num": match.vendor_item_matched or "",
            "uom": match.uom_matched or "",
            "qoe": match.qoe_matched,
            "contract_price": float(match.contract_price_matched) if match.contract_price_matched is not None else None,
            "similarity_score": match.similarity_score,
        }
        result = review_match_pair(input_dict, match_dict)
        new_status = "ACCEPTED" if result["decision"] == "ACCEPT" else "REJECTED"
        task_repo.update_match_decision(
            match.match_id,
            new_status,
            "LLM",
            llm_confidence=result.get("confidence"),
            llm_reason=result.get("reason"),
        )
        reviewed += 1

    return {"reviewed": reviewed}


# ---------------------------------------------------------------------------
# Step 7 -- 3-Source Item# Labeling
# ---------------------------------------------------------------------------
def run_item_labeling(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Label each INPUT item with Infor Item# from 3 sources.

    Source 1: MDM_ITEM (Manufacturer + ManufacturerNumber)
    Source 2: MDM_VENDORITEM (Vendor + VendorItem)
    Source 3: Infor CL match (from accepted INFOR_CL match results)

    All source values and the final field store only 6-digit Infor Item values.
    """
    state = state_machine.get_state(task_id)
    state["status"] = Status.ITEM_LABELING
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.ITEM_LABELING)

    task = task_repo.get_task(task_id)
    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    if not input_items:
        task_repo.delete_item_matches_for_task(task_id)
        return {"labeled": 0}

    q_mdm_item = load_query("preprocess", "item_matching", query="item_label_mdm_item")
    q_mdm_vi = load_query("preprocess", "item_matching", query="item_label_mdm_vendoritem")
    q_infor_item = load_query("preprocess", "item_matching", query="item_label_infor_item_by_pkid")
    q_item_desc = load_query("preprocess", "item_matching", query="item_description_by_item_number")

    contract_manufacturer_infor = (getattr(task, "contract_manufacturer_infor", None) or "").strip()

    # Pre-build accepted INFOR_CL items by input_item_id via infor_pkid lineage.
    infor_matches = task_repo.get_match_results(task_id, matched_source="INFOR_CL")
    accepted_infor_pkids_by_input: dict[int, set[str]] = {}
    for match in infor_matches:
        if match.match_status != "ACCEPTED" or not match.infor_pkid:
            continue
        accepted_infor_pkids_by_input.setdefault(match.input_item_id, set()).add(match.infor_pkid)

    labeled_count = 0
    updates = []
    item_match_rows = []
    item_desc_cache: dict[str, Optional[str]] = {}

    with _sql_session() as sess:
        infor_item_by_pkid: dict[str, list[str]] = {}
        for infor_pkids in accepted_infor_pkids_by_input.values():
            for infor_pkid in infor_pkids:
                if infor_pkid in infor_item_by_pkid:
                    continue
                rows = sess.execute(q_infor_item, {"infor_pkid": infor_pkid}).mappings().all()
                infor_item_by_pkid[infor_pkid] = sorted(
                    {
                        normalized
                        for row in rows
                        for normalized in [_normalize_infor_item_number(row.get("Item"))]
                        if normalized
                    }
                )

        for item in input_items:
            update = {
                "item_id": item.item_id,
                "infor_item_1": None,
                "infor_item_1_active": None,
                "infor_item_2": None,
                "infor_item_2_active": None,
                "infor_item_3": None,
                "infor_item_3_active": None,
                "infor_item_number": None,
            }

            # Source 1: MDM_ITEM
            mfg_code = contract_manufacturer_infor
            mfg_num = item.mfg_catalog_num or ""
            if mfg_code and mfg_num:
                rows = sess.execute(q_mdm_item, {"manufacturer": mfg_code, "mfg_catalog_num": mfg_num}).mappings().all()
                source_1_items = sorted(
                    {
                        normalized
                        for row in rows
                        for normalized in [_normalize_infor_item_number(row.get("Item"))]
                        if normalized
                    }
                )
                if source_1_items:
                    update["infor_item_1"] = ", ".join(source_1_items)
                    update["infor_item_1_active"] = "Yes"

            # Source 2: MDM_VENDORITEM
            v_id = (item.vendor_id_short or "")[:7] or (getattr(task, "vendor_id", None) or "")[:7]
            vpn = item.vendor_catalog_num or ""
            if v_id and vpn:
                rows = sess.execute(q_mdm_vi, {"vendor_id": v_id, "vendor_catalog_num": vpn}).mappings().all()
                source_2_items = sorted(
                    {
                        normalized
                        for row in rows
                        for normalized in [_normalize_infor_item_number(row.get("Item"))]
                        if normalized
                    }
                )
                if source_2_items:
                    update["infor_item_2"] = ", ".join(source_2_items)
                    update["infor_item_2_active"] = "Yes"

            # Source 3: Infor CL match
            infor_items = sorted(
                {
                    item_number
                    for infor_pkid in accepted_infor_pkids_by_input.get(item.item_id, set())
                    for item_number in infor_item_by_pkid.get(infor_pkid, [])
                }
            )
            if infor_items:
                update["infor_item_3"] = ", ".join(infor_items)
                update["infor_item_3_active"] = "Yes"  # from active CL table

            # Determine consensus
            items_found = set()
            for key in ("infor_item_1", "infor_item_2", "infor_item_3"):
                items_found.update(_split_multi_value_items(update.get(key)))

            if len(items_found) == 0:
                update["status"] = Status.NO_MATCH
            elif len(items_found) == 1:
                final_item = next(iter(items_found))
                update["infor_item_number"] = final_item
                update["status"] = Status.ITEM_LABELED
            else:
                update["infor_item_number"] = ", ".join(sorted(items_found))
                update["status"] = Status.MULTI_ITEM_ERROR

            final_items = _split_multi_value_items(update.get("infor_item_number"))
            for final_item in final_items:
                if final_item not in item_desc_cache:
                    rows = sess.execute(q_item_desc, {"item_number": final_item}).mappings().all()
                    item_desc_cache[final_item] = rows[0]["item_description"] if rows else None
                item_match_rows.append(
                    {
                        "task_id": task_id,
                        "item_id": item.item_id,
                        "infor_item_number": final_item,
                        "item_description": item_desc_cache[final_item],
                    }
                )

            updates.append(update)
            labeled_count += 1

    # Bulk update items
    if updates:
        task_repo.update_items_bulk(updates)
    task_repo.delete_item_matches_for_task(task_id)
    if item_match_rows:
        task_repo.add_item_matches_bulk(item_match_rows)

    state["item_labeling_done"] = True
    state["buy_uom_check_done"] = False
    state_machine.save_state(task_id, state)

    return {"labeled": labeled_count, "item_match_candidates": len(item_match_rows)}


# ---------------------------------------------------------------------------
# Step 8 -- Buy UOM aggregation for labeled item candidates
# ---------------------------------------------------------------------------
def run_buy_uom_check(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Aggregate valid buy UOM options from exploded item match candidates."""
    state = state_machine.get_state(task_id)
    state["status"] = Status.BUY_UOM_CHECKING
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.BUY_UOM_CHECKING)

    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    if not input_items:
        return {"checked": 0, "matched_items": 0}

    q_uom = load_query("preprocess", "item_matching", query="item_uom_options")
    candidate_rows = task_repo.get_item_matches(task_id)
    updates = [{"item_id": item.item_id, "infor_buy_uom_options": None} for item in input_items]
    options_by_item_id: dict[int, set[str]] = {}

    with _sql_session() as sess:
        uom_cache: dict[str, list[str]] = {}
        for candidate in candidate_rows:
            item_number = candidate.infor_item_number
            if item_number not in uom_cache:
                rows = sess.execute(q_uom, {"item_number": item_number}).mappings().all()
                uom_cache[item_number] = sorted(
                    {
                        f"{row['UOM']}*{row['UOMConversion']}"
                        for row in rows
                        if row.get("UOM") is not None and row.get("UOMConversion") is not None
                    }
                )
            if not uom_cache[item_number]:
                continue
            options_by_item_id.setdefault(candidate.item_id, set()).update(uom_cache[item_number])

    update_map = {entry["item_id"]: entry for entry in updates}
    for item_id, options in options_by_item_id.items():
        update_map[item_id]["infor_buy_uom_options"] = ", ".join(sorted(options))

    if updates:
        task_repo.update_items_bulk(updates)

    state["buy_uom_check_done"] = True
    state_machine.save_state(task_id, state)
    return {"checked": len(input_items), "matched_items": len(candidate_rows)}


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
    3. Infor cascade (via deterministic CCX HIGH matches)
    4. LLM review for MED/LOW CCX matches
    5. Infor residue matching + LLM review
    6. 3-source Item# labeling
    7. Buy UOM aggregation

    Returns aggregated results dict.
    """
    results = {}
    results["sku_matching"] = run_sku_matching(task_id, state_machine)
    results["contract_check"] = run_contract_check(task_id, state_machine)
    # Keep the initial INFOR_CL candidate set independent from the LLM toggle.
    results["infor_cascade"] = run_infor_cascade(task_id, state_machine)
    if enable_llm:
        results["llm_review_ccx"] = run_llm_review(task_id, state_machine)
    else:
        results["llm_review_ccx"] = _llm_step_skipped()
    results["infor_residue"] = run_infor_residue(task_id, state_machine)
    if enable_llm:
        results["llm_review_infor"] = run_infor_residue_llm_review(task_id, state_machine)
    else:
        results["llm_review_infor"] = _llm_step_skipped()
    results["item_labeling"] = run_item_labeling(task_id, state_machine)
    results["buy_uom_check"] = run_buy_uom_check(task_id, state_machine)
    return results


# ---------------------------------------------------------------------------
# Review decisions (human-in-the-loop)
# ---------------------------------------------------------------------------
def submit_contract_decision(
    task_id: str,
    contract_number: str,
    organization_eid: str | None,
    erp_vendor_id: str | None,
    include: bool,
    decided_by: str,
    state_machine: TaskStateMachine,
) -> dict:
    """Accept or reject matches for one contract summary row."""
    contract_filter = _normalize_scope_value(contract_number)
    organization_filter = _normalize_scope_value(organization_eid)
    vendor_filter = _normalize_scope_value(erp_vendor_id)
    matches = [
        match
        for match in task_repo.get_match_results(task_id)
        if _normalize_scope_value(match.contract_number) == contract_filter
        and _normalize_scope_value(match.organization_eid_matched) == organization_filter
        and _normalize_scope_value(match.erp_vendor_id_matched) == vendor_filter
    ]
    decision = "ACCEPTED" if include else "REJECTED"
    for m in matches:
        task_repo.update_match_decision(m.match_id, decision, decided_by)

    state = state_machine.get_state(task_id)
    state["ccx_decisions_done"] = True
    state_machine.save_state(task_id, state)

    return {
        "contract_number": contract_number,
        "organization_eid": organization_eid,
        "erp_vendor_id": erp_vendor_id,
        "decision": decision,
        "affected": len(matches),
    }


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
