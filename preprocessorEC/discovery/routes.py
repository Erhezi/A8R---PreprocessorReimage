"""Quick Discovery routes — upload, match, results, LLM run, prompt admin.

Thin HTTP layer: parse the request, call a service, translate errors to JSON.
All business logic lives in services/discovery_service.py and
services/discovery_llm.py.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re

from flask import (
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
)
from flask_login import current_user, login_required

from . import discovery_bp
from ..common.utils import role_required
from ..db import discovery_repo
from ..services import discovery_llm, discovery_service
from ..services.discovery_service import DiscoveryInputError
from ..services.llm_client import build_client, client_settings_from_config

logger = logging.getLogger(__name__)

PROMPT_KEY = "ITEM_COMPARE"


def _current_username() -> str:
    return current_user.username if current_user.is_authenticated else "system"


def _is_preprocessor() -> bool:
    return (getattr(current_user, "role", "") or "").lower() == "preprocessor"


def _int_arg(name: str, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _float_arg(name: str, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _result_filters() -> dict:
    sku_exact = request.args.get("sku_exact")
    if sku_exact in ("1", "true", "True", "yes"):
        sku_exact_val = True
    elif sku_exact in ("0", "false", "False", "no"):
        sku_exact_val = False
    else:
        sku_exact_val = None

    return {
        "verdict": request.args.get("verdict") or None,
        "sku_exact": sku_exact_val,
        "matched_on": request.args.get("matched_on") or None,
        "min_similarity": _float_arg("min_similarity"),
        "max_rank": _int_arg("max_rank"),
        "contract_id": request.args.get("contract_id") or None,
        "search": (request.args.get("search") or "").strip() or None,
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@discovery_bp.route("/discovery/")
@login_required
def discovery_home():
    return render_template(
        "discovery_home.html",
        max_rows=current_app.config.get("DISCOVERY_MAX_ROWS", 5000),
        is_preprocessor=_is_preprocessor(),
    )


@discovery_bp.route("/discovery/<int:set_id>")
@login_required
def discovery_set_page(set_id: int):
    discovery_set = discovery_repo.get_set(set_id)
    if discovery_set is None:
        return render_template("discovery_home.html",
                               max_rows=current_app.config.get("DISCOVERY_MAX_ROWS", 5000),
                               is_preprocessor=_is_preprocessor(),
                               missing_set_id=set_id), 404
    return render_template(
        "discovery_set.html",
        discovery_set=discovery_set.to_dict(),
        set_id=set_id,
        is_preprocessor=_is_preprocessor(),
    )


@discovery_bp.route("/discovery/prompts")
@login_required
def discovery_prompts_page():
    """Anyone may read the prompts — that is how a user understands a verdict.
    Only a preprocessor may save a new version (enforced on the POST route)."""
    return render_template(
        "discovery_prompt.html",
        is_preprocessor=_is_preprocessor(),
        template_variables=list(discovery_llm.TEMPLATE_VARIABLES),
    )


# ---------------------------------------------------------------------------
# Sets
# ---------------------------------------------------------------------------
@discovery_bp.route("/api/discovery/sets", methods=["GET"])
@login_required
def api_list_sets():
    limit = _int_arg("limit", 200) or 200
    limit = max(1, min(limit, 1000))
    mine_only = request.args.get("mine") in ("1", "true", "True")
    sets = discovery_repo.list_sets(
        limit=limit,
        created_by=_current_username() if mine_only else None,
    )
    return jsonify([s.to_dict() for s in sets])


@discovery_bp.route("/api/discovery/upload", methods=["POST"])
@login_required
def api_upload():
    """Upload a discovery file: SKU + Description (+ optional Supplier)."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext != ".xlsx":
        return jsonify({"error": "Unsupported file type. Use .xlsx"}), 400

    try:
        user_mapping = json.loads(request.form.get("column_mapping", "{}"))
    except (ValueError, TypeError):
        user_mapping = {}

    match_mode = (request.form.get("match_mode") or discovery_service.DEFAULT_MATCH_MODE).upper()
    set_name = (request.form.get("set_name") or "").strip() or None

    try:
        import pandas as pd

        dataframe = pd.read_excel(io.BytesIO(f.read()), dtype=str)
    except Exception as exc:
        logger.exception("Discovery upload could not be read: %s", exc)
        return jsonify({"error": f"Could not read the file: {exc}"}), 400

    try:
        result = discovery_service.create_set_from_upload(
            dataframe,
            user_mapping=user_mapping,
            match_mode=match_mode,
            set_name=set_name,
            source_filename=f.filename,
            created_by=_current_username(),
            max_rows=current_app.config.get("DISCOVERY_MAX_ROWS", 5000),
        )
    except DiscoveryInputError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Discovery upload failed: %s", exc)
        return jsonify({"error": f"Upload failed: {exc}"}), 500

    return jsonify(result)


@discovery_bp.route("/api/discovery/<int:set_id>", methods=["DELETE"])
@login_required
def api_delete_set(set_id: int):
    deleted = discovery_repo.delete_set(set_id)
    if not deleted:
        return jsonify({"error": "Set not found"}), 404
    return jsonify({"deleted": set_id})


