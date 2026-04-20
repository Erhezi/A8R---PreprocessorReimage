"""LLM-based review for MED/LOW similarity matches.

Sends match pairs to an OpenAI-compatible API to get a classification
of whether they represent the same item. Used for both CCX and Infor
residue matches that fall below the HIGH threshold.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from flask import current_app

logger = logging.getLogger(__name__)

# ── Prompt template ─────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are an expert supply-chain analyst reviewing potential duplicate items
between a hospital's input item list and existing contract lines.

For each pair you will receive:
- INPUT item: description, manufacturer number, vendor catalog number, UOM
- MATCH item: description, catalog numbers, UOM, source system

Decide whether the INPUT and MATCH represent the SAME physical product.
Consider:
1. Catalog / part number similarity (after normalisation)
2. Description overlap (brand, size, material, quantity)
3. UOM compatibility (e.g. BX vs CS with different QOE)

Respond with a JSON object:
{"decision": "ACCEPT" | "REJECT", "confidence": 0-100, "reason": "<one sentence>"}
"""

_USER_TEMPLATE = """\
INPUT item:
  Description: {input_desc}
  Mfg Catalog #: {input_mfg}
  Vendor Catalog #: {input_vpn}
  UOM: {input_uom}

MATCH item (source: {match_source}):
  Description: {match_desc}
  Catalog Reference: {match_ref}
  UOM: {match_uom}
  Similarity Score: {sim_score}

Is this the same product?"""


def _build_messages(
    input_item: dict,
    match_item: dict,
) -> list[dict]:
    """Build chat messages for one comparison pair."""
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _USER_TEMPLATE.format(
                input_desc=input_item.get("description", ""),
                input_mfg=input_item.get("mfg_catalog_num", ""),
                input_vpn=input_item.get("vendor_catalog_num", ""),
                input_uom=input_item.get("uom", ""),
                match_source=match_item.get("matched_source", ""),
                match_desc=match_item.get("description", ""),
                match_ref=match_item.get("matched_item_ref", ""),
                match_uom=match_item.get("uom", ""),
                sim_score=match_item.get("similarity_score", ""),
            ),
        },
    ]


def _get_client():
    """Lazy-load the OpenAI client using app config."""
    api_key = current_app.config.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except ImportError:
        logger.warning("openai package not installed; LLM review unavailable.")
        return None


def _parse_response(content: str) -> dict:
    """Parse the LLM JSON response; return a safe default on failure."""
    try:
        data = json.loads(content)
        decision = data.get("decision", "REJECT").upper()
        if decision not in ("ACCEPT", "REJECT"):
            decision = "REJECT"
        return {
            "decision": decision,
            "confidence": data.get("confidence", 0),
            "reason": data.get("reason", ""),
        }
    except (json.JSONDecodeError, AttributeError):
        return {"decision": "REJECT", "confidence": 0, "reason": "LLM response parse error"}


# ── Public API ──────────────────────────────────────────────────────────
def review_match_pair(
    input_item: dict,
    match_item: dict,
) -> dict:
    """Ask the LLM to review a single input↔match pair.

    Returns ``{"decision": "ACCEPT"|"REJECT", "confidence": int, "reason": str}``.
    Falls back to REJECT if the API is unavailable or errors.
    """
    client = _get_client()
    if client is None:
        return {"decision": "REJECT", "confidence": 0, "reason": "LLM unavailable"}

    model = current_app.config.get("OPENAI_MODEL", "gpt-4.1-mini")
    max_tokens = current_app.config.get("LLM_MAX_TOKENS", 1024)
    temperature = current_app.config.get("LLM_TEMPERATURE", 0.0)

    messages = _build_messages(input_item, match_item)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return _parse_response(content)
    except Exception as exc:
        logger.error("LLM review failed: %s", exc)
        return {"decision": "REJECT", "confidence": 0, "reason": f"LLM error: {exc}"}


def review_match_batch(
    pairs: list[tuple[dict, dict]],
) -> list[dict]:
    """Review multiple (input_item, match_item) pairs sequentially.

    Returns a list of decision dicts in the same order as *pairs*.
    """
    results = []
    for input_item, match_item in pairs:
        results.append(review_match_pair(input_item, match_item))
    return results
