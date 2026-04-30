"""Tasks module â€” landing page & task lifecycle JSON APIs.

Routes:
  GET  /api/tasks            â†’ JSON task list
  GET  /api/tasks/<id>       â†’ JSON task detail
  POST /api/tasks            â†’ create task
  PUT  /api/tasks/<id>       â†’ update task fields
  PUT  /api/tasks/<id>/advance â†’ trigger state-machine transition
  GET  /tasks/               â†’ Jinja task list page
  GET  /tasks/<id>           â†’ Jinja task detail page
"""

from __future__ import annotations

from flask import jsonify, request, render_template, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy import text

from . import tasks_bp
from ..db import task_repo
from ..db.engine import get_sqlserver_engine
from ..db.sql_loader import load_query
from ..state import TaskStateMachine, Phase, Status


def _sm() -> TaskStateMachine:
    """Build a fresh state machine for this request."""
    from ..db import workstate_repo
    return TaskStateMachine(task_repo, workstate_repo)


# -------------------------------------------------------------------------
# JSON API routes
# -------------------------------------------------------------------------
@tasks_bp.route("/api/tasks", methods=["GET"])
@login_required
def api_list_tasks():
    """Return paginated task list as JSON."""
    phase = request.args.get("phase")
    status = request.args.get("status")
    tasks = task_repo.list_tasks(phase=phase, status=status)
    return jsonify([t.to_dict() for t in tasks])


