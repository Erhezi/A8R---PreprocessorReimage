"""Task repository — ORM CRUD for Task, TaskItem, PreCheckError, MatchResult, TaskStatusLog.

Uses the SQL Server engine. Framework-agnostic (no Flask imports).
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Task, TaskItem, PreCheckError, MatchResult, TaskStatusLog, ItemMatchCandidate
from ..common.utils import ny_now
from .engine import get_sqlserver_engine


def _session() -> Session:
    return Session(get_sqlserver_engine())


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------
def create_task(
    process_type: str,
    source_type: str,
    organization: str,
    intention: str,
    intake_mode: str = "SINGLE",
    contract_number: Optional[str] = None,
    vendor_id: Optional[str] = None,
    purchase_from_loc: Optional[str] = None,
    erp_vendor_name: Optional[str] = None,
    purchase_from_loc_name: Optional[str] = None,
    oem_name: Optional[str] = None,
    mixed_intention: bool = False,
    contract_start_date=None,
    contract_end_date=None,
    notes: Optional[str] = None,
    wrike_id: Optional[str] = None,
    created_by: str = "",
) -> Task:
    """Insert a new Task and return it with the generated task_id."""
    with _session() as s:
        task = Task(
            task_id=uuid.uuid4().hex[:4].upper(),
            intake_mode=intake_mode,
            contract_number=contract_number,
            vendor_id=vendor_id,
            purchase_from_loc=purchase_from_loc,
            erp_vendor_name=erp_vendor_name,
            purchase_from_loc_name=purchase_from_loc_name,
            process_type=process_type,
            source_type=source_type,
            organization=organization,
            oem_name=oem_name,
            intention=intention,
            mixed_intention=mixed_intention,
            contract_start_date=contract_start_date,
            contract_end_date=contract_end_date,
            notes=notes,
            wrike_id=wrike_id,
            created_by=created_by,
        )
        s.add(task)
        s.commit()
        s.refresh(task)
        # Detach so caller can use outside session
        s.expunge(task)
        return task


def get_task(task_id: str) -> Optional[Task]:
    with _session() as s:
        task = s.get(Task, task_id)
        if task:
            s.expunge(task)
        return task


def list_tasks(
    created_by: Optional[str] = None,
    phase: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Task]:
    with _session() as s:
        q = s.query(Task)
        if created_by:
            q = q.filter(Task.created_by == created_by)
        if phase:
            q = q.filter(Task.phase == phase)
        if status:
            q = q.filter(Task.status == status)
        q = q.order_by(Task.created_at.desc()).offset(offset).limit(limit)
        tasks = q.all()
        for t in tasks:
            s.expunge(t)
        return tasks


def update_task_phase(task_id: str, phase: str, status: str) -> None:
    with _session() as s:
        task = s.get(Task, task_id)
        if task:
            task.phase = phase
            task.status = status
            task.updated_at = ny_now()
            s.commit()


def update_task_fields(task_id: str, **kwargs) -> None:
    """Update arbitrary fields on a Task."""
    with _session() as s:
        task = s.get(Task, task_id)
        if task:
            for k, v in kwargs.items():
                if hasattr(task, k):
                    setattr(task, k, v)
            task.updated_at = ny_now()
            s.commit()


def delete_task(task_id: str) -> bool:
    with _session() as s:
        # Check existence first
        task = s.get(Task, task_id)
        if not task:
            return False
        # Delete children with raw SQL to avoid ORM lazy-loading relationships
        # (some child tables may have columns not yet in DB; raw DELETE is safe
        # because it never SELECTs — it just removes rows if they exist).
        child_tables = [
            "[Preprocessor].PreprocessorItemMatching",
            "[Preprocessor].PreprocessorMatchResult",
            "[Preprocessor].PreprocessorPreCheckError",
            "[Preprocessor].PreprocessorTaskStatusLog",
            "[Preprocessor].PreprocessorTaskItem",
        ]
        for tbl in child_tables:
            s.execute(text(f"DELETE FROM {tbl} WHERE task_id = :tid"), {"tid": task_id})
        s.execute(text("DELETE FROM [Preprocessor].PreprocessorTask WHERE task_id = :tid"), {"tid": task_id})
        s.commit()
        return True


# ---------------------------------------------------------------------------
# TaskItem CRUD
# ---------------------------------------------------------------------------
def add_items(task_id: str, items: list[dict]) -> list[TaskItem]:
    """Bulk insert items for a task. Each dict should match TaskItem columns."""
    with _session() as s:
        db_items = []
        for item_data in items:
            item = TaskItem(task_id=task_id, **item_data)
            s.add(item)
            db_items.append(item)
        s.commit()
        for it in db_items:
            s.refresh(it)
            s.expunge(it)
        return db_items

def delete_items_for_task(task_id: str) -> int:
    """Delete all items for a task. Returns count of deleted rows.

    Pre-check errors reference task items via a FK on item_id, so errors
    must be deleted first (child before parent) to avoid a FK constraint
    violation from SQL Server.
    """
    with _session() as s:
        s.query(ItemMatchCandidate).filter(ItemMatchCandidate.task_id == task_id).delete()
        # 1. Child table first — errors reference item_id
        s.query(PreCheckError).filter(PreCheckError.task_id == task_id).delete()
        # 2. Parent table second
        count = s.query(TaskItem).filter(TaskItem.task_id == task_id).delete()
        s.commit()
        return count

def delete_item(item_id: int) -> bool:
    """Delete a single item and its associated pre-check errors.

    Deletes child errors first to avoid FK constraint violations.
    Returns True if the item existed and was deleted.
    """
    with _session() as s:
        s.query(ItemMatchCandidate).filter(ItemMatchCandidate.item_id == item_id).delete()
        s.query(PreCheckError).filter(PreCheckError.item_id == item_id).delete()
        count = s.query(TaskItem).filter(TaskItem.item_id == item_id).delete()
        s.commit()
        return count > 0


def soft_delete_item(item_id: int) -> bool:
    """Mark an item as DELETED_PC1 and resolve its errors."""
    with _session() as s:
        item = s.get(TaskItem, item_id)
        if not item:
            return False
        item.status = "DELETED_PC1"
        item.updated_at = ny_now()
        s.query(PreCheckError).filter(
            PreCheckError.item_id == item_id,
            PreCheckError.resolved == False,
        ).update({"resolved": True, "resolved_by": "SOFT_DELETE", "resolved_at": ny_now()},
                 synchronize_session="fetch")
        s.commit()
        return True


def update_dup_error_details(task_id: str, item_ids: list[int], new_detail: str) -> None:
    """Update error_detail for all unresolved DUPLICATE-type errors for given items."""
    with _session() as s:
        s.query(PreCheckError).filter(
            PreCheckError.task_id == task_id,
            PreCheckError.item_id.in_(item_ids),
            PreCheckError.error_type.like("DUPLICATE%"),
            PreCheckError.resolved == False,
        ).update({"error_detail": new_detail}, synchronize_session="fetch")
        s.commit()


def get_items(task_id: str, status: Optional[str] = None) -> list[TaskItem]:
    with _session() as s:
        q = s.query(TaskItem).filter(TaskItem.task_id == task_id)
        if status:
            q = q.filter(TaskItem.status == status)
        q = q.order_by(TaskItem.file_row)
        items = q.all()
        for it in items:
            s.expunge(it)
        return items


def update_item_status(item_id: int, status: str, error_message: Optional[str] = None) -> None:
    with _session() as s:
        item = s.get(TaskItem, item_id)
        if item:
            item.status = status
            item.error_message = error_message
            item.updated_at = ny_now()
            s.commit()


def update_items_bulk(updates: list[dict], **kwargs) -> None:
    """Update fields on multiple items.

    *updates* is a list of dicts, each containing an ``item_id`` key and
    the column values to set.  If called with plain ``item_ids`` + keyword
    args (legacy), the keyword values are applied uniformly.
    """
    with _session() as s:
        for entry in updates:
            iid = entry.get("item_id") if isinstance(entry, dict) else entry
            fields = {k: v for k, v in entry.items() if k != "item_id"} if isinstance(entry, dict) else kwargs
            item = s.get(TaskItem, iid)
            if item:
                for k, v in fields.items():
                    if hasattr(item, k):
                        setattr(item, k, v)
                item.updated_at = ny_now()
        s.commit()


def delete_item_matches_for_task(task_id: str) -> int:
    with _session() as s:
        count = s.query(ItemMatchCandidate).filter(ItemMatchCandidate.task_id == task_id).delete()
        s.commit()
        return count


def add_item_matches_bulk(matches: list[dict]) -> list[ItemMatchCandidate]:
    with _session() as s:
        db_matches = []
        for match_data in matches:
            candidate = ItemMatchCandidate(**match_data)
            s.add(candidate)
            db_matches.append(candidate)
        s.commit()
        for candidate in db_matches:
            s.refresh(candidate)
            s.expunge(candidate)
        return db_matches


def get_item_matches(task_id: str) -> list[ItemMatchCandidate]:
    with _session() as s:
        matches = (
            s.query(ItemMatchCandidate)
            .filter(ItemMatchCandidate.task_id == task_id)
            .order_by(ItemMatchCandidate.item_id, ItemMatchCandidate.infor_item_number)
            .all()
        )
        for match in matches:
            s.expunge(match)
        return matches


# ---------------------------------------------------------------------------
# PreCheckError CRUD
# ---------------------------------------------------------------------------
def add_precheck_error(
    task_id: str,
    item_id: Optional[int],
    phase: str,
    error_type: str,
    error_detail: Optional[str] = None,
) -> PreCheckError:
    with _session() as s:
        err = PreCheckError(
            task_id=task_id,
            item_id=item_id,
            phase=phase,
            error_type=error_type,
            error_detail=error_detail,
        )
        s.add(err)
        s.commit()
        s.refresh(err)
        s.expunge(err)
        return err


def get_precheck_errors(task_id: str, phase: Optional[str] = None, resolved: Optional[bool] = None) -> list[PreCheckError]:
    with _session() as s:
        q = s.query(PreCheckError).filter(PreCheckError.task_id == task_id)
        if phase:
            q = q.filter(PreCheckError.phase == phase)
        if resolved is not None:
            q = q.filter(PreCheckError.resolved == resolved)
        errors = q.all()
        for e in errors:
            s.expunge(e)
        return errors


def resolve_precheck_error(error_id: int, resolved_by: str) -> None:
    with _session() as s:
        err = s.get(PreCheckError, error_id)
        if err:
            err.resolved = True
            err.resolved_by = resolved_by
            err.resolved_at = ny_now()
            s.commit()


# ---------------------------------------------------------------------------
# MatchResult CRUD
# ---------------------------------------------------------------------------
def delete_match_results(task_id: str, matched_source: Optional[str] = None) -> int:
    """Delete match results for a task. Optionally filter by source (CCX, INFOR_CL, etc.).

    Returns count of deleted rows.
    """
    with _session() as s:
        q = s.query(MatchResult).filter(MatchResult.task_id == task_id)
        if matched_source:
            q = q.filter(MatchResult.matched_source == matched_source)
        count = q.delete()
        s.commit()
        return count


def add_match_result(
    task_id: str,
    input_item_id: int,
    matched_source: str,
    matched_item_ref: Optional[str] = None,
    similarity_score: Optional[float] = None,
    similarity_bucket: Optional[str] = None,
) -> MatchResult:
    with _session() as s:
        mr = MatchResult(
            task_id=task_id,
            input_item_id=input_item_id,
            matched_source=matched_source,
            matched_item_ref=matched_item_ref,
            similarity_score=similarity_score,
            similarity_bucket=similarity_bucket,
        )
        s.add(mr)
        s.commit()
        s.refresh(mr)
        s.expunge(mr)
        return mr


def add_match_results_bulk(task_id: str, matches: list[dict]) -> list[MatchResult]:
    """Bulk insert match results for a task. Each dict should have MatchResult columns."""
    with _session() as s:
        db_matches = []
        for m in matches:
            mr = MatchResult(task_id=task_id, **m)
            s.add(mr)
            db_matches.append(mr)
        s.commit()
        for mr in db_matches:
            s.refresh(mr)
            s.expunge(mr)
        return db_matches


def get_match_results(task_id: str, matched_source: Optional[str] = None) -> list[MatchResult]:
    with _session() as s:
        q = s.query(MatchResult).filter(MatchResult.task_id == task_id)
        if matched_source:
            q = q.filter(MatchResult.matched_source == matched_source)
        results = q.all()
        for r in results:
            s.expunge(r)
        return results


def get_match_results_by_contract(task_id: str) -> dict[str, list[MatchResult]]:
    """Return match results grouped by contract_number."""
    with _session() as s:
        results = (
            s.query(MatchResult)
            .filter(MatchResult.task_id == task_id)
            .order_by(MatchResult.contract_number)
            .all()
        )
        grouped: dict[str, list[MatchResult]] = {}
        for r in results:
            s.expunge(r)
            key = r.contract_number or "__no_contract__"
            grouped.setdefault(key, []).append(r)
        return grouped


def get_accepted_ccx_pkids(task_id: str) -> list[int]:
    """Get ccx_pkid values for ACCEPTED CCX matches."""
    with _session() as s:
        rows = (
            s.query(MatchResult.ccx_pkid)
            .filter(
                MatchResult.task_id == task_id,
                MatchResult.matched_source == "CCX",
                MatchResult.match_status == "ACCEPTED",
                MatchResult.ccx_pkid.isnot(None),
            )
            .distinct()
            .all()
        )
        return [r[0] for r in rows]


def get_rejected_ccx_pkids(task_id: str) -> list[int]:
    """Get ccx_pkid values for REJECTED CCX matches."""
    with _session() as s:
        rows = (
            s.query(MatchResult.ccx_pkid)
            .filter(
                MatchResult.task_id == task_id,
                MatchResult.matched_source == "CCX",
                MatchResult.match_status == "REJECTED",
                MatchResult.ccx_pkid.isnot(None),
            )
            .distinct()
            .all()
        )
        return [r[0] for r in rows]


def _parse_ccx_pkid_list(value: Optional[str]) -> list[int]:
    if not value:
        return []
    parsed = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parsed.append(int(chunk))
        except ValueError:
            continue
    return parsed


def _aggregate_cascade_status(source_matches: list[MatchResult]) -> str:
    if not source_matches:
        return "PENDING"
    if len(source_matches) > 1:
        return "PENDING"
    return (source_matches[0].match_status or "PENDING").upper()


def _aggregate_cascade_bucket(source_matches: list[MatchResult]) -> Optional[str]:
    priority = {"HIGH": 3, "MED": 2, "LOW": 1}
    selected_bucket = None
    selected_score = None
    for match in source_matches:
        bucket = (match.similarity_bucket or "").upper()
        score = priority.get(bucket, 0)
        if score <= 0:
            continue
        if selected_score is None or score < selected_score:
            selected_bucket = bucket or None
            selected_score = score
    return selected_bucket


_UNSET = object()


def get_items_by_source(task_id: str, source_dataset: str) -> list[TaskItem]:
    """Fetch items for a task filtered by source_dataset (INPUT | CCX | INFOR)."""
    with _session() as s:
        items = (
            s.query(TaskItem)
            .filter(TaskItem.task_id == task_id, TaskItem.source_dataset == source_dataset)
            .order_by(TaskItem.file_row)
            .all()
        )
        for it in items:
            s.expunge(it)
        return items


def update_match_decision(
    match_id: int,
    match_status: str,
    reviewed_by: str,
    llm_confidence: Optional[int] | object = _UNSET,
    llm_reason: Optional[str] | object = _UNSET,
) -> None:
    with _session() as s:
        mr = s.get(MatchResult, match_id)
        if mr:
            mr.match_status = match_status
            mr.reviewed_by = reviewed_by
            mr.reviewed_at = ny_now()
            if llm_confidence is not _UNSET:
                mr.llm_confidence = llm_confidence
            if llm_reason is not _UNSET:
                mr.llm_reason = llm_reason

            if mr.matched_source == "CCX" and mr.ccx_pkid is not None:
                linked_rows = (
                    s.query(MatchResult)
                    .filter(
                        MatchResult.task_id == mr.task_id,
                        MatchResult.matched_source == "INFOR_CL",
                        MatchResult.match_type == "CASCADE",
                    )
                    .all()
                )
                for linked in linked_rows:
                    lineage_pkids = _parse_ccx_pkid_list(linked.ccx_pkids_matched)
                    effective_pkids = set(lineage_pkids or ([] if linked.ccx_pkid is None else [linked.ccx_pkid]))
                    if mr.ccx_pkid not in effective_pkids:
                        continue
                    source_rows = (
                        s.query(MatchResult)
                        .filter(
                            MatchResult.task_id == mr.task_id,
                            MatchResult.input_item_id == linked.input_item_id,
                            MatchResult.matched_source == "CCX",
                            MatchResult.ccx_pkid.in_(sorted(effective_pkids)),
                        )
                        .all()
                    )
                    linked.match_status = _aggregate_cascade_status(source_rows)
                    linked.similarity_bucket = _aggregate_cascade_bucket(source_rows)
                    linked.reviewed_by = reviewed_by
                    linked.reviewed_at = mr.reviewed_at
            s.commit()


# ---------------------------------------------------------------------------
# TaskStatusLog
# ---------------------------------------------------------------------------
def add_status_log(
    task_id: str,
    old_phase: Optional[str],
    new_phase: Optional[str],
    old_status: Optional[str],
    new_status: Optional[str],
    changed_by: str,
    notes: Optional[str] = None,
) -> TaskStatusLog:
    with _session() as s:
        log = TaskStatusLog(
            task_id=task_id,
            old_phase=old_phase,
            new_phase=new_phase,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by,
            notes=notes,
        )
        s.add(log)
        s.commit()
        s.refresh(log)
        s.expunge(log)
        return log


def get_status_log(task_id: str) -> list[TaskStatusLog]:
    with _session() as s:
        logs = (
            s.query(TaskStatusLog)
            .filter(TaskStatusLog.task_id == task_id)
            .order_by(TaskStatusLog.changed_at.desc())
            .all()
        )
        for l in logs:
            s.expunge(l)
        return logs
