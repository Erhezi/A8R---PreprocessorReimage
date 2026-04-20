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


@preprocess_bp.route("/api/preprocess/<task_id>/sku-matching", methods=["POST"])
@login_required
def api_sku_matching(task_id: str):
    """Run just CCX SKU matching + similarity scoring."""
    result = preprocess_service.run_sku_matching(task_id, _sm())
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/contract-check", methods=["POST"])
@login_required
def api_contract_check(task_id: str):
    """Run contract-level grouping for review."""
    result = preprocess_service.run_contract_check(task_id, _sm())
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/contracts", methods=["GET"])
@login_required
def api_get_contracts(task_id: str):
    state = workstate_repo.load_state(task_id)
    if not state:
        return jsonify({"error": "No working state found"}), 404
    return jsonify({"contracts": state.get("contract_review", [])})


@preprocess_bp.route("/api/preprocess/<task_id>/contract-decision", methods=["POST"])
@login_required
def api_contract_decision(task_id: str):
    data = request.get_json(force=True)
    contract_number = data.get("contract_number")
    include = data.get("include", True)
    if not contract_number:
        return jsonify({"error": "contract_number required"}), 400
    user = current_user.username if current_user.is_authenticated else "system"
    result = preprocess_service.submit_contract_decision(
        task_id, contract_number, include, user, _sm()
    )
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/items", methods=["GET"])
@login_required
def api_get_items(task_id: str):
    source = request.args.get("source")  # optional: CCX | INFOR_CL | INFOR_IM
    matches = task_repo.get_match_results(task_id, matched_source=source)
    return jsonify([m.to_dict() for m in matches])


@preprocess_bp.route("/api/preprocess/<task_id>/item-decision", methods=["POST"])
@login_required
def api_item_decision(task_id: str):
    data = request.get_json(force=True)
    match_id = data.get("match_id")
    decision = data.get("decision")
    if not match_id or decision not in ("ACCEPTED", "REJECTED", "LLM_REVIEW"):
        return jsonify({"error": "match_id and valid decision required"}), 400
    user = current_user.username if current_user.is_authenticated else "system"
    result = preprocess_service.submit_item_decision(
        task_id, match_id, decision, user, _sm()
    )
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/summary", methods=["GET"])
@login_required
def api_summary(task_id: str):
    """Return preprocessed dataset summary: INPUT items with labeling info."""
    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    matches = task_repo.get_match_results(task_id)

    # Group matches by input_item_id
    matches_by_item = {}
    for m in matches:
        matches_by_item.setdefault(m.input_item_id, []).append(m.to_dict())

    summary = []
    for item in input_items:
        d = item.to_dict()
        d["matches"] = matches_by_item.get(item.item_id, [])
        summary.append(d)
    return jsonify(summary)


@preprocess_bp.route("/api/preprocess/<task_id>/infor-cascade", methods=["POST"])
@login_required
def api_infor_cascade(task_id: str):
    """Run Infor cascade step (after CCX decisions are made)."""
    result = preprocess_service.run_infor_cascade(task_id, _sm())
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/infor-residue", methods=["POST"])
@login_required
def api_infor_residue(task_id: str):
    """Run Infor residue matching step."""
    result = preprocess_service.run_infor_residue(task_id, _sm())
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/item-labeling", methods=["POST"])
@login_required
def api_item_labeling(task_id: str):
    """Run 3-source Item# labeling step."""
    result = preprocess_service.run_item_labeling(task_id, _sm())
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/llm-review", methods=["POST"])
@login_required
def api_llm_review(task_id: str):
    """Run LLM review for pending MED/LOW matches."""
    source = request.args.get("source", "CCX")
    if source == "CCX":
        result = preprocess_service.run_llm_review(task_id, _sm())
    else:
        result = preprocess_service.run_infor_residue_llm_review(task_id, _sm())
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/finalize", methods=["POST"])
@login_required
def api_finalize(task_id: str):
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.finalize_preprocess(task_id, _sm(), user)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


