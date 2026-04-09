"""Export service — Phase 5 business logic.

Handles: generating export files in various formats.
Pure Python, no Flask imports.
"""

from __future__ import annotations

from ..db import task_repo, workstate_repo
from ..state import TaskStateMachine, Phase, Status


def generate_export(task_id: str, fmt: str, state_machine: TaskStateMachine) -> dict:
    """Generate an export file for the task.

    Parameters
    ----------
    fmt : str
        Export format: 'batch_upload' | 'single_contract' | 'infor_direct'

    TODO: Extract formatting logic from original common/utils_export_data.py
    """
    state = state_machine.get_state(task_id)
    state["status"] = Status.EXPORTING
    state_machine.save_state(task_id, state)

    # TODO: Implement export generation
    return {"status": "not_implemented", "format": fmt}


def finalize_export(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """Mark export as done and advance to MONITORING."""
    state = state_machine.get_state(task_id)
    state["status"] = Status.EXPORTED
    state_machine.save_state(task_id, state)

    new_state = state_machine.advance(
        task_id, Phase.MONITORING, changed_by=user, notes="Export complete"
    )
    return {"phase": new_state["phase"], "status": new_state["status"]}
