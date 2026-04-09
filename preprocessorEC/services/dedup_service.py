"""Dedup service — Phase 4 business logic.

Handles: change simulation, deduplication resolution, integrity validation.
Pure Python, no Flask imports.
"""

from __future__ import annotations

from ..db import task_repo, workstate_repo
from ..state import TaskStateMachine, Phase, Status


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
