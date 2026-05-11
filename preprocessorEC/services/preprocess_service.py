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


def _live_input_items(task_id: str) -> list:
    """INPUT items minus soft-deleted rows.

    Single chokepoint for pipeline steps that drive matching, labeling, or
    bulk status updates — keeps DELETED_PC1 / DELETED_PREPROCESS rows from
    being resurrected or re-matched on a rerun.
    """
    return [
        item for item in task_repo.get_items_by_source(task_id, "INPUT")
        if (item.status or "") not in Status.DELETED_STATUSES
    ]


def _derive_item_status(types_open: set[str], buy_uom_severity: str) -> str:
    """Status priority: MULTI > BUY_UOM > DUPLICATE > PREPROCESSED."""
    if "MULTI_ITEM_ERROR" in types_open:
        return Status.MULTI_ITEM_ERROR
    if "BUY_UOM_ERROR" in types_open:
        return Status.BUY_UOM_WARN if buy_uom_severity == "WARN" else Status.BUY_UOM_ERROR
    if "DUPLICATE_ITEM_ERROR" in types_open:
        return Status.DUPLICATE_ITEM_ERROR
    return Status.ITEM_PREPROCESSED


def _recompute_explicit_duplicates(
    task_id: str,
    force_item_ids: Optional[set[int]] = None,
) -> dict:
    """Re-run explicit-mode duplicate detection across all live INPUT items.

    Mirrors PC1's explicit-mode key — ``clean_mfg + uom_to_match_infor`` — so
    that downstream phases see the same collision semantics. For each group
    of size >= 2 a ``DUPLICATE_ITEM_ERROR`` issue is created on every
    member, with detail listing partner rows. Items previously flagged but
    no longer in a dup group simply lose their issue row (the unresolved
    DUPLICATE_ITEM_ERROR rows for the task are deleted up-front and only
    current members are re-inserted — same approach the labeling and
    buy-UOM steps already use).

    Item statuses for everything touched are reconciled via
    ``_derive_item_status`` so the badge + filters stay consistent with the
    open-issue set.
    """
    items_by_id = {i.item_id: i for i in _live_input_items(task_id)}

    groups: dict[tuple[str, str], list] = {}
    for item in items_by_id.values():
        mfg = (item.mfg_catalog_num or "").strip().upper()
        uom = (item.uom_to_match_infor or "").strip().upper()
        if not mfg or not uom:
            continue
        groups.setdefault((mfg, uom), []).append(item)
    dup_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    in_dup_item_ids = {i.item_id for v in dup_groups.values() for i in v}

    # Snapshot existing open issues *before* clearing dup rows so the
    # affected_ids set still includes items that just fell out of any group.
    open_issues = [
        i for i in task_repo.get_preprocess_issues(task_id, include_resolved=False)
        if not i.resolved
    ]

    # Wipe the prior dup rows in one statement, then buffer new ones for a
    # single bulk insert. This used to fire one round-trip per group member
    # and per resolve, which dominated rerun cost on large files.
    task_repo.delete_unresolved_preprocess_issues(task_id, ["DUPLICATE_ITEM_ERROR"])

    pending_issue_records: list[dict] = []
    for (mfg, uom), members in dup_groups.items():
        member_summaries = [
            {"item_id": m.item_id, "file_row": m.file_row, "uom": m.uom, "qoe": m.qoe}
            for m in members
        ]
        for member in members:
            partners = [s for s in member_summaries if s["item_id"] != member.item_id]
            pending_issue_records.append({
                "task_id": task_id,
                "item_id": member.item_id,
                "issue_type": "DUPLICATE_ITEM_ERROR",
                "severity": "ERROR",
                "detail": json.dumps({
                    "key": f"{mfg}|{uom}",
                    "key_mfg": mfg,
                    "key_uom_to_match_infor": uom,
                    "qoe": member.qoe,
                    "partners": partners,
                }),
            })
    task_repo.add_preprocess_issues_bulk(pending_issue_records)

    # Recompute statuses for every item that has any open issue OR is now in
    # a dup group OR was passed in via force_item_ids (typically the just-
    # edited row).
    affected_ids = (
        {iss.item_id for iss in open_issues}
        | in_dup_item_ids
        | (force_item_ids or set())
    )

    open_issues_now = [
        i for i in task_repo.get_preprocess_issues(task_id, include_resolved=False)
        if not i.resolved
    ]
    types_by_item: dict[int, set[str]] = {}
    severity_by_item_type: dict[tuple[int, str], str] = {}
    for iss in open_issues_now:
        types_by_item.setdefault(iss.item_id, set()).add(iss.issue_type)
        severity_by_item_type[(iss.item_id, iss.issue_type)] = (iss.severity or "ERROR").upper()

    status_updates = []
    for item_id in affected_ids:
        item = items_by_id.get(item_id)
        if not item:
            continue
        types = types_by_item.get(item_id, set())
        buy_uom_sev = severity_by_item_type.get((item_id, "BUY_UOM_ERROR"), "ERROR")
        new_status = _derive_item_status(types, buy_uom_sev)
        if (item.status or "") != new_status:
            status_updates.append({"item_id": item_id, "status": new_status})

    if status_updates:
        task_repo.update_items_bulk(status_updates)

    return {
        "dup_groups": [
            {"key": f"{k[0]}|{k[1]}", "item_ids": [m.item_id for m in members]}
            for k, members in dup_groups.items()
        ],
    }


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

    input_items = _live_input_items(task_id)
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
                    match_process_type=row.get("match_process_type", "") or "",
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

                # uom_nuance: same-contract (type A) match with identical QOE but
                # a different UOM — flags UOM inconsistency for the same pack size.
                uom_nuance = "No"
                if pt == "A":
                    same_qoe = str(item.qoe or "").strip() == str(row.get("qoe_ccx") or "").strip()
                    diff_uom = (
                        str(item.uom or "").strip().upper()
                        != str(row.get("uom_ccx") or "").strip().upper()
                    )
                    if same_qoe and diff_uom:
                        uom_nuance = "Yes"

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
                    "uom_nuance": uom_nuance,
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
def _lookup_vendor_names(erp_vendor_ids: list[str]) -> dict[str, str]:
    """Batch-load VendorName by ERPVendorID for the LLM review prompt.

    Returns ``{erp_vendor_id: vendor_name}``. Missing IDs are simply absent
    from the dict; callers should fall back to the raw ID.
    """
    cleaned = sorted({(vid or "").strip() for vid in erp_vendor_ids if (vid or "").strip()})
    if not cleaned:
        return {}

    from sqlalchemy import bindparam

    stmt = load_query("db", "common", query="get_vendor_names_by_erp_ids").bindparams(
        bindparam("erp_vendor_ids", expanding=True)
    )
    name_by_id: dict[str, str] = {}
    with _sql_session() as sess:
        rows = sess.execute(stmt, {"erp_vendor_ids": cleaned}).all()
        for row in rows:
            erp_id = (row.ERPVendorID or "").strip()
            name = (row.VendorName or "").strip()
            if erp_id and name:
                name_by_id[erp_id] = name
    return name_by_id


