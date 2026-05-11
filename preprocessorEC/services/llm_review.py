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
- Pair type: A, B, C, or D (used by upstream scoring; you do NOT need to
  apply different rules per pair type — every pair is judged the same way)
- INPUT item: vendor, description, manufacturer number, vendor catalog number,
  UOM, QOE, contract price
- MATCH item: vendor, description, manufacturer number, vendor catalog number,
  UOM, QOE, contract price, source system

Goal: decide whether the INPUT and MATCH represent the SAME physical product
sold under the SAME effective packaging.

Output exactly one of three decisions:
- ACCEPT — the pair is (or is almost certainly) the same product in the same
  effective packaging.
- REJECT — the pair is a different product, OR the same product in a
  different packaging.
- PENDING — only when, after considering every field, you genuinely cannot
  decide between ACCEPT and REJECT. PENDING is for true judgement failures,
  not minor uncertainty. If the evidence leans either way, commit to that
  decision and put your hesitation in the `reason` field instead.

Signals to weigh together (no single field is decisive):
1. Catalog / part number similarity (after normalisation).
2. Description overlap — do both refer to the same physical item, size,
   formulation, packaging, and brand?
3. UOM and QOE compatibility, including known synonym packaging units
   across systems.
4. Contract price reasonableness given the stated UOM/QOE on each side.
5. Vendor identity (see below).

Vendor handling:
- The vendor field is the supplier on each side. It is intentionally NOT the
  manufacturer, because contracts often list the seller as the manufacturer
  (e.g. a Medline-sold contract may show every line as "manufactured by
  Medline"), which is misleading. Trust the vendor field; do not infer
  manufacturer competition from the description alone.
- If the two vendors are the same entity — same name, or one is a
  well-known parent / acquirer of the other, or there is well-known M&A
  history making them the same legal entity today — treat the vendor as
  matched. This is a strong positive signal.
- If one side is a manufacturer and the other is a distributor known to
  resell that manufacturer's product, and all other specs match, treat the
  vendor relationship as compatible (lean ACCEPT, not REJECT, on vendor
  grounds).
- If the descriptions, specs, and packaging look closely matched but the
  two vendors are well-known direct market competitors for this product
  category (each manufactures and sells their own branded equivalent),
  treat the pair as "market competitors" and REJECT — same-looking
  description does not mean same product when two competing brands each
  produce their own version.

Packaging and price-sanity (applies to ALL pair types):
- By default the two sides must represent the same effective packaging
  (same pack size and per-unit-of-sale). Different pack/count (e.g. EA 1
  vs CS 10, BX 20 vs EA 1) is a REJECT.
- Exception — likely data-entry error: contract documents are sometimes
  entered with wrong UOM, wrong QOE, or even wrong VPN. This is especially
  common in pair types C and D. When you are otherwise confident the
  underlying item is the same (description + manufacturer number +
  vendor align) AND the contract prices on the two sides are very close
  to each other, it is highly likely one side simply has a UOM/QOE/VPN
  data-entry error and the two are actually the same packaging. ACCEPT in
  that case so the row is surfaced in the export file for a human to do a
  second-pass review and correct the data.
  Example (ACCEPT): Medline ABC12345 / VPN ABC12345H / EA / 1 / $100 vs
                    Medline ABC12345 / VPN ABC12345  / CS / 10 / $105
                    → prices within a few %; CS/10 is almost certainly the
                    same pack as EA/1 with bad UOM/QOE entry.
- If UOM/QOE differ AND the contract prices are at obviously different
  scales (one is per-each, the other is per-case-of-N), the packaging
  really is different — REJECT.
  Example (REJECT): Medline ABC12345 / EA / 1 / $10 vs
                    Medline ABC12345 / CS / 10 / $105
                    → $10/each vs $105 for a case of 10 are different
                    packaging tiers, not a data error.
- If one side has a suspicious value (e.g. CS with QOE 1) but the prices
  still show clearly different pack scales, REJECT — the data is wrong but
  the two rows are still different packaging.
  Example (REJECT): Medline ABC12345 / EA / 1 / $10 vs
                    Medline ABC12345 / CS / 1 / $105
                    → CS/1 is suspect, but $10 vs $105 spread shows
                    different pack scales regardless.

General guardrails:
- Do not ACCEPT a match only because the descriptions are broadly similar.
- Use all fields together. If UOM looks interchangeable but the contract
  price is materially inconsistent for the stated pack and quantity,
  prefer REJECT.
  For example, if both sides have the same vendor and manufacturer number
  and both have QOE 6, but one side is priced ~6× the other, that
  usually means they are not the same contract line — REJECT.
- Reserve PENDING for genuine deadlocks. Most pairs should resolve to
  ACCEPT or REJECT.

Respond with a JSON object:
{"decision": "ACCEPT" | "REJECT" | "PENDING", "confidence": 0-100, "reason": "<one sentence>"}
"""

_USER_TEMPLATE = """\
Pair Type: {pair_type}

INPUT item:
  Vendor: {input_vendor}
  Description: {input_desc}
  Mfg Catalog #: {input_mfg}
  Vendor Catalog #: {input_vpn}
  UOM: {input_uom}
  QOE: {input_qoe}
  Contract Price: {input_price}

MATCH item (source: {match_source}):
  Vendor: {match_vendor}
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


# ── Public API ──────────────────────────────────────────────────────────
def review_match_pair(
    input_item: dict,
    match_item: dict,
) -> dict:
    """Ask the LLM to review a single input↔match pair.

    Returns ``{"decision": "ACCEPT"|"REJECT"|"PENDING", "confidence": int, "reason": str}``.
    Falls back to PENDING if the API is unavailable or errors so a human
    reviewer can still make the call.
    """
    client = _get_client()
    if client is None:
        return {"decision": "PENDING", "confidence": 0, "reason": "LLM unavailable"}

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
