"""LLM-based review for MED/LOW similarity matches.

Sends match pairs to an OpenAI-compatible API to get a classification
of whether they represent the same item. Used for both CCX and Infor
residue matches that fall below the HIGH threshold.
"""

from __future__ import annotations

import json
import logging

from flask import current_app

logger = logging.getLogger(__name__)

# ── Prompt template ─────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are an expert supply-chain analyst reviewing potential duplicate items
between a hospital's input item list and existing contract lines.

For each pair you will receive:
- Pair type: A, B, C, or D
- INPUT item: description, manufacturer number, vendor catalog number, UOM, QOE, contract price
- MATCH item: description, manufacturer number, vendor catalog number, UOM, QOE, contract price, source system

Decide whether the INPUT and MATCH represent the SAME physical product.
Consider:
1. Catalog / part number similarity (after normalisation)
2. Description overlap and whether both descriptions refer to the same physical item, size, formulation, packaging, and brand
3. UOM and QOE compatibility, including known synonym packaging units across systems
4. Contract price reasonableness relative to UOM and QOE; a large price gap can indicate that one side has the wrong item, wrong pack, or wrong record even if catalog numbers look similar

Special rule for pair types A and C:
- For pair type A and pair type C, the INPUT and MATCH must represent the same packaging, not just the same base product.
- If they are the same product but sold in different packaging, pack size, UOM, or quantity-per-pack, you must REJECT.
- Treat differences like BX 20 vs EA 1, CA vs BX, or other pack/count differences as different packaging unless the evidence clearly shows they are the exact same sellable pack.

Special rule for pair type D:
- For pair type D, ACCEPT when the INPUT and MATCH represent the same underlying physical product even if their UOM or pack size differs (e.g., EA vs BX, CA vs BX, different QOE).
- The goal of pair type D is to surface the same item being purchased under different packaging configurations across systems, so UOM/QOE differences alone are NOT a reason to reject.
- Still REJECT if catalog numbers, manufacturer, brand, formulation, size, or other product-identity attributes indicate they are different items, or if the contract price is wildly inconsistent in a way that cannot be explained by the UOM/QOE difference.

Do not accept a match only because the descriptions are broadly similar.
Use all fields together. If UOM looks interchangeable but the contract price is materially inconsistent for the stated pack and quantity, prefer REJECT.
For example, if both sides have the same vendor and manufacturer number and both have QOE 6, but one side is priced around 6 times higher than the other, that usually indicates they are not the same contract line and should be REJECTED.

Respond with a JSON object:
{"decision": "ACCEPT" | "REJECT", "confidence": 0-100, "reason": "<one sentence>"}
"""

_USER_TEMPLATE = """\
Pair Type: {pair_type}

INPUT item:
  Description: {input_desc}
  Mfg Catalog #: {input_mfg}
  Vendor Catalog #: {input_vpn}
  UOM: {input_uom}
  QOE: {input_qoe}
  Contract Price: {input_price}

MATCH item (source: {match_source}):
  Description: {match_desc}
  Mfg Catalog #: {match_mfg}
  Vendor Catalog #: {match_vpn}
  UOM: {match_uom}
  QOE: {match_qoe}
  Contract Price: {match_price}
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
                pair_type=match_item.get("pair_type", ""),
                input_desc=input_item.get("description", ""),
                input_mfg=input_item.get("mfg_catalog_num", ""),
                input_vpn=input_item.get("vendor_catalog_num", ""),
                input_uom=input_item.get("uom", ""),
                input_qoe=input_item.get("qoe", ""),
                input_price=input_item.get("contract_price", ""),
                match_source=match_item.get("matched_source", ""),
                match_desc=match_item.get("description", ""),
                match_mfg=match_item.get("mfg_catalog_num", ""),
                match_vpn=match_item.get("vendor_catalog_num", ""),
                match_uom=match_item.get("uom", ""),
                match_qoe=match_item.get("qoe", ""),
                match_price=match_item.get("contract_price", ""),
                sim_score=match_item.get("similarity_score", ""),
            ),
        },
    ]


