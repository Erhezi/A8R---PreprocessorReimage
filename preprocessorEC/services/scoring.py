"""Multi-factor confidence scoring for Phase 3 matching.

Ported from the original Contract Atlas scoring logic with enhancements:
  * 4 pair-type weight regimes (A / B / C / D)
  * MFN complexity-adjusted match scoring
  * EA-price match scoring
  * Description similarity via sentence-transformer + measurement extraction overlay
  * Vendor-item exact match (type C only)

Pair types (determined per match pair):
    A — same contract (input item found itself)
    B — different contract, same manufacturer, both MANUFACTURER type
    C — different contract, same vendor, both DISTRIBUTOR type
    D — all others (including Infor residue)

Weight regimes per pair type:
    Type A/B (skip description similarity):
        MFN 50%, EA Price 25%, UOM 10%, QOE 15%
    Type C (description computed):
        desc > 0.4: MFN 20%, Desc 30%, Price 10%, UOM 10%, QOE 10%, VendorItem 20%
        desc ≤ 0.4: MFN 10%, Desc 40%, Price 10%, UOM 10%, QOE 10%, VendorItem 20%
    Type D:
        desc > 0.4: MFN 40%, Desc 30%, Price 15%, UOM 10%, QOE 5%
        desc ≤ 0.4: MFN 20%, Desc 50%, Price 15%, UOM 10%, QOE 5%

Buckets:  HIGH ≥ 0.80,  MED ≥ 0.60,  LOW < 0.60
"""

from __future__ import annotations

import math
import re
from typing import Optional

from flask import current_app


# ── Thresholds ──────────────────────────────────────────────────────────
HIGH_THRESHOLD = 0.80
MED_THRESHOLD = 0.60


# ── Model access ────────────────────────────────────────────────────────
def _get_model():
    """Retrieve the sentence-transformer model from Flask app config."""
    return current_app.config.get("TRANSFORMER_MODEL")


# =====================================================================
# MFN (Manufacturer Part Number) scoring
# =====================================================================

def calculate_mfn_complexity(mfn: str) -> float:
    """Measure how unique / complex an MFN string is (0.0 – 1.0).

    Length 60%, character diversity 20%, char-type mix 20%.
    """
    if not mfn:
        return 0.0
    mfn = str(mfn).strip()
    if not mfn:
        return 0.0

    # Length factor — caps at 12 chars
    length_score = 0.0 if len(mfn) < 3 else min(len(mfn) / 12.0, 1.0)

    # Character diversity (unique chars / total length)
    diversity_ratio = len(set(mfn)) / max(len(mfn), 1)

    # Character type variety (digits, letters)
    has_digits = any(c.isdigit() for c in mfn)
    has_letters = any(c.isalpha() for c in mfn)
    char_type_score = (has_digits + has_letters) / 2.0

    return (length_score * 0.6) + (diversity_ratio * 0.2) + (char_type_score * 0.2)


def calculate_mfn_match_score(mfn_a: str, mfn_b: str) -> tuple[float, float]:
    """Score two MFNs against each other with complexity adjustment.

    Returns (match_score, complexity).  match_score can exceed 1.0 for
    exact matches of highly-complex strings — callers should clamp when
    combining into the weighted total.
    """
    mfn_a = str(mfn_a or "").strip().upper()
    mfn_b = str(mfn_b or "").strip().upper()

    complexity = (calculate_mfn_complexity(mfn_a) + calculate_mfn_complexity(mfn_b)) / 2

    if not mfn_a or not mfn_b:
        return 0.0, complexity

    # Exact match
    if mfn_a == mfn_b:
        if complexity > 0.85:
            return 3.0, complexity
        if complexity > 0.70:
            return 2.0, complexity
        if complexity < 0.30:
            return 0.5, complexity
        return 1.0, complexity

    # Alphanumeric reduction
    a_an = "".join(c for c in mfn_a if c.isalnum())
    b_an = "".join(c for c in mfn_b if c.isalnum())

    # Reduced match
    if a_an == b_an:
        if complexity > 0.85:
            return 2.5, complexity
        if complexity > 0.70:
            return 1.5, complexity
        if complexity < 0.30:
            return 0.5, complexity
        return 0.95, complexity

    # Containment (only for strings > 5 chars)
    if len(a_an) > 5 and len(b_an) > 5:
        if a_an in b_an or b_an in a_an:
            return 0.8 * (0.8 + 0.2 * complexity), complexity

    # Levenshtein distance via rapidfuzz (graceful fallback)
    try:
        from rapidfuzz.distance import Levenshtein
        max_len = max(len(a_an), len(b_an))
        if max_len == 0:
            return 0.0, complexity
        distance = Levenshtein.distance(a_an, b_an)
        similarity = 1 - (distance / max_len)
        base = max(0.0, min(0.5, similarity))
        if complexity < 0.3:
            return base * 0.6, complexity
        return base * (0.7 + 0.3 * complexity), complexity
    except ImportError:
        pass

    # Fallback: character overlap
    common = set(a_an) & set(b_an)
    if not common:
        return 0.0, complexity
    overlap = len(common) / max(len(set(a_an)), len(set(b_an)))
    base = max(0.0, min(0.5, overlap))
    if complexity < 0.3:
        return base * 0.5, complexity
    return base * (0.7 + 0.3 * complexity), complexity


