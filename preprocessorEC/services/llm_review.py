"""LLM-based review for MED/LOW similarity matches.

Sends match pairs to an OpenAI-compatible API to get a classification
of whether they represent the same item. Used for both CCX and Infor
residue matches that fall below the HIGH threshold.

The prompt text lives in the ``llm_review_prompts`` folder, one markdown file per
version, each stating the scenarios it suits. This module renders whichever
version is marked active.
"""

from __future__ import annotations

import json
import logging

from flask import current_app

from .llm_client import (
    build_client,
    chat_completion_model_kwargs,
    client_settings_from_config,
)
from .llm_review_prompts import PREPROCESS_REVIEW, active as _active_prompt

logger = logging.getLogger(__name__)


#: Active prompt version; see ``llm_review_prompts/README.md`` to add or roll back.
PROMPT = _active_prompt(PREPROCESS_REVIEW)

_SYSTEM_PROMPT = PROMPT.system_prompt
_USER_TEMPLATE = PROMPT.user_template


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
                pair_type=match_item.get("pair_type", ""),
                input_vendor=input_item.get("vendor", "") or "(not provided)",
                input_desc=input_item.get("description", ""),
                input_mfg=input_item.get("mfg_catalog_num", ""),
                input_vpn=input_item.get("vendor_catalog_num", ""),
                input_uom=input_item.get("uom", ""),
                input_qoe=input_item.get("qoe", ""),
                input_price=input_item.get("contract_price", ""),
                match_source=match_item.get("matched_source", ""),
                match_vendor=match_item.get("vendor", "") or "(not provided)",
                match_desc=match_item.get("description", ""),
                match_mfg=match_item.get("mfg_catalog_num", ""),
                match_vpn=match_item.get("vendor_catalog_num", ""),
                match_uom=match_item.get("uom", ""),
                match_qoe=match_item.get("qoe", ""),
                match_price=match_item.get("contract_price", ""),
            ),
        },
    ]


def _get_client():
    """Lazy-load the OpenAI-compatible client using app config."""
    return build_client(client_settings_from_config(current_app.config))


def _parse_response(content: str) -> dict:
    """Parse the LLM JSON response; return a safe default on failure."""
    try:
        data = json.loads(content)
        decision = data.get("decision", "PENDING").upper()
        if decision not in ("ACCEPT", "REJECT", "PENDING"):
            decision = "PENDING"
        return {
            "decision": decision,
            "confidence": data.get("confidence", 0),
            "reason": data.get("reason", ""),
        }
    except (json.JSONDecodeError, AttributeError):
        return {"decision": "PENDING", "confidence": 0, "reason": "LLM response parse error"}


def review_match_pair(
    input_item: dict,
    match_item: dict,
) -> dict:
    """Ask the LLM to review a single input-match pair.

    Returns ``{"decision": "ACCEPT"|"REJECT"|"PENDING", "confidence": int, "reason": str}``.
    Falls back to PENDING if the API is unavailable or errors so a human
    reviewer can still make the call.
    """
    client = _get_client()
    if client is None:
        return {"decision": "PENDING", "confidence": 0, "reason": "LLM unavailable"}

    model = current_app.config.get("OPENAI_MODEL", "gpt-5.6-luna")
    max_tokens = current_app.config.get("LLM_MAX_TOKENS", 1024)
    temperature = current_app.config.get("LLM_TEMPERATURE", 0.0)

    messages = _build_messages(input_item, match_item)

    try:
        from openai import APIConnectionError, APITimeoutError

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
            **chat_completion_model_kwargs(model, temperature=temperature),
        )
        content = response.choices[0].message.content
        return _parse_response(content)
    except APIConnectionError as exc:
        logger.error("LLM review connection failed for model %s: %s", model, exc)
        return {
            "decision": "PENDING",
            "confidence": 0,
            "reason": "LLM connection error. Check OPENAI_BASE_URL/AZURE_OPENAI_ENDPOINT and SSL settings.",
        }
    except APITimeoutError as exc:
        logger.error("LLM review timed out for model %s: %s", model, exc)
        return {
            "decision": "PENDING",
            "confidence": 0,
            "reason": "LLM request timed out.",
        }
    except Exception as exc:
        logger.error("LLM review failed: %s", exc)
        return {"decision": "PENDING", "confidence": 0, "reason": f"LLM error: {exc}"}


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
