"""Identity module -- Phase 2: standardized descriptions, manufacturer code, contract #, PC2.

JSON API routes:
  GET  /api/identity/<task_id>                          -> current identity state + task header
  POST /api/identity/<task_id>/copy-descriptions        -> copy description -> standardized_description
  POST /api/identity/<task_id>/standardized-descriptions -> upload manual descriptions
  GET  /api/identity/<task_id>/manufacturer-info         -> fetch mfg info for UPDATE contracts
  POST /api/identity/<task_id>/manufacturer-confirm      -> confirm/edit mfg code (UPDATE)
  GET  /api/identity/manufacturers/search                -> search manufacturer table (NEW)
  POST /api/identity/<task_id>/manufacturer-select       -> select mfg code from search (NEW)
  POST /api/identity/<task_id>/contract-number           -> enter contract # for NEW
  POST /api/identity/<task_id>/precheck2                 -> run PC2
  POST /api/identity/<task_id>/proceed                   -> advance to PREPROCESS

Jinja:
  GET  /identity/<task_id>                               -> identity page
"""

from __future__ import annotations

from flask import jsonify, request, render_template, abort
from flask_login import login_required, current_user

from . import identity_bp
from ..db import task_repo, workstate_repo
from ..services import identity_service
from ..state import TaskStateMachine


def _sm() -> TaskStateMachine:
    return TaskStateMachine(task_repo, workstate_repo)


@identity_bp.route("/api/identity/<task_id>", methods=["GET"])
@login_required
def api_identity_state(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    items = task_repo.get_items(task_id)
    errors = task_repo.get_precheck_errors(task_id, phase="PC2")
    state = _sm().get_state(task_id)
    return jsonify({
        "task_id": task_id,
        "phase": task.phase,
        "status": task.status,
        "task": task.to_dict(),
        "items": [i.to_dict() for i in items],
        "errors": [e.to_dict() for e in errors],
        "manufacturer_code": state.get("manufacturer_code", ""),
        "manufacturer_name": state.get("manufacturer_name", ""),
        "manufacturer_confirmed": state.get("manufacturer_confirmed", False),
    })


@identity_bp.route("/api/identity/<task_id>/copy-descriptions", methods=["POST"])
@login_required
def api_copy_descriptions(task_id: str):
    result = identity_service.copy_descriptions_from_input(task_id, _sm())
    return jsonify(result)


@identity_bp.route("/api/identity/<task_id>/standardized-descriptions", methods=["POST"])
@login_required
def api_apply_descriptions(task_id: str):
    data = request.get_json(force=True)
    descriptions = data.get("descriptions", {})
    descriptions = {int(k): v for k, v in descriptions.items()}
    result = identity_service.apply_standardized_descriptions(task_id, descriptions, _sm())
    return jsonify(result)


@identity_bp.route("/api/identity/<task_id>/manufacturer-info", methods=["GET"])
@login_required
def api_manufacturer_info(task_id: str):
    """Fetch manufacturer info from Infor header for UPDATE contracts."""
    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    org = task.organization or ""
    contract_id = task.contract_number or ""
    if not org or not contract_id:
        return jsonify({"found": False, "manufacturer_code": "", "manufacturer_name": "",
                        "error": "Organization or contract number missing"}), 200
    result = identity_service.get_manufacturer_info(org, contract_id)
    return jsonify(result)


@identity_bp.route("/api/identity/<task_id>/manufacturer-confirm", methods=["POST"])
@login_required
def api_manufacturer_confirm(task_id: str):
    """Confirm or edit the manufacturer code for UPDATE contracts."""
    data = request.get_json(force=True)
    code = data.get("code", "").strip().upper()
    name = data.get("name", "").strip().upper()
    result = identity_service.confirm_manufacturer(task_id, code, name, _sm())
    return jsonify(result)


@identity_bp.route("/api/identity/manufacturers/search", methods=["GET"])
@login_required
def api_search_manufacturers():
    """Search manufacturer table for NEW contracts."""
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])
    results = identity_service.search_manufacturers(q)
    return jsonify(results)


@identity_bp.route("/api/identity/<task_id>/manufacturer-select", methods=["POST"])
@login_required
def api_manufacturer_select(task_id: str):
    """Select a manufacturer from the search results (NEW/UPDATE/MIX contracts)."""
    data = request.get_json(force=True)
    code = data.get("code", "").strip().upper()
    name = data.get("name", "").strip().upper()
    result = identity_service.set_manufacturer_code(task_id, code, name, _sm())
    return jsonify(result)


@identity_bp.route("/api/identity/<task_id>/manufacturer-auto-confirm", methods=["POST"])
@login_required
def api_manufacturer_auto_confirm(task_id: str):
    """Auto-confirm manufacturer for EXPIRE contracts (no user action needed)."""
    result = identity_service.auto_confirm_expire_manufacturer(task_id, _sm())
    return jsonify(result)


@identity_bp.route("/api/identity/<task_id>/contract-number", methods=["POST"])
@login_required
def api_contract_number(task_id: str):
    data = request.get_json(force=True)
    raw = data.get("contract_number", "")
    if not raw or not raw.strip():
        return jsonify({"error": "Contract number is required"}), 400
    result = identity_service.enter_contract_number(task_id, raw, _sm())
    return jsonify(result)


@identity_bp.route("/api/identity/<task_id>/precheck2", methods=["POST"])
@login_required
def api_run_precheck2(task_id: str):
    result = identity_service.run_precheck2(task_id, _sm())
    return jsonify(result)


@identity_bp.route("/api/identity/<task_id>/proceed", methods=["POST"])
@login_required
def api_proceed(task_id: str):
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = identity_service.advance_to_preprocess(task_id, _sm(), user)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@identity_bp.route("/identity/<task_id>")
@login_required
def identity_page(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    return render_template("identity_form.html", task_id=task_id)