# =====================================================================
# EA-Price scoring
# =====================================================================

def calculate_ea_price_match_score(
    price_a, price_b, qoe_a, qoe_b,
) -> tuple[float, float]:
    """Compare EA prices (Contract Price / QOE).

    Returns (price_score 0-1, price_diff_pct signed).
    """
    try:
        ea_a = float(price_a) / float(qoe_a)
        ea_b = float(price_b) / float(qoe_b)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0.0, 0.0

    if ea_a == 0 and ea_b == 0:
        return 1.0, 0.0
    if ea_a == 0 or ea_b == 0:
        return 0.0, 0.0

    diff = abs(ea_b - ea_a)
    direction = 1 if ea_b > ea_a else -1
    pct = diff / ea_a * 100
    signed_pct = pct * direction

    if pct < 10:
        return 1.0, signed_pct
    if pct < 20:
        return 0.95, signed_pct
    if pct < 45:
        return 0.75, signed_pct
    return 0.0, signed_pct


def _compute_ea_prices(price_a, qoe_a, price_b, qoe_b) -> tuple[Optional[float], Optional[float]]:
    """Compute EA prices for display purposes."""
    try:
        ea_a = float(price_a) / float(qoe_a)
        ea_b = float(price_b) / float(qoe_b)
        return ea_a, ea_b
    except (ValueError, TypeError, ZeroDivisionError):
        return None, None


# =====================================================================
# Description similarity (transformer + measurement overlay)
# =====================================================================

_UNIT_MAP = {
    "mm": "mm", "millimeter": "mm", "millimeters": "mm",
    "cm": "cm", "centimeter": "cm", "centimeters": "cm",
    "in": "in", "inch": "in", "inches": "in",
    "ft": "ft", "foot": "ft", "feet": "ft",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "l": "l", "liter": "l", "liters": "l",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gram": "g", "grams": "g",
}


def _extract_measurements(text: str) -> set[str]:
    """Extract and normalise numeric measurements from a description."""
    normalised: set[str] = set()

    # Value+unit pairs
    for m in re.finditer(r"(\d+\.?\d*)\s*([a-zA-Z]+)", text):
        val, unit = m.groups()
        val = str(float(val)).rstrip("0").rstrip(".") if "." in val else val
        normalised.add(f"{val}{_UNIT_MAP.get(unit.lower(), unit.lower())}")

    # Dimensions like 10x20x30
    for m in re.finditer(r"(\d+\.?\d*)\s*[xX]\s*(\d+\.?\d*)(?:\s*[xX]\s*(\d+\.?\d*))?", text):
        dims = [str(float(d)).rstrip("0").rstrip(".") if "." in d else d for d in m.groups() if d]
        normalised.add("x".join(dims))

    # Standalone numbers
    for m in re.finditer(r"\b(\d+\.?\d*)\b", text):
        val = m.group(1)
        val = str(float(val)).rstrip("0").rstrip(".") if "." in val else val
        normalised.add(val)

    return normalised


def _cosine(vec_a, vec_b) -> float:
    """Cosine similarity between two vectors (0-1 scale)."""
    dot = sum(float(a) * float(b) for a, b in zip(vec_a, vec_b))
    na = math.sqrt(sum(float(a) ** 2 for a in vec_a))
    nb = math.sqrt(sum(float(b) ** 2 for b in vec_b))
    if na == 0 or nb == 0:
        return 0.0
    return float(dot / (na * nb))


