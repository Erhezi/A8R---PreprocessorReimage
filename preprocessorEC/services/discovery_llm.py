"""Quick Discovery — LLM item comparison with versioned prompts.

Differences from ``llm_review``, which judges contract-load matches:

* The prompt is a database row, not a module constant, so a preprocessor can
  edit it in the UI. Every judged match records the version that judged it.
* Verdicts are SAME / DIFFERENT / UNCERTAIN. Discovery has no UOM, QOE, or
  price, so the packaging rules of the contract-load prompt do not apply.
* Pairs are judged concurrently over a thread pool, with one shared client.

Framework-agnostic: worker threads never touch ``current_app``. The caller
snapshots config into plain values and passes them in.
"""

from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from ..common.utils import ny_now
from ..db import discovery_repo

logger = logging.getLogger(__name__)

VERDICTS = ("SAME", "DIFFERENT", "UNCERTAIN")

# Unit separator for the dedupe hash: a delimiter that cannot occur in
# cleansed text, so ("AB", "C") and ("A", "BC") can never collide.
_HASH_SEP = chr(31)

# Variables a prompt author may reference in user_template. Surfaced in the
# editor UI so the available context is discoverable.
TEMPLATE_VARIABLES = (
    "input_sku",
    "input_description",
    "input_supplier",
    "matched_sku",
    "matched_description",
    "matched_vendor_name",
    "matched_manufacturer_name",
    "sku_exact",
    "matched_on",
    "desc_similarity",
)

# Sandboxed so a prompt edit can't reach into Python internals. Prompts are
# preprocessor-gated, but the template is still user input rendered server-side.
_JINJA = SandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, autoescape=False)


class PromptRenderError(ValueError):
    """A prompt template failed to render; the run stops rather than sending junk."""


def render_user_prompt(user_template: str, pair: dict) -> str:
    """Render one comparison pair through the versioned user template."""
    context = {
        "input_sku": pair.get("input_sku") or "",
        "input_description": pair.get("input_description") or "",
        "input_supplier": pair.get("input_supplier") or "",
        "matched_sku": pair.get("matched_sku") or "",
        "matched_description": pair.get("matched_description") or "",
        "matched_vendor_name": pair.get("matched_vendor_name") or "",
        "matched_manufacturer_name": pair.get("matched_manufacturer_name") or "",
        "sku_exact": "Yes" if pair.get("sku_exact") else "No",
        "matched_on": (
            "reduced manufacturer part number"
            if pair.get("matched_on") == "REDUCED_MFG"
            else "reduced vendor part number"
        ),
        "desc_similarity": round(float(pair.get("desc_similarity") or 0.0), 3),
    }
    try:
        return _JINJA.from_string(user_template).render(**context)
    except TemplateError as exc:
        raise PromptRenderError(f"Prompt template failed to render: {exc}") from exc


def validate_template(system_prompt: str, user_template: str) -> None:
    """Reject a prompt edit that can't render, before it becomes the active version."""
    if not (system_prompt or "").strip():
        raise PromptRenderError("System prompt cannot be empty.")
    if not (user_template or "").strip():
        raise PromptRenderError("User template cannot be empty.")
    render_user_prompt(user_template, {
        "input_sku": "SAMPLE-1",
        "input_description": "SAMPLE ITEM DESCRIPTION",
        "input_supplier": "SAMPLE SUPPLIER",
        "matched_sku": "SAMPLE-1",
        "matched_description": "SAMPLE ITEM DESCRIPTION",
        "matched_vendor_name": "SAMPLE VENDOR",
        "matched_manufacturer_name": "SAMPLE MANUFACTURER",
        "sku_exact": True,
        "matched_on": "REDUCED_MFG",
        "desc_similarity": 0.9,
    })


def _payload_hash(pair: dict) -> str:
    """Identity of a comparison, ignoring which row asked for it.

    Duplicate SKUs across an uploaded file produce identical comparisons; hashing
    lets one API call answer all of them.
    """
    parts = [
        pair.get("input_description") or "",
        pair.get("input_supplier") or "",
        pair.get("matched_description") or "",
        pair.get("matched_vendor_name") or "",
        pair.get("matched_manufacturer_name") or "",
        pair.get("matched_sku") or "",
        pair.get("input_sku") or "",
        "1" if pair.get("sku_exact") else "0",
        pair.get("matched_on") or "",
    ]
    return hashlib.sha256(_HASH_SEP.join(parts).encode("utf-8")).hexdigest()


def _parse_response(content: str) -> dict:
    """Parse the model's JSON reply, coercing anything unexpected to UNCERTAIN."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {
            "verdict": "UNCERTAIN",
            "confidence": 0,
            "reason": "LLM response was not valid JSON.",
        }

    verdict = str(data.get("verdict", "") or "").strip().upper()
    if verdict not in VERDICTS:
        verdict = "UNCERTAIN"

    try:
        confidence = int(data.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))

    reason = str(data.get("reason", "") or "").strip()
    return {"verdict": verdict, "confidence": confidence, "reason": reason[:1000]}


def _judge_one(client, *, model, temperature, max_tokens, system_prompt, user_content) -> dict:
    """One API call. Errors come back as data so one bad pair can't kill a slice."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_completion_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        parsed = _parse_response(response.choices[0].message.content)
        parsed["error"] = None
        return parsed
    except Exception as exc:  # noqa: BLE001 — surfaced per row, not raised
        logger.error("Discovery LLM call failed: %s", exc)
        return {
            "verdict": None,
            "confidence": None,
            "reason": None,
            "error": f"{exc.__class__.__name__}: {exc}"[:500],
        }


