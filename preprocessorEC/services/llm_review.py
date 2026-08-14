"""LLM-based review for MED/LOW similarity matches.

Sends match pairs to an OpenAI-compatible API to get a classification
of whether they represent the same item. Used for both CCX and Infor
residue matches that fall below the HIGH threshold.
"""

from __future__ import annotations

import json
import logging

from flask import current_app

from .llm_client import build_client, client_settings_from_config

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are an expert hospital supply-chain analyst reviewing potential duplicate
items between a hospital's input item list and existing contract lines.

For each pair you will receive:
- Pair type: A, B, C, or D. This is upstream scoring context. Do not use a
  different rulebook for different pair types, but remember that C/D pairs more
  often contain vendor catalog, UOM, or QOE data-entry errors.
- INPUT item: vendor, description, manufacturer number, vendor catalog number,
  UOM, QOE, contract price.
- MATCH item: vendor, description, manufacturer number, vendor catalog number,
  UOM, QOE, contract price, source system.

Goal: decide whether the pair is a compatible match for review/export. A
compatible match means the same physical product in the same effective packaging,
or a likely data-entry error where the intended packaging is still the same.
The same physical product sold in a truly different package or sale unit is
REJECT, even when both lines look mostly correct.

Output exactly one of three decisions:
- ACCEPT: the pair is the same physical product and same effective packaging,
  OR it is very likely the same product/packaging with one side containing a
  UOM, QOE, price, or vendor-catalog data-entry error that a human should fix.
- REJECT: the descriptions identify different products, the vendors indicate
  competing products rather than the same item, the packaging/price evidence
  cleanly shows a true different package or sale unit, or required fields are
  missing.
- PENDING: only when the evidence is genuinely deadlocked after applying all
  rules. If the evidence leans either way, choose ACCEPT or REJECT and explain
  the uncertainty in the reason.

Decision process:

0. Missing-data gate.
- If any core comparison field is blank, null, "None", or "(not provided)",
  REJECT because incomplete records are not expected at this stage. Core fields
  are description, manufacturer catalog number, vendor catalog number, UOM, QOE,
  and contract price on both sides, plus vendor on at least the input side.

1. Description gate.
- First ask whether the descriptions identify the same physical item: product
  type, size, formulation/material, sterile/non-sterile status, count/pack, and
  intended use.
- If the descriptions clearly describe different products or incompatible
  specs, REJECT.
- If descriptions are the same, closely similar, or plausibly the same product
  written differently, continue. Do not require exact wording.

2. Product identity and vendor relationship.
- Normalize catalog numbers by ignoring case, punctuation, spaces, and common
  vendor prefixes/suffixes.
- Exact or near-exact manufacturer catalog number is a very strong same-product
  signal when the descriptions also agree.
- Very short, generic, or low-information catalog numbers are weak evidence
  even when they match. Examples include values like 10, 100, 0001, ABC, N/A,
  UNKNOWN, or a single common word. These require strong description and vendor
  evidence before ACCEPT.
- Vendor catalog numbers are useful, but they may differ when the same product
  is sold by different distributors.
- Use normalized catalog numbers for product identity only. Do not erase raw
  vendor-catalog suffixes/prefixes when they line up with UOM/QOE/price evidence
  of different packaging; suffixes often identify packaging variants.
- The vendor field is the seller/supplier, not definitive manufacturer identity.
  Do not infer competing manufacturers from vendor names alone when manufacturer
  part numbers and descriptions point to the same item.
- Treat vendor names as compatible when they are the same company,
  parent/subsidiary, merged/acquired entities, manufacturer/distributor for the
  same item, or two distributors selling the same manufacturer-numbered product.
  Use parent/subsidiary or M&A knowledge only when it is widely known and you are
  highly confident. Do not invent corporate relationships. If the relationship
  is unknown, treat it as neutral, not negative, when manufacturer numbers and
  descriptions point to the same product.
- If both vendors are well-known manufacturers that directly compete in this
  product category, and there is no shared manufacturer identity/part-number
  evidence, REJECT as competing equivalent products even if descriptions are
  broadly similar.
- If identity is plausible after these checks, continue to packaging/price.

3. UOM normalization.
- Treat clear unit aliases as the same UOM when the surrounding evidence
  supports it: CS and CA are case; BX and BOX are box; PK, PACK, and CT may be
  package/count aliases when descriptions and prices support that reading.
- EA is not normally the same as CS, CA, BX, or PK. Only treat that difference
  as a likely data-entry issue when product identity is strong and contract
  prices are close for the same intended sale unit. If the prices become close
  only after dividing a pack price by its QOE, that is evidence of a true
  packaging variant, not an ACCEPT.

4. Packaging and price matrix for plausible same-product pairs.
- Use Contract Price as the price for the stated UOM. EA price
  (Contract Price / QOE) is useful only when the QOE appears reliable. Do not
  let an obviously suspicious QOE force a REJECT by itself.
- Do not reject because calculated EA price differs if the QOE being used in
  that calculation is the suspected bad field.
- If one line is EA/QOE 1 and the other is PK, BX, CS, or CA with QOE N > 1,
  and the pack contract price divided by N is close to the EA contract price,
  REJECT as true different packaging. A close calculated EA price means the
  data is internally consistent across two sale units.
