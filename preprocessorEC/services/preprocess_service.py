"""Preprocess service -- Phase 3 business logic.

Unified CCX duplicate detection + Infor cascading/residue matching +
3-source item labeling + buy-UOM validation.

Pipeline:  SKU match -> similarity -> review -> Infor cascade ->
           Infor residue -> item labeling -> buy UOM -> finalise.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..db import task_repo, workstate_repo
from ..db.engine import get_sqlserver_engine
from ..db.sql_loader import load_query
from ..common.utils import reduce_catalog_number, ny_now
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


def _load_distributor_groups(sess: Session) -> dict[str, int]:
    rows = sess.execute(load_query("preprocess", "distributor_group")).mappings().all()
    distributor_groups: dict[str, int] = {}
    for row in rows:
        vendor_id = str(row.get("ERPVendorID") or "").strip().upper()
        group_id = row.get("Group")
        if vendor_id and group_id is not None:
            distributor_groups[vendor_id] = int(group_id)
    return distributor_groups


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


def _normalize_uom(value: object) -> Optional[str]:
    text = str(value or "").strip().upper()
    return text or None


def _build_buy_uom_option(uom: object, conversion: object) -> Optional[str]:
    normalized_uom = _normalize_uom(uom)
    if not normalized_uom:
        return None
    try:
        normalized_conversion = int(conversion)
    except (TypeError, ValueError):
        return None
    if normalized_conversion <= 0:
        return None
    return f"{normalized_uom}*{normalized_conversion}"


def _parse_buy_uom_options(value: Optional[str]) -> set[str]:
    if not value:
        return set()
    return {chunk.strip().upper() for chunk in value.split(",") if chunk.strip()}


def _expected_buy_uom_option(item) -> Optional[str]:
    return _build_buy_uom_option(getattr(item, "uom_to_match_infor", None), getattr(item, "qoe", None))


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

        distributor_groups = _load_distributor_groups(sess)
        task_vendor_group = distributor_groups.get(str(task.vendor_id or "").strip().upper())
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
                    task_vendor_group=task_vendor_group,
                    match_contract_id=row.get("ContractID", ""),
                    match_contract_manufacturer=row.get("contract_manufacturer", ""),
                    match_erp_vendor_id=row.get("ERPVendorID", ""),
                    match_vendor_group=distributor_groups.get(str(row.get("ERPVendorID") or "").strip().upper()),
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
            "pair_type": match.pair_type or "",
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
            "pair_type": match.pair_type or "",
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
    # Clear unresolved labeling issues — pipeline reruns rebuild from scratch.
    task_repo.delete_unresolved_preprocess_issues(task_id, ["MULTI_ITEM_ERROR"])
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
                update["status"] = Status.ITEM_FETCHED
            elif len(items_found) == 1:
                final_item = next(iter(items_found))
                update["infor_item_number"] = final_item
                update["status"] = Status.ITEM_LABELED
            else:
                update["infor_item_number"] = ", ".join(sorted(items_found))
                update["status"] = Status.MULTI_ITEM_ERROR
                task_repo.upsert_preprocess_issue(
                    task_id=task_id,
                    item_id=item.item_id,
                    issue_type="MULTI_ITEM_ERROR",
                    severity="ERROR",
                    detail=json.dumps({
                        "candidates": sorted(items_found),
                        "sources": {
                            "mdm_item":        update.get("infor_item_1"),
                            "mdm_vendoritem":  update.get("infor_item_2"),
                            "infor_cl":        update.get("infor_item_3"),
                        },
                    }),
                )

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
    # Clear unresolved buy-UOM issues — pipeline reruns rebuild from scratch.
    task_repo.delete_unresolved_preprocess_issues(task_id, ["BUY_UOM_ERROR"])
    if not input_items:
        return {"checked": 0, "matched_items": 0}

    task = task_repo.get_task(task_id)
    task_intention = (getattr(task, "intention", None) or "").upper()

    q_uom = load_query("preprocess", "item_matching", query="item_uom_options")
    q_inactive_gtin = load_query("preprocess", "item_matching", query="inactive_gtin_items")
    candidate_rows = task_repo.get_item_matches(task_id)
    input_item_by_id = {item.item_id: item for item in input_items}
    updates = [{"item_id": item.item_id, "infor_buy_uom_options": None} for item in input_items]
    options_by_item_id: dict[int, set[str]] = {}
    expected_option_by_item_id = {item.item_id: _expected_buy_uom_option(item) for item in input_items}
    status_by_item_id = {item.item_id: getattr(item, "status", None) for item in input_items}
    candidate_updates: list[dict] = []
    matched_candidate_count = 0

    with _sql_session() as sess:
        uom_cache: dict[str, list[str]] = {}
        inactive_gtin_rows = sess.execute(q_inactive_gtin).mappings().all()
        inactive_gtin_pairs = {
            (
                str(row.get("Item") or "").strip(),
                _normalize_uom(row.get("UOM")),
            )
            for row in inactive_gtin_rows
            if str(row.get("Item") or "").strip() and _normalize_uom(row.get("UOM"))
        }
        for candidate in candidate_rows:
            item_number = candidate.infor_item_number
            if item_number not in uom_cache:
                rows = sess.execute(q_uom, {"item_number": item_number}).mappings().all()
                uom_cache[item_number] = sorted(
                    {
                        option
                        for row in rows
                        for option in [_build_buy_uom_option(row.get("UOM"), row.get("UOMConversion"))]
                        if option
                    }
                )
            option_values = uom_cache[item_number]
            if option_values:
                options_by_item_id.setdefault(candidate.item_id, set()).update(option_values)

            expected_option = expected_option_by_item_id.get(candidate.item_id)
            if expected_option and expected_option in set(option_values):
                matched_candidate_count += 1

            input_item = input_item_by_id.get(candidate.item_id)
            input_infor_uom = _normalize_uom(getattr(input_item, "uom_to_match_infor", None))

            candidate_updates.append(
                {
                    "match_item_id": candidate.match_item_id,
                    "infor_buy_uom_options": ", ".join(option_values) if option_values else None,
                    "active_gtin": "invalid"
                    if input_infor_uom and (item_number, input_infor_uom) in inactive_gtin_pairs
                    else "okay",
                }
            )

    update_map = {entry["item_id"]: entry for entry in updates}
    for item_id, options in options_by_item_id.items():
        update_map[item_id]["infor_buy_uom_options"] = ", ".join(sorted(options))

    for item in input_items:
        expected_option = expected_option_by_item_id.get(item.item_id)
        option_values = options_by_item_id.get(item.item_id, set())
        current_status = status_by_item_id.get(item.item_id)
        has_item_number = bool(_split_multi_value_items(getattr(item, "infor_item_number", None)))
        if not has_item_number:
            update_map[item.item_id]["status"] = Status.ITEM_PREPROCESSED
            continue
        if current_status == Status.MULTI_ITEM_ERROR:
            continue
        if expected_option and expected_option not in option_values:
            item_intention = (getattr(item, "intention", None) or task_intention).upper()
            is_expire = item_intention == "EXPIRE"
            new_status = Status.BUY_UOM_WARN if is_expire else Status.BUY_UOM_ERROR
            severity = "WARN" if is_expire else "ERROR"
            update_map[item.item_id]["status"] = new_status
            task_repo.upsert_preprocess_issue(
                task_id=task_id,
                item_id=item.item_id,
                issue_type="BUY_UOM_ERROR",
                severity=severity,
                detail=json.dumps({
                    "expected": expected_option,
                    "available": sorted(option_values),
                    "infor_item_number": getattr(item, "infor_item_number", None),
                    "intention": item_intention,
                }),
            )

    if updates:
        task_repo.update_items_bulk(updates)
    if candidate_updates:
        task_repo.update_item_matches_bulk(candidate_updates)

    state["buy_uom_check_done"] = True
    state_machine.save_state(task_id, state)
    return {
        "checked": len(input_items),
        "matched_items": len(candidate_rows),
        "buy_uom_matched_candidates": matched_candidate_count,
    }


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


# ---------------------------------------------------------------------------
# Issue resolution helpers (per-item UI actions on task detail page)
# ---------------------------------------------------------------------------
def _query_buy_uom_options(sess: Session, infor_item_number: str) -> list[str]:
    q = load_query("preprocess", "item_matching", query="item_uom_options")
    rows = sess.execute(q, {"item_number": infor_item_number}).mappings().all()
    return sorted(
        {
            option
            for row in rows
            for option in [_build_buy_uom_option(row.get("UOM"), row.get("UOMConversion"))]
            if option
        }
    )


def _intention_for_item(item, task) -> str:
    return (getattr(item, "intention", None) or getattr(task, "intention", None) or "").upper()


def get_accepted_matches_for_item(task_id: str, item_id: int) -> list[dict]:
    """Return ACCEPTED CCX + INFOR_CL matches for one input item."""
    matches = task_repo.get_match_results(task_id)
    return [
        m.to_dict() for m in matches
        if m.input_item_id == item_id
        and (m.match_status or "").upper() == "ACCEPTED"
        and (m.matched_source or "") in ("CCX", "INFOR_CL")
    ]


def resolve_multi_item_pick(task_id: str, issue_id: int, infor_item_number: str, decided_by: str) -> dict:
    """User picks exactly one Infor item# to resolve a MULTI_ITEM_ERROR.

    Updates TaskItem.infor_item_number, prunes ItemMatchCandidate rows to the
    picked one, re-runs buy-UOM check for this item, raising a fresh
    BUY_UOM_ERROR/WARN issue if needed.
    """
    issue = task_repo.get_preprocess_issue(issue_id)
    if not issue or issue.task_id != task_id:
        raise ValueError("Issue not found")
    if issue.issue_type != "MULTI_ITEM_ERROR" or issue.resolved:
        raise ValueError("Issue not eligible for PICK_ITEM resolution")

    picked = _normalize_infor_item_number(infor_item_number)
    if not picked:
        raise ValueError("infor_item_number must be a 6-digit Infor item")

    # Validate the pick is one of the original candidates.
    try:
        detail = json.loads(issue.detail or "{}")
    except (TypeError, ValueError):
        detail = {}
    candidates = set(detail.get("candidates") or [])
    if candidates and picked not in candidates:
        raise ValueError(f"{picked} is not one of the candidates {sorted(candidates)}")

    # Prune ItemMatchCandidate rows to the picked one.
    surviving_match_item_id = None
    item_desc = None
    candidate_rows = task_repo.get_item_matches(task_id)
    to_delete = []
    for cand in candidate_rows:
        if cand.item_id != issue.item_id:
            continue
        if cand.infor_item_number == picked:
            surviving_match_item_id = cand.match_item_id
            item_desc = cand.item_description
        else:
            to_delete.append(cand.match_item_id)
    if to_delete:
        task_repo.delete_item_matches_by_ids(to_delete)
    if surviving_match_item_id is None:
        # Pick wasn't materialised earlier — insert a new candidate row.
        with _sql_session() as sess:
            q_item_desc = load_query("preprocess", "item_matching", query="item_description_by_item_number")
            rows = sess.execute(q_item_desc, {"item_number": picked}).mappings().all()
            item_desc = rows[0]["item_description"] if rows else None
        task_repo.add_item_matches_bulk([{
            "task_id": task_id,
            "item_id": issue.item_id,
            "infor_item_number": picked,
            "item_description": item_desc,
        }])

    # Recompute buy-UOM for just this item.
    task = task_repo.get_task(task_id)
    item = task_repo.get_task_item(issue.item_id)
    expected_option = _expected_buy_uom_option(item) if item else None
    intention = _intention_for_item(item, task) if item else ""
    is_expire = intention == "EXPIRE"

    with _sql_session() as sess:
        option_values = _query_buy_uom_options(sess, picked)

    options_str = ", ".join(option_values) if option_values else None
    item_status = Status.ITEM_PREPROCESSED
    new_buy_uom_issue = None
    if expected_option and expected_option not in set(option_values):
        item_status = Status.BUY_UOM_WARN if is_expire else Status.BUY_UOM_ERROR
        new_buy_uom_issue = task_repo.upsert_preprocess_issue(
            task_id=task_id,
            item_id=issue.item_id,
            issue_type="BUY_UOM_ERROR",
            severity="WARN" if is_expire else "ERROR",
            detail=json.dumps({
                "expected": expected_option,
                "available": option_values,
                "infor_item_number": picked,
                "intention": intention,
                "raised_after": "PICK_ITEM",
            }),
        )

    task_repo.update_items_bulk([{
        "item_id": issue.item_id,
        "infor_item_number": picked,
        "infor_buy_uom_options": options_str,
        "status": item_status,
    }])

    task_repo.resolve_preprocess_issue(
        issue_id=issue_id,
        resolution_action="PICK_ITEM",
        resolved_by=decided_by,
        detail=json.dumps({**detail, "picked": picked}),
    )

    return {
        "issue_id": issue_id,
        "picked": picked,
        "item_status": item_status,
        "buy_uom_issue_id": new_buy_uom_issue.issue_id if new_buy_uom_issue else None,
    }


def resolve_buy_uom_note(task_id: str, issue_id: int, decided_by: str) -> dict:
    """Demote BUY_UOM_ERROR to WARN and carry forward to next phase."""
    issue = task_repo.get_preprocess_issue(issue_id)
    if not issue or issue.task_id != task_id:
        raise ValueError("Issue not found")
    if issue.issue_type != "BUY_UOM_ERROR" or issue.resolved or issue.severity != "ERROR":
        raise ValueError("Issue not eligible for NOTE resolution")

    task_repo.update_items_bulk([{"item_id": issue.item_id, "status": Status.BUY_UOM_WARN}])
    task_repo.resolve_preprocess_issue(
        issue_id=issue_id,
        resolution_action="NOTE",
        resolved_by=decided_by,
    )
    # Persist the demoted severity on the (now resolved) row for clearer audit.
    task_repo.update_preprocess_issue(issue_id=issue_id, severity="WARN")
    return {"issue_id": issue_id, "item_status": Status.BUY_UOM_WARN}


def resolve_buy_uom_recheck(task_id: str, issue_id: int, decided_by: str) -> dict:
    """Re-query Infor UOM options. If expected option now present, mark resolved."""
    issue = task_repo.get_preprocess_issue(issue_id)
    if not issue or issue.task_id != task_id:
        raise ValueError("Issue not found")
    if issue.issue_type != "BUY_UOM_ERROR" or issue.resolved:
        raise ValueError("Issue not eligible for RECHECK")

    item = task_repo.get_task_item(issue.item_id)
    if not item or not item.infor_item_number:
        raise ValueError("Item has no Infor item number to recheck")

    expected_option = _expected_buy_uom_option(item)
    item_numbers = _split_multi_value_items(item.infor_item_number)

    with _sql_session() as sess:
        options_by_item = {n: _query_buy_uom_options(sess, n) for n in item_numbers}

    aggregate_options: set[str] = set()
    for opts in options_by_item.values():
        aggregate_options.update(opts)
    passed = bool(expected_option) and expected_option in aggregate_options

    # Append attempt to detail log.
    try:
        detail = json.loads(issue.detail or "{}")
    except (TypeError, ValueError):
        detail = {}
    attempts = detail.get("recheck_attempts") or []
    attempts.append({
        "checked_at": ny_now().isoformat(),
        "checked_by": decided_by,
        "expected": expected_option,
        "available": sorted(aggregate_options),
        "passed": passed,
    })
    detail["recheck_attempts"] = attempts
    detail["available"] = sorted(aggregate_options)

    options_str = ", ".join(sorted(aggregate_options)) if aggregate_options else None

    if passed:
        task_repo.update_items_bulk([{
            "item_id": issue.item_id,
            "infor_buy_uom_options": options_str,
            "status": Status.ITEM_PREPROCESSED,
        }])
        task_repo.resolve_preprocess_issue(
            issue_id=issue_id,
            resolution_action="RECHECK_PASSED",
            resolved_by=decided_by,
            detail=json.dumps(detail),
        )
        return {"issue_id": issue_id, "passed": True, "item_status": Status.ITEM_PREPROCESSED}

    # Still failing — keep open, just log the attempt.
    task_repo.update_items_bulk([{
        "item_id": issue.item_id,
        "infor_buy_uom_options": options_str,
    }])
    task_repo.update_preprocess_issue(issue_id=issue_id, detail=json.dumps(detail))
    return {"issue_id": issue_id, "passed": False, "attempts": len(attempts)}


def resolve_buy_uom_ignore(task_id: str, issue_id: int, decided_by: str) -> dict:
    """EXPIRE-intent only: dismiss the warning and advance item to ITEM_PREPROCESSED."""
    issue = task_repo.get_preprocess_issue(issue_id)
    if not issue or issue.task_id != task_id:
        raise ValueError("Issue not found")
    if issue.issue_type != "BUY_UOM_ERROR" or issue.resolved:
        raise ValueError("Issue not eligible for IGNORE")

    item = task_repo.get_task_item(issue.item_id)
    task = task_repo.get_task(task_id)
    if not item or _intention_for_item(item, task) != "EXPIRE":
        raise ValueError("IGNORE is only available for EXPIRE-intent items")

    task_repo.update_items_bulk([{"item_id": issue.item_id, "status": Status.ITEM_PREPROCESSED}])
    task_repo.resolve_preprocess_issue(
        issue_id=issue_id,
        resolution_action="IGNORE_EXPIRE",
        resolved_by=decided_by,
    )
    return {"issue_id": issue_id, "item_status": Status.ITEM_PREPROCESSED}


def finalize_preprocess(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """Mark preprocess complete and advance to DEDUP phase.

    Blocks if any unresolved ERROR-severity preprocess issues remain. WARN
    issues carry forward into DEDUP.
    """
    pending_matches = [
        m for m in task_repo.get_match_results(task_id)
        if (m.match_status or "").upper() == "PENDING"
    ]
    if pending_matches:
        raise ValueError(
            "Cannot finalize: {n} match(es) still PENDING — accept or reject every match before advancing".format(
                n=len(pending_matches)
            )
        )

    unresolved_errors = task_repo.get_unresolved_error_issues(task_id)
    if unresolved_errors:
        raise ValueError(
            "Cannot finalize: {n} unresolved ERROR issue(s) on items {items}".format(
                n=len(unresolved_errors),
                items=sorted({issue.item_id for issue in unresolved_errors}),
            )
        )

    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    finalize_updates = [
        {"item_id": item.item_id, "status": Status.ITEM_PREPROCESSED}
        for item in input_items
        if "ERROR" not in str(getattr(item, "status", "")).upper()
    ]
    if finalize_updates:
        task_repo.update_items_bulk(finalize_updates)

    state = state_machine.get_state(task_id)
    state["status"] = Status.PREPROCESSED
    state_machine.save_state(task_id, state)

    new_state = state_machine.advance(
        task_id, Phase.DEDUP, changed_by=user, notes="Preprocess complete, advancing to Dedup"
    )
    return {"phase": new_state["phase"], "status": new_state["status"]}
