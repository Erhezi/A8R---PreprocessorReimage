"""Quick Discovery — the located-contract report.

A different question from the results grid. The grid answers "what did the LLM
say about each candidate pair"; this answers "for each line I uploaded, which
contract line did we locate for it, if any". That flips three things:

* It is driven by the input file, not by the matches, so a line that matched
  nothing still gets a row. A report that silently omitted them would read as
  full coverage.
* Candidates judged DIFFERENT carry no contract, so their contract columns are
  dropped rather than exported as a match someone might act on.
* An exact catalog number with a near-identical description counts as SAME
  without an LLM verdict. Those pairs are deliberately never sent to the model
  (see ``_auto_skip_clause``), so treating "no verdict" as "not located" would
  blank out precisely the rows that matched best.

Effective date, expiration date, and the Infor item number are not on the
match snapshot, so they are read live from CCX through the business key.
"""

from __future__ import annotations

from typing import Optional

from ..db import discovery_repo

# Column order of the report. Supplier is dropped when the upload had no
# supplier column, so the sheet has no column that is blank in every row; when
# present it sits second, beside Input Row, since both describe the input side.
SUPPLIER_COLUMN = "Supplier"

LOCATED_CONTRACT_COLUMNS = (
    "Input Row",
    "SKU",
    "Description",
    "Exact",
    "Similarity",
    "Verdict",
    "Matched SKU",
    "Matched Description",
    "Matched Contract",
    "UOM",
    "QOE",
    "Price",
    "Infor IM Item",
    "Effective Date",
    "Expiration Date",
    "Vendor",
    "Vendor ID",
    "Organization",
    "Manufacturer",
    "Total Matched Lines",
)

# Verdicts that keep their contract columns. DIFFERENT is excluded entirely.
LOCATED_VERDICTS = ("SAME", "UNCERTAIN", None)


def effective_verdict(match: dict, similarity_threshold: Optional[float]) -> Optional[str]:
    """What this pair counts as in the report.

    Precedence is human, then model, then the auto-skip rule. The rule is last
    because it is an inference rather than a judgement: it only speaks for pairs
    nobody and nothing has ruled on.
    """
    if match.get("user_verdict"):
        return match["user_verdict"]
    if match.get("llm_verdict"):
        return match["llm_verdict"]
    if similarity_threshold is not None and match.get("sku_exact"):
        similarity = match.get("desc_similarity")
        if similarity is not None and float(similarity) >= float(similarity_threshold):
            return "SAME"
    return None


def _to_date(value):
    """CCX dates come back as date objects; keep them as dates for Excel."""
    return value or None


def _blank_match_row(item: dict, located_count: int, has_supplier: bool) -> dict:
    """An input line with no contract to report against."""
    row = {
        "Input Row": item.get("file_row"),
        "SKU": item.get("sku_input"),
        "Description": item.get("description_input"),
        "Exact": "",
        "Similarity": None,
        "Verdict": "",
        "Matched SKU": "",
        "Matched Description": "",
        "Matched Contract": "",
        "UOM": "",
        "QOE": None,
        "Price": None,
        "Infor IM Item": "",
        "Effective Date": None,
        "Expiration Date": None,
        "Vendor": "",
        "Vendor ID": "",
        "Organization": "",
        "Manufacturer": "",
        "Total Matched Lines": located_count,
    }
    if has_supplier:
        row[SUPPLIER_COLUMN] = item.get("supplier_input")
    return row