# ---------------------------------------------------------------------------
# New API routes for enriched UI
# ---------------------------------------------------------------------------
@preprocess_bp.route("/api/preprocess/<task_id>/contract-summary", methods=["GET"])
@login_required
def api_contract_summary(task_id: str):
    """Return contract-level match summary with per-bucket counts."""
    matches = task_repo.get_match_results(task_id)
    contracts: dict[str, dict] = {}
    for m in matches:
        cid = m.contract_number or "__no_contract__"
        if cid not in contracts:
            contracts[cid] = {
                "contract_id": cid,
                "total": 0, "high": 0, "med": 0, "low": 0,
                "accepted": 0, "rejected": 0, "pending": 0,
                "included": True,
            }
        c = contracts[cid]
        c["total"] += 1
        bucket = (m.similarity_bucket or "LOW").upper()
        if bucket == "HIGH":
            c["high"] += 1
        elif bucket == "MED":
            c["med"] += 1
        else:
            c["low"] += 1
        status = (m.match_status or "PENDING").upper()
        if status == "ACCEPTED":
            c["accepted"] += 1
        elif status == "REJECTED":
            c["rejected"] += 1
        else:
            c["pending"] += 1

    return jsonify(list(contracts.values()))


@preprocess_bp.route("/api/preprocess/<task_id>/matches", methods=["GET"])
@login_required
def api_get_matches(task_id: str):
    """Return match results with optional filtering.

    Query params:
        bucket  — HIGH | MED | LOW
        contract — contract number filter
        source  — CCX | INFOR_CL
        status  — ACCEPTED | REJECTED | PENDING
    """
    source = request.args.get("source")
    matches = task_repo.get_match_results(task_id, matched_source=source)

    bucket_filter = request.args.get("bucket", "").upper()
    contract_filter = request.args.get("contract", "").upper()
    status_filter = request.args.get("status", "").upper()

    # Build input item lookup for enrichment
    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    item_by_id = {it.item_id: it for it in input_items}

    results = []
    for m in matches:
        if bucket_filter and (m.similarity_bucket or "").upper() != bucket_filter:
            continue
        if contract_filter and (m.contract_number or "").upper() != contract_filter:
            continue
        if status_filter and (m.match_status or "").upper() != status_filter:
            continue

        md = m.to_dict()
        # Enrich with input item fields
        inp = item_by_id.get(m.input_item_id)
        if inp:
            md["input_mfg_catalog_num"] = inp.mfg_catalog_num
            md["input_vendor_catalog_num"] = inp.vendor_catalog_num
            md["input_description"] = inp.description
            md["input_uom"] = inp.uom
            md["input_qoe"] = inp.qoe
            md["input_unit_price"] = float(inp.unit_price) if inp.unit_price else None
        results.append(md)

    return jsonify(results)


@preprocess_bp.route("/api/preprocess/<task_id>/update-false-positives", methods=["POST"])
@login_required
def api_update_false_positives(task_id: str):
    """Mark selected match_ids as REJECTED (false positive).

    Body: {"match_ids": [1, 2, 3]}
    """
    data = request.get_json(force=True)
    match_ids = data.get("match_ids", [])
    if not match_ids or not isinstance(match_ids, list):
        return jsonify({"error": "match_ids list required"}), 400

    user = current_user.username if current_user.is_authenticated else "system"
    updated = 0
    for mid in match_ids:
        try:
            task_repo.update_match_decision(int(mid), "REJECTED", user)
            updated += 1
        except (ValueError, TypeError):
            continue

    return jsonify({"updated": updated})


@preprocess_bp.route("/api/preprocess/<task_id>/toggle-contract", methods=["POST"])
@login_required
def api_toggle_contract(task_id: str):
    """Include or exclude all matches under a contract.

    Body: {"contract_number": "X", "include": true|false}
    """
    data = request.get_json(force=True)
    contract_number = data.get("contract_number")
    include = data.get("include", True)
    if not contract_number:
        return jsonify({"error": "contract_number required"}), 400

    user = current_user.username if current_user.is_authenticated else "system"
    new_status = "ACCEPTED" if include else "REJECTED"

    matches = task_repo.get_match_results(task_id)
    updated = 0
    for m in matches:
        if (m.contract_number or "").upper() == contract_number.upper():
            task_repo.update_match_decision(m.match_id, new_status, user)
            updated += 1

    return jsonify({"contract_number": contract_number, "status": new_status, "updated": updated})


@preprocess_bp.route("/preprocess/<task_id>")
@login_required
def preprocess_page(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    return render_template("preprocess.html", task_id=task_id)