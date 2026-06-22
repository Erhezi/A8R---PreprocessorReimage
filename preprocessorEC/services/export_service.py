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


def set_contract_replacement(
    task_id: str,
    organization_eid: str | None,
    contract_id: str,
    erp_vendor_id: str | None,
    replace: bool,
    decided_by: str,
) -> dict:
    """Mark (or un-mark) a matched contract as a REPLACE contract.

    Post-finalize entry point used from the export preview. Unlike the
    preprocess-phase ``submit_contract_decision``, this deliberately does NOT
    flip any PreprocessorMatchResult rows: by export time the matched portion
    of every contract sheet is already frozen in the dedup workspace, so the
    REPLACE flag only tells the export step to append the contract's
    non-matching CCX lines (rejected + never-matched) as left-over rows.

    ``replace=False`` removes the decision row, reverting the sheet to matched
    rows only.
    """
    if replace:
        task_repo.upsert_contract_decision(
            task_id,
            organization_eid,
            contract_id,
            erp_vendor_id,
            "REPLACE",
            decided_by,
        )
        removed = 0
    else:
        removed = task_repo.delete_contract_decision(
            task_id,
            organization_eid,
            contract_id,
            erp_vendor_id,
        )
    return {
        "task_id": task_id,
        "organization_eid": organization_eid or "",
        "contract_id": contract_id or "",
        "erp_vendor_id": erp_vendor_id or "",
        "replace": bool(replace),
        "removed": removed,
    }


def finalize_export(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """Mark export as done and advance to MONITORING."""
    state = state_machine.get_state(task_id)
    state["status"] = Status.EXPORTED
    state_machine.save_state(task_id, state)

    new_state = state_machine.advance(
        task_id, Phase.MONITORING, changed_by=user, notes="Export complete"
    )
    return {"phase": new_state["phase"], "status": new_state["status"]}
