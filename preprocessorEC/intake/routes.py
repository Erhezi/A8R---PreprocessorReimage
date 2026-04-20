"""Intake module â€” Phase 1: file upload, pre-check PC1, error queue.

JSON API routes:
  GET  /api/intake/<task_id>           â†’ current intake state
  POST /api/intake/<task_id>/upload    â†’ upload items file (xlsx/csv)
  POST /api/intake/<task_id>/precheck  â†’ run PC1
  GET  /api/intake/<task_id>/errors    â†’ PC1 error list
  POST /api/intake/<task_id>/recheck   â†’ re-run PC1 on specific items
  POST /api/intake/<task_id>/proceed   â†’ advance to IDENTITY

Jinja routes:
  GET  /intake/<task_id>               â†’ intake form page
"""

from __future__ import annotations

import io
import os

from flask import jsonify, request, render_template, abort, current_app
from flask_login import login_required, current_user

from . import intake_bp
from ..db import task_repo, workstate_repo
from ..services import intake_service
from ..state import TaskStateMachine, Phase


def _sm() -> TaskStateMachine:
    return TaskStateMachine(task_repo, workstate_repo)


# -------------------------------------------------------------------------
# JSON APIs
# -------------------------------------------------------------------------
@intake_bp.route("/api/intake/<task_id>", methods=["GET"])
@login_required
def api_intake_state(task_id: str):
    """Return the current intake state for a task."""
    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    items = task_repo.get_items(task_id)
    errors = task_repo.get_precheck_errors(task_id, phase="PC1")

    # Build dup_groups from persisted errors so the UI can group duplicates.
    # Group by (error_type, error_detail) for unresolved DUPLICATE_* errors.
    _dup_map: dict[tuple[str, str], list[int]] = {}
    for e in errors:
        if e.error_type and e.error_type.startswith("DUPLICATE") and e.item_id is not None and not e.resolved:
            key = (e.error_type, e.error_detail)
            _dup_map.setdefault(key, []).append(e.item_id)
    dup_groups = [
        {"error_type": k[0], "item_ids": sorted(set(ids))}
        for k, ids in _dup_map.items() if len(set(ids)) > 1
    ]

    return jsonify({
        "task_id": task_id,
        "phase": task.phase,
        "status": task.status,
        "precheck_mode": task.precheck_mode or "default",
        "process_type": task.process_type or "",
        "item_count": len(items),
        "items": [i.to_dict() for i in items],
        "errors": [e.to_dict() for e in errors],
        "dup_groups": dup_groups,
    })


@intake_bp.route("/api/intake/<task_id>/items/<int:item_id>", methods=["DELETE"])
@login_required
def api_delete_item(task_id: str, item_id: int):
    """Soft-delete a single item row (mark as DELETED)."""
    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    ok = task_repo.soft_delete_item(item_id)
    if not ok:
        return jsonify({"error": "Item not found"}), 404
    return jsonify({"deleted": item_id, "status": "DELETED"})