@tasks_bp.route("/api/tasks/<task_id>", methods=["GET"])
@login_required
def api_get_task(task_id: str):
    """Return a single task's detail as JSON."""
    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    items = task_repo.get_items(task_id)
    errors = task_repo.get_precheck_errors(task_id)
    log = task_repo.get_status_log(task_id)

    return jsonify({
        "task": task.to_dict(),
        "items": [i.to_dict() for i in items],
        "errors": [e.to_dict() for e in errors],
        "status_log": [
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
    })


@tasks_bp.route("/api/tasks", methods=["POST"])
@login_required
def api_create_task():
    """Create a new task from JSON body."""
    data = request.get_json(force=True)
    intake_mode = data.get("intake_mode", "SINGLE").upper()

    if intake_mode == "BATCH":
        # Batch mode: only intention is required (default MIX)
        intention = data.get("intention", "MIX")
        task = task_repo.create_task(
            process_type=data.get("process_type", ""),
            source_type=data.get("source_type", ""),
            organization=data.get("organization", "ALL"),
            intention=intention,
            intake_mode="BATCH",
            mixed_intention=(intention == "MIX"),
            notes=data.get("notes"),
            wrike_id=data.get("wrike_id"),
            created_by=current_user.username if current_user.is_authenticated else "system",
        )
        return jsonify(task.to_dict()), 201

    # Single (per-contract) mode
    required = ["process_type", "source_type", "organization", "intention"]
    missing = [f for f in required if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    # MIX is only valid in batch mode
    if data["intention"] == "MIX":
        return jsonify({"error": "MIX intention is only available in Batch mode"}), 400

    task = task_repo.create_task(
        intake_mode="SINGLE",
        contract_number=data.get("contract_number"),
        vendor_id=data.get("vendor_id"),
        purchase_from_loc=data.get("purchase_from_loc"),
        erp_vendor_name=data.get("erp_vendor_name"),
        purchase_from_loc_name=data.get("purchase_from_loc_name"),
        process_type=data["process_type"],
        source_type=data["source_type"],
        organization=data["organization"],
        oem_name=data.get("oem_name"),
        intention=data["intention"],
        mixed_intention=False,
        contract_start_date=data.get("contract_start_date"),
        contract_end_date=data.get("contract_end_date"),
        notes=data.get("notes"),
        wrike_id=data.get("wrike_id"),
        created_by=current_user.username if current_user.is_authenticated else "system",
    )
    return jsonify(task.to_dict()), 201


@tasks_bp.route("/api/tasks/<task_id>", methods=["DELETE"])
@login_required
def api_delete_task(task_id: str):
    """Permanently delete a task and cascade-remove its entire sub-task family.

    A sub-task (parent_task_id != NULL) cannot be deleted on its own — the
    request is rejected with 400 and the caller must target the root task
    to remove the whole lineage.
    """
    try:
        deleted = task_repo.delete_task(task_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not deleted:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({"deleted": task_id}), 200


@tasks_bp.route("/api/tasks/<task_id>", methods=["PUT"])
@login_required
def api_update_task(task_id: str):
    """Update editable fields on a task."""
    data = request.get_json(force=True)
    allowed = {
        "contract_number", "vendor_id", "purchase_from_loc",
        "erp_vendor_name", "purchase_from_loc_name",
        "oem_name", "notes", "contract_start_date", "contract_end_date",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    task_repo.update_task_fields(task_id, **updates)
    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task.to_dict())


@tasks_bp.route("/api/tasks/<task_id>/advance", methods=["PUT"])
@login_required
def api_advance_task(task_id: str):
    """Advance a task to the next phase via the state machine."""
    data = request.get_json(force=True)
    target_phase = data.get("target_phase")
    if not target_phase:
        return jsonify({"error": "target_phase is required"}), 400

    sm = _sm()
    try:
        new_state = sm.advance(
            task_id,
            target_phase,
            changed_by=current_user.username if current_user.is_authenticated else "system",
            notes=data.get("notes", ""),
        )
        return jsonify({"phase": new_state["phase"], "status": new_state["status"]})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


# -------------------------------------------------------------------------
# Jinja template routes (consume the JSON APIs above)
# -------------------------------------------------------------------------
@tasks_bp.route("/api/contract-lookup", methods=["GET"])
@login_required
def api_contract_lookup():
    """Look up a contract from CCXInforSyncedContractHeader by ContractID."""
    contract_id = request.args.get("contract_id", "").strip()
    if not contract_id:
        return jsonify({"error": "contract_id is required"}), 400

    engine = get_sqlserver_engine()
    with engine.connect() as conn:
        row = conn.execute(
            load_query("tasks", "tasks", query="contract_lookup"),
            {"cid": contract_id},
        ).mappings().first()

    if not row:
        return jsonify({"found": False}), 200

    with engine.connect() as conn:
        tier_row = conn.execute(
            load_query("tasks", "tasks", query="contract_tier_count"),
            {"cid": contract_id},
        ).mappings().first()
    tier_count = int(tier_row["cnt"]) if tier_row else 1

    return jsonify({
        "found": True,
        "contract_number": row["ContractID"],
        "vendor_id": row["ERPVendorID"],
        "process_type": str(row["ContractProcessType"] or "").strip().upper(),
        "source_type": str(row["ContractSourceType"] or "").strip().upper(),
        "organization": str(row["Organization"] or "").strip(),
        "oem_name": row["Manufacturer"],
        "vendor_name": row["Vendor"],
        "contract_start_date": str(row["ContractStartDate"]) if row["ContractStartDate"] else None,
        "contract_end_date": str(row["ContractEndDate"]) if row["ContractEndDate"] else None,
        "tier_required": tier_count > 1,
        "dc_contract_ref_count": tier_count,
    })


@tasks_bp.route("/api/contract-validate", methods=["GET"])
@login_required
def api_contract_validate():
    """Validate form fields against CCXInforSyncedContractHeader.

    Uses contract_id + organization to locate a unique row when
    multiple rows exist per contract_id.
    """
    contract_id = request.args.get("contract_id", "").strip()
    organization = request.args.get("organization", "").strip()
    if not contract_id:
        return jsonify({"error": "contract_id is required"}), 400

    engine = get_sqlserver_engine()

    # If organization is provided, try to narrow down
    with engine.connect() as conn:
        if organization:
            row = conn.execute(
                load_query("tasks", "tasks", query="contract_validate_by_org"),
                {"cid": contract_id, "org": organization},
            ).mappings().first()
        else:
            row = None

        # Fallback: just by contract_id
        if not row:
            row = conn.execute(
                load_query("tasks", "tasks", query="contract_validate_any"),
                {"cid": contract_id},
            ).mappings().first()

    if not row:
        return jsonify({"found": False}), 200

    return jsonify({
        "found": True,
        "contract_number": row["ContractID"],
        "vendor_id": str(row["ERPVendorID"] or "").strip(),
        "process_type": str(row["ContractProcessType"] or "").strip().upper(),
        "source_type": str(row["ContractSourceType"] or "").strip().upper(),
        "organization": str(row["Organization"] or "").strip(),
        "oem_name": str(row["Manufacturer"] or "").strip(),
        "vendor_name": str(row["Vendor"] or "").strip(),
        "contract_start_date": str(row["ContractStartDate"]) if row["ContractStartDate"] else None,
        "contract_end_date": str(row["ContractEndDate"]) if row["ContractEndDate"] else None,
    })


@tasks_bp.route("/api/vendor-search", methods=["GET"])
@login_required
def api_vendor_search():
    """Search vw_PurchaseVendorLocation by vendor name or purchase-from name."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    engine = get_sqlserver_engine()
    like = f"%{q.upper()}%"
    with engine.connect() as conn:
        rows = conn.execute(
            load_query("tasks", "tasks", query="vendor_search"),
            {"q": like},
        ).mappings().all()
    return jsonify([
        {
            "erp_vendor_id": r["ERPVendorID"],
            "vendor_name": r["VendorName"],
            "purchase_from_name": r["PurchaseFromName"],
            "active": r["Active"],
        }
        for r in rows
    ])


@tasks_bp.route("/tasks/")
@login_required
def task_list():
    """Render the task list landing page."""
    from ..common.utils import ORG_CHOICES
    return render_template("task_list.html", org_choices=ORG_CHOICES)


@tasks_bp.route("/tasks/<task_id>")
@login_required
def task_detail(task_id: str):
    """Render the per-task detail page."""
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    return render_template("task_detail.html", task_id=task_id, task=task.to_dict())