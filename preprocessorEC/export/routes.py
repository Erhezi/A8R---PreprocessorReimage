"""Export module â€” Phase 5: export file generation.

Stub routes â€” full implementation in Phase D.
"""

from __future__ import annotations

from flask import jsonify, request, render_template, abort
from flask_login import login_required, current_user

from . import export_bp
from ..db import task_repo, workstate_repo
from ..services import export_service
from ..state import TaskStateMachine


def _sm() -> TaskStateMachine:
    return TaskStateMachine(task_repo, workstate_repo)


@export_bp.route("/api/export/<task_id>/generate", methods=["POST"])
@login_required
def api_generate(task_id: str):
    data = request.get_json(force=True)
    fmt = data.get("format", "batch_upload")
    result = export_service.generate_export(task_id, fmt, _sm())
    return jsonify(result)


@export_bp.route("/api/export/<task_id>/finalize", methods=["POST"])
@login_required
def api_finalize(task_id: str):
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = export_service.finalize_export(task_id, _sm(), user)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@export_bp.route("/export/<task_id>")
@login_required
def export_page(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    return render_template("export.html", task_id=task_id)