def _get_client():
    """Lazy-load the OpenAI-compatible client using app config."""
    api_key = current_app.config.get("OPENAI_API_KEY", "")
    if not api_key:
        return None

    timeout = current_app.config.get("OPENAI_TIMEOUT_SECONDS", 30.0)
    max_retries = current_app.config.get("OPENAI_MAX_RETRIES", 2)
    disable_ssl_verify = bool(current_app.config.get("OPENAI_DISABLE_SSL_VERIFY", False))
    base_url = current_app.config.get("OPENAI_BASE_URL", "")
    organization = current_app.config.get("OPENAI_ORGANIZATION", "")
    project = current_app.config.get("OPENAI_PROJECT", "")
    azure_endpoint = current_app.config.get("AZURE_OPENAI_ENDPOINT", "")
    azure_api_version = current_app.config.get("AZURE_OPENAI_API_VERSION", "")

    try:
        import httpx
        from openai import AzureOpenAI, OpenAI

        http_client = httpx.Client(
            timeout=timeout,
            verify=_build_ssl_verify(disable_ssl_verify),
        )

        if azure_endpoint:
            if not azure_api_version:
                logger.error("AZURE_OPENAI_ENDPOINT is set but AZURE_OPENAI_API_VERSION is missing.")
                return None

            return AzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=azure_api_version,
                timeout=timeout,
                max_retries=max_retries,
                http_client=http_client,
            )

        client_kwargs = {
            "api_key": api_key,
            "timeout": timeout,
            "max_retries": max_retries,
            "http_client": http_client,
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        if organization:
            client_kwargs["organization"] = organization
        if project:
            client_kwargs["project"] = project

        return OpenAI(**client_kwargs)
    except ImportError:
        logger.warning("openai package not installed; LLM review unavailable.")
        return None


def _build_ssl_verify(disable_ssl_verify: bool):
    if disable_ssl_verify:
        return False

    ca_bundle = current_app.config.get("OPENAI_CA_BUNDLE", "").strip()
    if ca_bundle:
        return ca_bundle

    use_system_ca_store = bool(current_app.config.get("OPENAI_USE_SYSTEM_CA_STORE", False))
    if not use_system_ca_store:
        return True

    try:
        import importlib
        import ssl

        truststore = importlib.import_module("truststore")
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        logger.warning("truststore not installed; falling back to certifi CA bundle.")
        return True


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


def _normalize_text(value) -> str:
    return str(value or "").strip().upper()


def _normalize_qoe(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def _requires_same_packaging(pair_type: str) -> bool:
    return _normalize_text(pair_type) in {"A", "C"}


def _same_packaging(input_item: dict, match_item: dict) -> bool:
    input_uom = _normalize_text(input_item.get("uom"))
    match_uom = _normalize_text(match_item.get("uom"))
    input_qoe = _normalize_qoe(input_item.get("qoe"))
    match_qoe = _normalize_qoe(match_item.get("qoe"))

    return bool(input_uom and match_uom and input_qoe and match_qoe and input_uom == match_uom and input_qoe == match_qoe)


# ── Public API ──────────────────────────────────────────────────────────
def review_match_pair(
    input_item: dict,
    match_item: dict,
) -> dict:
    """Ask the LLM to review a single input↔match pair.

    Returns ``{"decision": "ACCEPT"|"REJECT", "confidence": int, "reason": str}``.
    Falls back to REJECT if the API is unavailable or errors.
    """
    if _requires_same_packaging(match_item.get("pair_type", "")) and not _same_packaging(input_item, match_item):
        return {
            "decision": "REJECT",
            "confidence": 100,
            "reason": "Pair type A/C requires the same packaging; UOM or QOE indicates a different pack.",
        }

    client = _get_client()
    if client is None:
        return {"decision": "REJECT", "confidence": 0, "reason": "LLM unavailable"}

    model = current_app.config.get("OPENAI_MODEL", "gpt-4.1-mini")
    max_tokens = current_app.config.get("LLM_MAX_TOKENS", 1024)
    temperature = current_app.config.get("LLM_TEMPERATURE", 0.0)

    messages = _build_messages(input_item, match_item)

    try:
        from openai import APIConnectionError, APITimeoutError

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return _parse_response(content)
    except APIConnectionError as exc:
        logger.error("LLM review connection failed for model %s: %s", model, exc)
        return {
            "decision": "REJECT",
            "confidence": 0,
            "reason": "LLM connection error. Check OPENAI_BASE_URL/AZURE_OPENAI_ENDPOINT and SSL settings.",
        }
    except APITimeoutError as exc:
        logger.error("LLM review timed out for model %s: %s", model, exc)
        return {
            "decision": "REJECT",
            "confidence": 0,
            "reason": "LLM request timed out.",
        }
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