def _llm_review_matches(matches: list, item_by_id: dict, task=None) -> int:
    """Run review_match_pair against each match and persist the verdict.

    Returns the number of matches actually reviewed (skips orphans whose input
    item is no longer present).
    """
    task_vendor_name = (task.erp_vendor_name or "").strip() if task else ""
    task_vendor_id = (task.vendor_id or "").strip() if task else ""

    # Pre-fetch vendor names for every distinct ERP vendor ID we will need:
    # the task's own vendor (input side) plus every matched contract's vendor.
    erp_ids_needed = {task_vendor_id} if task_vendor_id else set()
    for m in matches:
        mid = (m.erp_vendor_id_matched or "").strip()
        if mid:
            erp_ids_needed.add(mid)
    vendor_name_by_id = _lookup_vendor_names(sorted(erp_ids_needed))

    # Resolve the input-side vendor name once for the whole task.
    input_vendor = (
        task_vendor_name
        or vendor_name_by_id.get(task_vendor_id, "")
        or task_vendor_id
    )

    reviewed = 0
    for match in matches:
        item = item_by_id.get(match.input_item_id)
        if not item:
            continue

        match_erp_id = (match.erp_vendor_id_matched or "").strip()
        match_vendor_name = vendor_name_by_id.get(match_erp_id, "")
        if match_vendor_name:
            match_vendor = match_vendor_name
        elif match_erp_id:
            match_vendor = f"ERPVendorID {match_erp_id}"
        else:
            match_vendor = ""

        input_dict = {
            "vendor": input_vendor,
            "description": item.description or "",
            "mfg_catalog_num": item.mfg_catalog_num or "",
            "vendor_catalog_num": item.vendor_catalog_num or "",
            "uom": item.uom or "",
            "qoe": item.qoe,
            "contract_price": float(item.unit_price) if item.unit_price is not None else None,
        }
        match_dict = {
            "matched_source": match.matched_source,
            "vendor": match_vendor,
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
        decision = result["decision"]
        if decision == "ACCEPT":
            new_status = "ACCEPTED"
        elif decision == "REJECT":
            new_status = "REJECTED"
        else:
            # PENDING (or unknown) — leave for human review.
            new_status = "LLM_REVIEW"
        task_repo.update_match_decision(
            match.match_id,
            new_status,
            "LLM",
            llm_confidence=result.get("confidence"),
            llm_reason=result.get("reason"),
        )
        reviewed += 1
    return reviewed


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

    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    item_by_id = {it.item_id: it for it in input_items}
    task = task_repo.get_task(task_id)

    reviewed = _llm_review_matches(pending_matches, item_by_id, task=task)
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

            cascaded_uom_nuance = (
                "Yes"
                if any((m.uom_nuance or "").strip().lower() == "yes" for m in source_matches)
                else "No"
            )
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
                "uom_nuance": cascaded_uom_nuance,
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

    input_items = _live_input_items(task_id)
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
                    "uom_nuance": "No",
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
    task = task_repo.get_task(task_id)

    reviewed = _llm_review_matches(pending, item_by_id, task=task)
    return {"reviewed": reviewed}


def run_llm_review_pending_all(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Send every remaining PENDING match (any bucket, any source) to the LLM.

    Triggered by the user after manual review when leftover PENDING rows should
    be auto-decided. CCX is processed first so the cascade in
    update_match_decision settles linked INFOR_CL CASCADE rows before the
    INFOR_CL pass re-reads PENDING from the DB.
    """
    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    item_by_id = {it.item_id: it for it in input_items}
    task = task_repo.get_task(task_id)

    reviewed = 0
    for source in ("CCX", "INFOR_CL"):
        pending = [
            m for m in task_repo.get_match_results(task_id, matched_source=source)
            if m.match_status == "PENDING"
        ]
        if not pending:
            continue
        reviewed += _llm_review_matches(pending, item_by_id, task=task)

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
    input_items = _live_input_items(task_id)
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

    # Buffer MULTI_ITEM_ERROR records and flush in one bulk insert after the
    # loop. Per-item upsert was causing one round-trip per flagged row.
    pending_issue_records: list[dict] = []

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
                pending_issue_records.append({
                    "task_id": task_id,
                    "item_id": item.item_id,
                    "issue_type": "MULTI_ITEM_ERROR",
                    "severity": "ERROR",
                    "detail": json.dumps({
                        "candidates": sorted(items_found),
                        "sources": {
                            "mdm_item":        update.get("infor_item_1"),
                            "mdm_vendoritem":  update.get("infor_item_2"),
                            "infor_cl":        update.get("infor_item_3"),
                        },
                    }),
                })

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
    task_repo.add_preprocess_issues_bulk(pending_issue_records)
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

    input_items = _live_input_items(task_id)
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
    # Buffer BUY_UOM_ERROR/WARN records and bulk-insert at the end. Per-item
    # upsert was firing one round-trip per flagged row.
    pending_issue_records: list[dict] = []

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
            pending_issue_records.append({
                "task_id": task_id,
                "item_id": item.item_id,
                "issue_type": "BUY_UOM_ERROR",
                "severity": severity,
                "detail": json.dumps({
                    "expected": expected_option,
                    "available": sorted(option_values),
                    "infor_item_number": getattr(item, "infor_item_number", None),
                    "intention": item_intention,
                }),
            })

    if updates:
        task_repo.update_items_bulk(updates)
    if candidate_updates:
        task_repo.update_item_matches_bulk(candidate_updates)
    task_repo.add_preprocess_issues_bulk(pending_issue_records)

    state["buy_uom_check_done"] = True
    state["status"] = Status.PENDING_FINALIZATION
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.PENDING_FINALIZATION)
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

    Gate-keeper: in ``explicit`` precheck mode we first reconcile dup state
    across all input rows. If any open ``DUPLICATE_ITEM_ERROR`` remains the
    pipeline is blocked so the user resolves duplicates before re-running.
    """
    task = task_repo.get_task(task_id)
    precheck_mode = (getattr(task, "precheck_mode", None) or "default").lower()
    if precheck_mode == "explicit":
        dup_summary = _recompute_explicit_duplicates(task_id)
        if dup_summary.get("dup_groups"):
            count = sum(len(g["item_ids"]) for g in dup_summary["dup_groups"])
            raise ValueError(
                f"Cannot re-preprocess: {count} row(s) across "
                f"{len(dup_summary['dup_groups'])} duplicate group(s) must be "
                "resolved (Edit UOM/QOE or Delete) before re-running."
            )

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
    decision: str,
    decided_by: str,
    state_machine: TaskStateMachine,
) -> dict:
    """Apply a tri-state contract decision (INCLUDE | EXCLUDE | REPLACE).

    INCLUDE / REPLACE flip every match under the scope to ACCEPTED;
    EXCLUDE flips them to REJECTED. REPLACE additionally persists a
    PreprocessorContractDecision row so the export step knows to also
    append unmatched CCX lines on this contract to the review sheet.
    """
    decision = (decision or "").upper()
    if decision not in task_repo.CONTRACT_DECISION_VALUES:
        raise ValueError(
            f"decision must be one of {task_repo.CONTRACT_DECISION_VALUES}"
        )

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
    match_status = "REJECTED" if decision == "EXCLUDE" else "ACCEPTED"
    for m in matches:
        task_repo.update_match_decision(m.match_id, match_status, decided_by)

    task_repo.upsert_contract_decision(
        task_id,
        organization_eid,
        contract_number,
        erp_vendor_id,
        decision,
        decided_by,
    )

    state = state_machine.get_state(task_id)
    state["ccx_decisions_done"] = True
    state_machine.save_state(task_id, state)

    return {
        "contract_number": contract_number,
        "organization_eid": organization_eid,
        "erp_vendor_id": erp_vendor_id,
        "decision": decision,
        "match_status": match_status,
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
        resolution_action="NOTED",
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


def resolve_buy_uom_edit(
    task_id: str,
    issue_id: int,
    new_uom: str,
    new_qoe,
    decided_by: str,
) -> dict:
    """Edit the input UOM/QOE to resolve a BUY_UOM_ERROR/BUY_UOM_WARN issue.

    Validation mirrors PC1: standardize the UOM, translate to its Lawson form,
    check it against the valid-UOM reference, parse QOE as a positive int, and
    enforce the same UOM/QOE compatibility rules. On success, updates the
    PreprocessorTaskItem (uom, uom_to_match_infor, qoe), refreshes
    input_ea_price on every related PreprocessorMatchResult row (it depends on
    QOE), then re-runs the buy-UOM check for this item alone. The issue is
    resolved when the new UOM*QOE combination matches an Infor option.
    """
    from . import intake_service  # local import to avoid circular dependency
    issue = task_repo.get_preprocess_issue(issue_id)
    if not issue or issue.task_id != task_id:
        raise ValueError("Issue not found")
    if issue.issue_type not in ("BUY_UOM_ERROR", "DUPLICATE_ITEM_ERROR") or issue.resolved:
        raise ValueError("Issue not eligible for EDIT_UOM_QOE")

    raw_uom = (new_uom or "").strip()
    if not raw_uom:
        raise ValueError("UOM is required")
    std_uom, _ = intake_service._standardize_uom(raw_uom)
    uom_map = intake_service._load_uom_to_match_infor_map()
    uom_to_match_infor = intake_service._translate_uom_to_match_infor(std_uom, uom_map)
    validated_uom = uom_to_match_infor or std_uom
    valid_uoms = intake_service._load_valid_uoms()
    if not validated_uom or validated_uom not in valid_uoms:
        raise ValueError(f"UOM '{validated_uom or raw_uom}' is not in the valid UOM reference")

    try:
        qoe_val = int(new_qoe)
    except (TypeError, ValueError):
        raise ValueError("QOE must be an integer")
    if qoe_val <= 0:
        raise ValueError("QOE must be positive")

    compat_errors = [
        detail
        for _etype, detail, severity in intake_service._check_qoe_uom_compat(validated_uom, qoe_val)
        if severity == "ERROR"
    ]
    if compat_errors:
        raise ValueError("; ".join(compat_errors))

    item = task_repo.get_task_item(issue.item_id)
    if not item:
        raise ValueError("Item not found")

    task_repo.update_items_bulk([{
        "item_id": issue.item_id,
        "uom": std_uom,
        "uom_to_match_infor": uom_to_match_infor or None,
        "qoe": qoe_val,
    }])

    # input_ea_price on related match rows is derived from input price and qoe.
    new_input_ea = None
    if item.unit_price is not None and qoe_val:
        try:
            new_input_ea = round(float(item.unit_price) / qoe_val, 4)
        except (TypeError, ValueError, ZeroDivisionError):
            new_input_ea = None
    task_repo.update_match_input_ea_price(task_id, issue.item_id, new_input_ea)

    expected_option = f"{validated_uom}*{qoe_val}"
    item_numbers = _split_multi_value_items(item.infor_item_number)
    aggregate_options: set[str] = set()
    with _sql_session() as sess:
        for n in item_numbers:
            aggregate_options.update(_query_buy_uom_options(sess, n))
    options_str = ", ".join(sorted(aggregate_options)) if aggregate_options else None
    task_repo.update_items_bulk([{
        "item_id": issue.item_id,
        "infor_buy_uom_options": options_str,
    }])

    task = task_repo.get_task(task_id)
    intention = _intention_for_item(item, task)
    is_expire = intention == "EXPIRE"
    precheck_mode = (getattr(task, "precheck_mode", None) or "default").lower()
    buy_uom_passed = expected_option in aggregate_options

    # Update the BUY_UOM_ERROR issue (if any) to reflect this edit attempt.
    buy_uom_issue_id = issue_id if issue.issue_type == "BUY_UOM_ERROR" else None
    if buy_uom_issue_id is None:
        # Editing from a DUPLICATE_ITEM_ERROR — find the open BUY_UOM_ERROR for
        # this item, if one exists, to attach the edit attempt to.
        for other in task_repo.get_preprocess_issues(task_id, include_resolved=False):
            if other.resolved or other.item_id != issue.item_id:
                continue
            if other.issue_type == "BUY_UOM_ERROR":
                buy_uom_issue_id = other.issue_id
                break

    if buy_uom_issue_id is not None:
        bu_issue = task_repo.get_preprocess_issue(buy_uom_issue_id)
        try:
            bu_detail = json.loads((bu_issue.detail if bu_issue else "") or "{}")
        except (TypeError, ValueError):
            bu_detail = {}
        edits = bu_detail.get("edit_attempts") or []
        edits.append({
            "edited_at": ny_now().isoformat(),
            "edited_by": decided_by,
            "uom": std_uom,
            "uom_to_match_infor": uom_to_match_infor or None,
            "qoe": qoe_val,
            "expected": expected_option,
            "passed": buy_uom_passed,
        })
        bu_detail["edit_attempts"] = edits
        bu_detail["expected"] = expected_option
        bu_detail["available"] = sorted(aggregate_options)

        if buy_uom_passed:
            task_repo.resolve_preprocess_issue(
                issue_id=buy_uom_issue_id,
                resolution_action="EDIT_UOM_QOE",
                resolved_by=decided_by,
                detail=json.dumps(bu_detail),
            )
        else:
            task_repo.update_preprocess_issue(
                issue_id=buy_uom_issue_id,
                severity="WARN" if is_expire else "ERROR",
                detail=json.dumps(bu_detail),
            )
    elif not buy_uom_passed:
        # No prior BUY_UOM_ERROR but the edit fails buy_uom — raise one.
        task_repo.upsert_preprocess_issue(
            task_id=task_id,
            item_id=issue.item_id,
            issue_type="BUY_UOM_ERROR",
            severity="WARN" if is_expire else "ERROR",
            detail=json.dumps({
                "expected": expected_option,
                "available": sorted(aggregate_options),
                "infor_item_number": item.infor_item_number,
                "intention": intention,
                "raised_after": "EDIT_UOM_QOE",
            }),
        )

    # Recompute task-wide explicit-mode duplicates. This reconciles the
    # DUPLICATE_ITEM_ERROR issue set across all rows (including the partner
    # of the edited row) and updates each affected item's status from the
    # current open-issue set.
    dup_summary = {"dup_groups": []}
    if precheck_mode == "explicit":
        dup_summary = _recompute_explicit_duplicates(
            task_id, force_item_ids={issue.item_id}
        )
    else:
        # Outside explicit mode, just reconcile the edited item's status.
        types_open = set()
        buy_uom_sev = "ERROR"
        for iss in task_repo.get_preprocess_issues(task_id, include_resolved=False):
            if iss.resolved or iss.item_id != issue.item_id:
                continue
            types_open.add(iss.issue_type)
            if iss.issue_type == "BUY_UOM_ERROR":
                buy_uom_sev = (iss.severity or "ERROR").upper()
        new_status = _derive_item_status(types_open, buy_uom_sev)
        task_repo.update_items_bulk([{"item_id": issue.item_id, "status": new_status}])

    final_item = task_repo.get_task_item(issue.item_id)
    final_status = final_item.status if final_item else Status.ITEM_PREPROCESSED
    in_dup = any(
        issue.item_id in group.get("item_ids", [])
        for group in dup_summary.get("dup_groups", [])
    )

    return {
        "issue_id": issue_id,
        "passed": buy_uom_passed and not in_dup,
        "buy_uom_passed": buy_uom_passed,
        "in_duplicate_group": in_dup,
        "item_status": final_status,
        "uom": std_uom,
        "uom_to_match_infor": uom_to_match_infor or None,
        "qoe": qoe_val,
    }


def soft_delete_preprocess_item(task_id: str, item_id: int, decided_by: str) -> dict:
    """Soft-delete an item from Phase 3 (mark DELETED_PREPROCESS).

    Resolves all open Phase-3 issues for the item, refreshes match-result
    rows so it stops contributing downstream, and re-runs explicit-mode dup
    recompute so a partner row whose only collision was with the deleted
    row clears its ``DUPLICATE_ITEM_ERROR``.
    """
    item = task_repo.get_task_item(item_id)
    if not item or item.task_id != task_id:
        raise ValueError("Item not found")
    if item.source_dataset != "INPUT":
        raise ValueError("Only input items can be deleted from preprocess")

    ok = task_repo.soft_delete_item_phase3(item_id, resolved_by=decided_by)
    if not ok:
        raise ValueError("Item not found")

    # Drop derived match-result rows for this input item so it no longer
    # influences downstream phases.
    task_repo.delete_match_results(task_id, input_item_id=item_id)

    task = task_repo.get_task(task_id)
    precheck_mode = (getattr(task, "precheck_mode", None) or "default").lower()
    dup_summary = {"dup_groups": []}
    if precheck_mode == "explicit":
        dup_summary = _recompute_explicit_duplicates(task_id)

    return {
        "deleted": item_id,
        "status": Status.DELETED_PREPROCESS,
        "dup_groups": dup_summary.get("dup_groups", []),
    }


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


def _get_unresolved_preprocess_issues(task_id: str) -> list:
    return [
        issue
        for issue in task_repo.get_preprocess_issues(task_id, include_resolved=False)
        if (issue.severity or "").upper() in ("ERROR", "WARN")
    ]


def _summarize_issue_severities(issues: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        severity = (issue.severity or "UNKNOWN").upper()
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _mark_resolved_preprocess_items_complete(task_id: str, unresolved_item_ids: set[int] | None = None) -> None:
    unresolved_item_ids = unresolved_item_ids or set()
    input_items = _live_input_items(task_id)
    updates = [
        {"item_id": item.item_id, "status": Status.ITEM_PREPROCESSED}
        for item in input_items
        if item.item_id not in unresolved_item_ids
        and "ERROR" not in str(getattr(item, "status", "")).upper()
    ]
    if updates:
        task_repo.update_items_bulk(updates)


def _complete_preprocess_and_advance(
    task_id: str,
    state_machine: TaskStateMachine,
    user: str,
    status_notes: str,
) -> dict:
    task = task_repo.get_task(task_id)
    if not task or task.phase != Phase.PREPROCESS:
        state = state_machine.get_state(task_id)
        return {"phase": state.get("phase"), "status": state.get("status"), "advanced": False}

    state = state_machine.get_state(task_id)
    if state.get("phase") != Phase.PREPROCESS:
        state["phase"] = Phase.PREPROCESS
        state_machine.save_state(task_id, state)

    if state.get("status") != Status.PREPROCESSED:
        state_machine.update_status(
            task_id,
            Status.PREPROCESSED,
            changed_by=user,
            notes=status_notes,
        )

    new_state = state_machine.advance(
        task_id,
        Phase.DEDUP,
        changed_by=user,
        notes="Preprocess complete, advancing to Dedup",
    )

    # Materialize the Phase 4 dedup workspace eagerly so the user lands on
    # /dedup/<task_id> with rows already populated. The populator is
    # idempotent; if rows exist (e.g. a re-advance after manual rollback)
    # this is a no-op.
    try:
        from .dedup_workspace import populate_dedup_workspace
        populate_dedup_workspace(task_id)
    except Exception as exc:  # pragma: no cover — log and continue
        logger.exception("Dedup workspace populate failed for task %s: %s", task_id, exc)

    return {"phase": new_state["phase"], "status": new_state["status"], "advanced": True}


def maybe_auto_advance_preprocess(task_id: str, state_machine: TaskStateMachine, user: str) -> dict | None:
    """Advance to Dedup after the last preprocess issue is cleared."""
    task = task_repo.get_task(task_id)
    if not task or task.phase != Phase.PREPROCESS:
        return None

    task_repo.reaggregate_cascade_statuses(task_id)
    pending_matches = [
        m for m in task_repo.get_match_results(task_id)
        if (m.match_status or "").upper() == "PENDING"
    ]
    if pending_matches or _get_unresolved_preprocess_issues(task_id):
        return None

    # Zero-viable guard: don't silently advance an empty task. Log and skip.
    if not _live_input_items(task_id):
        state = state_machine.get_state(task_id)
        task_repo.add_status_log(
            task_id=task_id,
            old_phase=Phase.PREPROCESS,
            new_phase=Phase.PREPROCESS,
            old_status=state.get("status"),
            new_status=state.get("status"),
            changed_by=user,
            notes="Auto-advance skipped: task has 0 viable items to move forward (all input rows soft-deleted).",
        )
        return None

    _mark_resolved_preprocess_items_complete(task_id)
    return _complete_preprocess_and_advance(
        task_id,
        state_machine,
        user,
        "All preprocess issues resolved",
    )


def finalize_preprocess(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """Mark preprocess complete.

    PENDING match decisions still hard-block (the user must accept or reject
    every match first). Unresolved ERROR/WARN item issues, however, leave
    the task in ON_HOLD_PREPROCESS - still in PREPROCESS phase - so the
    user can navigate to /tasks/<task_id> and resolve them. Calling finalize
    again after they're cleared advances the phase to DEDUP.
    """
    # Zero-viable guard: every input row was soft-deleted. Block advance and
    # leave a status_log entry so the task history records why.
    if not _live_input_items(task_id):
        state = state_machine.get_state(task_id)
        msg = "Cannot advance to Dedup: task has 0 viable items to move forward (all input rows soft-deleted)."
        task_repo.add_status_log(
            task_id=task_id,
            old_phase=Phase.PREPROCESS,
            new_phase=Phase.PREPROCESS,
            old_status=state.get("status"),
            new_status=state.get("status"),
            changed_by=user,
            notes=msg,
        )
        raise ValueError(msg)

    # Self-heal: cascade rows are aggregated from their CCX sources at creation;
    # if those sources were decided afterwards the rollup may be stale. Re-run
    # before checking PENDING so we don't block on aggregation lag.
    task_repo.reaggregate_cascade_statuses(task_id)

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

    unresolved_issues = _get_unresolved_preprocess_issues(task_id)
    unresolved_item_ids = {issue.item_id for issue in unresolved_issues}
    _mark_resolved_preprocess_items_complete(task_id, unresolved_item_ids)

    if unresolved_issues:
        severity_counts = _summarize_issue_severities(unresolved_issues)
        severity_summary = ", ".join(
            f"{count} {severity}" for severity, count in sorted(severity_counts.items())
        )
        state_machine.update_status(
            task_id,
            Status.ON_HOLD_PREPROCESS,
            changed_by=user,
            notes=f"Preprocess complete with {len(unresolved_issues)} unresolved issue(s): {severity_summary}",
        )
        return {
            "phase": Phase.PREPROCESS,
            "status": Status.ON_HOLD_PREPROCESS,
            "unresolved_count": len(unresolved_issues),
            "unresolved_by_severity": severity_counts,
            "item_ids": sorted(unresolved_item_ids),
        }

    return _complete_preprocess_and_advance(
        task_id,
        state_machine,
        user,
        "Preprocess complete",
    )
