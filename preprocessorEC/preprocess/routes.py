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

from functools import lru_cache

from flask import jsonify, request, render_template, abort
from flask_login import login_required, current_user
from sqlalchemy import inspect, text

from . import preprocess_bp
from ..db import task_repo, workstate_repo
from ..db.engine import get_sqlserver_engine
from ..services import preprocess_service, scoring
from ..services import llm_review_prompts
from ..state import TaskStateMachine


def _sm() -> TaskStateMachine:
    return TaskStateMachine(task_repo, workstate_repo)


def _with_auto_advance(task_id: str, result: dict, user: str) -> dict:
    task_state = preprocess_service.maybe_auto_advance_preprocess(task_id, _sm(), user)
    if task_state:
        result["task_state"] = task_state
    return result


def _normalize_scope_value(value: str | None) -> str:
    return (value or "").strip().upper()


@lru_cache(maxsize=1)
def _get_ccx_line_count_column() -> str | None:
    columns = {
        column["name"]
        for column in inspect(get_sqlserver_engine()).get_columns(
            "CCXSyncedContractLineCnt",
            schema="Preprocessor",
        )
    }
    if "LineCnt_CCX" in columns:
        return "LineCnt_CCX"
    if "LineCnt_Infor" in columns:
        return "LineCnt_Infor"
    return None


def _fetch_contract_lookup(conn, matched_source: str, organization_eid: str, contract_id: str, erp_vendor_id: str) -> dict:
    if not matched_source or not organization_eid or not contract_id or not erp_vendor_id:
        return {}

    if matched_source == "CCX":
        line_count_column = _get_ccx_line_count_column()
        if not line_count_column:
            return {}
        stmt = text(
            f"""
            SELECT
                [{line_count_column}] AS total_lines,
                [Manufacturer] AS mf_name,
                [Vendor] AS vendor_name,
                [ContractDescription] AS contract_description
            FROM [Preprocessor].[CCXSyncedContractLineCnt]
            WHERE OrganizationEID = :organization_eid
              AND ContractID = :contract_id
              AND ERPVendorID = :erp_vendor_id
            """
        )
    elif matched_source == "INFOR_CL":
        stmt = text(
            """
            SELECT
                [LineCnt_Infor] AS total_lines,
                [ManufacturerName_Infor] AS mf_name,
                [VendorName_Infor] AS vendor_name,
                [ContractDescription_Infor] AS contract_description
            FROM [Preprocessor].[InforActiveContractLineCnt]
            WHERE OrganizationEID = :organization_eid
              AND ContractID = :contract_id
              AND ERPVendorID_Infor = :erp_vendor_id
            """
        )
    else:
        return {}

    row = conn.execute(
        stmt,
        {
            "organization_eid": organization_eid,
            "contract_id": contract_id,
            "erp_vendor_id": erp_vendor_id,
        },
    ).mappings().first()
    if not row:
        return {}
    return {
        "total_lines": row.get("total_lines"),
        "mf_name": row.get("mf_name"),
        "vendor_name": row.get("vendor_name"),
        "contract_description": row.get("contract_description"),
    }


def _requested_threshold_config(data: dict):
    """Pull an optional threshold_config off a request body.

    Returns ``(value, error_message)``. An unknown key is rejected rather than
    silently falling back, so a typo in a scripted call cannot quietly rescore a
    task under the default.
    """
    requested = data.get("threshold_config")
    if requested is None:
        return None, None
    if str(requested).strip().upper() not in scoring.THRESHOLD_CONFIGS:
        return None, f"threshold_config must be one of {sorted(scoring.THRESHOLD_CONFIGS)}"
    return requested, None


def _requested_prompt_version(data: dict):
    """Pull an optional prompt_version off a request body.

    Returns the value, or None to keep whatever the task last ran under. Raises
    KeyError naming the valid options when the value is not a known prompt.
    """
    requested = data.get("prompt_version")
    if requested is None or not str(requested).strip():
        return None
    llm_review_prompts.resolve(requested)  # raises KeyError if unknown
    return requested


