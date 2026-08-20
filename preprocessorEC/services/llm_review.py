"""LLM-based review for MED/LOW similarity matches.

Sends match pairs to an OpenAI-compatible API to get a classification
of whether they represent the same item. Used for both CCX and Infor
residue matches that fall below the HIGH threshold.

The prompt text lives in the ``llm_review_prompts`` folder, one markdown file per
version, each stating the scenarios it suits. Which version runs, and in which
input mode, are per-task choices made in the UI before preprocessing.

Two input modes, selectable against any prompt:

* ``GROUP`` judges one input row against all of its matches in a single call. The
  input row is described to the model once instead of once per candidate, which
  keeps the reading of it stable across that row's matches and cuts the call
  count on rows with several. The reply carries one entry per candidate.
* ``PAIR`` judges one (input row, matched row) comparison per call, and the reply
  is a single verdict.

The mode reaches the prompt text as a Jinja variable, because the framing at the
top and the reply shape at the bottom genuinely differ; the judging rules between
them are written once. See ``llm_review_prompts/README.md``.
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
from . import llm_review_prompts
from .llm_review_prompts import PREPROCESS_REVIEW, ReviewPrompt, resolve_mode

logger = logging.getLogger(__name__)

DECISIONS = ("ACCEPT", "REJECT", "PENDING")


def resolve_prompt(selection: str | None = None) -> ReviewPrompt:
    """Resolve a user selection to a prompt; ``None`` yields the default."""
    return llm_review_prompts.resolve(selection, PREPROCESS_REVIEW)


def _pending(reason: str) -> dict:
    """Unresolved verdict — the row stays with a human."""
    return {"decision": "PENDING", "confidence": 0, "reason": reason}


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------
def _pair_context(input_item: dict, match_item: dict) -> dict:
    return {
        "pair_type": match_item.get("pair_type", ""),
        "input_vendor": input_item.get("vendor", "") or "(not provided)",
        "input_desc": input_item.get("description", ""),
        "input_mfg": input_item.get("mfg_catalog_num", ""),
        "input_vpn": input_item.get("vendor_catalog_num", ""),
        "input_uom": input_item.get("uom", ""),
        "input_qoe": input_item.get("qoe", ""),
        "input_price": input_item.get("contract_price", ""),
        "match_source": match_item.get("matched_source", ""),
        "match_vendor": match_item.get("vendor", "") or "(not provided)",
        "match_desc": match_item.get("description", ""),
        "match_mfg": match_item.get("mfg_catalog_num", ""),
        "match_vpn": match_item.get("vendor_catalog_num", ""),
        "match_uom": match_item.get("uom", ""),
        "match_qoe": match_item.get("qoe", ""),
        "match_price": match_item.get("contract_price", ""),
    }


def _build_messages(
    prompt: ReviewPrompt, mode: str, input_item: dict, match_items: list[dict],
) -> list[dict]:
    """Build chat messages for one call.

    Under PAIR *match_items* holds the single match being judged; under GROUP it
    holds every match for the input row. Either way the flat ``match_*``
    variables describe the first entry, and ``candidates`` carries them all
    numbered from 1 — that numbering is the contract between a GROUP prompt and
    ``_parse_group``.
    """
    context = _pair_context(input_item, match_items[0] if match_items else {})
    context["candidate_count"] = len(match_items)
    context["candidates"] = [
        dict(_pair_context(input_item, match_item), index=index)
        for index, match_item in enumerate(match_items, 1)
    ]
    return [
        {"role": "system", "content": prompt.render_system(mode)},
        {"role": "user", "content": prompt.render_user(mode, **context)},
    ]


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def _decision_of(data: dict) -> dict:
    """Coerce one reply entry into a verdict dict."""
    decision = str(data.get("decision", "PENDING")).strip().upper()
    if decision not in DECISIONS:
        decision = "PENDING"
    return {
        "decision": decision,
        "confidence": data.get("confidence", 0),
        "reason": data.get("reason", ""),
    }


def _parse_response(content: str) -> dict:
    """Parse a single-judgement JSON reply (PAIR mode)."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return _pending("LLM response parse error")
    if not isinstance(data, dict):
        return _pending("LLM response was not a JSON object")
    return _decision_of(data)