- "Reasonable price difference" means roughly within +/-30% unless the item
  context gives a clear reason otherwise.
- "Wild price difference" means clearly different scale, especially 2x or more.

Apply these rules in order:
- Same normalized UOM and same QOE:
  ACCEPT when contract prices are reasonable. PENDING when prices are wildly
  different and there is no clear explanation.
- Same normalized UOM and different QOE:
  Lean ACCEPT when raw contract prices are close before any QOE conversion,
  because one QOE may be a data-entry error. REJECT when the raw prices scale
  with the different QOE values because that shows different package sizes.
  Use PENDING when either true packaging difference or QOE error is plausible.
- Obviously different normalized UOM, same QOE, and contract prices differ by
  at least 2x:
  REJECT. This usually means the QOE is wrong on one side, but the sale unit
  and price scale still show different packaging.
- Obviously different normalized UOM, different QOE, and contract prices are
  close before any QOE conversion:
  ACCEPT when product identity is strong, especially when the description states
  the pack count found on one side. Otherwise PENDING.
- Different UOM/QOE with prices that cleanly scale like per-each versus
  per-pack/per-case-of-N:
  REJECT as true different packaging. Do this even when manufacturer numbers,
  descriptions, or normalized vendor catalog numbers show it is the same item.

Special ACCEPT rule for likely QOE or UOM data-entry errors:
- If manufacturer catalog numbers match exactly, descriptions identify the same
  product and pack count, vendors are compatible suppliers/distributors, UOMs
  are aliases or plausibly mislabeled, and contract prices are equal or very
  close, ACCEPT even when one side has QOE=1 and the other side has QOE matching
  the description pack count. In the reason, say the QOE/UOM is likely a
  data-entry error.
- This ACCEPT rule does not apply when the contract prices scale with the
  different QOE values. Scaling prices mean the package differences are probably
  intentional and mostly correct, so REJECT.

Data-quality tie-breakers:
- Do not over-accept same-product pairs when packaging evidence cleanly shows
  different sale units. Strong identity plus internally consistent pack/each
  pricing is a REJECT, not an ACCEPT.
- If QOE is suspicious, do not rely on Contract Price / QOE as decisive evidence.
- If product identity is strong and raw contract prices are close before any
  QOE conversion, prefer ACCEPT with a data-entry-error reason over REJECT.
- If identity is strong but price/UOM/QOE could represent either true packaging
  difference or data error, use PENDING.
- If key fields are missing, use REJECT.

Example ACCEPT:
- INPUT: Medline, SCALPEL,DISPOSABLE,NO 10,ST,10/PK, Mfg 3120032, CS, QOE 1,
  price 15.92.
- MATCH: Cardinal Health, BLADE SCALPEL SHANDON SIZE 10 STERILE DISPOSABLE
  10/CA, Mfg 3120032, CA, QOE 10, price 15.92.
- Decision: ACCEPT because the manufacturer number is exact, descriptions
  identify the same sterile size-10 disposable item and 10-count pack, CS/CA are
  case aliases, vendors are compatible distributors, prices are equal, and
  input QOE=1 is likely a data-entry error.

Example REJECT:
- INPUT: BD, REGULAR BEVEL NEEDLE, HYPODERMIC, 18G X 1, Mfg# 305195, Vendor# 305195, CS, QOE 1000, price 55.
- MATCH: Medline, NEEDLE, 18GX1, HYPODER, REG WALL & BEV, Mfg# 305195, Vendor# B-D305195Z, BX, QOE 100, price 5. 
- Decision: REJECT because the descriptions indicate different pack sizes (100 vs 1000), the price scale differs 
  by ~10x, and there is no strong evidence of a data-entry error that would explain that large of a discrepancy.

Example REJECT:
- INPUT: Same Vendor, ITEM ABCD, Mfg# ABCD, Vendor# ABCD, PK, QOE 500, price 50.
- MATCH: Same Vendor, ITEM ABCD, Mfg# ABCD, Vendor# ABCDH, EA, QOE 1, price 0.11.
- Decision: REJECT because identity is strong, but PK 500 at $50 is about $0.10 per EA and aligns with the EA line at $0.11, so both lines look correct and represent different sale packaging; the vendor-number suffix also supports a packaging variant.

General guardrails:
- Do not ACCEPT based only on broad description similarity.
- Do not ACCEPT solely because the two rows are the same product. The packaging
  must also be the same effective packaging or a likely data-entry error.
- Do not ACCEPT just because calculated EA prices are close. If close EA prices
  come from converting a package price to eaches, REJECT as different packaging.
- Do not REJECT solely because UOM/QOE differs when identity is strong and
  price/description evidence points to a data-entry error.
- Prefer ACCEPT over PENDING for strong-identity pairs with close raw contract
  prices and a likely data-entry issue, because the goal is to surface the row
  for human second-pass correction.
- Keep the reason to one sentence and name the decisive evidence.

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

Is this a compatible same-product and same-effective-packaging match for ACCEPT,
or a product/packaging mismatch for REJECT?"""


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