def _requested_review_mode(data: dict):
    """Pull an optional review_mode off a request body.

    Returns ``(value, error_message)``. An unknown mode is rejected rather than
    silently falling back, so a typo cannot quietly rejudge a task per pair when
    the caller asked for per input group.
    """
    requested = data.get("review_mode")
    if requested is None or not str(requested).strip():
        return None, None
    if str(requested).strip().upper() not in llm_review_prompts.MODES:
        return None, f"review_mode must be one of {list(llm_review_prompts.MODES)}"
    return requested, None


def _selected_prompt_name(stored: str | None) -> str:
    """Which prompt the picker should pre-select for a task.

    Falls back to the default when the task has never been reviewed, or when it
    was stamped with a version that has since been retired out of the picker —
    the dropdown can only offer what it lists.
    """
    try:
        prompt = llm_review_prompts.resolve(stored)
    except KeyError:
        return llm_review_prompts.DEFAULT_PROMPT_NAME
    if prompt.name not in llm_review_prompts.names():
        return llm_review_prompts.DEFAULT_PROMPT_NAME
    return prompt.name


@preprocess_bp.route("/api/preprocess/<task_id>/run", methods=["POST"])
@login_required
def api_run_preprocess(task_id: str):
    data = request.get_json(silent=True) or {}
    enable_llm = data.get("enable_llm", True)
    threshold_config, error = _requested_threshold_config(data)
    if error:
        return jsonify({"error": error}), 400
    try:
        prompt_version = _requested_prompt_version(data)
    except KeyError as exc:
        return jsonify({"error": str(exc.args[0])}), 400
    review_mode, error = _requested_review_mode(data)
    if error:
        return jsonify({"error": error}), 400
    try:
        result = preprocess_service.run_full_preprocess(
            task_id,
            _sm(),
            enable_llm=bool(enable_llm),
            threshold_config=threshold_config,
            prompt_version=prompt_version,
            review_mode=review_mode,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/data-freshness", methods=["GET"])
@login_required
def api_data_freshness(task_id: str):
    """Report whether this task's CCX matches predate the last source reload.

    The cascade itself is safe either way (it anchors on the stable Infor_pkid),
    but the matched contract lines a reviewer sees were snapshotted from a table
    that has since been replaced, so prices, UOMs, or whole contracts may have
    moved on. Re-running SKU matching is the only way to get current truth.
    """
    return jsonify(preprocess_service.get_ccx_data_freshness(task_id))


@preprocess_bp.route("/api/preprocess/<task_id>/sku-matching", methods=["POST"])
@login_required
def api_sku_matching(task_id: str):
    """Run just CCX SKU matching + similarity scoring.

    Accepts an optional ``threshold_config``: this step rebuilds every CCX match
    from scratch, so it is where a new bucket configuration takes effect and gets
    recorded on the task. Later steps read it back off the task row.
    """
    data = request.get_json(silent=True) or {}
    threshold_config, error = _requested_threshold_config(data)
    if error:
        return jsonify({"error": error}), 400
    result = preprocess_service.run_sku_matching(
        task_id, _sm(), threshold_config=threshold_config,
    )
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


def _resolve_contract_decision(data: dict) -> str:
    """Accept either the tri-state ``decision`` field (INCLUDE | EXCLUDE |
    REPLACE) or the legacy boolean ``include`` (True → INCLUDE, False → EXCLUDE)."""
    raw = data.get("decision")
    if raw:
        return str(raw).upper()
    if "include" in data:
        return "INCLUDE" if bool(data.get("include")) else "EXCLUDE"
    return "INCLUDE"


@preprocess_bp.route("/api/preprocess/<task_id>/contract-decision", methods=["POST"])
@login_required
def api_contract_decision(task_id: str):
    data = request.get_json(force=True)
    contract_number = data.get("contract_number")
    has_organization_eid = "organization_eid" in data
    has_erp_vendor_id = "erp_vendor_id" in data
    organization_eid = data.get("organization_eid")
    erp_vendor_id = data.get("erp_vendor_id")
    decision = _resolve_contract_decision(data)
    if not contract_number:
        return jsonify({"error": "contract_number required"}), 400
    if not has_organization_eid or not has_erp_vendor_id:
        return jsonify({"error": "organization_eid and erp_vendor_id required"}), 400
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.submit_contract_decision(
            task_id,
            contract_number,
            organization_eid,
            erp_vendor_id,
            decision,
            user,
            _sm(),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
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


@preprocess_bp.route("/api/preprocess/<task_id>/buy-uom", methods=["POST"])
@login_required
def api_buy_uom(task_id: str):
    """Run Buy UOM aggregation for labeled item candidates."""
    result = preprocess_service.run_buy_uom_check(task_id, _sm())
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/<task_id>/llm-review", methods=["POST"])
@login_required
def api_llm_review(task_id: str):
    """Run LLM review for pending MED/LOW matches.

    Accepts an optional ``prompt_version`` and ``review_mode``.
    """
    data = request.get_json(silent=True) or {}
    try:
        prompt_version = _requested_prompt_version(data)
    except KeyError as exc:
        return jsonify({"error": str(exc.args[0])}), 400
    review_mode, error = _requested_review_mode(data)
    if error:
        return jsonify({"error": error}), 400

    source = request.args.get("source", "CCX")
    if source == "CCX":
        result = preprocess_service.run_llm_review(
            task_id, _sm(), prompt_version=prompt_version, review_mode=review_mode,
        )
    else:
        result = preprocess_service.run_infor_residue_llm_review(
            task_id, _sm(), prompt_version=prompt_version, review_mode=review_mode,
        )
    return jsonify(result)


@preprocess_bp.route("/api/preprocess/llm-review-prompts/<name>", methods=["GET"])
@login_required
def api_llm_review_prompt(name: str):
    """Full text of one review prompt, for the prompt-viewer modal.

    Retired versions load too, so a task stamped with an old version can still
    show the text its stored verdicts were judged under.
    """
    try:
        prompt = llm_review_prompts.load(name)
    except KeyError as exc:
        return jsonify({"error": str(exc.args[0])}), 404
    # Render for the mode the caller is looking at, so the modal shows the text
    # that would actually be sent rather than the Jinja source with both branches.
    mode = request.args.get("mode") or prompt.default_mode
    if not prompt.supports(mode):
        mode = prompt.default_mode
    return jsonify(prompt.to_dict(mode))


@preprocess_bp.route("/api/preprocess/<task_id>/llm-review-pending", methods=["POST"])
@login_required
def api_llm_review_pending(task_id: str):
    """Send every remaining PENDING match (any bucket, any source) to the LLM.

    Used after manual review to auto-decide leftover PENDING rows in one batch.
    """
    data = request.get_json(silent=True) or {}
    try:
        prompt_version = _requested_prompt_version(data)
    except KeyError as exc:
        return jsonify({"error": str(exc.args[0])}), 400
    review_mode, error = _requested_review_mode(data)
    if error:
        return jsonify({"error": error}), 400
    result = preprocess_service.run_llm_review_pending_all(
        task_id, _sm(), prompt_version=prompt_version, review_mode=review_mode,
    )
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
def _build_contract_summary_rows(
    task_id: str,
    *,
    scope: tuple[str, str, str] | None = None,
) -> list[dict]:
    """Aggregate MatchResult rows into contract-summary entries.

    ``scope`` is an optional ``(contract_id, organization_eid, erp_vendor_id)``
    triple used to restrict the aggregation to a single contract. NULL
    matched-scope columns are treated as empty strings to mirror the
    Python normalization used elsewhere.
    """
    matches = task_repo.get_match_results(task_id)
    if scope is not None:
        cid_filter, org_filter, vendor_filter = (
            (scope[0] or "").strip(),
            (scope[1] or "").strip(),
            (scope[2] or "").strip(),
        )
        matches = [
            m
            for m in matches
            if (m.contract_number or "").strip() == cid_filter
            and (m.organization_eid_matched or "").strip() == org_filter
            and (m.erp_vendor_id_matched or "").strip() == vendor_filter
        ]

    decisions = task_repo.get_contract_decisions_map(task_id)
    contracts: dict[tuple[str, str, str, str, str], dict] = {}

    with get_sqlserver_engine().connect() as conn:
        for m in matches:
            cid = m.contract_number or "__no_contract__"
            source = m.matched_source or ""
            organization_eid = m.organization_eid_matched or ""
            organization = m.organization_matched or ""
            erp_vendor_id = m.erp_vendor_id_matched or ""
            key = (source, organization_eid, organization, cid, erp_vendor_id)

            if key not in contracts:
                lookup = _fetch_contract_lookup(conn, source, organization_eid, cid, erp_vendor_id)
                contracts[key] = {
                    "contract_id": cid,
                    "source": source,
                    "organization": organization,
                    "organization_eid": organization_eid,
                    "erp_vendor_id": erp_vendor_id,
                    "total_lines": lookup.get("total_lines"),
                    "mf_name": lookup.get("mf_name"),
                    "vendor_name": lookup.get("vendor_name"),
                    "contract_description": lookup.get("contract_description"),
                    "total": 0,
                    "high": 0,
                    "med": 0,
                    "low": 0,
                    "accepted": 0,
                    "rejected": 0,
                    "pending": 0,
                    "included": True,
                    "decision": decisions.get(
                        (organization_eid, cid, erp_vendor_id),
                        "",
                    ),
                }

            c = contracts[key]
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

    for contract in contracts.values():
        contract["included"] = not (
            contract["total"] > 0
            and contract["rejected"] == contract["total"]
        )

    return list(contracts.values())


@preprocess_bp.route("/api/preprocess/<task_id>/contract-summary", methods=["GET"])
@login_required
def api_contract_summary(task_id: str):
    """Return contract-level match summary with per-bucket counts."""
    return jsonify(_build_contract_summary_rows(task_id))


def _norm_qoe(value) -> str | None:
    """Compare QOE by numeric value, so 5, "5", and "05" are one thing."""
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text.upper()


def _same_uom_qoe(input_item, match) -> str | None:
    """Yes when the input row and the matched line share sale unit AND pack size.

    Both sides are read on the Infor-mapped UOM rather than the raw one, because
    that is the unit these rows are compared on downstream — the raw UOM can be a
    vendor spelling of the same unit. Both must agree: BX 5 vs PK 5 is No on the
    unit, BX 5 vs EA 1 is No on both, PK 10 vs PK 10 is Yes.

    Returns None when either side is missing a value, since that is unknown
    rather than a mismatch.
    """
    if input_item is None:
        return None
    input_uom = str(input_item.uom_to_match_infor or "").strip().upper()
    match_uom = str(match.uom_to_match_infor_matched or "").strip().upper()
    input_qoe = _norm_qoe(input_item.qoe)
    match_qoe = _norm_qoe(match.qoe_matched)
    if not input_uom or not match_uom or input_qoe is None or match_qoe is None:
        return None
    return "Yes" if (input_uom == match_uom and input_qoe == match_qoe) else "No"


@preprocess_bp.route("/api/preprocess/<task_id>/matches", methods=["GET"])
@login_required
def api_get_matches(task_id: str):
    """Return match results with optional filtering.

    Query params:
        bucket  — HIGH | MED | LOW
        contract — one or more contract number filters
        organization_eid — organization EID filter
        erp_vendor_id — ERP vendor ID filter
        source  — CCX | INFOR_CL
        status  — ACCEPTED | REJECTED | PENDING
    """
    source = request.args.get("source")
    matches = task_repo.get_match_results(task_id, matched_source=source)

    bucket_filter = request.args.get("bucket", "").upper()
    contract_filters = {
        value.upper()
        for value in request.args.getlist("contract")
        if value and value.strip()
    }
    status_filter = request.args.get("status", "").upper()
    uom_nuance_filter = request.args.get("uom_nuance", "").strip().lower()
    has_organization_filter = "organization_eid" in request.args
    has_vendor_filter = "erp_vendor_id" in request.args
    organization_filter = _normalize_scope_value(request.args.get("organization_eid"))
    vendor_filter = _normalize_scope_value(request.args.get("erp_vendor_id"))

    # Build input item lookup for enrichment
    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    item_by_id = {it.item_id: it for it in input_items}

    results = []
    for m in matches:
        if bucket_filter and (m.similarity_bucket or "").upper() != bucket_filter:
            continue
        if contract_filters and (m.contract_number or "").upper() not in contract_filters:
            continue
        if has_organization_filter and _normalize_scope_value(m.organization_eid_matched) != organization_filter:
            continue
        if has_vendor_filter and _normalize_scope_value(m.erp_vendor_id_matched) != vendor_filter:
            continue
        if status_filter and (m.match_status or "").upper() != status_filter:
            continue
        if uom_nuance_filter and (m.uom_nuance or "").strip().lower() != uom_nuance_filter:
            continue

        md = m.to_dict()
        # Enrich with input item fields
        inp = item_by_id.get(m.input_item_id)
        if inp:
            md["input_mfg_catalog_num"] = inp.mfg_catalog_num
            md["input_vendor_catalog_num"] = inp.vendor_catalog_num
            md["input_description"] = inp.description
            md["input_uom"] = inp.uom
            md["input_uom_to_match_infor"] = inp.uom_to_match_infor
            md["input_qoe"] = inp.qoe
            md["input_unit_price"] = float(inp.unit_price) if inp.unit_price is not None else None
        md["same_uom_qoe"] = _same_uom_qoe(inp, m)
        results.append(md)

    return jsonify(results)


@preprocess_bp.route("/api/preprocess/<task_id>/item-matches", methods=["GET"])
@login_required
def api_get_item_matches(task_id: str):
    """Return exploded item matching results enriched with input item fields."""
    input_items = task_repo.get_items_by_source(task_id, "INPUT")
    item_by_id = {it.item_id: it for it in input_items}
    rows = []
    for match in task_repo.get_item_matches(task_id):
        input_item = item_by_id.get(match.item_id)
        expected_buy_uom_option = None
        buy_uom_match = None
        if input_item and input_item.uom_to_match_infor and input_item.qoe:
            expected_buy_uom_option = f"{str(input_item.uom_to_match_infor).strip().upper()}*{int(input_item.qoe)}"
        if expected_buy_uom_option:
            option_set = {
                chunk.strip().upper()
                for chunk in str(match.infor_buy_uom_options or "").split(",")
                if chunk.strip()
            }
            buy_uom_match = expected_buy_uom_option in option_set
        rows.append(
            {
                "match_item_id": match.match_item_id,
                "input_item_id": match.item_id,
                "input_uom": input_item.uom if input_item else None,
                "input_uom_to_match_infor": input_item.uom_to_match_infor if input_item else None,
                "input_qoe": input_item.qoe if input_item else None,
                "expected_buy_uom_option": expected_buy_uom_option,
                "buy_uom_match": buy_uom_match,
                "input_description": input_item.description if input_item else None,
                "infor_item_number": match.infor_item_number,
                "item_description": match.item_description,
                "infor_buy_uom_options": match.infor_buy_uom_options,
                "active_gtin": match.active_gtin,
            }
        )
    return jsonify(rows)


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


@preprocess_bp.route("/api/preprocess/<task_id>/update-true-matches", methods=["POST"])
@login_required
def api_update_true_matches(task_id: str):
    """Mark selected match_ids as ACCEPTED (true match).

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
            task_repo.update_match_decision(int(mid), "ACCEPTED", user)
            updated += 1
        except (ValueError, TypeError):
            continue

    return jsonify({"updated": updated})


@preprocess_bp.route("/api/preprocess/<task_id>/update-pending", methods=["POST"])
@login_required
def api_update_pending(task_id: str):
    """Mark selected match_ids back to PENDING for re-review.

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
            task_repo.update_match_decision(int(mid), "PENDING", user)
            updated += 1
        except (ValueError, TypeError):
            continue

    return jsonify({"updated": updated})


@preprocess_bp.route("/api/preprocess/<task_id>/toggle-contract", methods=["POST"])
@login_required
def api_toggle_contract(task_id: str):
    """Apply a tri-state contract decision to all matches under a contract.

    Body: ``{"contract_number": "X", "organization_eid": "Y",
    "erp_vendor_id": "Z", "decision": "INCLUDE" | "EXCLUDE" | "REPLACE"}``.
    Legacy boolean ``include`` is still accepted (True → INCLUDE,
    False → EXCLUDE).
    """
    data = request.get_json(force=True)
    contract_number = data.get("contract_number")
    has_organization_eid = "organization_eid" in data
    has_erp_vendor_id = "erp_vendor_id" in data
    organization_eid = data.get("organization_eid")
    erp_vendor_id = data.get("erp_vendor_id")
    decision = _resolve_contract_decision(data)
    if not contract_number:
        return jsonify({"error": "contract_number required"}), 400
    if not has_organization_eid or not has_erp_vendor_id:
        return jsonify({"error": "organization_eid and erp_vendor_id required"}), 400

    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.submit_contract_decision(
            task_id,
            contract_number,
            organization_eid,
            erp_vendor_id,
            decision,
            user,
            _sm(),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Recompute summary rows for just the affected scope so the UI can patch
    # contractSummaryData locally instead of re-fetching the full table.
    contract_rows = _build_contract_summary_rows(
        task_id,
        scope=(contract_number, organization_eid, erp_vendor_id),
    )

    return jsonify(
        {
            "contract_number": contract_number,
            "organization_eid": organization_eid,
            "erp_vendor_id": erp_vendor_id,
            "decision": result["decision"],
            "status": result["match_status"],
            "updated": result["affected"],
            "cascade_updated": result.get("cascade_affected", 0),
            "contract_rows": contract_rows,
        }
    )


@preprocess_bp.route("/preprocess/<task_id>")
@login_required
def preprocess_page(task_id: str):
    task = task_repo.get_task(task_id)
    if not task:
        abort(404)
    # Refresh explicit-mode duplicate state on page entry so the gate-keeper
    # surfaces any new collisions caused by edits since last view.
    if (task.precheck_mode or "").lower() == "explicit":
        try:
            preprocess_service._recompute_explicit_duplicates(task_id)
        except Exception:  # noqa: BLE001 — safety net, don't break page render
            pass
    return render_template(
        "preprocess.html",
        task_id=task_id,
        task=task.to_dict(),
        threshold_configs=scoring.threshold_config_options(),
        selected_threshold_config=scoring.resolve_threshold_config(task.threshold_config),
        prompt_versions=llm_review_prompts.options(),
        selected_prompt_version=_selected_prompt_name(task.llm_prompt_version),
        review_modes=llm_review_prompts.mode_options(),
        selected_review_mode=llm_review_prompts.resolve_mode(task.llm_review_mode),
    )


# ---------------------------------------------------------------------------
# Phase 3 issue review (post-finalize, on task detail page)
# ---------------------------------------------------------------------------
@preprocess_bp.route("/api/preprocess/<task_id>/issues", methods=["GET"])
@login_required
def api_get_issues(task_id: str):
    """All preprocess issues for a task (resolved + unresolved)."""
    issues = task_repo.get_preprocess_issues(task_id, include_resolved=True)
    return jsonify([issue.to_dict() for issue in issues])


@preprocess_bp.route("/api/preprocess/<task_id>/items/<int:item_id>/accepted-matches", methods=["GET"])
@login_required
def api_get_accepted_matches(task_id: str, item_id: int):
    """ACCEPTED CCX + INFOR_CL matches for one input item — drill-down panel."""
    matches = preprocess_service.get_accepted_matches_for_item(task_id, item_id)
    return jsonify(matches)


@preprocess_bp.route("/api/preprocess/<task_id>/issues/<int:issue_id>/select-infor-item", methods=["POST"])
@login_required
def api_select_infor_item(task_id: str, issue_id: int):
    """Resolve MULTI_ITEM_ERROR by picking exactly one Infor item#."""
    data = request.get_json(force=True) or {}
    picked = data.get("infor_item_number")
    if not picked:
        return jsonify({"error": "infor_item_number required"}), 400
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.resolve_multi_item_pick(task_id, issue_id, picked, user)
        return jsonify(_with_auto_advance(task_id, result, user))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@preprocess_bp.route("/api/preprocess/<task_id>/issues/<int:issue_id>/note", methods=["POST"])
@login_required
def api_note_buy_uom(task_id: str, issue_id: int):
    """Demote BUY_UOM_ERROR to WARN; carry forward."""
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.resolve_buy_uom_note(task_id, issue_id, user)
        return jsonify(_with_auto_advance(task_id, result, user))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@preprocess_bp.route("/api/preprocess/<task_id>/issues/<int:issue_id>/recheck", methods=["POST"])
@login_required
def api_recheck_buy_uom(task_id: str, issue_id: int):
    """Re-query Infor UOM for the item; resolve if buy UOM is now present."""
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.resolve_buy_uom_recheck(task_id, issue_id, user)
        return jsonify(_with_auto_advance(task_id, result, user))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@preprocess_bp.route("/api/preprocess/<task_id>/issues/<int:issue_id>/edit-uom-qoe", methods=["POST"])
@login_required
def api_edit_buy_uom(task_id: str, issue_id: int):
    """Edit input UOM/QOE on a BUY_UOM_ERROR item.

    Body: {"uom": "BX", "qoe": 5}
    """
    data = request.get_json(force=True) or {}
    new_uom = data.get("uom")
    new_qoe = data.get("qoe")
    if new_uom is None or new_qoe is None:
        return jsonify({"error": "uom and qoe required"}), 400
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.resolve_buy_uom_edit(
            task_id, issue_id, new_uom, new_qoe, user
        )
        return jsonify(_with_auto_advance(task_id, result, user))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@preprocess_bp.route("/api/preprocess/<task_id>/issues/<int:issue_id>/ignore", methods=["POST"])
@login_required
def api_ignore_buy_uom(task_id: str, issue_id: int):
    """EXPIRE-intent only: dismiss WARN, advance item to ITEM_PREPROCESSED."""
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.resolve_buy_uom_ignore(task_id, issue_id, user)
        return jsonify(_with_auto_advance(task_id, result, user))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@preprocess_bp.route("/api/preprocess/<task_id>/items/<int:item_id>", methods=["DELETE"])
@login_required
def api_soft_delete_preprocess_item(task_id: str, item_id: int):
    """Soft-delete an input item from Phase 3 (mark DELETED_PREPROCESS).

    Used to resolve a DUPLICATE_ITEM_ERROR when the user wants to drop one
    of the colliding rows rather than re-edit it.
    """
    user = current_user.username if current_user.is_authenticated else "system"
    try:
        result = preprocess_service.soft_delete_preprocess_item(task_id, item_id, user)
        return jsonify(_with_auto_advance(task_id, result, user))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