def _parse_group(content: str, count: int) -> list[dict]:
    """Split one grouped reply into *count* per-candidate verdicts.

    Entries are keyed by the candidate number the prompt asked for rather than by
    position: a model that drops or reorders one entry would otherwise shift every
    later verdict onto the wrong contract line, silently mislabelling rows. A
    candidate the model said nothing about comes back PENDING, not a guess.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return [_pending("LLM response parse error") for _ in range(count)]
    if not isinstance(data, dict):
        return [_pending("LLM response was not a JSON object") for _ in range(count)]

    by_index: dict[int, dict] = {}
    results = data.get("results")
    if isinstance(results, list):
        for position, entry in enumerate(results, 1):
            if not isinstance(entry, dict):
                continue
            try:
                # Fall back to position only when the key is absent entirely; a
                # present-but-unparseable key is a real misalignment.
                index = int(entry.get("candidate", position))
            except (TypeError, ValueError):
                continue
            by_index.setdefault(index, entry)

    return [
        _decision_of(by_index[index]) if index in by_index
        else _pending(f"LLM returned no result for candidate {index} of {count}")
        for index in range(1, count + 1)
    ]


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------
def _get_client():
    """Lazy-load the OpenAI-compatible client using app config."""
    return build_client(client_settings_from_config(current_app.config))


def _group_max_tokens(base: int, count: int) -> int:
    """A grouped reply carries one verdict per candidate, so the ceiling has to
    grow with the group or the JSON is truncated and the whole call is lost."""
    return max(int(base), min(8000, 260 * count + 300))


def _chat(messages: list[dict], max_tokens: int) -> tuple[str | None, str | None]:
    """Call the chat API. Returns ``(content, error)`` — exactly one is set."""
    client = _get_client()
    if client is None:
        return None, "LLM unavailable"

    model = current_app.config.get("OPENAI_MODEL", "gpt-5.6-luna")
    temperature = current_app.config.get("LLM_TEMPERATURE", 0.0)

    try:
        from openai import APIConnectionError, APITimeoutError

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
            **chat_completion_model_kwargs(model, temperature=temperature),
        )
        return response.choices[0].message.content, None
    except APIConnectionError as exc:
        logger.error("LLM review connection failed for model %s: %s", model, exc)
        return None, (
            "LLM connection error. Check OPENAI_BASE_URL/AZURE_OPENAI_ENDPOINT "
            "and SSL settings."
        )
    except APITimeoutError as exc:
        logger.error("LLM review timed out for model %s: %s", model, exc)
        return None, "LLM request timed out."
    except Exception as exc:  # noqa: BLE001 — any failure leaves the row for a human
        logger.error("LLM review failed: %s", exc)
        return None, f"LLM error: {exc}"


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def review_match_pair(
    input_item: dict,
    match_item: dict,
    prompt: ReviewPrompt | None = None,
) -> dict:
    """Ask the LLM to review a single input-match pair.

    Returns ``{"decision": "ACCEPT"|"REJECT"|"PENDING", "confidence": int, "reason": str}``.
    Falls back to PENDING if the API is unavailable or errors so a human
    reviewer can still make the call.
    """
    prompt = prompt or resolve_prompt()
    max_tokens = current_app.config.get("LLM_MAX_TOKENS", 1024)
    content, error = _chat(_build_messages(prompt, "PAIR", input_item, [match_item]), max_tokens)
    if error is not None:
        return _pending(error)
    return _parse_response(content)


def review_match_group(
    input_item: dict,
    match_items: list[dict],
    prompt: ReviewPrompt | None = None,
) -> list[dict]:
    """Review one input row against all of its matches in one call.

    Returns one verdict dict per entry of *match_items*, in the same order. A
    failed call yields PENDING for the whole group rather than dropping it, so no
    match silently loses its review.
    """
    if not match_items:
        return []
    prompt = prompt or resolve_prompt()
    base_tokens = current_app.config.get("LLM_MAX_TOKENS", 1024)
    content, error = _chat(
        _build_messages(prompt, "GROUP", input_item, match_items),
        _group_max_tokens(base_tokens, len(match_items)),
    )
    if error is not None:
        return [_pending(error) for _ in match_items]
    return _parse_group(content, len(match_items))


def review_matches(
    input_item: dict,
    match_items: list[dict],
    prompt: ReviewPrompt | None = None,
    mode: str | None = None,
) -> list[dict]:
    """Review one input row's matches in whichever input mode is selected.

    GROUP spends one call on the whole list; PAIR spends one per match. Returns
    one verdict per entry of *match_items* either way, so the caller does not
    branch on the mode.
    """
    if not match_items:
        return []
    prompt = prompt or resolve_prompt()
    mode = resolve_mode(mode)
    if mode == "GROUP":
        return review_match_group(input_item, match_items, prompt)
    return [review_match_pair(input_item, match_item, prompt) for match_item in match_items]


def review_match_batch(
    pairs: list[tuple[dict, dict]],
    prompt: ReviewPrompt | None = None,
) -> list[dict]:
    """Review multiple (input_item, match_item) pairs sequentially.

    Returns a list of decision dicts in the same order as *pairs*.
    """
    prompt = prompt or resolve_prompt()
    return [review_match_pair(input_item, match_item, prompt) for input_item, match_item in pairs]
