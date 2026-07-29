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
from ..common.utils import ny_now
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
    """Return the task list as JSON.

    Optional server-side `phase` / `status` filters plus a `limit` override
    (default 200, capped at 10000). The landing page pulls the full set with
    a high limit and runs search / Wrike-filter / pagination client-side.
    """
    phase = request.args.get("phase")
    status = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 10000))
    tasks = task_repo.list_tasks(phase=phase, status=status, limit=limit)
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


# -------------------------------------------------------------------------
# Contract-number registration — preprocessor / MDM only.
#
# NEW/LOCATE tasks carry free-text under `contract_number` until the real CCX
# system contract id is acquired. These endpoints let a preprocessor/MDM user
# swap that free text for a verified CCX ContractID so downstream monitoring can
# track item synchronization by contract. The original free text is preserved
# in the task notes.
# -------------------------------------------------------------------------
_CONTRACT_EDIT_ROLES = {"preprocessor", "mdm"}


def _has_contract_edit_role() -> bool:
    return (getattr(current_user, "role", "") or "").lower() in _CONTRACT_EDIT_ROLES


def _reg_norm(value) -> str:
    return str(value or "").strip().upper()


def _reg_org_match(a, b) -> bool:
    """Organizations match — tolerant of the label/db-value drift between the
    task's stored organization and the CCX Organization string (same
    contains-both-ways logic the create-task fetch uses)."""
    na, nb = _reg_norm(a), _reg_norm(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _reg_date_match(a, b) -> bool:
    # Compare the date portion only. Two empty dates are consistent (nothing to
    # contradict); one present and one missing is a mismatch.
    return str(a or "")[:10] == str(b or "")[:10]


def _fetch_contract_rows(contract_id: str):
    engine = get_sqlserver_engine()
    with engine.connect() as conn:
        return conn.execute(
            load_query("tasks", "tasks", query="contract_rows_by_id"),
            {"cid": contract_id},
        ).mappings().all()


def _evaluate_contract_registration(task, rows) -> dict:
    """Compare a task's header against the CCX rows for an entered contract id.

    Vendor (ERP vendor id) and organization are the hard gates; the contract
    end date is a soft gate. Against the best-matching CCX row, the outcome is:
      NOT_FOUND     — no CCX row for the contract id
      MATCH         — vendor + org + end date all match
      END_DATE_ONLY — vendor + org match but end date differs (needs user OK)
      BLOCKED       — vendor and/or org differ (cannot locate the contract)
    """
    if not rows:
        return {"found": False, "outcome": "NOT_FOUND"}

    best = None
    best_score = None
    for r in rows:
        vendor = bool(_reg_norm(task.vendor_id)) and _reg_norm(task.vendor_id) == _reg_norm(r["ERPVendorID"])
        org = _reg_org_match(task.organization, r["Organization"])
        end = _reg_date_match(task.contract_end_date, r["ContractEndDate"])
        # Rank rows so the closest match wins: vendor+org first, then end date.
        score = (
            1 if (vendor and org) else 0,
            1 if end else 0,
            1 if vendor else 0,
            1 if org else 0,
        )
        if best_score is None or score > best_score:
            best_score = score
            best = {"row": r, "vendor": vendor, "organization": org, "end_date": end}

    if best["vendor"] and best["organization"] and best["end_date"]:
        outcome = "MATCH"
    elif best["vendor"] and best["organization"]:
        outcome = "END_DATE_ONLY"
    else:
        outcome = "BLOCKED"

    r = best["row"]
    return {
        "found": True,
        "outcome": outcome,
        "comparison": {
            "vendor": best["vendor"],
            "organization": best["organization"],
            "end_date": best["end_date"],
        },
        "ccx": {
            "contract_number": str(r["ContractID"] or "").strip(),
            "vendor_id": str(r["ERPVendorID"] or "").strip(),
            "vendor_name": str(r["Vendor"] or "").strip(),
            "organization": str(r["Organization"] or "").strip(),
            "contract_end_date": str(r["ContractEndDate"])[:10] if r["ContractEndDate"] else None,
        },
    }


@tasks_bp.route("/api/tasks/<task_id>/contract-registration-precheck", methods=["GET"])
@login_required
def api_contract_registration_precheck(task_id: str):
    """Verify an entered CCX contract number against a task's header (no writes)."""
    if not _has_contract_edit_role():
        return jsonify({"error": "You do not have permission to edit the contract number."}), 403
    contract_id = request.args.get("contract_id", "").strip()
    if not contract_id:
        return jsonify({"error": "contract_id is required"}), 400
    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    result = _evaluate_contract_registration(task, _fetch_contract_rows(contract_id))
    result["current_contract"] = task.contract_number
    result["task"] = {
        "vendor_id": task.vendor_id,
        "organization": task.organization,
        "contract_end_date": str(task.contract_end_date)[:10] if task.contract_end_date else None,
    }
    return jsonify(result), 200


@tasks_bp.route("/api/tasks/<task_id>/contract-number", methods=["POST"])
@login_required
def api_register_contract_number(task_id: str):
    """Register a verified CCX contract number on a task.

    Re-validates server-side, then (on MATCH, or END_DATE_ONLY with explicit
    permission) sets ``contract_number`` to the CCX ContractID and preserves the
    prior free text in the task notes.

    When the vendor/org do not match (BLOCKED), a preprocessor/MDM user may pass
    ``allow_vendor_org_overwrite`` to overwrite the task's vendor and
    organization with the CCX contract's values; the original vendor and
    organization are preserved in the task notes.
    """
    if not _has_contract_edit_role():
        return jsonify({"error": "You do not have permission to edit the contract number."}), 403

    data = request.get_json(force=True) or {}
    contract_id = str(data.get("contract_id", "")).strip()
    allow_end_date_mismatch = bool(data.get("allow_end_date_mismatch", False))
    allow_vendor_org_overwrite = bool(data.get("allow_vendor_org_overwrite", False))
    if not contract_id:
        return jsonify({"error": "contract_id is required"}), 400

    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    result = _evaluate_contract_registration(task, _fetch_contract_rows(contract_id))
    outcome = result["outcome"]
    ccx = result["ccx"]

    if outcome == "NOT_FOUND":
        return jsonify({
            "error": "Contract number not found in the CCX synced contracts.",
            "outcome": outcome,
        }), 404
    if outcome == "BLOCKED" and not allow_vendor_org_overwrite:
        return jsonify({
            "error": ("We won't be able to locate this contract — the vendor ID and/or "
                      "organization do not match this task. Try resolving the identity "
                      "first and come back later."),
            "outcome": outcome,
            "comparison": result["comparison"],
        }), 409
    if outcome == "END_DATE_ONLY" and not allow_end_date_mismatch:
        return jsonify({
            "error": ("The contract was found but its end date does not match this task. "
                      "Confirm to proceed with the contract number update anyway."),
            "outcome": outcome,
            "needs_confirmation": True,
            "ccx": ccx,
        }), 409

    # Proceed — MATCH, END_DATE_ONLY (with permission), or BLOCKED (with an
    # explicit vendor/org overwrite).
    overwrite = outcome == "BLOCKED" and allow_vendor_org_overwrite
    new_cid = ccx["contract_number"] or contract_id
    user = getattr(current_user, "username", "") or "system"
    today = ny_now().strftime("%Y-%m-%d")

    fields = {"contract_number": new_cid}
    note_lines = []

    if overwrite:
        orig_vendor = task.vendor_id or ""
        orig_vendor_name = task.erp_vendor_name or ""
        orig_org = task.organization or ""
        new_vendor = ccx["vendor_id"]
        new_vendor_name = ccx["vendor_name"]
        new_org = ccx["organization"]
        # The ERP vendor id encodes the purchase-from location as the "-Bxxx"
        # suffix; the location *name* isn't on the CCX header, so clear it
        # rather than leave the previous vendor's location showing.
        pf_loc = new_vendor.split("-", 1)[1] if "-" in new_vendor else None
        fields.update({
            "vendor_id": new_vendor or None,
            "erp_vendor_name": new_vendor_name or None,
            "purchase_from_loc": pf_loc,
            "purchase_from_loc_name": None,
            "organization": new_org or task.organization,
        })
        orig_vendor_disp = orig_vendor if not orig_vendor_name else f"{orig_vendor} - {orig_vendor_name}"
        note_lines.append(
            f"(vendor and organization overwritten to match contract {new_cid} — "
            f"original vendor: {orig_vendor_disp or '—'}, "
            f"original organization: {orig_org or '—'}, by {user} on {today})"
        )

    old_text = task.contract_number
    note_lines.append(
        f"(registered as {new_cid}, previously named as "
        f"{old_text if (old_text and old_text.strip()) else '—'} by {user} on {today})"
    )

    note_block = "\n".join(note_lines)
    if task.notes and task.notes.strip():
        fields["notes"] = task.notes.rstrip() + "\n\n" + note_block
    else:
        fields["notes"] = note_block

    task_repo.update_task_fields(task_id, **fields)
    updated = task_repo.get_task(task_id)
    return jsonify({"ok": True, "outcome": outcome, "overwritten": overwrite, "task": updated.to_dict()}), 200


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