"""Quick Discovery repository — CRUD for discovery sets, items, matches, prompts.

Uses the SQL Server engine. Framework-agnostic (no Flask imports).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import case, func, text
from sqlalchemy.orm import Session

from ..models import (
    DiscoveryItem,
    DiscoveryMatch,
    DiscoveryPrompt,
    DiscoverySet,
)
from ..common.utils import ny_now, SQLSERVER_IN_CHUNK
from .engine import get_sqlserver_engine

# Boolean predicates on BIT columns are written as `col == True`, not
# `col.is_(True)`: T-SQL allows IS only with NULL, so is_() emits `IS 1`
# and SQL Server rejects the statement.

# Insert batch size. These go through executemany (row-wise parameters), so the
# 2100-parameter statement cap doesn't apply — this just bounds client buffering.
INSERT_BATCH_SIZE = 5000


def _session() -> Session:
    return Session(get_sqlserver_engine())


def _chunked(items: list, size: int = SQLSERVER_IN_CHUNK):
    for start in range(0, len(items), size):
        yield items[start:start + size]


# ---------------------------------------------------------------------------
# Sets
# ---------------------------------------------------------------------------
def create_set(
    *,
    set_name: Optional[str],
    source_filename: Optional[str],
    match_mode: str,
    org_eid: str,
    has_supplier: bool,
    created_by: str,
) -> DiscoverySet:
    with _session() as s:
        row = DiscoverySet(
            set_name=set_name,
            source_filename=source_filename,
            match_mode=match_mode,
            org_eid=org_eid,
            has_supplier=has_supplier,
            status="UPLOADED",
            created_by=created_by,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        s.expunge(row)
        return row


def get_set(set_id: int) -> Optional[DiscoverySet]:
    with _session() as s:
        row = s.get(DiscoverySet, set_id)
        if row is not None:
            s.expunge(row)
        return row


def list_sets(limit: int = 200, created_by: Optional[str] = None) -> list[DiscoverySet]:
    with _session() as s:
        q = s.query(DiscoverySet)
        if created_by:
            q = q.filter(DiscoverySet.created_by == created_by)
        rows = q.order_by(DiscoverySet.set_id.desc()).limit(limit).all()
        for r in rows:
            s.expunge(r)
        return rows


def update_set(set_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = ny_now()
    with _session() as s:
        s.query(DiscoverySet).filter(DiscoverySet.set_id == set_id).update(
            fields, synchronize_session=False
        )
        s.commit()


def delete_set(set_id: int) -> bool:
    """Delete a set and everything under it. Children first (FK order)."""
    with _session() as s:
        s.query(DiscoveryMatch).filter(DiscoveryMatch.set_id == set_id).delete(
            synchronize_session=False
        )
        s.query(DiscoveryItem).filter(DiscoveryItem.set_id == set_id).delete(
            synchronize_session=False
        )
        deleted = s.query(DiscoverySet).filter(DiscoverySet.set_id == set_id).delete(
            synchronize_session=False
        )
        s.commit()
        return bool(deleted)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
def add_items_bulk(set_id: int, items: list[dict]) -> int:
    """Insert uploaded lines. Each dict carries the parsed row fields."""
    if not items:
        return 0
    now = ny_now()
    payload = []
    for item in items:
        row = dict(item)
        row["set_id"] = set_id
        row.setdefault("match_count", 0)
        row.setdefault("created_at", now)
        payload.append(row)
    with _session() as s:
        for batch in _chunked(payload, INSERT_BATCH_SIZE):
            s.bulk_insert_mappings(DiscoveryItem, batch)
        s.commit()
    return len(payload)


def get_items(set_id: int) -> list[DiscoveryItem]:
    with _session() as s:
        rows = (
            s.query(DiscoveryItem)
            .filter(DiscoveryItem.set_id == set_id)
            .order_by(DiscoveryItem.discovery_item_id)
            .all()
        )
        for r in rows:
            s.expunge(r)
        return rows


def set_item_match_counts(counts: list[dict]) -> None:
    """Bulk-update match_count. Each dict needs discovery_item_id + match_count."""
    if not counts:
        return
    with _session() as s:
        for batch in _chunked(counts, INSERT_BATCH_SIZE):
            s.bulk_update_mappings(DiscoveryItem, batch)
        s.commit()


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------
def delete_matches(set_id: int) -> int:
    with _session() as s:
        deleted = s.query(DiscoveryMatch).filter(DiscoveryMatch.set_id == set_id).delete(
            synchronize_session=False
        )
        s.commit()
        return deleted


def add_matches_bulk(set_id: int, matches: list[dict]) -> int:
    if not matches:
        return 0
    now = ny_now()
    payload = []
    for match in matches:
        row = dict(match)
        row["set_id"] = set_id
        row.setdefault("llm_status", "NONE")
        row.setdefault("created_at", now)
        payload.append(row)
    with _session() as s:
        for batch in _chunked(payload, INSERT_BATCH_SIZE):
            s.bulk_insert_mappings(DiscoveryMatch, batch)
        s.commit()
    return len(payload)


def count_matches(set_id: int) -> int:
    with _session() as s:
        return (
            s.query(func.count(DiscoveryMatch.discovery_match_id))
            .filter(DiscoveryMatch.set_id == set_id)
            .scalar()
            or 0
        )


def _results_query(s: Session, set_id: int, filters: dict):
    """Build the joined results query with optional filters applied."""
    q = (
        s.query(DiscoveryMatch, DiscoveryItem)
        .join(DiscoveryItem, DiscoveryMatch.discovery_item_id == DiscoveryItem.discovery_item_id)
        .filter(DiscoveryMatch.set_id == set_id)
    )

    verdict = filters.get("verdict")
    if verdict == "UNJUDGED":
        q = q.filter(DiscoveryMatch.llm_verdict.is_(None))
    elif verdict:
        q = q.filter(DiscoveryMatch.llm_verdict == verdict)

    sku_exact = filters.get("sku_exact")
    if sku_exact is not None:
        q = q.filter(DiscoveryMatch.sku_exact == bool(sku_exact))

    if filters.get("matched_on"):
        q = q.filter(DiscoveryMatch.matched_on == filters["matched_on"])

    if filters.get("min_similarity") is not None:
        q = q.filter(DiscoveryMatch.desc_similarity >= float(filters["min_similarity"]))

    if filters.get("max_rank") is not None:
        q = q.filter(DiscoveryMatch.rank_in_item <= int(filters["max_rank"]))

    if filters.get("contract_id"):
        q = q.filter(DiscoveryMatch.contract_id_matched == filters["contract_id"])

    if filters.get("search"):
        like = f"%{filters['search']}%"
        q = q.filter(
            DiscoveryItem.sku_input.like(like)
            | DiscoveryItem.description_input.like(like)
            | DiscoveryMatch.description_matched.like(like)
            | DiscoveryMatch.mfg_catalog_num_matched.like(like)
            | DiscoveryMatch.vendor_catalog_num_matched.like(like)
        )

    return q


def _matched_sku_expr():
    """The SKU shown in the 'Matched SKU' column, which side depends on the hit."""
    return case(
        (DiscoveryMatch.matched_on == "REDUCED_MFG", DiscoveryMatch.mfg_catalog_num_matched),
        else_=DiscoveryMatch.vendor_catalog_num_matched,
    )


# Sortable columns, keyed by the field name the browser sends. Anything not in
# here is ignored rather than trusted — this feeds an ORDER BY.
def _sort_columns() -> dict:
    return {
        "file_row": DiscoveryItem.file_row,
        "sku_input": DiscoveryItem.sku_input,
        "description_input": DiscoveryItem.description_input,
        "supplier_input": DiscoveryItem.supplier_input,
        "sku_exact": DiscoveryMatch.sku_exact,
        "matched_on": DiscoveryMatch.matched_on,
        "desc_similarity": DiscoveryMatch.desc_similarity,
        "rank_in_item": DiscoveryMatch.rank_in_item,
        "matched_sku": _matched_sku_expr(),
        "description_matched": DiscoveryMatch.description_matched,
        "contract_id_matched": DiscoveryMatch.contract_id_matched,
        "organization_matched": DiscoveryMatch.organization_matched,
        "vendor_name_matched": DiscoveryMatch.vendor_name_matched,
        "mfg_name_matched": DiscoveryMatch.mfg_name_matched,
        "llm_verdict": DiscoveryMatch.llm_verdict,
        "llm_confidence": DiscoveryMatch.llm_confidence,
        "llm_reason": DiscoveryMatch.llm_reason,
        "llm_prompt_version_id": DiscoveryMatch.llm_prompt_version_id,
    }


def _order_by(sort: Optional[str], direction: Optional[str]) -> list:
    """Build the ORDER BY, always ending in a unique tiebreaker.

    OFFSET/FETCH paging over a non-deterministic order lets rows repeat on one
    page and vanish from another, so discovery_match_id always closes the sort.
    """
    desc_dir = (direction or "").lower() == "desc"
    column = _sort_columns().get(sort or "")

    if column is None:
        # Default view: each input line's best match first.
        return [
            DiscoveryMatch.discovery_item_id.asc(),
            DiscoveryMatch.rank_in_item.asc(),
            DiscoveryMatch.discovery_match_id.asc(),
        ]
    return [
        column.desc() if desc_dir else column.asc(),
        DiscoveryMatch.discovery_match_id.asc(),
    ]


def get_results_page(
    set_id: int,
    filters: dict,
    offset: int = 0,
    limit: int = 100,
    sort: Optional[str] = None,
    direction: Optional[str] = None,
) -> dict:
    """Server-side paged results. A set can hold tens of thousands of matches,
    well past the point where shipping everything to the browser is sensible —
    which is also why sorting has to happen here and not in the page."""
    with _session() as s:
        q = _results_query(s, set_id, filters)
        total = q.order_by(None).count()
        rows = (
            q.order_by(*_order_by(sort, direction))
            .offset(offset)
            .limit(limit)
            .all()
        )
        results = []
        for match, item in rows:
            payload = match.to_dict()
            payload.update({
                "file_row": item.file_row,
                "sku_input": item.sku_input,
                "sku_raw": item.sku_raw,
                "reduced_sku": item.reduced_sku,
                "description_input": item.description_input,
                "supplier_input": item.supplier_input,
            })
            results.append(payload)
        # Echo the sort that was actually applied, not what was asked for — an
        # unrecognised column silently falls back, and the caller should see that.
        applied = sort if sort in _sort_columns() else ""
        return {
            "total": total, "offset": offset, "limit": limit,
            "sort": applied,
            "direction": (direction or "asc").lower() if applied else "asc",
            "rows": results,
        }


def get_results_for_export(
    set_id: int,
    filters: dict,
    sort: Optional[str] = None,
    direction: Optional[str] = None,
) -> list[dict]:
    """Same shape as get_results_page but unpaged, for the xlsx export.

    Takes the sort too, so the spreadsheet comes out in the order the user
    arranged on screen.
    """
    with _session() as s:
        rows = (
            _results_query(s, set_id, filters)
            .order_by(*_order_by(sort, direction))
            .all()
        )
        out = []
        for match, item in rows:
            payload = match.to_dict()
            payload.update({
                "file_row": item.file_row,
                "sku_input": item.sku_input,
                "description_input": item.description_input,
                "supplier_input": item.supplier_input,
            })
            out.append(payload)
        return out


def get_summary(set_id: int) -> dict:
    """Counts for the header cards and the LLM progress bar."""
    with _session() as s:
        total = (
            s.query(func.count(DiscoveryMatch.discovery_match_id))
            .filter(DiscoveryMatch.set_id == set_id)
            .scalar()
            or 0
        )
        items_total = (
            s.query(func.count(DiscoveryItem.discovery_item_id))
            .filter(DiscoveryItem.set_id == set_id)
            .scalar()
            or 0
        )
        items_with_match = (
            s.query(func.count(func.distinct(DiscoveryMatch.discovery_item_id)))
            .filter(DiscoveryMatch.set_id == set_id)
            .scalar()
            or 0
        )
        exact = (
            s.query(func.count(DiscoveryMatch.discovery_match_id))
            .filter(DiscoveryMatch.set_id == set_id, DiscoveryMatch.sku_exact == True)
            .scalar()
            or 0
        )
        by_status = dict(
            s.query(DiscoveryMatch.llm_status, func.count(DiscoveryMatch.discovery_match_id))
            .filter(DiscoveryMatch.set_id == set_id)
            .group_by(DiscoveryMatch.llm_status)
            .all()
        )
        by_verdict = dict(
            s.query(DiscoveryMatch.llm_verdict, func.count(DiscoveryMatch.discovery_match_id))
            .filter(DiscoveryMatch.set_id == set_id, DiscoveryMatch.llm_verdict.isnot(None))
            .group_by(DiscoveryMatch.llm_verdict)
            .all()
        )
        contracts = (
            s.query(func.count(func.distinct(DiscoveryMatch.contract_id_matched)))
            .filter(DiscoveryMatch.set_id == set_id)
            .scalar()
            or 0
        )
        return {
            "match_count": total,
            "item_count": items_total,
            "items_with_match": items_with_match,
            "items_without_match": max(0, items_total - items_with_match),
            "sku_exact_count": exact,
            "contract_count": contracts,
            "llm_by_status": {k: v for k, v in by_status.items()},
            "llm_by_verdict": {k: v for k, v in by_verdict.items()},
            "llm_pending": by_status.get("PENDING", 0) + by_status.get("IN_PROGRESS", 0),
            "llm_done": by_status.get("DONE", 0),
            "llm_error": by_status.get("ERROR", 0),
        }


# ---------------------------------------------------------------------------
# LLM run control
# ---------------------------------------------------------------------------
def reset_stuck_in_progress(set_id: int) -> int:
    """Return IN_PROGRESS rows to PENDING.

    A slice claims rows before calling the LLM; if that request dies mid-flight
    the rows would otherwise stay claimed forever. Called when a new run starts.
    """
    with _session() as s:
        updated = (
            s.query(DiscoveryMatch)
            .filter(DiscoveryMatch.set_id == set_id, DiscoveryMatch.llm_status == "IN_PROGRESS")
            .update({"llm_status": "PENDING"}, synchronize_session=False)
        )
        s.commit()
        return updated


def cancel_llm_queue(set_id: int) -> int:
    """Un-queue everything still waiting. Rows already DONE keep their verdicts."""
    with _session() as s:
        updated = (
            s.query(DiscoveryMatch)
            .filter(
                DiscoveryMatch.set_id == set_id,
                DiscoveryMatch.llm_status.in_(["PENDING", "IN_PROGRESS"]),
            )
            .update({"llm_status": "NONE"}, synchronize_session=False)
        )
        s.commit()
        return updated


def _scope_filter(q, scope: str, top_n: Optional[int]):
    """Narrow a DiscoveryMatch query to the requested scope."""
    if scope == "TOP_N":
        return q.filter(DiscoveryMatch.rank_in_item <= int(top_n or 1))
    if scope == "ALL":
        return q
    raise ValueError(f"Unknown scope: {scope}")


def _auto_skip_clause(skip_exact_above: Optional[float]):
    """Rows the auto-skip rule excludes: exact SKU *and* near-identical wording.

    An exact catalog number plus a description that already scores at or above
    the threshold locally is not a judgement call — paying an LLM to confirm it
    is waste. ``desc_similarity`` NULL compares as unknown, so unscored rows are
    never auto-skipped.
    """
    if skip_exact_above is None:
        return None
    return (DiscoveryMatch.sku_exact == True) & (  # noqa: E712 - BIT column
        DiscoveryMatch.desc_similarity >= float(skip_exact_above)
    )


def count_llm_candidates(
    set_id: int,
    scope: str,
    *,
    top_n: Optional[int] = None,
    skip_exact_above: Optional[float] = None,
    include_done: bool = False,
) -> dict:
    """Preview what a run would cost before any of it is spent.

    Returns counts for the rows in scope, split into what would be sent, what
    the auto-skip rule removes, and what already carries a verdict.
    """
    allowed = ["NONE", "PENDING", "ERROR"] + (["DONE"] if include_done else [])
    with _session() as s:
        base = _scope_filter(
            s.query(func.count(DiscoveryMatch.discovery_match_id))
            .filter(DiscoveryMatch.set_id == set_id),
            scope, top_n,
        )
        in_scope = base.scalar() or 0
        already_done = (
            _scope_filter(
                s.query(func.count(DiscoveryMatch.discovery_match_id))
                .filter(DiscoveryMatch.set_id == set_id,
                        DiscoveryMatch.llm_status == "DONE"),
                scope, top_n,
            ).scalar() or 0
        )
        sendable = _scope_filter(
            s.query(func.count(DiscoveryMatch.discovery_match_id))
            .filter(DiscoveryMatch.set_id == set_id,
                    DiscoveryMatch.llm_status.in_(allowed)),
            scope, top_n,
        )
        eligible_before_rule = sendable.scalar() or 0

        clause = _auto_skip_clause(skip_exact_above)
        if clause is None:
            skipped_by_rule = 0
        else:
            skipped_by_rule = (
                _scope_filter(
                    s.query(func.count(DiscoveryMatch.discovery_match_id))
                    .filter(DiscoveryMatch.set_id == set_id,
                            DiscoveryMatch.llm_status.in_(allowed),
                            clause),
                    scope, top_n,
                ).scalar() or 0
            )

        return {
            "in_scope": in_scope,
            "already_done": already_done if not include_done else 0,
            "skipped_by_rule": skipped_by_rule,
            "eligible": max(0, eligible_before_rule - skipped_by_rule),
        }


def queue_for_llm(
    set_id: int,
    scope: str,
    *,
    top_n: Optional[int] = None,
    match_ids: Optional[list[int]] = None,
    include_done: bool = False,
    skip_exact_above: Optional[float] = None,
    include_ids: Optional[list[int]] = None,
    exclude_ids: Optional[list[int]] = None,
) -> int:
    """Mark rows PENDING for the LLM runner.

    ``scope`` is ALL, TOP_N (best ``top_n`` matches per input line), or SELECTED
    (exactly ``match_ids``). Rows already DONE are skipped unless
    ``include_done`` — that is what stops a second click re-billing work already
    paid for.

    ``skip_exact_above`` applies the auto-skip rule to ALL/TOP_N. The per-row
    checkboxes then arrive as deltas from that rule: ``exclude_ids`` for rows the
    user unticked, ``include_ids`` for rows the rule dropped but the user wants
    judged anyway. Sending deltas rather than a full id list is what keeps this
    workable on a set with a hundred thousand matches.

    Any queue left over from a previous click is cleared first, so the selection
    the user is looking at is the selection that runs.
    """
    allowed = ["NONE", "PENDING", "ERROR"] + (["DONE"] if include_done else [])

    with _session() as s:
        # Replace, don't accumulate.
        s.query(DiscoveryMatch).filter(
            DiscoveryMatch.set_id == set_id,
            DiscoveryMatch.llm_status.in_(["PENDING", "IN_PROGRESS"]),
        ).update({"llm_status": "NONE"}, synchronize_session=False)
        s.flush()

        if scope == "SELECTED":
            if not match_ids:
                s.commit()
                return 0
            for batch in _chunked([int(m) for m in match_ids]):
                s.query(DiscoveryMatch).filter(
                    DiscoveryMatch.set_id == set_id,
                    DiscoveryMatch.discovery_match_id.in_(batch),
                    DiscoveryMatch.llm_status.in_(allowed),
                ).update({"llm_status": "PENDING"}, synchronize_session=False)
        else:
            q = _scope_filter(
                s.query(DiscoveryMatch).filter(
                    DiscoveryMatch.set_id == set_id,
                    DiscoveryMatch.llm_status.in_(allowed),
                ),
                scope, top_n,
            )
            clause = _auto_skip_clause(skip_exact_above)
            if clause is not None:
                q = q.filter(~clause)
            q.update({"llm_status": "PENDING"}, synchronize_session=False)
            s.flush()

            # Per-row overrides, applied after the rule so they always win.
            for batch in _chunked([int(m) for m in (exclude_ids or [])]):
                s.query(DiscoveryMatch).filter(
                    DiscoveryMatch.set_id == set_id,
                    DiscoveryMatch.discovery_match_id.in_(batch),
                    DiscoveryMatch.llm_status == "PENDING",
                ).update({"llm_status": "NONE"}, synchronize_session=False)
            for batch in _chunked([int(m) for m in (include_ids or [])]):
                s.query(DiscoveryMatch).filter(
                    DiscoveryMatch.set_id == set_id,
                    DiscoveryMatch.discovery_match_id.in_(batch),
                    DiscoveryMatch.llm_status.in_(allowed),
                ).update({"llm_status": "PENDING"}, synchronize_session=False)

        s.flush()
        queued = (
            s.query(func.count(DiscoveryMatch.discovery_match_id))
            .filter(DiscoveryMatch.set_id == set_id,
                    DiscoveryMatch.llm_status == "PENDING")
            .scalar() or 0
        )
        s.commit()
        return queued


_CLAIM_SQL = text("""
UPDATE TOP (:slice_size) [Preprocessor].[PreprocessorDiscoveryMatch]
SET llm_status = 'IN_PROGRESS'
OUTPUT inserted.discovery_match_id
WHERE set_id = :set_id AND llm_status = 'PENDING'
""")


def claim_llm_slice(set_id: int, slice_size: int) -> list[int]:
    """Atomically claim up to ``slice_size`` PENDING rows.

    The UPDATE ... OUTPUT is a single statement, so two browser tabs polling the
    same set can never claim the same row and double-charge the API.
    """
    with _session() as s:
        rows = s.execute(
            _CLAIM_SQL, {"slice_size": int(slice_size), "set_id": set_id}
        ).fetchall()
        s.commit()
        return [r[0] for r in rows]


def get_matches_for_llm(match_ids: list[int]) -> list[dict]:
    """Load the comparison payload for claimed rows, joined to their input line."""
    if not match_ids:
        return []
    out = []
    with _session() as s:
        for batch in _chunked(match_ids):
            rows = (
                s.query(DiscoveryMatch, DiscoveryItem)
                .join(
                    DiscoveryItem,
                    DiscoveryMatch.discovery_item_id == DiscoveryItem.discovery_item_id,
                )
                .filter(DiscoveryMatch.discovery_match_id.in_(batch))
                .all()
            )
            for match, item in rows:
                out.append({
                    "discovery_match_id": match.discovery_match_id,
                    "input_sku": item.sku_input,
                    "input_description": item.description_input,
                    "input_supplier": item.supplier_input,
                    "matched_sku": (
                        match.mfg_catalog_num_matched
                        if match.matched_on == "REDUCED_MFG"
                        else match.vendor_catalog_num_matched
                    ),
                    "matched_description": match.description_matched,
                    "matched_vendor_name": match.vendor_name_matched,
                    "matched_manufacturer_name": match.mfg_name_matched,
                    "sku_exact": bool(match.sku_exact),
                    "matched_on": match.matched_on,
                    "desc_similarity": match.desc_similarity,
                })
    return out


def save_llm_verdicts(updates: list[dict]) -> int:
    """Persist verdicts. Each dict needs discovery_match_id + the llm_* fields."""
    if not updates:
        return 0
    with _session() as s:
        for batch in _chunked(updates, INSERT_BATCH_SIZE):
            s.bulk_update_mappings(DiscoveryMatch, batch)
        s.commit()
    return len(updates)


def count_llm_remaining(set_id: int) -> int:
    with _session() as s:
        return (
            s.query(func.count(DiscoveryMatch.discovery_match_id))
            .filter(
                DiscoveryMatch.set_id == set_id,
                DiscoveryMatch.llm_status.in_(["PENDING", "IN_PROGRESS"]),
            )
            .scalar()
            or 0
        )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def get_active_prompt(prompt_key: str = "ITEM_COMPARE") -> Optional[DiscoveryPrompt]:
    with _session() as s:
        row = (
            s.query(DiscoveryPrompt)
            .filter(
                DiscoveryPrompt.prompt_key == prompt_key,
                DiscoveryPrompt.is_active == True,
            )
            .first()
        )
        if row is not None:
            s.expunge(row)
        return row


def get_prompt(prompt_version_id: int) -> Optional[DiscoveryPrompt]:
    with _session() as s:
        row = s.get(DiscoveryPrompt, prompt_version_id)
        if row is not None:
            s.expunge(row)
        return row


def list_prompts(prompt_key: str = "ITEM_COMPARE") -> list[DiscoveryPrompt]:
    with _session() as s:
        rows = (
            s.query(DiscoveryPrompt)
            .filter(DiscoveryPrompt.prompt_key == prompt_key)
            .order_by(DiscoveryPrompt.version_no.desc())
            .all()
        )
        for r in rows:
            s.expunge(r)
        return rows


def create_prompt_version(
    *,
    prompt_key: str,
    system_prompt: str,
    user_template: str,
    created_by: str,
    notes: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    activate: bool = True,
) -> DiscoveryPrompt:
    """Insert a new version. Existing versions are never modified.

    When ``activate``, the previous active row is deactivated first — the
    filtered unique index permits only one active version per key.
    """
    with _session() as s:
        current_max = (
            s.query(func.max(DiscoveryPrompt.version_no))
            .filter(DiscoveryPrompt.prompt_key == prompt_key)
            .scalar()
        )
        next_version = int(current_max or 0) + 1

        if activate:
            s.query(DiscoveryPrompt).filter(
                DiscoveryPrompt.prompt_key == prompt_key,
                DiscoveryPrompt.is_active == True,
            ).update({"is_active": False}, synchronize_session=False)
            s.flush()

        row = DiscoveryPrompt(
            prompt_key=prompt_key,
            version_no=next_version,
            system_prompt=system_prompt,
            user_template=user_template,
            model=model,
            temperature=temperature,
            is_active=bool(activate),
            notes=notes,
            created_by=created_by,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        s.expunge(row)
        return row


def activate_prompt_version(prompt_version_id: int) -> bool:
    """Make an existing version active, deactivating its siblings."""
    with _session() as s:
        row = s.get(DiscoveryPrompt, prompt_version_id)
        if row is None:
            return False
        s.query(DiscoveryPrompt).filter(
            DiscoveryPrompt.prompt_key == row.prompt_key,
            DiscoveryPrompt.is_active == True,
        ).update({"is_active": False}, synchronize_session=False)
        s.flush()
        row.is_active = True
        s.commit()
        return True
