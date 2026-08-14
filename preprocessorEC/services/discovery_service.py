"""Quick Discovery — upload parsing, CCX SKU matching, similarity, ranking.

A discovery set is a task-free lookup: a user uploads SKU + Description
(+ optional Supplier), and we answer "do we already buy any of these?" against
CCX contract lines.

Framework-agnostic (no Flask imports). The sentence-transformer model is passed
in by the caller rather than read from ``current_app``.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import bindparam
from sqlalchemy.orm import Session

from ..common.utils import (
    clean_text,
    reduce_catalog_number,
    SQLSERVER_IN_CHUNK,
)
from ..db import discovery_repo
from ..db.engine import get_sqlserver_engine
from ..db.sql_loader import load_query
from .scoring import compute_similarities_batch

logger = logging.getLogger(__name__)

# MHS org EID — matches every organization's contract lines.
MHS_ORG_EID = "105188574"

MATCH_MODES = ("MFG", "VENDOR", "EITHER")
DEFAULT_MATCH_MODE = "EITHER"

# The three columns an upload may map. SKU and description are required.
COLUMN_KEYS = ("sku", "description", "supplier")
COLUMN_ALIASES = {
    "sku": [
        "sku", "item_sku", "item_number", "item_no", "catalog_number", "catalog_num",
        "catalog_#", "cat_#", "part_number", "part_no", "part_#", "mfg_catalog_num",
        "manufacturer_part_number", "manufacturer_catalog_number", "mfg#",
        "vendor_catalog_num", "vendor_part_number", "vendor#",
    ],
    "description": [
        "description", "desc", "item_description", "product_description", "item_desc",
    ],
    "supplier": [
        "supplier", "supplier_name", "vendor", "vendor_name", "manufacturer",
        "manufacturer_name", "mfg_name", "distributor",
    ],
}


class DiscoveryInputError(ValueError):
    """Raised for user-correctable upload problems; routes turn these into 400s."""


def _sql_session() -> Session:
    return Session(get_sqlserver_engine())


def _normalize_header(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_")


def resolve_columns(headers: list[str], user_mapping: Optional[dict] = None) -> dict:
    """Map the three discovery keys onto the uploaded file's headers.

    An explicit mapping from the browser wins; anything unmapped falls back to
    alias matching so a well-formed file needs no manual mapping at all.
    """
    user_mapping = user_mapping or {}
    resolved: dict[str, Optional[str]] = {}

    for key in COLUMN_KEYS:
        chosen = user_mapping.get(key)
        if chosen and chosen in headers:
            resolved[key] = chosen
            continue
        resolved[key] = None

    normalized = {_normalize_header(h): h for h in headers}
    taken = {v for v in resolved.values() if v}
    for key in COLUMN_KEYS:
        if resolved[key]:
            continue
        for alias in COLUMN_ALIASES[key]:
            candidate = normalized.get(alias)
            if candidate and candidate not in taken:
                resolved[key] = candidate
                taken.add(candidate)
                break

    missing = [k for k in ("sku", "description") if not resolved.get(k)]
    if missing:
        raise DiscoveryInputError(
            "Could not find required column(s): "
            + ", ".join(missing)
            + ". Map them explicitly or rename the header."
        )
    return resolved


def parse_upload(dataframe, columns: dict, max_rows: int) -> list[dict]:
    """Turn the uploaded dataframe into DiscoveryItem payload dicts.

    ``sku_raw`` keeps exactly what was uploaded, ``sku_input`` is cleansed, and
    ``reduced_sku`` is the reduced form — the only one matching runs against.
    Keeping all three separate is deliberate: reduction strips leading zeros and
    punctuation, so overwriting the original would lose real catalog identity.
    """
    if len(dataframe) > max_rows:
        raise DiscoveryInputError(
            f"File has {len(dataframe):,} rows; the limit is {max_rows:,} per set. "
            "Split the file and upload it as multiple sets."
        )
    if dataframe.empty:
        raise DiscoveryInputError("The uploaded file has no data rows.")

    sku_col = columns["sku"]
    desc_col = columns["description"]
    supplier_col = columns.get("supplier")

    items: list[dict] = []
    skipped: list[int] = []

    for index, row in dataframe.iterrows():
        file_row = int(index) + 2  # +1 for the header, +1 for 1-based rows

        raw_sku = row.get(sku_col)
        raw_desc = row.get(desc_col)
        sku_raw = "" if raw_sku is None else str(raw_sku).strip()
        desc_raw = "" if raw_desc is None else str(raw_desc).strip()

        if sku_raw.lower() in ("", "nan", "none") or desc_raw.lower() in ("", "nan", "none"):
            skipped.append(file_row)
            continue

        sku_input = clean_text(sku_raw)
        description = clean_text(desc_raw)
        if not sku_input or not description:
            skipped.append(file_row)
            continue

        supplier = None
        if supplier_col:
            raw_supplier = row.get(supplier_col)
            supplier_raw = "" if raw_supplier is None else str(raw_supplier).strip()
            if supplier_raw.lower() not in ("", "nan", "none"):
                supplier = clean_text(supplier_raw)[:255] or None

        items.append({
            "file_row": file_row,
            "sku_raw": sku_raw[:255],
            "sku_input": sku_input[:255],
            "reduced_sku": reduce_catalog_number(sku_input)[:255],
            "description_input": description,
            "supplier_input": supplier,
        })

    if not items:
        raise DiscoveryInputError(
            "No usable rows found — every row was missing a SKU or a description."
        )
    if skipped:
        logger.info(
            "Discovery upload skipped %d row(s) missing SKU or description (first few: %s).",
            len(skipped), skipped[:10],
        )
    return items


def create_set_from_upload(
    dataframe,
    *,
    user_mapping: Optional[dict],
    match_mode: str,
    set_name: Optional[str],
    source_filename: Optional[str],
    created_by: str,
    max_rows: int,
) -> dict:
    """Parse + persist an uploaded file as a new discovery set."""
    mode = (match_mode or DEFAULT_MATCH_MODE).upper()
    if mode not in MATCH_MODES:
        raise DiscoveryInputError(
            f"Unknown match mode '{match_mode}'. Use one of: {', '.join(MATCH_MODES)}."
        )

    columns = resolve_columns(list(dataframe.columns), user_mapping)
    items = parse_upload(dataframe, columns, max_rows)
    has_supplier = any(item["supplier_input"] for item in items)

    discovery_set = discovery_repo.create_set(
        set_name=(set_name or source_filename or "Untitled set")[:200],
        source_filename=(source_filename or None),
        match_mode=mode,
        org_eid=MHS_ORG_EID,
        has_supplier=has_supplier,
        created_by=created_by,
    )
    discovery_repo.add_items_bulk(discovery_set.set_id, items)
    discovery_repo.update_set(
        discovery_set.set_id, row_count=len(items), status="UPLOADED"
    )

    return {
        "set_id": discovery_set.set_id,
        "row_count": len(items),
        "skipped_rows": len(dataframe) - len(items),
        "has_supplier": has_supplier,
        "match_mode": mode,
        "columns": columns,
    }


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def _load_ccx_rows(reduced_values: list[str], query_name: str, bind_name: str, org_eid: str) -> list:
    """Run one dup_detection set-query, chunked under the parameter cap."""
    if not reduced_values:
        return []
    stmt = load_query("preprocess", "dup_detection", query=query_name).bindparams(
        bindparam(bind_name, expanding=True)
    )
    rows: list = []
    with _sql_session() as sess:
        for start in range(0, len(reduced_values), SQLSERVER_IN_CHUNK):
            batch = reduced_values[start:start + SQLSERVER_IN_CHUNK]
            rows.extend(
                sess.execute(stmt, {bind_name: batch, "org_eid": org_eid}).mappings().all()
            )
    return rows


def _snapshot(row, matched_on: str, sku_exact: bool) -> dict:
    """Project a CCX candidate row into DiscoveryMatch columns.

    The six business-key fields are stored because CCX_pkid is a surrogate the
    daily reload re-issues; pkid is kept for debugging only.
    """
    return {
        "ccx_pkid": row.get("CCX_pkid"),
        "matched_on": matched_on,
        "sku_exact": sku_exact,
        "organization_eid_matched": row.get("OrganizationEID"),
        "organization_matched": row.get("Organization"),
        "contract_id_matched": row.get("ContractID"),
        "erp_vendor_id_matched": row.get("ERPVendorID"),
        "mfg_catalog_num_matched": row.get("mfg_catalog_num_ccx"),
        "uom_matched": row.get("uom_ccx"),
        "uom_to_match_infor_matched": row.get("uom_to_match_infor_ccx"),
        "vendor_catalog_num_matched": row.get("vendor_catalog_num_ccx"),
        "description_matched": row.get("description_ccx"),
        "qoe_matched": row.get("qoe_ccx"),
        "unit_price_matched": row.get("unit_price_ccx"),
        "contract_description": row.get("ContractDescription"),
        "vendor_name_matched": row.get("vendor_name"),
        "mfg_name_matched": row.get("mfg_name_infor"),
        "contract_manufacturer_matched": row.get("contract_manufacturer"),
    }


def run_matching(set_id: int, model=None) -> dict:
    """Match a set's SKUs against CCX contract lines, score, and rank.

    ``model`` is the sentence-transformer, passed in by the route so this module
    stays free of Flask. When None, ``compute_similarities_batch`` falls back to
    token overlap.
    """
    discovery_set = discovery_repo.get_set(set_id)
    if discovery_set is None:
        raise DiscoveryInputError(f"Discovery set {set_id} not found.")

    items = discovery_repo.get_items(set_id)
    if not items:
        raise DiscoveryInputError("This set has no items to match.")

    discovery_repo.update_set(set_id, status="MATCHING")
    discovery_repo.delete_matches(set_id)

    mode = (discovery_set.match_mode or DEFAULT_MATCH_MODE).upper()
    org_eid = discovery_set.org_eid or MHS_ORG_EID

    # One reduced SKU can appear on many input lines; index so a single CCX row
    # fans back out to every line that produced it.
    items_by_reduced: dict[str, list] = {}
    for item in items:
        if item.reduced_sku:
            items_by_reduced.setdefault(item.reduced_sku, []).append(item)
    reduced_values = sorted(items_by_reduced)

    if not reduced_values:
        discovery_repo.update_set(set_id, status="MATCHED", match_count=0)
        return {"set_id": set_id, "matched_count": 0, "items_with_match": 0}

    # (discovery_item_id, ccx_pkid) -> payload. In EITHER mode a line reachable
    # both ways is stored once; REDUCED_MFG wins because a manufacturer part
    # number is the stronger identity signal.
    pairs: dict[tuple, dict] = {}

    def collect(rows, matched_on: str, ccx_col: str, reduced_col: str) -> None:
        for row in rows:
            reduced = (row.get(reduced_col) or "").strip().upper()
            matched_raw = clean_text(row.get(ccx_col) or "")
            for item in items_by_reduced.get(reduced, []):
                key = (item.discovery_item_id, row.get("CCX_pkid"))
                if key in pairs and pairs[key]["matched_on"] == "REDUCED_MFG":
                    continue
                payload = _snapshot(
                    row, matched_on, sku_exact=bool(matched_raw) and matched_raw == item.sku_input
                )
                payload["discovery_item_id"] = item.discovery_item_id
                pairs[key] = payload

    if mode in ("MFG", "EITHER"):
        collect(
            _load_ccx_rows(reduced_values, "ccx_match_mfg_set", "reduced_mfg_nums", org_eid),
            "REDUCED_MFG",
            "mfg_catalog_num_ccx",
            "reduced_mfg_num_ccx",
        )
    if mode in ("VENDOR", "EITHER"):
        collect(
            _load_ccx_rows(reduced_values, "ccx_match_vendor_set", "reduced_vendor_nums", org_eid),
            "REDUCED_VPN",
            "vendor_catalog_num_ccx",
            "reduced_vendor_num_ccx",
        )

    if not pairs:
        discovery_repo.update_set(set_id, status="MATCHED", match_count=0)
        return {"set_id": set_id, "matched_count": 0, "items_with_match": 0}

    # Group by input line so each line's candidates are embedded in one batch.
    by_item: dict[int, list[dict]] = {}
    for payload in pairs.values():
        by_item.setdefault(payload["discovery_item_id"], []).append(payload)

    items_by_id = {item.discovery_item_id: item for item in items}
    matches: list[dict] = []
    item_counts: list[dict] = []

    for item_id, candidates in by_item.items():
        item = items_by_id.get(item_id)
        if item is None:
            continue
        scores = compute_similarities_batch(
            item.description_input,
            [c.get("description_matched") or "" for c in candidates],
            model=model,
        )
        for candidate, score in zip(candidates, scores):
            candidate["desc_similarity"] = float(score)

        # Exact SKU first, then closest description — the order a human would
        # scan, and the order the LLM-on-demand "top N" scope relies on.
        candidates.sort(
            key=lambda c: (0 if c["sku_exact"] else 1, -(c.get("desc_similarity") or 0.0))
        )
        for rank, candidate in enumerate(candidates, start=1):
            candidate["rank_in_item"] = rank

        matches.extend(candidates)
        item_counts.append({
            "discovery_item_id": item_id,
            "match_count": len(candidates),
        })

    discovery_repo.add_matches_bulk(set_id, matches)
    discovery_repo.set_item_match_counts(item_counts)
    discovery_repo.update_set(set_id, status="MATCHED", match_count=len(matches))

    logger.info(
        "Discovery set %s: %d input line(s) produced %d match(es) across %d line(s) with hits.",
        set_id, len(items), len(matches), len(by_item),
    )

    return {
        "set_id": set_id,
        "matched_count": len(matches),
        "items_with_match": len(by_item),
        "items_total": len(items),
        "match_mode": mode,
    }
