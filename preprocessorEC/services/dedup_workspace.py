"""Phase 4 — dedup workspace populator.

Materializes one row per ACCEPTED match (CCX or INFOR_CL) into
``PreprocessorTaskItemForDecision`` so the dedup UI, integrity validator
and IM checks can operate on a stable, editable snapshot independent of
``PreprocessorMatchResult``.

The function is idempotent: it no-ops when rows already exist for the
task, so it is safe to call on advance and as a lazy guard on first
read.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy import bindparam
from sqlalchemy.orm import Session

from ..db.engine import get_sqlserver_engine
from ..db.sql_loader import load_query
from ..models import (
    MatchResult,
    Task,
    TaskItem,
    TaskItemForDecision,
)
from .dedup_resolution import (
    classify_group,
    default_actions,
    editable_for_side,
)


def _session() -> Session:
    return Session(get_sqlserver_engine())


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ea_price_from(unit_price, qoe) -> Optional[float]:
    """Per-EA price = unit_price / qoe, falling back to unit_price when qoe is 0/None."""
    up = _safe_float(unit_price)
    if up is None:
        return None
    try:
        q = int(qoe) if qoe is not None else 0
    except (TypeError, ValueError):
        q = 0
    if q <= 0:
        return up
    return up / q


def _fetch_contract_headers(
    session: Session, contract_ids: Iterable[str]
) -> dict[tuple[str, str], dict]:
    """Return {(norm(Organization), norm(ContractID)): {source_type, process_type}}."""
    contract_ids = sorted({(c or "").strip() for c in contract_ids if (c or "").strip()})
    if not contract_ids:
        return {}

    stmt = load_query("dedup", "dedup", query="contract_headers_by_org_contract")
    bound = stmt.bindparams(bindparam("contract_ids", expanding=True))
    rows = session.execute(bound, {"contract_ids": contract_ids}).mappings().all()

    out: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (_norm(row.get("Organization")), _norm(row.get("ContractID")))
        # First write wins; CCXInforSyncedContractHeader can have multiple
        # rows per (Org, Contract) for tier variants, but source/process
        # type are constant across them.
        if key not in out:
            out[key] = {
                "source_type": row.get("ContractSourceType"),
                "process_type": row.get("ContractProcessType"),
            }
    return out


def _fetch_infor_items(
    session: Session, infor_pkids: Iterable[str]
) -> dict[str, str]:
    """Return {Infor_pkid: Item} for the given pkids."""
    infor_pkids = sorted({(p or "").strip() for p in infor_pkids if (p or "").strip()})
    if not infor_pkids:
        return {}

    stmt = load_query("dedup", "dedup", query="infor_items_by_pkid")
    bound = stmt.bindparams(bindparam("infor_pkids", expanding=True))
    rows = session.execute(bound, {"infor_pkids": infor_pkids}).mappings().all()
    return {str(row.get("Infor_pkid")): (row.get("Item") or "") for row in rows}


def workspace_exists(task_id: str) -> bool:
    with _session() as s:
        row = s.execute(
            load_query("dedup", "dedup", query="workspace_exists"),
            {"task_id": task_id},
        ).first()
        return row is not None


def populate_dedup_workspace(task_id: str, *, force: bool = False) -> dict:
    """Materialize ACCEPTED matches into PreprocessorTaskItemForDecision.

    Idempotent — returns ``{created: 0, skipped: True}`` if rows already
    exist for the task and ``force`` is False. Pass ``force=True`` to
    wipe and rebuild (used by the Phase 4C "Reset to defaults" flow).
    """
    with _session() as session:
        if force:
            session.query(TaskItemForDecision).filter(
                TaskItemForDecision.task_id == task_id
            ).delete(synchronize_session=False)
            session.commit()
        else:
            existing = session.query(TaskItemForDecision.dedup_id).filter(
                TaskItemForDecision.task_id == task_id
            ).first()
            if existing:
                return {"created": 0, "skipped": True}

        task: Optional[Task] = session.get(Task, task_id)
        if not task:
            return {"created": 0, "skipped": False, "error": "task_not_found"}

        accepted_matches = (
            session.query(MatchResult)
            .filter(
                MatchResult.task_id == task_id,
                MatchResult.match_status == "ACCEPTED",
                MatchResult.matched_source.in_(["CCX", "INFOR_CL"]),
            )
            .all()
        )
        if not accepted_matches:
            return {"created": 0, "skipped": False}

        input_item_ids = {m.input_item_id for m in accepted_matches if m.input_item_id is not None}
        input_items: dict[int, TaskItem] = {}
        if input_item_ids:
            for item in (
                session.query(TaskItem)
                .filter(TaskItem.item_id.in_(input_item_ids))
                .all()
            ):
                input_items[item.item_id] = item

        # Pull contract headers (matched + input) in a single query keyed by
        # ContractID; we filter by Organization in Python.
        contract_ids: set[str] = {
            (m.contract_id_matched or "").strip()
            for m in accepted_matches
            if m.contract_id_matched
        }
        if task.contract_number:
            contract_ids.add(task.contract_number.strip())
        header_lookup = _fetch_contract_headers(session, contract_ids)

        # Resolve infor_item_matched via InforActiveCLRefCCXSyncedCL.Item.
        infor_pkids: set[str] = set()
        for m in accepted_matches:
            if m.infor_pkid:
                infor_pkids.add(m.infor_pkid)
            if m.infor_pkids_matched:
                for token in str(m.infor_pkids_matched).split(","):
                    token = token.strip()
                    if token:
                        infor_pkids.add(token)
        infor_item_lookup = _fetch_infor_items(session, infor_pkids)

        # Input header info — prefer header-table values, fall back to Task.
        input_header_key = (_norm(task.organization), _norm(task.contract_number))
        input_header = header_lookup.get(input_header_key, {})
        input_source_type = input_header.get("source_type") or task.source_type
        input_process_type = input_header.get("process_type") or task.process_type

        rows_to_insert: list[TaskItemForDecision] = []
        for m in accepted_matches:
            input_item = input_items.get(m.input_item_id) if m.input_item_id else None

            matched_key = (_norm(m.organization_matched), _norm(m.contract_id_matched))
            matched_header = header_lookup.get(matched_key, {})
            matched_source_type = matched_header.get("source_type")
            matched_process_type = matched_header.get("process_type")

            # Resolve infor_item_matched from the most reliable pkid.
            infor_item_matched = ""
            if m.infor_pkid:
                infor_item_matched = infor_item_lookup.get(m.infor_pkid, "") or ""
            if not infor_item_matched and m.infor_pkids_matched:
                for token in str(m.infor_pkids_matched).split(","):
                    token = token.strip()
                    if token and infor_item_lookup.get(token):
                        infor_item_matched = infor_item_lookup[token]
                        break

            # Per-row intention: prefer item-level when set (MIX tasks),
            # otherwise fall back to the task header.
            row_intention = (
                getattr(input_item, "intention", None)
                or task.intention
            )

            erp_vendor_id_input = (
                f"{task.vendor_id}-{task.purchase_from_loc}"
                if task.vendor_id and task.purchase_from_loc
                else (task.vendor_id or "")
            )

            organization_eid_input = getattr(input_item, "organization_eid", None)

            group = classify_group(
                input_org_eid=organization_eid_input,
                input_vendor=erp_vendor_id_input,
                input_contract=task.contract_number,
                matched_org_eid=m.organization_eid_matched,
                matched_vendor=m.erp_vendor_id_matched,
                matched_contract=m.contract_id_matched,
                # Input items don't currently carry organization_eid (it's
                # never written during intake), so pass the org NAME as a
                # fallback signal — see _orgs_equal in dedup_resolution.
                input_org_name=task.organization,
                matched_org_name=m.organization_matched,
            )
            default_in, default_match = default_actions(
                group=group,
                intention=row_intention,
                input_source_type=input_source_type,
                matched_source_type=matched_source_type,
                input_org_eid=organization_eid_input,
                matched_org_eid=m.organization_eid_matched,
            )

            # A row is editable only when both sides are LOCAL — that's the
            # only configuration where our system permits line-level edits.
            row_editable = (
                editable_for_side(input_source_type)
                and editable_for_side(matched_source_type)
            )

            ea_price_input = _safe_float(getattr(m, "input_ea_price", None))
            if ea_price_input is None and input_item is not None:
                ea_price_input = _ea_price_from(input_item.unit_price, input_item.qoe)

            # Decisions are locked whenever the default is 'keep' or 'drop' —
            # only 'any' lets the user toggle. Pre-stamp the locked value so
            # the workspace state is consistent and the finalize gate doesn't
            # need a special "default fills in for null" branch.
            input_decision_seed = default_in if default_in in ("keep", "drop") else None
            matched_decision_seed = default_match if default_match in ("keep", "drop") else None

            rows_to_insert.append(TaskItemForDecision(
                match_id=m.match_id,
                task_id=task_id,
                input_item_id=m.input_item_id,
                input_decision=input_decision_seed,
                matched_decision=matched_decision_seed,

                matched_source=m.matched_source,
                match_status=m.match_status,
                similarity_bucket=m.similarity_bucket,
                similarity_score=m.similarity_score,
                contract_id_matched=m.contract_id_matched,
                erp_vendor_id_matched=m.erp_vendor_id_matched,
                organization_eid_matched=m.organization_eid_matched,
                organization_matched=m.organization_matched,
                manufacturer_number_matched=m.manufacturer_number_matched,
                vendor_item_matched=m.vendor_item_matched,
                uom_matched=m.uom_matched,
                uom_to_match_infor_matched=m.uom_to_match_infor_matched,
                qoe_matched=m.qoe_matched,
                contract_price_matched=m.contract_price_matched,
                ea_price_matched=_safe_float(getattr(m, "match_ea_price", None)),
                item_desc_matched=m.item_desc_matched,
                infor_pkids_matched=m.infor_pkids_matched,
                infor_pkid=m.infor_pkid,
                infor_item_matched=infor_item_matched or "",
                match_type=m.match_type,
                pair_type=m.pair_type,
                llm_reason=m.llm_reason,
                llm_warning=getattr(m, "llm_warning", None),

                task_intention=row_intention,
                contract_id_input=task.contract_number,
                erp_vendor_id_input=erp_vendor_id_input,
                organization_eid_input=organization_eid_input,
                organization_input=task.organization,
                manufacturer_number_input=getattr(input_item, "mfg_catalog_num", None),
                vendor_item_input=getattr(input_item, "vendor_catalog_num", None),
                uom_input=getattr(input_item, "uom", None),
                uom_to_match_infor_input=getattr(input_item, "uom_to_match_infor", None),
                qoe_input=getattr(input_item, "qoe", None),
                contract_price_input=getattr(input_item, "unit_price", None),
                ea_price_input=ea_price_input,
                item_description_input=getattr(input_item, "description", None),
                infor_item_number=(getattr(input_item, "infor_item_number", None) or ""),

                matched_contract_source_type=matched_source_type,
                matched_contract_process_type=matched_process_type,
                input_contract_source_type=input_source_type,
                input_contract_process_type=input_process_type,

                editable=row_editable,
                resolution_grouping=group,
                default_action_input=default_in,
                default_action_matched=default_match,
            ))

        # dedup_sort: per input_item_id, ascending by ea_price_matched
        # (NULLs sort last). Stable on match_id as tiebreak so reruns don't
        # shuffle the order for a given task.
        by_input: dict[int, list[TaskItemForDecision]] = defaultdict(list)
        for row in rows_to_insert:
            by_input[row.input_item_id].append(row)
        for group_rows in by_input.values():
            group_rows.sort(
                key=lambda r: (
                    r.ea_price_matched is None,
                    r.ea_price_matched if r.ea_price_matched is not None else 0.0,
                    r.match_id,
                )
            )
            for sort_index, row in enumerate(group_rows):
                row.dedup_sort = sort_index

        session.bulk_save_objects(rows_to_insert)
        session.commit()

        return {"created": len(rows_to_insert), "skipped": False}