@discovery_bp.route("/api/discovery/<int:set_id>/match", methods=["POST"])
@login_required
def api_match(set_id: int):
    """Run CCX SKU matching, local similarity scoring, and ranking."""
    try:
        result = discovery_service.run_matching(
            set_id,
            model=current_app.config.get("TRANSFORMER_MODEL"),
        )
    except DiscoveryInputError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Discovery matching failed for set %s: %s", set_id, exc)
        discovery_repo.update_set(set_id, status="UPLOADED")
        return jsonify({"error": f"Matching failed: {exc}"}), 500
    return jsonify(result)


@discovery_bp.route("/api/discovery/<int:set_id>/summary", methods=["GET"])
@login_required
def api_summary(set_id: int):
    discovery_set = discovery_repo.get_set(set_id)
    if discovery_set is None:
        return jsonify({"error": "Set not found"}), 404
    summary = discovery_repo.get_summary(set_id)
    summary["set"] = discovery_set.to_dict()
    return jsonify(summary)


@discovery_bp.route("/api/discovery/<int:set_id>/results", methods=["GET"])
@login_required
def api_results(set_id: int):
    """Server-side paged results — a set can hold tens of thousands of rows."""
    offset = max(0, _int_arg("offset", 0) or 0)
    limit = _int_arg("limit", 100) or 100
    limit = max(1, min(limit, 500))
    return jsonify(
        discovery_repo.get_results_page(set_id, _result_filters(), offset=offset, limit=limit)
    )