def _token_overlap(a: str, b: str) -> float:
    """Jaccard token overlap fallback (0-1)."""
    ta, tb = set(a.upper().split()), set(b.upper().split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def calculate_description_similarity(desc_a: str, desc_b: str, model=None) -> float:
    """Compute description similarity (0-1).

    Combines transformer-based semantic similarity (70%) and measurement
    overlap (30%) when numbers are present.  Falls back to token-overlap.
    """
    a_norm = str(desc_a or "").strip().lower()
    b_norm = str(desc_b or "").strip().lower()
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0

    if model is None:
        model = _get_model()

    if model is not None:
        a_nums = _extract_measurements(a_norm)
        b_nums = _extract_measurements(b_norm)

        if a_nums or b_nums:
            inter = len(a_nums & b_nums)
            union = len(a_nums | b_nums)
            num_sim = ((inter / union) + 1) if union > 0 else 1
        else:
            num_sim = 1  # neutral

        embeddings = model.encode([a_norm, b_norm])
        semantic = _cosine(embeddings[0], embeddings[1])

        if num_sim == 1:
            combined = semantic
        else:
            combined = semantic * 0.7 + num_sim * 0.3

        return float(min(max(combined, 0.0), 1.0))

    return _token_overlap(a_norm, b_norm)


def compute_similarities_batch(
    desc_input: str,
    match_descriptions: list[str],
    model=None,
) -> list[float]:
    """Score one input description against many match descriptions (batch).

    Returns list of similarity scores (0-1).
    """
    if not match_descriptions:
        return []

    input_norm = str(desc_input or "").strip().lower()
    exact_match_scores: list[Optional[float]] = []
    unresolved_indices: list[int] = []
    unresolved_descriptions: list[str] = []

    for index, description in enumerate(match_descriptions):
        description_norm = str(description or "").strip().lower()
        if input_norm and description_norm and input_norm == description_norm:
            exact_match_scores.append(1.0)
        else:
            exact_match_scores.append(None)
            unresolved_indices.append(index)
            unresolved_descriptions.append(description)

    if not unresolved_descriptions:
        return [score if score is not None else 0.0 for score in exact_match_scores]

    if model is None:
        model = _get_model()

    if model is not None:
        all_texts = [desc_input] + unresolved_descriptions
        embeddings = model.encode(all_texts)
        input_vec = embeddings[0]
        resolved_scores = [float(_cosine(input_vec, embeddings[i + 1])) for i in range(len(unresolved_descriptions))]
        for index, score in zip(unresolved_indices, resolved_scores):
            exact_match_scores[index] = score
        return [score if score is not None else 0.0 for score in exact_match_scores]

    for index, description in zip(unresolved_indices, unresolved_descriptions):
        exact_match_scores[index] = _token_overlap(desc_input or "", description or "")
    return [score if score is not None else 0.0 for score in exact_match_scores]


# =====================================================================
# Vendor-item exact match (Type C)
# =====================================================================

def calculate_vendor_item_match(vpn_a: str, vpn_b: str) -> float:
    """Exact vendor part number match: 1.0 if equal, else 0.0."""
    a = str(vpn_a or "").strip().upper()
    b = str(vpn_b or "").strip().upper()
    if not a or not b:
        return 0.0
    return 1.0 if a == b else 0.0


# =====================================================================
# Pair-type determination
# =====================================================================

def determine_pair_type(
    task_contract_number: str,
    task_process_type: str,
    task_contract_manufacturer: str,
    task_vendor_id: str,
    match_contract_id: str,
    match_contract_manufacturer: str,
    match_erp_vendor_id: str,
) -> str:
    """Determine the pair type (A/B/C/D) for a match pair.

    A — same contract (input item found itself in CCX)
    B — different contract, same manufacturer, both MANUFACTURER-type
    C — different contract, same vendor, both DISTRIBUTOR-type
    D — everything else (including all Infor residue matches)
    """
    task_cn = str(task_contract_number or "").strip().upper()
    match_cn = str(match_contract_id or "").strip().upper()

    if task_cn and match_cn and task_cn == match_cn:
        return "A"

    proc = str(task_process_type or "").upper()

    # Type B: both manufacturer, same manufacturer code
    if "MANUFACTURER" in proc:
        task_mfg = str(task_contract_manufacturer or "").strip().upper()
        match_mfg = str(match_contract_manufacturer or "").strip().upper()
        if task_mfg and match_mfg and task_mfg == match_mfg:
            return "B"

    # Type C: both distributor, same vendor
    if "DISTRIBUTOR" in proc:
        task_vid = str(task_vendor_id or "")[:7].strip().upper()
        match_vid = str(match_erp_vendor_id or "")[:7].strip().upper()
        if task_vid and match_vid and task_vid == match_vid:
            return "C"

    return "D"


# =====================================================================
# Multi-factor confidence scoring
# =====================================================================

def calculate_confidence_score(
    *,
    mfn_input: str,
    mfn_match: str,
    desc_input: str,
    desc_match: str,
    uom_input: str,
    uom_match: str,
    qoe_input,
    qoe_match,
    price_input,
    price_match,
    vpn_input: str = "",
    vpn_match: str = "",
    pair_type: str = "D",
    model=None,
    precheck_mode: str = "default",
    cn_input: str = "",
    cn_match: str = "",
) -> dict:
    """Calculate multi-factor weighted confidence score.

    Returns a dict with all sub-scores and the final weighted_score + bucket.
    """
    # --- Sub-factor computation ---
    mfn_score_raw, mfn_complexity = calculate_mfn_match_score(mfn_input, mfn_match)
    # Clamp mfn_score to [0, 1] for weighting
    mfn_score = float(min(max(mfn_score_raw, 0.0), 1.0))

    uom_score = 1.0 if str(uom_input or "").strip().upper() == str(uom_match or "").strip().upper() else 0.0
    qoe_score = 1.0 if str(qoe_input or "").strip() == str(qoe_match or "").strip() else 0.0

    price_score, price_diff_pct = calculate_ea_price_match_score(
        price_match, price_input, qoe_match, qoe_input,
    )

    match_ea, input_ea = _compute_ea_prices(price_match, qoe_match, price_input, qoe_input)

    # Description similarity — skip for types A and B
    if pair_type in ("A", "B"):
        desc_score = None  # not computed
    else:
        desc_score = calculate_description_similarity(desc_input, desc_match, model=model)

    # Vendor-item score — only for type C
    vi_score = None
    if pair_type == "C":
        vi_score = calculate_vendor_item_match(vpn_input, vpn_match)

    # --- Weighted combination ---
    if pair_type in ("A", "B"):
        # Skip description, no vendor-item
        weighted = (
            mfn_score * 0.50
            + price_score * 0.25
            + uom_score * 0.10
            + qoe_score * 0.15
        )
    elif pair_type == "C":
        vi = vi_score if vi_score is not None else 0.0
        ds = desc_score if desc_score is not None else 0.0
        if ds > 0.4:
            weighted = (
                mfn_score * 0.20
                + ds * 0.30
                + price_score * 0.10
                + uom_score * 0.10
                + qoe_score * 0.10
                + vi * 0.20
            )
        else:
            weighted = (
                mfn_score * 0.10
                + ds * 0.40
                + price_score * 0.10
                + uom_score * 0.10
                + qoe_score * 0.10
                + vi * 0.20
            )
    else:
        # Type D — original weights
        ds = desc_score if desc_score is not None else 0.0
        if ds > 0.4:
            weighted = (
                mfn_score * 0.40
                + ds * 0.30
                + price_score * 0.15
                + uom_score * 0.10
                + qoe_score * 0.05
            )
        else:
            weighted = (
                mfn_score * 0.20
                + ds * 0.50
                + price_score * 0.15
                + uom_score * 0.10
                + qoe_score * 0.05
            )

    weighted = float(min(weighted, 1.0))

    # --- Precheck-mode overrides (strict / explicit) ---
    if precheck_mode in ("strict", "explicit"):
        cn_a = str(cn_match or "").strip().upper()
        cn_b = str(cn_input or "").strip().upper()
        if cn_a and cn_b and cn_a == cn_b:
            # Same contract: non-exact MFN ⇒ score 0
            if str(mfn_match or "").strip().upper() != str(mfn_input or "").strip().upper():
                weighted = 0.0
    if precheck_mode == "explicit":
        if str(mfn_match or "").strip().upper() == str(mfn_input or "").strip().upper():
            if uom_score == 0.0 and qoe_score == 0.0:
                weighted = 0.0

    bucket = bucket_score(weighted)

    return {
        "mfn_score": round(float(mfn_score_raw), 4),
        "mfn_complexity": round(float(mfn_complexity), 4),
        "uom_score": round(float(uom_score), 4),
        "qoe_score": round(float(qoe_score), 4),
        "price_score": round(float(price_score), 4),
        "price_diff_pct": round(float(price_diff_pct), 2),
        "desc_score": round(float(desc_score), 4) if desc_score is not None else None,
        "vendor_item_score": round(float(vi_score), 4) if vi_score is not None else None,
        "weighted_score": round(weighted, 4),
        "match_ea_price": round(match_ea, 4) if match_ea is not None else None,
        "input_ea_price": round(input_ea, 4) if input_ea is not None else None,
        "similarity_score": round(weighted * 100, 2),  # 0-100 for MatchResult.similarity_score
        "similarity_bucket": bucket,
    }


# =====================================================================
# Bucket helper
# =====================================================================

def bucket_score(score: Optional[float]) -> str:
    """Classify a score (0-1 scale) into HIGH / MED / LOW."""
    if score is None:
        return "LOW"
    if score >= HIGH_THRESHOLD:
        return "HIGH"
    if score >= MED_THRESHOLD:
        return "MED"
    return "LOW"
