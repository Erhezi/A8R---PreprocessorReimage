"""Dedup service — Phase 4 business logic.

Handles: change simulation, deduplication resolution, integrity validation.
Pure Python, no Flask imports.
"""

from __future__ import annotations

from ..db import task_repo, workstate_repo
from ..state import TaskStateMachine, Phase, Status


VALID_DEDUP_DECISIONS = {"UPLOAD", "EXPIRE", "KEEP_AS_IS"}


def get_dedup_candidates(task_id: str) -> list[dict]:
    """Return accepted CCX rows enriched with their input-item fields."""
    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    item_by_id = {item.item_id: item for item in input_items}

    results = []
    for match in task_repo.get_dedup_candidates(task_id):
        row = dict(match)
        input_item = item_by_id.get(row.get("input_item_id"))
        if input_item:
            row["input_mfg_catalog_num"] = input_item.mfg_catalog_num
            row["input_vendor_catalog_num"] = input_item.vendor_catalog_num
            row["input_description"] = input_item.description
            row["input_uom"] = input_item.uom
            row["input_qoe"] = input_item.qoe
            row["input_unit_price"] = float(input_item.unit_price) if input_item.unit_price else None
        results.append(row)
    return results


def apply_dedup_decision(task_id: str, match_ids: list[int], decision: str, decided_by: str) -> dict:
    """Apply a bulk dedup decision to accepted CCX match rows for one task."""
    normalized_decision = (decision or "").strip().upper()
    if normalized_decision not in VALID_DEDUP_DECISIONS:
        raise ValueError("Invalid dedup decision.")
    if not match_ids:
        raise ValueError("No match rows were selected.")

    allowed_match_ids = {int(row["match_id"]) for row in task_repo.get_dedup_candidates(task_id)}
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
