"""Dedup module â€” Phase 4: change simulation + integrity validation.

Stub routes â€” full implementation in Phase D.
"""

from __future__ import annotations

from flask import jsonify, request, render_template, abort
from flask_login import login_required, current_user

from . import dedup_bp
from ..db import task_repo, workstate_repo
from ..services import dedup_service
from ..state import TaskStateMachine


def _sm() -> TaskStateMachine:
    return TaskStateMachine(task_repo, workstate_repo)


@dedup_bp.route("/api/dedup/<task_id>/simulate", methods=["POST"])
@login_required
def api_simulate(task_id: str):
    result = dedup_service.simulate_changes(task_id, _sm())
    return jsonify(result)


@dedup_bp.route("/api/dedup/<task_id>/validate", methods=["POST"])
@login_required
def api_validate(task_id: str):
    result = dedup_service.validate_integrity(task_id, _sm())
    return jsonify(result)


@dedup_bp.route("/api/dedup/<task_id>/finalize", methods=["POST"])
@login_required
def api_finalize(task_id: str):
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = dedup_service.finalize_dedup(task_id, _sm(), user)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@dedup_bp.route("/api/dedup/<task_id>/matches", methods=["GET"])
@login_required
def api_get_matches(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    return jsonify(dedup_service.get_dedup_candidates(task_id))


@dedup_bp.route("/api/dedup/<task_id>/decisions", methods=["POST"])
@login_required
def api_update_decisions(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)

    payload = request.get_json(silent=True) or {}
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = dedup_service.apply_dedup_decision(
            task_id,
            payload.get("match_ids") or [],
            payload.get("decision") or "",
            user,
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@dedup_bp.route("/dedup/<task_id>")
@login_required
def dedup_page(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    return render_template("dedup.html", task_id=task_id, task=task)