def judge_pairs(
    pairs: list[dict],
    *,
    client,
    prompt: dict,
    model: str,
    temperature: float,
    max_tokens: int,
    max_workers: int = 8,
) -> list[dict]:
    """Judge many pairs concurrently; returns DiscoveryMatch update dicts.

    Identical comparisons are collapsed to one API call and the verdict is fanned
    back out, so a file with repeated SKUs doesn't pay twice.
    """
    if not pairs:
        return []

    system_prompt = prompt["system_prompt"]
    user_template = prompt["user_template"]
    prompt_version_id = prompt["prompt_version_id"]

    # Render first: a broken template should fail the whole run loudly rather
    # than burn tokens on the pairs that happen to render.
    rendered: dict[str, str] = {}
    pair_hashes: list[str] = []
    for pair in pairs:
        key = _payload_hash(pair)
        pair_hashes.append(key)
        if key not in rendered:
            rendered[key] = render_user_prompt(user_template, pair)

    unique_keys = list(rendered)
    verdicts: dict[str, dict] = {}

    if client is None:
        unavailable = {
            "verdict": None,
            "confidence": None,
            "reason": None,
            "error": "LLM unavailable — OPENAI_API_KEY is not configured.",
        }
        verdicts = {key: unavailable for key in unique_keys}
    else:
        workers = max(1, min(int(max_workers), len(unique_keys)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(
                lambda key: _judge_one(
                    client,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    user_content=rendered[key],
                ),
                unique_keys,
            ))
        verdicts = dict(zip(unique_keys, results))

    now = ny_now()
    updates = []
    for pair, key in zip(pairs, pair_hashes):
        result = verdicts[key]
        failed = result.get("error") is not None
        updates.append({
            "discovery_match_id": pair["discovery_match_id"],
            "llm_status": "ERROR" if failed else "DONE",
            "llm_verdict": result.get("verdict"),
            "llm_confidence": result.get("confidence"),
            "llm_reason": result.get("reason"),
            "llm_error": result.get("error"),
            "llm_prompt_version_id": prompt_version_id,
            "llm_reviewed_at": now,
        })

    if len(unique_keys) < len(pairs):
        logger.info(
            "Discovery LLM slice: %d pair(s) collapsed to %d unique comparison(s).",
            len(pairs), len(unique_keys),
        )
    return updates


def run_slice(
    set_id: int,
    *,
    client,
    prompt: dict,
    model: str,
    temperature: float,
    max_tokens: int,
    slice_size: int,
    max_workers: int,
) -> dict:
    """Claim, judge, and persist one slice of pending pairs.

    The browser calls this repeatedly until ``remaining`` reaches zero. Claiming
    is atomic, so an interrupted run just resumes on the next call and two open
    tabs can't judge the same row twice.
    """
    match_ids = discovery_repo.claim_llm_slice(set_id, slice_size)
    if not match_ids:
        remaining = discovery_repo.count_llm_remaining(set_id)
        if remaining == 0:
            discovery_repo.update_set(set_id, status="LLM_COMPLETE")
        return {"processed": 0, "remaining": remaining, "done": remaining == 0}

    pairs = discovery_repo.get_matches_for_llm(match_ids)
    try:
        updates = judge_pairs(
            pairs,
            client=client,
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_workers=max_workers,
        )
    except PromptRenderError:
        # Hand the claimed rows back so a fixed template can retry them.
        discovery_repo.save_llm_verdicts([
            {"discovery_match_id": mid, "llm_status": "PENDING"} for mid in match_ids
        ])
        raise

    discovery_repo.save_llm_verdicts(updates)
    discovery_repo.update_set(set_id, active_prompt_version_id=prompt["prompt_version_id"])

    remaining = discovery_repo.count_llm_remaining(set_id)
    discovery_repo.update_set(
        set_id, status="LLM_COMPLETE" if remaining == 0 else "LLM_RUNNING"
    )

    errors = sum(1 for u in updates if u["llm_status"] == "ERROR")
    return {
        "processed": len(updates),
        "errors": errors,
        "remaining": remaining,
        "done": remaining == 0,
    }


def get_active_prompt_dict(prompt_key: str = "ITEM_COMPARE") -> Optional[dict]:
    """Active prompt as a plain dict — safe to hand to worker threads."""
    row = discovery_repo.get_active_prompt(prompt_key)
    if row is None:
        return None
    return {
        "prompt_version_id": row.prompt_version_id,
        "prompt_key": row.prompt_key,
        "version_no": row.version_no,
        "system_prompt": row.system_prompt,
        "user_template": row.user_template,
        "model": row.model,
        "temperature": row.temperature,
    }


def resolve_model_settings(prompt: dict, config_settings: dict) -> dict:
    """A prompt version may pin its own model/temperature; otherwise use config."""
    return {
        "model": prompt.get("model") or config_settings.get("model"),
        "temperature": (
            prompt["temperature"]
            if prompt.get("temperature") is not None
            else config_settings.get("temperature", 0.0)
        ),
        "max_tokens": config_settings.get("max_tokens", 1024),
    }
