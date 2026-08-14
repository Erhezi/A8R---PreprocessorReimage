"""Task repository — ORM CRUD for Task, TaskItem, PreCheckError, MatchResult, TaskStatusLog.

Uses the SQL Server engine. Framework-agnostic (no Flask imports).
"""

from __future__ import annotations

from functools import lru_cache
import uuid
from typing import Optional

from sqlalchemy import MetaData, Table, func, inspect, text
from sqlalchemy.orm import Session

from ..models import (
    Task,
    TaskItem,
    PreCheckError,
    MatchResult,
    TaskStatusLog,
    ItemMatchCandidate,
    PreprocessIssue,
    TaskItemForDecision,
    ContractDecision,
)
from ..state import Status
from ..common.utils import ny_now, SQLSERVER_IN_CHUNK as _IN_CLAUSE_CHUNK
from .engine import get_sqlserver_engine


def _session() -> Session:
    return Session(get_sqlserver_engine())


def _chunked(items: list, size: int = _IN_CLAUSE_CHUNK):
    """Yield successive ``size``-length slices of ``items``."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


@lru_cache(maxsize=1)
def _get_match_result_columns() -> set[str]:
    return {
        column["name"]
        for column in inspect(get_sqlserver_engine()).get_columns(
            "PreprocessorMatchResult",
            schema="Preprocessor",
        )
    }


@lru_cache(maxsize=1)
def _get_match_result_table() -> Table:
    metadata = MetaData()
    return Table(
        "PreprocessorMatchResult",
        metadata,
        schema="Preprocessor",
        autoload_with=get_sqlserver_engine(),
    )


def match_result_has_dedup_columns() -> bool:
    columns = _get_match_result_columns()
    return {
        "dedup_decision",
        "dedup_decided_by",
        "dedup_decided_at",
    }.issubset(columns)


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
    parent_task_id: Optional[str] = None,
    spawn_reason: Optional[str] = None,
    phase: Optional[str] = None,
    status: Optional[str] = None,
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
            parent_task_id=parent_task_id,
            spawn_reason=spawn_reason,
        )
        if phase:
            task.phase = phase
        if status:
            task.status = status
        s.add(task)
        s.commit()
        s.refresh(task)
        # Detach so caller can use outside session
        s.expunge(task)
        return task


def list_subtasks(parent_task_id: str) -> list[Task]:
    """Return tasks spawned from a given parent."""
    with _session() as s:
        tasks = (
            s.query(Task)
            .filter(Task.parent_task_id == parent_task_id)
            .order_by(Task.created_at.asc())
            .all()
        )
        for t in tasks:
            s.expunge(t)
        return tasks


def move_items_to_task(
    item_ids: list[int],
    target_task_id: str,
    move_pc1_errors: bool = True,
) -> int:
    """Re-assign TaskItem rows (and optionally their PC1 PreCheckError rows) to
    *target_task_id*. Returns the number of items moved.

    Used when splitting ERROR_PC1 items off into a sub-task: their item_id stays
    stable but task_id flips to the new sub-task so downstream queries scoped by
    task_id don't return stale rows.
    """
    if not item_ids:
        return 0
    with _session() as s:
        moved = (
            s.query(TaskItem)
            .filter(TaskItem.item_id.in_(item_ids))
            .update({TaskItem.task_id: target_task_id}, synchronize_session=False)
        )
        if move_pc1_errors:
            s.query(PreCheckError).filter(
                PreCheckError.item_id.in_(item_ids),
                PreCheckError.phase == "PC1",
            ).update({PreCheckError.task_id: target_task_id}, synchronize_session=False)
        s.commit()
        return moved


def get_task(task_id: str) -> Optional[Task]:
    with _session() as s:
        task = s.get(Task, task_id)
        if task:
            s.expunge(task)
        return task


def get_task_item(item_id: int) -> Optional[TaskItem]:
    with _session() as s:
        item = s.get(TaskItem, item_id)
        if item:
            s.expunge(item)
        return item


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


_TASK_CHILD_TABLES = [
    # TaskItemForDecision must come before MatchResult — its match_id FK
    # references MatchResult.match_id.
    "[Preprocessor].PreprocessorTaskItemForDecision",
    "[Preprocessor].PreprocessorItemMatching",
    "[Preprocessor].PreprocessorMatchResult",
    "[Preprocessor].PreprocessorIMCheckResult",
    "[Preprocessor].PreprocessorIntegrityIssue",
    "[Preprocessor].PreprocessorPreCheckError",
    "[Preprocessor].PreprocessorPreprocessIssue",
    "[Preprocessor].PreprocessorTaskStatusLog",
    "[Preprocessor].PreprocessorContractDecision",
    "[Preprocessor].PreprocessorTaskItem",
]


def _purge_task_rows(session, task_id: str) -> None:
    """Delete all child rows then the Task row itself for a single task_id.

    Raw SQL on purpose — it never SELECTs, so it tolerates schema columns the
    ORM doesn't know about. Order is important: item-linked tables before
    PreprocessorTaskItem, all task-children before the PreprocessorTask row.

    The OBJECT_ID guard skips tables that the ORM defines but haven't been
    created in this database yet (e.g. newer tables in older environments).
    """
    for tbl in _TASK_CHILD_TABLES:
        session.execute(
            text(
                f"IF OBJECT_ID(N'{tbl}', N'U') IS NOT NULL "
                f"DELETE FROM {tbl} WHERE task_id = :tid"
            ),
            {"tid": task_id},
        )
    session.execute(
        text("DELETE FROM [Preprocessor].PreprocessorTask WHERE task_id = :tid"),
        {"tid": task_id},
    )


def delete_task(task_id: str) -> bool:
    """Delete a root task and cascade-remove its entire sub-task family.

    A task with a non-null parent_task_id is treated as a sub-task and cannot
    be deleted on its own — callers must delete the root task to remove the
    whole lineage. Raises ValueError when the constraint is violated.

    Returns True if rows were removed, False if the task did not exist.
    """
    with _session() as s:
        task = s.get(Task, task_id)
        if not task:
            return False
        if task.parent_task_id:
            raise ValueError(
                f"Task {task_id} is a sub-task of {task.parent_task_id}. "
                f"Sub-tasks can only be deleted by deleting their root task."
            )

        # BFS to collect every descendant; reversing yields deepest-first so
        # the FK from child.parent_task_id to its parent is satisfied at each
        # delete step.
        descendants: list[str] = []
        frontier = [task_id]
        while frontier:
            next_frontier: list[str] = []
            for current in frontier:
                rows = s.execute(
                    text(
                        "SELECT task_id FROM [Preprocessor].PreprocessorTask "
                        "WHERE parent_task_id = :tid"
                    ),
                    {"tid": current},
                ).fetchall()
                for (child_id,) in rows:
                    descendants.append(child_id)
                    next_frontier.append(child_id)
            frontier = next_frontier

        for tid in reversed(descendants):
            _purge_task_rows(s, tid)
        _purge_task_rows(s, task_id)
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

    Item-linked child rows reference task items via item_id FKs, so those
    children must be deleted first (child before parent) to avoid SQL Server
    constraint violations.
    """
    with _session() as s:
        s.query(ItemMatchCandidate).filter(ItemMatchCandidate.task_id == task_id).delete()
        # 1. Child tables first — both tables reference item_id
        s.query(PreCheckError).filter(PreCheckError.task_id == task_id).delete()
        s.query(PreprocessIssue).filter(PreprocessIssue.task_id == task_id).delete()
        # 2. Parent table second
        count = s.query(TaskItem).filter(TaskItem.task_id == task_id).delete()
        s.commit()
        return count