@discovery_bp.route("/api/discovery/<int:set_id>/export.xlsx", methods=["GET"])
@login_required
def api_export(set_id: int):
    discovery_set = discovery_repo.get_set(set_id)
    if discovery_set is None:
        return jsonify({"error": "Set not found"}), 404

    rows = discovery_repo.get_results_for_export(set_id, _result_filters())

    import pandas as pd

    columns = [
        ("file_row", "Input Row"),
        ("sku_input", "Input SKU"),
        ("description_input", "Input Description"),
        ("supplier_input", "Input Supplier"),
        ("matched_on", "Matched On"),
        ("sku_exact", "SKU Exact"),
        ("desc_similarity", "Description Similarity"),
        ("rank_in_item", "Rank"),
        ("mfg_catalog_num_matched", "Matched Mfg #"),
        ("vendor_catalog_num_matched", "Matched Vendor #"),
        ("description_matched", "Matched Description"),
        ("uom_matched", "Matched UOM"),
        ("qoe_matched", "Matched QOE"),
        ("unit_price_matched", "Matched Price"),
        ("contract_id_matched", "Contract"),
        ("contract_description", "Contract Description"),
        ("organization_matched", "Organization"),
        ("erp_vendor_id_matched", "ERP Vendor ID"),
        ("vendor_name_matched", "Vendor Name"),
        ("mfg_name_matched", "Manufacturer Name"),
        ("llm_verdict", "LLM Verdict"),
        ("llm_confidence", "LLM Confidence"),
        ("llm_reason", "LLM Reason"),
        ("llm_prompt_version_id", "Prompt Version"),
    ]
    frame = pd.DataFrame(
        [{label: row.get(key) for key, label in columns} for row in rows],
        columns=[label for _key, label in columns],
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Discovery")
    buffer.seek(0)

    # Set names are free text and may contain path separators or other
    # characters that don't belong in a download filename.
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", discovery_set.set_name or f"discovery-{set_id}")
    name = name.strip("._-") or f"discovery-{set_id}"
    return send_file(
        buffer,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"{name}_discovery_{set_id}.xlsx",
    )


# ---------------------------------------------------------------------------
# LLM run
# ---------------------------------------------------------------------------
@discovery_bp.route("/api/discovery/<int:set_id>/llm/start", methods=["POST"])
@login_required
def api_llm_start(set_id: int):
    """Queue rows for judging and return the total the browser must work through."""
    data = request.get_json(silent=True) or {}
    scope = (data.get("scope") or "ALL").upper()
    top_n = data.get("top_n")
    match_ids = data.get("match_ids")
    include_done = bool(data.get("include_done"))

    if discovery_repo.get_set(set_id) is None:
        return jsonify({"error": "Set not found"}), 404

    # Rows claimed by a run that died mid-flight would otherwise stay claimed.
    discovery_repo.reset_stuck_in_progress(set_id)

    try:
        queued = discovery_repo.queue_for_llm(
            set_id,
            scope,
            top_n=top_n,
            match_ids=match_ids,
            include_done=include_done,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    prompt = discovery_llm.get_active_prompt_dict(PROMPT_KEY)
    if prompt is None:
        return jsonify({
            "error": "No active comparison prompt. Apply migration 032 or activate a version."
        }), 400

    discovery_repo.update_set(
        set_id, status="LLM_RUNNING" if queued else "MATCHED"
    )
    return jsonify({
        "queued": queued,
        "remaining": discovery_repo.count_llm_remaining(set_id),
        "prompt_version_id": prompt["prompt_version_id"],
        "prompt_version_no": prompt["version_no"],
        "slice_size": current_app.config.get("DISCOVERY_LLM_SLICE", 50),
    })


@discovery_bp.route("/api/discovery/<int:set_id>/llm/run-slice", methods=["POST"])
@login_required
def api_llm_run_slice(set_id: int):
    """Judge one slice. The page calls this until ``remaining`` hits zero."""
    prompt = discovery_llm.get_active_prompt_dict(PROMPT_KEY)
    if prompt is None:
        return jsonify({"error": "No active comparison prompt."}), 400

    settings = client_settings_from_config(current_app.config)
    model_settings = discovery_llm.resolve_model_settings(prompt, settings)

    # Built once per request on the request thread, then shared by the workers —
    # they have no application context of their own.
    client = build_client(settings)

    data = request.get_json(silent=True) or {}
    slice_size = data.get("slice_size") or current_app.config.get("DISCOVERY_LLM_SLICE", 50)
    slice_size = max(1, min(int(slice_size), 500))

    try:
        result = discovery_llm.run_slice(
            set_id,
            client=client,
            prompt=prompt,
            model=model_settings["model"],
            temperature=model_settings["temperature"],
            max_tokens=model_settings["max_tokens"],
            slice_size=slice_size,
            max_workers=current_app.config.get("DISCOVERY_LLM_WORKERS", 8),
        )
    except discovery_llm.PromptRenderError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Discovery LLM slice failed for set %s: %s", set_id, exc)
        return jsonify({"error": f"LLM slice failed: {exc}"}), 500

    result["prompt_version_id"] = prompt["prompt_version_id"]
    return jsonify(result)


@discovery_bp.route("/api/discovery/<int:set_id>/llm/cancel", methods=["POST"])
@login_required
def api_llm_cancel(set_id: int):
    """Drop everything still queued. Rows already judged keep their verdicts."""
    cleared = discovery_repo.cancel_llm_queue(set_id)
    summary = discovery_repo.get_summary(set_id)
    discovery_repo.update_set(
        set_id, status="LLM_COMPLETE" if summary["llm_done"] else "MATCHED"
    )
    return jsonify({"cleared": cleared, "remaining": 0})


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
@discovery_bp.route("/api/discovery/prompts", methods=["GET"])
@login_required
def api_list_prompts():
    prompts = discovery_repo.list_prompts(PROMPT_KEY)
    return jsonify({
        "prompt_key": PROMPT_KEY,
        "can_edit": _is_preprocessor(),
        "variables": list(discovery_llm.TEMPLATE_VARIABLES),
        "versions": [p.to_dict() for p in prompts],
    })


@discovery_bp.route("/api/discovery/prompts", methods=["POST"])
@login_required
@role_required("preprocessor")
def api_create_prompt():
    """Save a new prompt version. Existing versions are never mutated."""
    data = request.get_json(silent=True) or {}
    system_prompt = data.get("system_prompt") or ""
    user_template = data.get("user_template") or ""

    try:
        discovery_llm.validate_template(system_prompt, user_template)
    except discovery_llm.PromptRenderError as exc:
        return jsonify({"error": str(exc)}), 400

    temperature = data.get("temperature")
    if temperature not in (None, ""):
        try:
            temperature = float(temperature)
        except (TypeError, ValueError):
            return jsonify({"error": "temperature must be a number"}), 400
    else:
        temperature = None

    row = discovery_repo.create_prompt_version(
        prompt_key=PROMPT_KEY,
        system_prompt=system_prompt,
        user_template=user_template,
        created_by=_current_username(),
        notes=(data.get("notes") or "").strip()[:500] or None,
        model=(data.get("model") or "").strip() or None,
        temperature=temperature,
        activate=bool(data.get("activate", True)),
    )
    return jsonify(row.to_dict())


@discovery_bp.route("/api/discovery/prompts/<int:prompt_version_id>/activate", methods=["POST"])
@login_required
@role_required("preprocessor")
def api_activate_prompt(prompt_version_id: int):
    if not discovery_repo.activate_prompt_version(prompt_version_id):
        return jsonify({"error": "Prompt version not found"}), 404
    return jsonify({"activated": prompt_version_id})


@discovery_bp.route("/api/discovery/prompts/preview", methods=["POST"])
@login_required
def api_preview_prompt():
    """Render a template against a sample pair so an author can see the result."""
    data = request.get_json(silent=True) or {}
    sample = data.get("sample") or {
        "input_sku": "AB-1234",
        "input_description": "SCALPEL, DISPOSABLE, NO 10, STERILE, 10/PK",
        "input_supplier": "MEDLINE",
        "matched_sku": "AB1234",
        "matched_description": "BLADE SCALPEL SIZE 10 STERILE DISPOSABLE 10/CA",
        "matched_vendor_name": "CARDINAL HEALTH",
        "matched_manufacturer_name": "ASPEN SURGICAL",
        "sku_exact": False,
        "matched_on": "REDUCED_MFG",
        "desc_similarity": 0.82,
    }
    try:
        rendered = discovery_llm.render_user_prompt(data.get("user_template") or "", sample)
    except discovery_llm.PromptRenderError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"rendered": rendered, "sample": sample})
