"""Preprocess module â€” Phase 3: unified dup detection + item matching.

JSON API routes:
  POST /api/preprocess/<task_id>/run               â†’ trigger full pipeline
  GET  /api/preprocess/<task_id>/contracts          â†’ contract-level review
  POST /api/preprocess/<task_id>/contract-decision  â†’ include/exclude contract
  GET  /api/preprocess/<task_id>/items              â†’ item-level review (HIGH/MED/LOW)
  POST /api/preprocess/<task_id>/item-decision      â†’ keep/drop/LLM
  GET  /api/preprocess/<task_id>/summary            â†’ preprocessed dataset
  POST /api/preprocess/<task_id>/finalize           â†’ advance to DEDUP

Jinja:
  GET  /preprocess/<task_id>                        â†’ preprocess page
"""

from __future__ import annotations

from flask import jsonify, request, render_template, abort
from flask_login import login_required, current_user

from . import preprocess_bp
from ..db import task_repo, workstate_repo
from ..services import preprocess_service
from ..state import TaskStateMachine


def _sm() -> TaskStateMachine:
    return TaskStateMachine(task_repo, workstate_repo)


@preprocess_bp.route("/api/preprocess/<task_id>/run", methods=["POST"])
@login_required
def api_run_preprocess(task_id: str):
    result = preprocess_service.run_full_preprocess(task_id, _sm())
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/contracts", methods=["GET"])
@login_required
def api_get_contracts(task_id: str):
    # TODO: Implement contract-level review data
    return jsonify({"status": "not_implemented"})


@preprocess_bp.route("/api/preprocess/<task_id>/contract-decision", methods=["POST"])
@login_required
def api_contract_decision(task_id: str):
    data = request.get_json(force=True)
    user = current_user.username if current_user.is_authenticated else "system"
    result = preprocess_service.submit_contract_decision(
        task_id, data["contract_number"], data["include"], user, _sm()
    )
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/items", methods=["GET"])
@login_required
def api_get_items(task_id: str):
    matches = task_repo.get_match_results(task_id)
    return jsonify([m.to_dict() for m in matches])


@preprocess_bp.route("/api/preprocess/<task_id>/item-decision", methods=["POST"])
@login_required
def api_item_decision(task_id: str):
    data = request.get_json(force=True)
    user = current_user.username if current_user.is_authenticated else "system"
    result = preprocess_service.submit_item_decision(
        task_id, data["match_id"], data["decision"], user, _sm()
    )
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/summary", methods=["GET"])
@login_required
def api_summary(task_id: str):
    # TODO: Return preprocessed dataset
    return jsonify({"status": "not_implemented"})


@preprocess_bp.route("/api/preprocess/<task_id>/finalize", methods=["POST"])
@login_required
def api_finalize(task_id: str):
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.finalize_preprocess(task_id, _sm(), user)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@preprocess_bp.route("/preprocess/<task_id>")
@login_required
def preprocess_page(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    return render_template("preprocess.html", task_id=task_id)



