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


@dedup_bp.route("/api/dedup/<task_id>/decision", methods=["POST"])
@login_required
def api_set_decision(task_id: str):
    """Apply a per-side keep/drop decision.

    Body shape:
      side='input'   -> {input_item_id, decision}
      side='matched' -> {dedup_id, decision}
    """
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)

    payload = request.get_json(silent=True) or {}
    user = current_user.username if current_user.is_authenticated else "system"
    side = (payload.get("side") or "").strip().lower()
    decision = payload.get("decision") or ""

    try:
        if side == "input":
            input_item_id = payload.get("input_item_id")
            if input_item_id is None:
                return jsonify({"error": "input_item_id is required for input-side decisions."}), 400
            result = dedup_service.set_input_decision(
                task_id, int(input_item_id), decision, user
            )
        elif side == "matched":
            dedup_id = payload.get("dedup_id")
            if dedup_id is None:
                return jsonify({"error": "dedup_id is required for matched-side decisions."}), 400
            result = dedup_service.set_matched_decision(
                task_id, int(dedup_id), decision, user
            )
        else:
            return jsonify({"error": "side must be 'input' or 'matched'."}), 400
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@dedup_bp.route("/api/dedup/<task_id>/edit", methods=["POST"])
@login_required
def api_edit_field(task_id: str):
    """Edit one field on the input or matched side of a dedup row."""
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)

    payload = request.get_json(silent=True) or {}
    user = current_user.username if current_user.is_authenticated else "system"
    dedup_id = payload.get("dedup_id")
    if dedup_id is None:
        return jsonify({"error": "dedup_id is required."}), 400

    try:
        result = dedup_service.edit_field(
            task_id=task_id,
            dedup_id=int(dedup_id),
            side=payload.get("side") or "",
            field=payload.get("field") or "",
            new_value=payload.get("value"),
            edited_by=user,
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@dedup_bp.route("/api/dedup/<task_id>/reset", methods=["POST"])
@login_required
def api_reset_workspace(task_id: str):
    """Wipe and re-populate the dedup workspace from defaults.

    Discards every decision and edit captured so far. The frontend should
    confirm with the user before invoking this.
    """
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)

    try:
        result = dedup_service.reset_workspace(task_id)
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