def soft_delete_item(item_id: int) -> bool:
    """Mark an item as DELETED_PC1 and resolve its errors."""
    with _session() as s:
        item = s.get(TaskItem, item_id)
        if not item:
            return False
        item.status = Status.DELETED_PC1
        item.updated_at = ny_now()
        s.query(PreCheckError).filter(
            PreCheckError.item_id == item_id,
            PreCheckError.resolved == False,
        ).update({"resolved": True, "resolved_by": "SOFT_DELETE", "resolved_at": ny_now()},
                 synchronize_session="fetch")
        s.commit()
        return True


def soft_delete_item_phase3(item_id: int, resolved_by: str = "SOFT_DELETE") -> bool:
    """Mark an item as DELETED_PREPROCESS and resolve its open Phase-3 issues."""
    with _session() as s:
        item = s.get(TaskItem, item_id)
        if not item:
            return False
        item.status = Status.DELETED_PREPROCESS
        item.updated_at = ny_now()
        s.query(PreprocessIssue).filter(
            PreprocessIssue.item_id == item_id,
            PreprocessIssue.resolved == False,  # noqa: E712
        ).update(
            {
                "resolved": True,
                "resolved_by": resolved_by,
                "resolved_at": ny_now(),
                "resolution_action": "SOFT_DELETE",
            },
            synchronize_session="fetch",
        )
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


