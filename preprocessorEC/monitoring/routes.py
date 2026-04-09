"""Monitoring module â€” Phase 6: task reporting + sync tracking.

Stub routes â€” full implementation in Phase D.
"""

from __future__ import annotations

from flask import jsonify, render_template, abort
from flask_login import login_required

from . import monitoring_bp
from ..db import task_repo
from ..services import monitoring_service


@monitoring_bp.route("/api/monitoring/<task_id>", methods=["GET"])
@login_required
def api_task_report(task_id: str):
    result = monitoring_service.get_task_report(task_id)
    return jsonify(result)


@monitoring_bp.route("/monitoring/<task_id>")
@login_required
def monitoring_page(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    return render_template("monitoring.html", task_id=task_id)