def _match_row(item: dict, match: dict, verdict, details: dict,
               located_count: int, has_supplier: bool) -> dict:
    matched_sku = (
        match.get("mfg_catalog_num_matched")
        if match.get("matched_on") == "REDUCED_MFG"
        else match.get("vendor_catalog_num_matched")
    )
    row = {
        "Input Row": item.get("file_row"),
        "SKU": item.get("sku_input"),
        "Description": item.get("description_input"),
        "Exact": "Yes" if match.get("sku_exact") else "No",
        "Similarity": match.get("desc_similarity"),
        "Verdict": verdict or "",
        "Matched SKU": matched_sku,
        "Matched Description": match.get("description_matched"),
        "Matched Contract": match.get("contract_id_matched"),
        "UOM": match.get("uom_matched"),
        "QOE": match.get("qoe_matched"),
        "Price": match.get("unit_price_matched"),
        # Kept as text: a six-digit Infor item is an identifier, and Excel would
        # strip a leading zero if it were handed a number.
        "Infor IM Item": ", ".join(sorted(details.get("infor_items") or ())),
        "Effective Date": _to_date(details.get("effective_date")),
        "Expiration Date": _to_date(details.get("expiration_date")),
        "Vendor": match.get("vendor_name_matched"),
        "Vendor ID": match.get("erp_vendor_id_matched"),
        "Organization": match.get("organization_matched"),
        "Manufacturer": match.get("mfg_name_matched"),
        "Total Matched Lines": located_count,
    }
    if has_supplier:
        row[SUPPLIER_COLUMN] = item.get("supplier_input")
    return row


def columns_for(has_supplier: bool) -> list[str]:
    """Report columns. Input Row leads so the sheet reads in file order, with
    supplier next to it when the upload carried one."""
    columns = list(LOCATED_CONTRACT_COLUMNS)
    if has_supplier:
        columns.insert(1, SUPPLIER_COLUMN)
    return columns


def build_located_contract_report(
    set_id: int,
    *,
    has_supplier: bool,
    similarity_threshold: Optional[float] = 1.0,
    include_unmatched: bool = True,
) -> dict:
    """Rows plus counts for the located-contract report.

    ``Total Matched Lines`` counts what this report actually located for the
    input line, after DIFFERENT candidates are dropped — not what the matcher
    originally proposed. A line whose every candidate was rejected reads 0, the
    same as a line that never matched anything, because after review those two
    outcomes are the same: no contract was found. The pre-review candidate count
    is still in the results export.
    """
    items = discovery_repo.get_items_with_matches(set_id)

    # One CCX read for the whole report rather than one per row.
    details_by_key = discovery_repo.get_ccx_line_details([
        match.get("mfg_catalog_num_matched")
        for item in items for match in item["matches"]
    ])

    rows: list[dict] = []
    stats = {
        "input_lines": len(items),
        "located_lines": 0,
        "unmatched_lines": 0,
        "excluded_different": 0,
        "auto_same": 0,
        "missing_dates": 0,
        "missing_infor_item": 0,
    }

    for item in items:
        matches = item["matches"]
        kept = []

        for match in matches:
            verdict = effective_verdict(match, similarity_threshold)
            if verdict == "DIFFERENT":
                stats["excluded_different"] += 1
                continue
            if verdict == "SAME" and not match.get("user_verdict") and not match.get("llm_verdict"):
                stats["auto_same"] += 1
            kept.append((match, verdict))

        if not kept:
            stats["unmatched_lines"] += 1
            if include_unmatched:
                rows.append(_blank_match_row(item, 0, has_supplier))
            continue

        stats["located_lines"] += 1
        located_count = len(kept)
        for match, verdict in kept:
            key = discovery_repo.ccx_business_key(
                match.get("organization_eid_matched"),
                match.get("contract_id_matched"),
                match.get("erp_vendor_id_matched"),
                match.get("mfg_catalog_num_matched"),
                match.get("uom_matched"),
                match.get("uom_to_match_infor_matched"),
            )
            details = details_by_key.get(key)
            if details is None:
                # The daily CCX reload can retire a line between matching and
                # export. Report the match without dates rather than dropping it.
                stats["missing_dates"] += 1
                details = {}
            elif not details.get("infor_items"):
                # A live CCX line with no Infor counterpart — the contract line
                # exists but is not on an Infor item master record.
                stats["missing_infor_item"] += 1
            rows.append(
                _match_row(item, match, verdict, details, located_count, has_supplier)
            )

    return {"rows": rows, "columns": columns_for(has_supplier), "stats": stats}