@intake_bp.route("/api/intake/<task_id>/upload", methods=["POST"])
@login_required
def api_upload_items(task_id: str):
    """Upload an Excel or CSV file of items for this task."""
    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".xlsx",):
        return jsonify({"error": "Unsupported file type. Use .xlsx"}), 400

    # Column mapping sent from front-end (key→original header name)
    import json as _json
    raw_mapping = request.form.get("column_mapping", "{}")
    try:
        user_mapping = _json.loads(raw_mapping)  # e.g. {"mfg_catalog_num": "Mfr Part #", ...}
    except (ValueError, TypeError):
        user_mapping = {}

    try:
        import pandas as pd

        df = pd.read_excel(io.BytesIO(f.read()), dtype=str)

        # Build reverse map: original_header → internal key
        reverse = {v: k for k, v in user_mapping.items() if v}

        # Rename columns using the user-provided mapping
        df = df.rename(columns=reverse)

        # Normalise remaining column names that weren't explicitly mapped
        df.columns = [
            c if c in reverse.values()
            else c.strip().lower().replace(" ", "_")
            for c in df.columns
        ]

        # Fallback auto-match for any column not explicitly mapped
        col_aliases = {
            "mfg_catalog_num": ["mfg_catalog_num", "mfg_cat_num", "mfg_cat_#", "manufacturer_catalog_number",
                                "mfg#", "manufacturer_part_number", "manufacturer_catalog_#", "manufacturer_part_#"],
            "vendor_catalog_num": ["vendor_catalog_num", "vendor_cat_num", "vendor_cat_#", "vendor#",
                                   "vendor_part_number", "vendor_catalog_#", "vendor_part_#"],
            "description": ["description", "desc", "item_description"],
            "uom": ["uom", "unit_of_measure"],
            "unit_price": ["unit_price", "price", "cost", "contract_price"],
            "qoe": ["qoe", "quantity", "qty", "conversion_factor", "conversion_factor_to_ea",
                     "qoe_(conversion_factor_to_ea)"],
            "tier_description": ["tier_description", "tier_desc", "contract_tier_description"],
            "tier_level": ["tier_level"],
            "intention": ["intention", "action"],
            "organization": ["organization", "org", "company", "contract_company"],
            "contract_number": ["contract_number", "contract_id", "contractid"],
            "vendor_id": ["vendor_id", "erp_vendor_id"],
            "process_type": ["process_type", "contract_process_type"],
            "source_type": ["source_type", "contract_source_type"],
            "oem_name": ["oem_name", "contract_manufacturer", "manufacturer"],
        }

        norm_cols = [c.strip().lower().replace(" ", "_") for c in df.columns]

        def _find_col(target_names):
            for name in target_names:
                if name in norm_cols:
                    return df.columns[norm_cols.index(name)]
            return None

        # Resolve each expected column
        resolved = {}
        for key, aliases in col_aliases.items():
            # If already present by key name (from user mapping), use it
            if key in df.columns:
                resolved[key] = key
            else:
                found = _find_col(aliases)
                if found:
                    resolved[key] = found

        items_to_add = []
        for idx, row in df.iterrows():
            def _str(val, fallback=""):
                """Convert cell value to string, treating NaN/nan as empty."""
                import math
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    return fallback
                s = str(val).strip()
                return fallback if s.lower() == "nan" else s

            def _num(val, fallback=0):
                """Convert cell value to a number, treating NaN/blank as fallback."""
                s = _str(val, "")
                if not s:
                    return fallback
                try:
                    return float(s)
                except (ValueError, TypeError):
                    return fallback

            item = {
                "mfg_catalog_num": _str(row.get(resolved.get("mfg_catalog_num", ""), "")),
                "vendor_catalog_num": _str(row.get(resolved.get("vendor_catalog_num", ""), "")) or None,
                "description": _str(row.get(resolved.get("description", ""), "")),
                "uom": _str(row.get(resolved.get("uom", ""), "")),
                "unit_price": _num(row.get(resolved.get("unit_price", ""), "0"), 0),
                "qoe": _num(row.get(resolved.get("qoe", ""), "1"), 1),
                "intention": _str(row.get(resolved.get("intention", ""), task.intention)) or task.intention,
                "file_row": idx + 2,  # 1-indexed header + data row
            }
            # Optional tier fields
            if "tier_description" in resolved:
                item["tier_description"] = _str(row.get(resolved["tier_description"], "")) or None
            if "tier_level" in resolved:
                item["tier_level"] = _str(row.get(resolved["tier_level"], "")) or None

            items_to_add.append(item)

        task_repo.add_items(task_id, items_to_add)

        # Save original file to network drive
        _UPLOAD_DIR = r"I:\Procurement PMO\dli2\PreprocessorFiles"
        try:
            task_dir = os.path.join(_UPLOAD_DIR, task_id)
            os.makedirs(task_dir, exist_ok=True)
            save_path = os.path.join(task_dir, f.filename)
            f.seek(0)
            f.save(save_path)
        except Exception as save_exc:
            current_app.logger.warning("Could not save file to network drive: %s", save_exc)

        # Move task status to PENDING_PRECHECK
        task_repo.update_task_phase(task_id, "INTAKE", "PENDING_PRECHECK")

        return jsonify({"uploaded": len(items_to_add), "task_id": task_id}), 201

    except Exception as exc:
        current_app.logger.exception("Upload failed")
        return jsonify({"error": f"Upload failed: {str(exc)}"}), 400


