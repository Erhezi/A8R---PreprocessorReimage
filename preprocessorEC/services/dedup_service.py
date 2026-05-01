"""Dedup service — Phase 4 business logic.

Handles: workspace materialization (delegated to dedup_workspace),
per-side keep/drop decisions, inline edits, reset, change simulation,
integrity validation. Pure Python, no Flask imports.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from ..common.utils import ny_now
from ..db import task_repo, workstate_repo
from ..db.engine import get_sqlserver_engine
from ..models import TaskItemForDecision
from ..state import TaskStateMachine, Phase, Status
from .dedup_resolution import editable_for_side
from .dedup_workspace import populate_dedup_workspace

logger = logging.getLogger(__name__)


def _session() -> Session:
    return Session(get_sqlserver_engine())


# Legacy decision vocabulary — kept for the bulk decision endpoint until
# the old dedup.html toolbar is fully retired.
VALID_DEDUP_DECISIONS = {"UPLOAD", "EXPIRE", "KEEP_AS_IS"}

# Per-side decisions in the new 4C flow.
VALID_SIDE_DECISIONS = {"keep", "drop"}
VALID_SIDES = {"input", "matched"}

# Editable-field allowlist per side. Keys are the public field names
# the API accepts; values are the workspace columns they map to.
EDITABLE_INPUT_FIELDS: dict[str, str] = {
    "manufacturer_number": "manufacturer_number_input",
    "vendor_item": "vendor_item_input",
    "uom": "uom_input",
    "qoe": "qoe_input",
    "item_description": "item_description_input",
}
EDITABLE_MATCHED_FIELDS: dict[str, str] = {
    "manufacturer_number": "manufacturer_number_matched",
    "vendor_item": "vendor_item_matched",
    "uom": "uom_matched",
    "qoe": "qoe_matched",
    "item_description": "item_desc_matched",
}


def _ensure_workspace(task_id: str) -> None:
    """Lazy-backfill: populate the workspace if it's empty (e.g. tasks
    that advanced before the workspace existed). No-op when rows exist."""
    try:
        populate_dedup_workspace(task_id)
    except Exception as exc:  # pragma: no cover — log and continue
        logger.exception("Lazy workspace populate failed for %s: %s", task_id, exc)


def get_dedup_candidates(task_id: str) -> list[dict]:
    """Return CCX dedup workspace rows for the dedup review UI.

    Input fields are already baked into the workspace row by the populator,
    so the service no longer joins back to PreprocessorTaskItem.
    """
    _ensure_workspace(task_id)
    return task_repo.get_dedup_candidates(task_id, source="CCX")


def _coerce_field_value(field: str, raw_value):
    """Coerce a raw API value into the right Python type for the column.

    QOE is the only numeric editable field; everything else is text.
    Empty strings on text fields are normalized to None so the column
    isn't filled with a blank.
    """
    if field == "qoe":
        if raw_value in (None, "", "null"):
            raise ValueError("QOE cannot be blank.")
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"QOE must be an integer; got {raw_value!r}.") from exc
        if value <= 0:
            raise ValueError("QOE must be a positive integer.")
        return value
    if isinstance(raw_value, str):
        cleaned = raw_value.strip()
        return cleaned or None
    return raw_value


def _resolve_field(side: str, field: str) -> str:
    """Map a public (side, field) pair to the underlying column name."""
    if side == "input":
        column = EDITABLE_INPUT_FIELDS.get(field)
    elif side == "matched":
        column = EDITABLE_MATCHED_FIELDS.get(field)
    else:
        raise ValueError(f"Invalid side {side!r}; expected 'input' or 'matched'.")
    if not column:
        raise ValueError(f"Field {field!r} is not editable on the {side} side.")
    return column


def _append_edit_log(existing_json: str | None, entry: dict) -> str:
    try:
        log = json.loads(existing_json) if existing_json else []
        if not isinstance(log, list):
            log = []
    except (ValueError, TypeError):
        log = []
    log.append(entry)
    return json.dumps(log)


def set_input_decision(
    task_id: str, input_item_id: int, decision: str, decided_by: str
) -> dict:
    """Apply a keep/drop decision to the INPUT side of every workspace row
    sharing ``(task_id, input_item_id)``. The input is one logical item —
    the decision must be uniform across its match group.
    """
    decision_norm = (decision or "").strip().lower()
    if decision_norm not in VALID_SIDE_DECISIONS:
        raise ValueError(f"Invalid decision {decision!r}; expected 'keep' or 'drop'.")

    with _session() as s:
        now = ny_now()
        count = (
            s.query(TaskItemForDecision)
            .filter(
                TaskItemForDecision.task_id == task_id,
                TaskItemForDecision.input_item_id == input_item_id,
            )
            .update(
                {
                    TaskItemForDecision.input_decision: decision_norm,
                    TaskItemForDecision.dedup_decided_by: decided_by,
                    TaskItemForDecision.dedup_decided_at: now,
                },
                synchronize_session=False,
            )
        )
        s.commit()
        if count == 0:
            raise ValueError(
                f"No dedup workspace rows found for task={task_id} input_item_id={input_item_id}."
            )
        return {"updated": count, "side": "input", "decision": decision_norm}


def set_matched_decision(
    task_id: str, dedup_id: int, decision: str, decided_by: str
) -> dict:
    """Apply a keep/drop decision to the MATCHED side of one workspace row."""
    decision_norm = (decision or "").strip().lower()
    if decision_norm not in VALID_SIDE_DECISIONS:
        raise ValueError(f"Invalid decision {decision!r}; expected 'keep' or 'drop'.")

    with _session() as s:
        row = s.get(TaskItemForDecision, dedup_id)
        if not row or row.task_id != task_id:
            raise ValueError(f"Dedup row {dedup_id} not found for task {task_id}.")
        row.matched_decision = decision_norm
        row.dedup_decided_by = decided_by
        row.dedup_decided_at = ny_now()
        s.commit()
        return {"updated": 1, "side": "matched", "decision": decision_norm}


def edit_field(
    task_id: str,
    dedup_id: int,
    side: str,
    field: str,
    new_value,
    edited_by: str,
) -> dict:
    """Edit a single field on the input or matched side of a dedup row.

    - Premier sides reject (system-level constraint).
    - Field must be in the side's allowlist.
    - For input edits the change propagates to all rows in the same
      ``(task_id, input_item_id)`` group, since they all show the same
      input item; each touched row gets its own edit-log entry.
    """
    side_norm = (side or "").strip().lower()
    field_norm = (field or "").strip().lower()
    if side_norm not in VALID_SIDES:
        raise ValueError(f"Invalid side {side!r}; expected 'input' or 'matched'.")

    column = _resolve_field(side_norm, field_norm)
    coerced_value = _coerce_field_value(field_norm, new_value)

    with _session() as s:
        anchor = s.get(TaskItemForDecision, dedup_id)
        if not anchor or anchor.task_id != task_id:
            raise ValueError(f"Dedup row {dedup_id} not found for task {task_id}.")

        side_source_type = (
            anchor.input_contract_source_type if side_norm == "input"
            else anchor.matched_contract_source_type
        )
        if not editable_for_side(side_source_type):
            raise ValueError(
                f"{side_norm.title()} side is on a Premier contract and cannot be edited."
            )

        if side_norm == "input":
            targets = (
                s.query(TaskItemForDecision)
                .filter(
                    TaskItemForDecision.task_id == task_id,
                    TaskItemForDecision.input_item_id == anchor.input_item_id,
                )
                .all()
            )
        else:
            targets = [anchor]

        now = ny_now()
        timestamp = now.isoformat() if now else None
        updated_dedup_ids: list[int] = []
        for row in targets:
            original = getattr(row, column)
            entry = {
                "side": side_norm,
                "field": field_norm,
                "original": original if not hasattr(original, "isoformat") else original.isoformat(),
                "current": coerced_value,
                "edited_at": timestamp,
                "edited_by": edited_by,
            }
            setattr(row, column, coerced_value)
            row.edits = _append_edit_log(row.edits, entry)
            updated_dedup_ids.append(row.dedup_id)

        s.commit()
        return {
            "updated": len(updated_dedup_ids),
            "dedup_ids": updated_dedup_ids,
            "side": side_norm,
            "field": field_norm,
            "value": coerced_value,
        }


def reset_workspace(task_id: str) -> dict:
    """Wipe every workspace row for ``task_id`` and re-derive defaults
    from PreprocessorMatchResult. Decisions and edits are discarded —
    this is the explicit "Reset to defaults" action from 4C.
    """
    return populate_dedup_workspace(task_id, force=True)


def apply_dedup_decision(task_id: str, match_ids: list[int], decision: str, decided_by: str) -> dict:
    """Apply a bulk dedup decision to accepted CCX rows for one task."""
    normalized_decision = (decision or "").strip().upper()
    if normalized_decision not in VALID_DEDUP_DECISIONS:
        raise ValueError("Invalid dedup decision.")
    if not match_ids:
        raise ValueError("No match rows were selected.")

    allowed_match_ids = {int(row["match_id"]) for row in task_repo.get_dedup_candidates(task_id, source="CCX")}
    target_match_ids = [int(match_id) for match_id in match_ids if int(match_id) in allowed_match_ids]
    if not target_match_ids:
        raise ValueError("Selected rows are not valid accepted CCX dedup candidates.")

    updated_count = task_repo.update_dedup_decisions(target_match_ids, normalized_decision, decided_by)
    return {
        "updated": updated_count,
        "decision": normalized_decision,
        "match_ids": target_match_ids,
    }


def simulate_changes(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Simulate the contract line changes (create/update/expire/merge/mute).

    TODO: Extract logic from original change_simulation/routes.py
    """
    state = state_machine.get_state(task_id)
    state["status"] = Status.SIMULATING
    state_machine.save_state(task_id, state)
    return {"status": "not_implemented"}


def validate_integrity(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Run data integrity checks on the preprocessed + deduped dataset.

    TODO: Define integrity rules per design.txt Phase 4
    """
    return {"status": "not_implemented"}


def finalize_dedup(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """Finalize dedup and advance to EXPORT phase."""
    state = state_machine.get_state(task_id)
    state["status"] = Status.DEDUP_COMPLETE
    state_machine.save_state(task_id, state)

    new_state = state_machine.advance(
        task_id, Phase.EXPORT, changed_by=user, notes="Dedup complete, advancing to Export"
    )
    return {"phase": new_state["phase"], "status": new_state["status"]}
