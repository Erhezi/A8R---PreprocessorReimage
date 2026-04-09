"""Monitoring service — Phase 6 business logic.

Handles: task reporting, sync tracking.
Pure Python, no Flask imports.
"""

from __future__ import annotations

from ..db import task_repo


def get_task_report(task_id: str) -> dict:
    """Generate a monitoring report for a task.

    TODO: Implement reporting logic
    """
    task = task_repo.get_task(task_id)
    if not task:
        return {"error": "Task not found"}

    log = task_repo.get_status_log(task_id)
    return {
        "task_id": task_id,
        "phase": task.phase,
        "status": task.status,
        "history": [
            {
                "old_phase": entry.old_phase,
                "new_phase": entry.new_phase,
                "old_status": entry.old_status,
                "new_status": entry.new_status,
                "changed_by": entry.changed_by,
                "changed_at": entry.changed_at.isoformat() if entry.changed_at else None,
                "notes": entry.notes,
            }
            for entry in log
        ],
    }