@intake_bp.route("/api/intake/<task_id>/reupload", methods=["POST"])
@login_required
def api_reupload_items(task_id: str):
    """Delete all existing items and replace with a new upload."""
    task = task_repo.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    # Block re-upload once task has left INTAKE phase
    if task.phase != "INTAKE":
        return jsonify({"error": "Re-upload is only allowed during the INTAKE phase"}), 400

    # Delete existing items + errors
    task_repo.delete_items_for_task(task_id)

    # Delegate to the main upload handler (it reads request.files & form)
    return api_upload_items(task_id)


@intake_bp.route("/api/intake/<task_id>/precheck", methods=["POST"])
@login_required
def api_run_precheck(task_id: str):
    """Run PC1 pre-check on uploaded items."""
    # Accept optional precheck_mode from request body
    data = request.get_json(silent=True) or {}
    precheck_mode = data.get("precheck_mode")
    if precheck_mode and precheck_mode in ("default", "strict", "explicit", "distributor"):
        task_repo.update_task_fields(task_id, precheck_mode=precheck_mode)

    sm = _sm()
    result = intake_service.run_precheck(task_id, sm)
    return jsonify(result)


@intake_bp.route("/api/intake/<task_id>/errors", methods=["GET"])
@login_required
def api_get_errors(task_id: str):
    """Get all PC1 errors for a task."""
    errors = task_repo.get_precheck_errors(task_id, phase="PC1")
    return jsonify([e.to_dict() for e in errors])


@intake_bp.route("/api/intake/<task_id>/recheck", methods=["POST"])
@login_required
def api_recheck(task_id: str):
    """Re-run PC1 on specific items after fixes."""
    data = request.get_json(force=True)
    item_ids = data.get("item_ids", [])
    if not item_ids:
        return jsonify({"error": "item_ids required"}), 400

    sm = _sm()
    result = intake_service.recheck_items(task_id, item_ids, sm)
    return jsonify(result)


@intake_bp.route("/api/intake/<task_id>/proceed", methods=["POST"])
@login_required
def api_proceed(task_id: str):
    """Advance passing items to Phase 2 (Identity).

    LOCAL contracts: partial advance allowed (some items failed).
    PREMIER contracts: blocked unless all items passed.
    """
    sm = _sm()
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = intake_service.proceed_with_passing(task_id, sm, user)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@intake_bp.route("/api/intake/<task_id>/items/<int:item_id>", methods=["PUT"])
@login_required
def api_edit_item(task_id: str, item_id: int):
    """In-place edit of an ERROR_PC1 item's fields."""
    data = request.get_json(force=True)
    try:
        result = intake_service.update_item_fields(task_id, item_id, data)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@intake_bp.route("/api/intake/<task_id>/items/<int:item_id>/pass", methods=["POST"])
@login_required
def api_manual_pass(task_id: str, item_id: int):
    """Manually pass a WARN_PC1 item with audit trail."""
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = intake_service.manually_pass_item(task_id, item_id, user)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@intake_bp.route("/api/intake/<task_id>/recheck-all", methods=["POST"])
@login_required
def api_recheck_all(task_id: str):
    """Reset ALL error/warn items to UPLOADED and re-run PC1."""
    data = request.get_json(silent=True) or {}
    precheck_mode = data.get("precheck_mode")
    if precheck_mode and precheck_mode in ("default", "strict", "explicit", "distributor"):
        task_repo.update_task_fields(task_id, precheck_mode=precheck_mode)

    sm = _sm()
    items = task_repo.get_items(task_id)
    error_warn_ids = [i.item_id for i in items if i.status in ("ERROR_PC1", "WARN_PC1")]
    if not error_warn_ids:
        return jsonify({"error": "No items to re-check"}), 400
    result = intake_service.recheck_items(task_id, error_warn_ids, sm)
    return jsonify(result)


# -------------------------------------------------------------------------
# Jinja template route
# -------------------------------------------------------------------------
@intake_bp.route("/intake/<task_id>")
@login_required
def intake_form(task_id: str):
    """Render the intake form page."""
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    return render_template("intake_form.html", task_id=task_id)