def get_items_by_statuses(task_id: str, statuses: list[str]) -> list[TaskItem]:
    """Return task items whose status is in *statuses*."""
    if not statuses:
        return []
    with _session() as s:
        items = (
            s.query(TaskItem)
            .filter(TaskItem.task_id == task_id, TaskItem.status.in_(statuses))
            .order_by(TaskItem.file_row)
            .all()
        )
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

    The list-of-dicts path uses ``bulk_update_mappings`` so a 5,000-row
    payload doesn't issue 5,000 SELECT+UPDATE round-trips.
    """
    if not updates:
        return
    now = ny_now()
    with _session() as s:
        if isinstance(updates[0], dict):
            allowed = {c.key for c in TaskItem.__table__.columns}
            payload = []
            for entry in updates:
                iid = entry.get("item_id")
                if iid is None:
                    continue
                row = {k: v for k, v in entry.items() if k in allowed}
                row["item_id"] = iid
                row.setdefault("updated_at", now)
                payload.append(row)
            if payload:
                s.bulk_update_mappings(TaskItem, payload)
        else:
            # Legacy path: list of bare item_ids + uniform kwargs
            for iid in updates:
                item = s.get(TaskItem, iid)
                if item:
                    for k, v in kwargs.items():
                        if hasattr(item, k):
                            setattr(item, k, v)
                    item.updated_at = now
        s.commit()


def update_task_and_items_manufacturer(
    task_id: str,
    manufacturer_code: str,
    manufacturer_name: str,
) -> int:
    """Set task-level manufacturer fields and stamp them on all task items.

    Returns the number of task item rows matched by the set-based update.
    """
    now = ny_now()
    with _session() as s:
        task = s.get(Task, task_id)
        if not task:
            return 0
        task.contract_manufacturer_infor = manufacturer_code
        task.contract_manufacturer_name_infor = manufacturer_name
        task.updated_at = now
        item_count = (
            s.query(TaskItem)
            .filter(TaskItem.task_id == task_id)
            .update(
                {
                    TaskItem.manufacturer_infor: manufacturer_code,
                    TaskItem.manufacturer_name_infor: manufacturer_name,
                    TaskItem.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        s.commit()
        return item_count


def copy_descriptions_to_standardized(task_id: str, statuses: list[str]) -> int:
    """Copy description -> standardized_description for matching item statuses."""
    if not statuses:
        return 0
    trimmed_description = func.ltrim(func.rtrim(TaskItem.description))
    with _session() as s:
        updated = (
            s.query(TaskItem)
            .filter(
                TaskItem.task_id == task_id,
                TaskItem.status.in_(statuses),
                TaskItem.description.isnot(None),
                trimmed_description != "",
            )
            .update(
                {
                    TaskItem.standardized_description: func.upper(trimmed_description),
                    TaskItem.updated_at: ny_now(),
                },
                synchronize_session=False,
            )
        )
        s.commit()
        return updated


def bulk_reset_items_to_uploaded(task_id: str) -> None:
    """Reset every non-soft-deleted item on *task_id* to UPLOADED.

    Single UPDATE statement; replaces a per-item loop that would otherwise
    issue one round-trip per row at the start of every PC1 run. We filter by
    status rather than passing an ``item_id IN (...)`` list because SQL Server
    caps a single statement at 2,100 parameters, which a 5k-row task blows
    past.
    """
    with _session() as s:
        s.query(TaskItem).filter(
            TaskItem.task_id == task_id,
            TaskItem.status != Status.DELETED_PC1,
        ).update(
            {"status": Status.UPLOADED, "error_message": None, "updated_at": ny_now()},
            synchronize_session=False,
        )
        s.commit()


def bulk_resolve_precheck_errors(task_id: str, phase: str, resolved_by: str) -> None:
    """Mark every unresolved error for (task, phase) as resolved in one query."""
    with _session() as s:
        s.query(PreCheckError).filter(
            PreCheckError.task_id == task_id,
            PreCheckError.phase == phase,
            PreCheckError.resolved == False,  # noqa: E712
        ).update(
            {"resolved": True, "resolved_by": resolved_by, "resolved_at": ny_now()},
            synchronize_session=False,
        )
        s.commit()


def bulk_resolve_precheck_errors_for_items(
    task_id: str, phase: str, item_ids: list[int], resolved_by: str,
) -> None:
    """Mark every unresolved error for the given item_ids (within a phase) as
    resolved in one query. Used by bulk-pass so a 50-item approval doesn't
    issue 50+ resolve round-trips.
    """
    if not item_ids:
        return
    with _session() as s:
        s.query(PreCheckError).filter(
            PreCheckError.task_id == task_id,
            PreCheckError.phase == phase,
            PreCheckError.item_id.in_(item_ids),
            PreCheckError.resolved == False,  # noqa: E712
        ).update(
            {"resolved": True, "resolved_by": resolved_by, "resolved_at": ny_now()},
            synchronize_session=False,
        )
        s.commit()


def bulk_update_item_statuses(updates: list[dict]) -> None:
    """Apply per-item ``(status, error_message)`` updates in one session.

    Each dict needs ``item_id`` and ``status``; ``error_message`` is optional
    (defaults to ``None``). Uses ``bulk_update_mappings`` so the per-row
    overhead is a prepared-statement parameter pack rather than a SELECT.
    """
    if not updates:
        return
    now = ny_now()
    payload = [
        {
            "item_id": u["item_id"],
            "status": u["status"],
            "error_message": u.get("error_message"),
            "updated_at": now,
        }
        for u in updates
        if u.get("item_id") is not None
    ]
    if not payload:
        return
    with _session() as s:
        s.bulk_update_mappings(TaskItem, payload)
        s.commit()


def delete_item_matches_for_task(task_id: str) -> int:
    with _session() as s:
        count = s.query(ItemMatchCandidate).filter(ItemMatchCandidate.task_id == task_id).delete()
        s.commit()
        return count


def delete_item_matches_by_ids(match_item_ids: list[int]) -> int:
    if not match_item_ids:
        return 0
    with _session() as s:
        count = (
            s.query(ItemMatchCandidate)
            .filter(ItemMatchCandidate.match_item_id.in_(match_item_ids))
            .delete(synchronize_session=False)
        )
        s.commit()
        return count


def add_item_matches_bulk(matches: list[dict]) -> list[ItemMatchCandidate]:
    if not matches:
        return []
    now = ny_now()
    payload = []
    valid_columns = {column.name for column in ItemMatchCandidate.__table__.columns}
    for match_data in matches:
        row = {
            key: value
            for key, value in match_data.items()
            if key in valid_columns and key != "match_item_id"
        }
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        payload.append(row)
    with _session() as s:
        s.bulk_insert_mappings(ItemMatchCandidate, payload)
        s.commit()
    return []


def update_item_matches_bulk(updates: list[dict]) -> None:
    if not updates:
        return
    now = ny_now()
    valid_columns = {column.name for column in ItemMatchCandidate.__table__.columns}
    payload = []
    for entry in updates:
        match_item_id = entry.get("match_item_id") if isinstance(entry, dict) else None
        if match_item_id is None:
            continue
        row = {
            key: value
            for key, value in entry.items()
            if key in valid_columns and key != "match_item_id"
        }
        if not row:
            continue
        row["match_item_id"] = match_item_id
        row["updated_at"] = now
        payload.append(row)
    if not payload:
        return
    with _session() as s:
        s.bulk_update_mappings(ItemMatchCandidate, payload)
        s.commit()


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


def add_precheck_errors_bulk(records: list[dict]) -> None:
    """Insert many PreCheckError rows in one round-trip.

    Each dict must contain ``task_id``, ``phase``, ``error_type``; ``item_id``
    and ``error_detail`` are optional. Used by intake_service.run_precheck to
    avoid issuing one INSERT per validation issue on large files.
    """
    if not records:
        return
    now = ny_now()
    payload = []
    for record in records:
        row = dict(record)
        row.setdefault("resolved", False)
        row.setdefault("created_at", now)
        payload.append(row)
    with _session() as s:
        s.bulk_insert_mappings(PreCheckError, payload)
        s.commit()


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
def delete_match_results(
    task_id: str,
    matched_source: Optional[str] = None,
    input_item_id: Optional[int] = None,
) -> int:
    """Delete match results for a task. Optionally filter by source (CCX,
    INFOR_CL, etc.) and/or by originating input item id.

    Returns count of deleted rows.
    """
    with _session() as s:
        q = s.query(MatchResult).filter(MatchResult.task_id == task_id)
        if matched_source:
            q = q.filter(MatchResult.matched_source == matched_source)
        if input_item_id is not None:
            q = q.filter(MatchResult.input_item_id == input_item_id)
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
    if not matches:
        return []

    insertable_columns = _get_match_result_columns()
    rows_to_insert = [
        {
            key: value
            for key, value in {"task_id": task_id, **match}.items()
            if key in insertable_columns
        }
        for match in matches
    ]
    with _session() as s:
        s.execute(_get_match_result_table().insert(), rows_to_insert)
        s.commit()
    return []


def get_match_results(task_id: str, matched_source: Optional[str] = None) -> list[MatchResult]:
    with _session() as s:
        q = s.query(MatchResult).filter(MatchResult.task_id == task_id)
        if matched_source:
            q = q.filter(MatchResult.matched_source == matched_source)
        results = q.all()
        for r in results:
            s.expunge(r)
        return results


def count_live_input_items(task_id: str) -> int:
    """Count INPUT items that aren't soft-deleted.

    One COUNT(*) — use instead of materializing every TaskItem entity when
    only a zero-viable check is needed.
    """
    with _session() as s:
        count = (
            s.query(func.count(TaskItem.item_id))
            .filter(
                TaskItem.task_id == task_id,
                TaskItem.source_dataset == "INPUT",
                func.coalesce(TaskItem.status, "").notin_(Status.DELETED_STATUSES),
            )
            .scalar()
        )
        return int(count or 0)


def mark_input_items_preprocessed(task_id: str) -> int:
    """Stamp ITEM_PREPROCESSED on every live INPUT item that has no
    unresolved ERROR/WARN preprocess issue and no ERROR-carrying status.

    Single set-based UPDATE with a correlated NOT EXISTS — no id lists, so
    the 2100-parameter statement cap can't be hit regardless of task size.
    Returns the number of rows updated.
    """
    with _session() as s:
        unresolved_issue = (
            s.query(PreprocessIssue.issue_id)
            .filter(
                PreprocessIssue.task_id == task_id,
                PreprocessIssue.item_id == TaskItem.item_id,
                PreprocessIssue.resolved == False,  # noqa: E712
                PreprocessIssue.severity.in_(("ERROR", "WARN")),
            )
            .exists()
        )
        count = (
            s.query(TaskItem)
            .filter(
                TaskItem.task_id == task_id,
                TaskItem.source_dataset == "INPUT",
                func.coalesce(TaskItem.status, "").notin_(Status.DELETED_STATUSES),
                ~func.coalesce(TaskItem.status, "").like("%ERROR%"),
                ~unresolved_issue,
            )
            .update(
                {
                    TaskItem.status: Status.ITEM_PREPROCESSED,
                    TaskItem.updated_at: ny_now(),
                },
                synchronize_session=False,
            )
        )
        s.commit()
        return int(count or 0)


def count_pending_matches(task_id: str) -> int:
    """Count match rows still awaiting a decision.

    Single COUNT(*) — use instead of loading every MatchResult ORM row
    just to test for PENDING (which is ~53k wide rows on a large task).
    """
    with _session() as s:
        count = (
            s.query(func.count(MatchResult.match_id))
            .filter(
                MatchResult.task_id == task_id,
                func.upper(func.coalesce(MatchResult.match_status, "")) == "PENDING",
            )
            .scalar()
        )
        return int(count or 0)


def get_dedup_candidates(task_id: str, *, source: Optional[str] = "CCX") -> list[dict]:
    """Return Phase 4 dedup workspace rows for a task.

    Reads from PreprocessorTaskItemForDecision (the new workspace table).
    By default filters to ``matched_source='CCX'`` because the dedup UI
    only renders the CCX side; pass ``source=None`` to include INFOR_CL
    rows (used by the integrity validator and IM-check pipeline).
    """
    with _session() as s:
        query = s.query(TaskItemForDecision).filter(
            TaskItemForDecision.task_id == task_id
        )
        if source:
            query = query.filter(TaskItemForDecision.matched_source == source)
        rows = query.order_by(
            TaskItemForDecision.input_item_id.asc(),
            TaskItemForDecision.dedup_sort.asc(),
            TaskItemForDecision.dedup_id.asc(),
        ).all()
        return [row.to_dict() for row in rows]


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


def get_first_ccx_match_time(task_id: str):
    """When SKU matching first wrote a CCX match row for this task.

    Used as the task's data watermark: anything older than the last CCX reload
    was matched against a snapshot that no longer exists.
    """
    with _session() as s:
        return (
            s.query(func.min(MatchResult.created_at))
            .filter(
                MatchResult.task_id == task_id,
                MatchResult.matched_source == "CCX",
            )
            .scalar()
        )


def get_ccx_match_business_keys(task_id: str) -> list[dict]:
    """Return the snapshotted CCX business key + current ccx_pkid per match row.

    Feeds ``preprocess_service._refresh_ccx_pkids``, which re-resolves stale
    pkids after a daily source reload.
    """
    with _session() as s:
        rows = (
            s.query(
                MatchResult.match_id,
                MatchResult.ccx_pkid,
                MatchResult.organization_eid_matched,
                MatchResult.contract_id_matched,
                MatchResult.erp_vendor_id_matched,
                MatchResult.manufacturer_number_matched,
                MatchResult.uom_matched,
                MatchResult.uom_to_match_infor_matched,
                MatchResult.input_item_id,
            )
            .filter(
                MatchResult.task_id == task_id,
                MatchResult.matched_source == "CCX",
            )
            .all()
        )
        return [
            {
                "match_id": r[0],
                "ccx_pkid": r[1],
                "organization_eid_matched": r[2],
                "contract_id_matched": r[3],
                "erp_vendor_id_matched": r[4],
                "manufacturer_number_matched": r[5],
                "uom_matched": r[6],
                "uom_to_match_infor_matched": r[7],
                "input_item_id": r[8],
            }
            for r in rows
        ]


def update_match_ccx_pkids(updates: list[dict]) -> int:
    """Rewrite ``ccx_pkid`` on match rows. Each dict needs match_id + ccx_pkid."""
    if not updates:
        return 0
    with _session() as s:
        s.bulk_update_mappings(MatchResult, updates)
        s.commit()
    return len(updates)


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


def _aggregate_cascade_status(source_matches: list) -> str:
    """Roll up the CCX source decisions for an INFOR_CL cascade row.

    Accepts MatchResult entities or column-only Rows — only
    ``match_status`` is read.

    A cascade row says "this input item has a CL link to this Infor item".
    The link is valid as long as at least one of its CCX sources confirms
    the input/Infor pairing. So:

    - any source still PENDING → cascade is PENDING (review still needed)
    - any source ACCEPTED       → cascade is ACCEPTED (link confirmed)
    - all sources REJECTED      → cascade is REJECTED
    """
    if not source_matches:
        return "PENDING"
    statuses = {(m.match_status or "PENDING").upper() for m in source_matches}
    if "PENDING" in statuses or "LLM_REVIEW" in statuses:
        return "PENDING"
    if "ACCEPTED" in statuses:
        return "ACCEPTED"
    return "REJECTED"


def reaggregate_cascade_statuses(task_id: str) -> int:
    """Re-aggregate INFOR_CL CASCADE rows from their source CCX matches.

    Use to self-heal stale cascade aggregations. Returns the number of rows
    whose status or bucket changed.

    Two column-only SELECTs (cascade rows + all CCX rows for the task),
    aggregation in Python, one bulk UPDATE for changed rows — never one
    query per cascade row.
    """
    with _session() as s:
        cascade_rows = (
            s.query(
                MatchResult.match_id,
                MatchResult.input_item_id,
                MatchResult.ccx_pkid,
                MatchResult.ccx_pkids_matched,
                MatchResult.match_status,
                MatchResult.similarity_bucket,
            )
            .filter(
                MatchResult.task_id == task_id,
                MatchResult.matched_source == "INFOR_CL",
                MatchResult.match_type == "CASCADE",
            )
            .all()
        )
        if not cascade_rows:
            return 0

        ccx_by_item_pkid: dict[tuple[int, int], list] = {}
        ccx_rows = (
            s.query(
                MatchResult.input_item_id,
                MatchResult.ccx_pkid,
                MatchResult.match_status,
                MatchResult.similarity_bucket,
            )
            .filter(
                MatchResult.task_id == task_id,
                MatchResult.matched_source == "CCX",
                MatchResult.ccx_pkid.isnot(None),
            )
            .all()
        )
        for ccx in ccx_rows:
            ccx_by_item_pkid.setdefault(
                (ccx.input_item_id, ccx.ccx_pkid), []
            ).append(ccx)

        updates: list[dict] = []
        for cascade in cascade_rows:
            lineage_pkids = _parse_ccx_pkid_list(cascade.ccx_pkids_matched)
            effective_pkids = set(
                lineage_pkids or ([] if cascade.ccx_pkid is None else [cascade.ccx_pkid])
            )
            if not effective_pkids:
                continue
            source_rows = [
                row
                for pkid in effective_pkids
                for row in ccx_by_item_pkid.get((cascade.input_item_id, pkid), [])
            ]
            new_status = _aggregate_cascade_status(source_rows)
            new_bucket = _aggregate_cascade_bucket(source_rows)
            if cascade.match_status != new_status or cascade.similarity_bucket != new_bucket:
                updates.append({
                    "match_id": cascade.match_id,
                    "match_status": new_status,
                    "similarity_bucket": new_bucket,
                })

        if updates:
            s.bulk_update_mappings(MatchResult, updates)
            s.commit()
        return len(updates)


def _aggregate_cascade_bucket(source_matches: list) -> Optional[str]:
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


def bulk_update_match_decision_by_contract(
    task_id: str,
    contract_number: str,
    organization_eid: str,
    erp_vendor_id: str,
    match_status: str,
    reviewed_by: str,
) -> dict:
    """Stamp ``match_status`` on every MatchResult under a contract scope and
    re-aggregate INFOR_CL/CASCADE rows whose lineage spans the affected
    input items — all in one session.

    Scope match treats NULL and '' as equivalent, mirroring the Python
    ``_normalize_scope_value`` rule used elsewhere.

    Returns ``{"primary": <int>, "cascade": <int>}``.
    """
    contract_norm = (contract_number or "").strip()
    org_norm = (organization_eid or "").strip()
    vendor_norm = (erp_vendor_id or "").strip()

    scope_filter = (
        MatchResult.task_id == task_id,
        func.coalesce(MatchResult.contract_number, "") == contract_norm,
        func.coalesce(MatchResult.organization_eid_matched, "") == org_norm,
        func.coalesce(MatchResult.erp_vendor_id_matched, "") == vendor_norm,
    )

    with _session() as s:
        now = ny_now()

        affected_rows = (
            s.query(
                MatchResult.match_id,
                MatchResult.input_item_id,
                MatchResult.matched_source,
                MatchResult.ccx_pkid,
            )
            .filter(*scope_filter)
            .all()
        )
        if not affected_rows:
            return {"primary": 0, "cascade": 0}

        affected_input_item_ids = {r.input_item_id for r in affected_rows}

        primary_count = (
            s.query(MatchResult)
            .filter(*scope_filter)
            .update(
                {
                    MatchResult.match_status: match_status,
                    MatchResult.reviewed_by: reviewed_by,
                    MatchResult.reviewed_at: now,
                },
                synchronize_session=False,
            )
        )

        cascade_count = _reaggregate_cascade_for_input_items(
            s,
            task_id=task_id,
            input_item_ids=affected_input_item_ids,
            reviewed_by=reviewed_by,
            reviewed_at=now,
        )

        s.commit()
        return {"primary": primary_count, "cascade": cascade_count}


def _reaggregate_cascade_for_input_items(
    s: Session,
    *,
    task_id: str,
    input_item_ids: set[int],
    reviewed_by: Optional[str] = None,
    reviewed_at=None,
) -> int:
    """Re-aggregate INFOR_CL/CASCADE rows for the given input items in one pass.

    Loads all relevant cascade rows + their CCX source rows with two queries,
    then computes the new (status, bucket) for each cascade row in Python.
    Returns the number of rows whose aggregate changed.
    """
    if not input_item_ids:
        return 0

    sorted_input_ids = sorted(input_item_ids)
    cascade_rows: list[MatchResult] = []
    for id_chunk in _chunked(sorted_input_ids):
        cascade_rows.extend(
            s.query(MatchResult)
            .filter(
                MatchResult.task_id == task_id,
                MatchResult.matched_source == "INFOR_CL",
                MatchResult.match_type == "CASCADE",
                MatchResult.input_item_id.in_(id_chunk),
            )
            .all()
        )
    if not cascade_rows:
        return 0

    ccx_pkids_needed: set[int] = set()
    cascade_pkids: dict[int, set[int]] = {}
    for cascade in cascade_rows:
        lineage = _parse_ccx_pkid_list(cascade.ccx_pkids_matched)
        effective_pkids = set(
            lineage or ([] if cascade.ccx_pkid is None else [cascade.ccx_pkid])
        )
        cascade_pkids[cascade.match_id] = effective_pkids
        ccx_pkids_needed.update(effective_pkids)

    ccx_sources_by_item: dict[int, list[MatchResult]] = {}
    if ccx_pkids_needed:
        sorted_pkids = sorted(ccx_pkids_needed)
        # Both IN lists count toward the 2100-parameter cap, so chunk each.
        for id_chunk in _chunked(sorted_input_ids):
            for pkid_chunk in _chunked(sorted_pkids):
                ccx_rows = (
                    s.query(MatchResult)
                    .filter(
                        MatchResult.task_id == task_id,
                        MatchResult.matched_source == "CCX",
                        MatchResult.input_item_id.in_(id_chunk),
                        MatchResult.ccx_pkid.in_(pkid_chunk),
                    )
                    .all()
                )
                for ccx in ccx_rows:
                    ccx_sources_by_item.setdefault(
                        ccx.input_item_id, []
                    ).append(ccx)

    cascade_count = 0
    for cascade in cascade_rows:
        effective_pkids = cascade_pkids.get(cascade.match_id) or set()
        if not effective_pkids:
            continue
        source_rows = [
            ccx
            for ccx in ccx_sources_by_item.get(cascade.input_item_id, [])
            if ccx.ccx_pkid in effective_pkids
        ]
        new_status = _aggregate_cascade_status(source_rows)
        new_bucket = _aggregate_cascade_bucket(source_rows)
        if (
            cascade.match_status != new_status
            or cascade.similarity_bucket != new_bucket
        ):
            cascade.match_status = new_status
            cascade.similarity_bucket = new_bucket
            if reviewed_by is not None:
                cascade.reviewed_by = reviewed_by
            if reviewed_at is not None:
                cascade.reviewed_at = reviewed_at
            cascade_count += 1

    return cascade_count


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


def update_match_input_ea_price(task_id: str, input_item_id: int, input_ea_price: Optional[float]) -> int:
    """Refresh input_ea_price on every MatchResult row for an input item.

    Called after the input QOE/price changes so the stored EA price stays
    consistent with the input it was derived from.
    """
    with _session() as s:
        count = (
            s.query(MatchResult)
            .filter(
                MatchResult.task_id == task_id,
                MatchResult.input_item_id == input_item_id,
            )
            .update({MatchResult.input_ea_price: input_ea_price}, synchronize_session=False)
        )
        s.commit()
        return count


def update_dedup_decisions(match_ids: list[int], decision: str, decided_by: str) -> int:
    """Stamp a bulk dedup decision on PreprocessorTaskItemForDecision.

    Lookup is by ``match_id`` so existing UI payloads (which carry
    MatchResult.match_id) keep working. Returns the number of workspace
    rows updated.
    """
    if not match_ids:
        return 0

    with _session() as s:
        now = ny_now()
        count = (
            s.query(TaskItemForDecision)
            .filter(TaskItemForDecision.match_id.in_(match_ids))
            .update(
                {
                    TaskItemForDecision.dedup_decision: decision,
                    TaskItemForDecision.dedup_decided_by: decided_by,
                    TaskItemForDecision.dedup_decided_at: now,
                },
                synchronize_session=False,
            )
        )
        s.commit()
        return count


# ---------------------------------------------------------------------------
# PreprocessIssue — per-item Phase 3 issues (BUY_UOM_ERROR, MULTI_ITEM_ERROR)
# ---------------------------------------------------------------------------
def upsert_preprocess_issue(
    task_id: str,
    item_id: int,
    issue_type: str,
    severity: str,
    detail: Optional[str] = None,
) -> PreprocessIssue:
    """Create or refresh an unresolved issue of (task_id, item_id, issue_type).

    If an unresolved row already exists, severity/detail are overwritten and
    updated_at bumped. Resolved rows are left alone (so the audit trail of
    past resolutions is preserved) and a new row is inserted.
    """
    with _session() as s:
        existing = (
            s.query(PreprocessIssue)
            .filter(
                PreprocessIssue.task_id == task_id,
                PreprocessIssue.item_id == item_id,
                PreprocessIssue.issue_type == issue_type,
                PreprocessIssue.resolved == False,  # noqa: E712
            )
            .first()
        )
        if existing:
            existing.severity = severity
            existing.detail = detail
            existing.updated_at = ny_now()
            issue = existing
        else:
            issue = PreprocessIssue(
                task_id=task_id,
                item_id=item_id,
                issue_type=issue_type,
                severity=severity,
                detail=detail,
            )
            s.add(issue)
        s.commit()
        s.refresh(issue)
        s.expunge(issue)
        return issue


def get_preprocess_issues(task_id: str, include_resolved: bool = True) -> list[PreprocessIssue]:
    with _session() as s:
        query = s.query(PreprocessIssue).filter(PreprocessIssue.task_id == task_id)
        if not include_resolved:
            query = query.filter(PreprocessIssue.resolved == False)  # noqa: E712
        rows = query.order_by(PreprocessIssue.item_id, PreprocessIssue.created_at).all()
        for row in rows:
            s.expunge(row)
        return rows


def get_unresolved_error_issues(task_id: str) -> list[PreprocessIssue]:
    with _session() as s:
        rows = (
            s.query(PreprocessIssue)
            .filter(
                PreprocessIssue.task_id == task_id,
                PreprocessIssue.resolved == False,  # noqa: E712
                PreprocessIssue.severity == "ERROR",
            )
            .all()
        )
        for row in rows:
            s.expunge(row)
        return rows


def get_preprocess_issue(issue_id: int) -> Optional[PreprocessIssue]:
    with _session() as s:
        issue = s.get(PreprocessIssue, issue_id)
        if issue:
            s.expunge(issue)
        return issue


def update_preprocess_issue(
    issue_id: int,
    severity: Optional[str] = None,
    detail: Optional[str] = None,
) -> Optional[PreprocessIssue]:
    with _session() as s:
        issue = s.get(PreprocessIssue, issue_id)
        if not issue:
            return None
        if severity is not None:
            issue.severity = severity
        if detail is not None:
            issue.detail = detail
        issue.updated_at = ny_now()
        s.commit()
        s.refresh(issue)
        s.expunge(issue)
        return issue


def resolve_preprocess_issue(
    issue_id: int,
    resolution_action: str,
    resolved_by: str,
    detail: Optional[str] = None,
) -> Optional[PreprocessIssue]:
    with _session() as s:
        issue = s.get(PreprocessIssue, issue_id)
        if not issue:
            return None
        issue.resolved = True
        issue.resolved_by = resolved_by
        issue.resolved_at = ny_now()
        issue.resolution_action = resolution_action
        if detail is not None:
            issue.detail = detail
        issue.updated_at = ny_now()
        s.commit()
        s.refresh(issue)
        s.expunge(issue)
        return issue


def add_preprocess_issues_bulk(records: list[dict]) -> None:
    """Insert many PreprocessIssue rows in one round-trip.

    Each dict must contain ``task_id``, ``item_id``, ``issue_type``,
    ``severity``; ``detail`` is optional. Used by the preprocess pipeline
    after deleting unresolved issues of the same type so that a 5,000-row
    rerun doesn't issue one INSERT per flagged row.

    ``resolved`` / ``created_at`` / ``updated_at`` are set explicitly because
    ``bulk_insert_mappings`` skips Python-side ``default=`` callables.
    """
    if not records:
        return
    now = ny_now()
    payload = []
    for r in records:
        row = dict(r)
        row.setdefault("resolved", False)
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        payload.append(row)
    with _session() as s:
        s.bulk_insert_mappings(PreprocessIssue, payload)
        s.commit()


def delete_preprocess_issues_for_task(task_id: str) -> int:
    with _session() as s:
        count = (
            s.query(PreprocessIssue)
            .filter(PreprocessIssue.task_id == task_id)
            .delete(synchronize_session=False)
        )
        s.commit()
        return count


def delete_unresolved_preprocess_issues(task_id: str, issue_types: list[str]) -> int:
    if not issue_types:
        return 0
    with _session() as s:
        count = (
            s.query(PreprocessIssue)
            .filter(
                PreprocessIssue.task_id == task_id,
                PreprocessIssue.issue_type.in_(issue_types),
                PreprocessIssue.resolved == False,  # noqa: E712
            )
            .delete(synchronize_session=False)
        )
        s.commit()
        return count


# ---------------------------------------------------------------------------
# ContractDecision — per-(task, contract scope) tri-state reviewer choice
# (INCLUDE | EXCLUDE | REPLACE). See migration 026.
# ---------------------------------------------------------------------------
CONTRACT_DECISION_VALUES = ("INCLUDE", "EXCLUDE", "REPLACE")


def _contract_decision_scope(
    organization_eid: Optional[str],
    contract_id: str,
    erp_vendor_id: Optional[str],
) -> tuple[str, str, str]:
    return (
        (organization_eid or ""),
        (contract_id or ""),
        (erp_vendor_id or ""),
    )


def upsert_contract_decision(
    task_id: str,
    organization_eid: Optional[str],
    contract_id: str,
    erp_vendor_id: Optional[str],
    decision: str,
    decided_by: str,
) -> ContractDecision:
    if decision not in CONTRACT_DECISION_VALUES:
        raise ValueError(f"decision must be one of {CONTRACT_DECISION_VALUES}")
    org_eid, cid, vendor = _contract_decision_scope(organization_eid, contract_id, erp_vendor_id)
    with _session() as s:
        row = (
            s.query(ContractDecision)
            .filter(
                ContractDecision.task_id == task_id,
                ContractDecision.organization_eid == org_eid,
                ContractDecision.contract_id == cid,
                ContractDecision.erp_vendor_id == vendor,
            )
            .one_or_none()
        )
        if row is None:
            row = ContractDecision(
                task_id=task_id,
                organization_eid=org_eid,
                contract_id=cid,
                erp_vendor_id=vendor,
                decision=decision,
                decided_by=decided_by,
                decided_at=ny_now(),
            )
            s.add(row)
        else:
            row.decision = decision
            row.decided_by = decided_by
            row.decided_at = ny_now()
        s.commit()
        s.refresh(row)
        s.expunge(row)
        return row


def delete_contract_decision(
    task_id: str,
    organization_eid: Optional[str],
    contract_id: str,
    erp_vendor_id: Optional[str],
) -> int:
    """Remove a contract decision row for a scope; returns rows deleted (0/1).

    Used to un-mark a REPLACE from the export preview so the contract sheet
    reverts to matched rows only.
    """
    org_eid, cid, vendor = _contract_decision_scope(organization_eid, contract_id, erp_vendor_id)
    with _session() as s:
        deleted = (
            s.query(ContractDecision)
            .filter(
                ContractDecision.task_id == task_id,
                ContractDecision.organization_eid == org_eid,
                ContractDecision.contract_id == cid,
                ContractDecision.erp_vendor_id == vendor,
            )
            .delete(synchronize_session=False)
        )
        s.commit()
        return deleted


def get_contract_decisions(task_id: str) -> list[ContractDecision]:
    with _session() as s:
        rows = (
            s.query(ContractDecision)
            .filter(ContractDecision.task_id == task_id)
            .all()
        )
        for row in rows:
            s.expunge(row)
        return rows


def get_contract_decisions_map(task_id: str) -> dict[tuple[str, str, str], str]:
    """Return {(organization_eid, contract_id, erp_vendor_id): decision}."""
    return {
        (row.organization_eid, row.contract_id, row.erp_vendor_id): row.decision
        for row in get_contract_decisions(task_id)
    }


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
