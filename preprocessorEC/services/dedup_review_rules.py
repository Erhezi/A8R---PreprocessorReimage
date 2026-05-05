"""Action/Notes rules for the dedup_output_to_review per-contract sheets.

Pure functions, no DB or Flask coupling. Mirrors the spec at
``prompt/dedup_review_rules_spec.md`` (and ``prompt/temp_report.md`` history).

Inputs come from a single ``PreprocessorTaskItemForDecision`` row joined to
the matched CCX line; callers pass the relevant columns by keyword to
``notes_for``. The function set is intentionally flat so the rules read like
the spec table.
"""

from __future__ import annotations

from typing import Optional

from . import dedup_resolution as _dr

# Prices match within +/- this absolute EA delta. Per spec section 2.
EA_TOLERANCE = 0.0001

# Action strings — keep verbatim with the spec.
ACTION_SS_UPSERT = "Same contract item, Update"
ACTION_SS_EXPIRE = "Same contract item, Update expiration date to expire"
ACTION_DV_UPSERT = "Buy from different vendor, keep both"
ACTION_ODO_UPSERT = "Buy for different organization using same contract ID, review"
ACTION_TCCD_UPSERT = "Consider only keep one record, review"
ACTION_CECCD_UPSERT = "Buy for different organization using different contract, review"
ACTION_NON_SS_EXPIRE = "Not affected by expiring the input line, keep the record"


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def _is_premier(source_type: Optional[str]) -> bool:
    return _norm(source_type) == "PREMIER"


def _intent(intention: Optional[str]) -> str:
    """Normalize task intention to one of UPDATE / NEW / EXPIRE.

    Anything else (MIX, missing) is treated as UPDATE — for MIX tasks the
    workspace populator already snapshots the per-item intention into
    ``task_intention``, so this branch is a defensive fallback.
    """
    n = _norm(intention)
    if n in {"UPDATE", "NEW", "EXPIRE"}:
        return n
    return "UPDATE"


def _price_rel(ea_in: Optional[float], ea_mt: Optional[float]) -> str:
    """``EQ`` | ``MT_BETTER`` | ``IN_BETTER``.

    When either side is missing, default to ``EQ`` so we don't fabricate a
    "X has better price" claim. Reviewers will spot the missing price.
    """
    if ea_in is None or ea_mt is None:
        return "EQ"
    diff = float(ea_mt) - float(ea_in)
    if abs(diff) < EA_TOLERANCE:
        return "EQ"
    return "MT_BETTER" if diff < 0 else "IN_BETTER"


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------

def action_for(group: Optional[str], intention: Optional[str]) -> str:
    """Return the Action cell value for a dedup pair."""
    g = _norm(group)
    intent = _intent(intention)

    if intent == "EXPIRE":
        if g == "SS":
            return ACTION_SS_EXPIRE
        # DV / ODO / TCCD / CECCD all share the same EXPIRE action.
        return ACTION_NON_SS_EXPIRE if g in {"DV", "ODO", "TCCD", "CECCD"} else ""

    # UPDATE / NEW
    if g == "SS":
        return ACTION_SS_UPSERT
    if g == "DV":
        return ACTION_DV_UPSERT
    if g == "ODO":
        return ACTION_ODO_UPSERT
    if g == "TCCD":
        return ACTION_TCCD_UPSERT
    if g == "CECCD":
        return ACTION_CECCD_UPSERT
    return ""


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def notes_for(
    group: Optional[str],
    intention: Optional[str],
    *,
    matched_contract_id: Optional[str] = None,
    matched_org_eid: Optional[str] = None,
    input_org_eid: Optional[str] = None,
    matched_source_type: Optional[str] = None,
    input_source_type: Optional[str] = None,
    ea_matched: Optional[float] = None,
    ea_input: Optional[float] = None,
) -> str:
    """Return the Notes cell value for a dedup pair."""
    g = _norm(group)
    intent = _intent(intention)

    # Notes are only populated for UPDATE / NEW on ODO / TCCD / CECCD.
    if g in {"SS", "DV"} or intent == "EXPIRE":
        return ""

    matched_org = _dr.org_type(matched_org_eid)
    input_org = _dr.org_type(input_org_eid)
    mt_p = _is_premier(matched_source_type)
    in_p = _is_premier(input_source_type)
    pr = _price_rel(ea_input, ea_matched)
    cid = (matched_contract_id or "").strip()

    if g == "ODO":
        return _odo_notes(matched_org, input_org)
    if g == "TCCD":
        return _tccd_notes(pr, mt_p, in_p, cid)
    if g == "CECCD":
        return _ceccd_notes(pr, matched_org, input_org, mt_p, in_p, cid)
    return ""


def _odo_notes(matched_org: str, input_org: str) -> str:
    if matched_org == "ME" and input_org == "ME":
        return (
            "Different member entity contract item, keep both and make sure "
            "the data elements are consistent with each other"
        )
    # Either side is MHS.
    return (
        "If not for tracking price difference between member entity and MHS, "
        "consider maintain only the MHS contract and remove the member entity "
        "contract entirely. Otherwise if price difference is desired, keep "
        "both and make sure the data elements are consistent with each other."
    )


def _tccd_notes(pr: str, mt_p: bool, in_p: bool, cid: str) -> str:
    if pr == "EQ":
        if mt_p and in_p:
            return (
                "both contracts have the same price, both are premier contract, "
                "keep both and ensure the data elements are consistent with each other"
            )
        if mt_p and not in_p:
            return (
                "both contracts have the same price, but matched contract is premier "
                "while input contract is local, consider keep the matched record and "
                "drop the input line"
            )
        if not mt_p and in_p:
            return (
                "both contracts have the same price, but input contract is premier "
                "while matched contract is local, consider keep the input record and "
                "drop the matched line"
            )
        # both local
        return (
            "both contracts have the same price, both are local contract, "
            "review and keep only one record"
        )

    if pr == "MT_BETTER":
        if mt_p and in_p:
            return (
                f"contract {cid} has better price, both are premier contract, "
                f"keep both and ensure the data elements are consistent with each other, "
                f"consider setting priority based on price on Infor to default to the "
                f"favorable pricing"
            )
        if mt_p and not in_p:
            return (
                f"contract {cid} has better price, matched contract is premier while "
                f"input contract is local, consider keep the matched record and drop "
                f"the input line"
            )
        if not mt_p and in_p:
            return (
                f"contract {cid} has better price, but input is premier contract, "
                f"keep both and ensure the data elements are consistent with each other, "
                f"consider setting priority based on price on Infor to default to the "
                f"favorable pricing"
            )
        # both local
        return (
            f"contract {cid} has better price, both are local contract, "
            f"review and keep the matched record and drop the input line"
        )

    # IN_BETTER
    if mt_p and in_p:
        return (
            "input contract has better price, both are premier contract, "
            "keep both and ensure the data elements are consistent with each other, "
            "consider setting priority based on price on Infor to default to the "
            "favorable pricing"
        )
    if mt_p and not in_p:
        return (
            "input contract has better price, but matched contract is premier while "
            "input contract is local, keep both and ensure the data elements are "
            "consistent with each other, consider setting priority based on price on "
            "Infor to default to the favorable pricing"
        )
    if not mt_p and in_p:
        return (
            "input contract has better price, input contract is premier while matched "
            "contract is local, consider keep the input record and drop the matched line"
        )
    # both local
    return (
        "input contract has better price, both are local contract, "
        "review and keep the input record and drop the matched line"
    )


def _ceccd_notes(
    pr: str,
    matched_org: str,
    input_org: str,
    mt_p: bool,
    in_p: bool,
    cid: str,
) -> str:
    # ME-ME: keep both regardless of contract type. Verify price diff is real.
    if matched_org == "ME" and input_org == "ME":
        return _ceccd_me_me(pr, cid)
    if matched_org == "MHS" and input_org == "ME":
        return _ceccd_mhs_me(pr, mt_p, in_p, cid)
    if matched_org == "ME" and input_org == "MHS":
        return _ceccd_me_mhs(pr, mt_p, in_p, cid)
    # (MHS, MHS) cannot occur in CECCD by definition (different organizations).
    return ""


def _ceccd_me_me(pr: str, cid: str) -> str:
    if pr == "EQ":
        return (
            "both contracts have the same price, but for different member entities, "
            "keep both and ensure the data elements are consistent with each other"
        )
    if pr == "MT_BETTER":
        return (
            f"contract {cid} has better price, but for different member entities, "
            f"keep both and ensure the data elements are consistent with each other, "
            f"verfify that we truely have contract price difference between different "
            f"member enetities for the item"
        )
    # IN_BETTER
    return (
        "input contract has better price, but for different member entities, "
        "keep both and ensure the data elements are consistent with each other, "
        "verfify that we truely have contract price difference between different "
        "member enetities for the item"
    )


def _ceccd_mhs_me(pr: str, mt_p: bool, in_p: bool, cid: str) -> str:
    """matched_org=MHS, input_org=ME."""
    if pr == "EQ":
        if mt_p and in_p:
            return (
                "both contracts have the same price, both are premier contract, "
                "keep both and ensure the data elements are consistent with each other"
            )
        if not mt_p and not in_p:
            return (
                "both contracts have the same price, both are local contract, "
                "consider keep the matched MHS record and drop the input ME record"
            )
        if not mt_p and in_p:
            return (
                "both contracts have the same price, but input ME contract is premier, "
                "keep both and ensure the data elements are consistent with each other"
            )
        # mt_p, not in_p
        return (
            "both contracts have the same price, input ME contract is local, "
            "consider keep the matched MHS record and drop the input ME record"
        )

    if pr == "MT_BETTER":
        if mt_p and in_p:
            return (
                f"MHS contract {cid} has better price, both are premier contract, "
                f"keep both and ensure the data elements are consistent with each other, "
                f"verify the price difference is due to member entity truely have to pay "
                f"higher price than MHS for the item"
            )
        if not mt_p and not in_p:
            return (
                f"MHS contract {cid} has better price, both are local contract, "
                f"verify the price difference is due to member entity truely have to pay "
                f"higher price than MHS for the item, otherwise consider keep the matched "
                f"MHS record and drop the input ME record"
            )
        if not mt_p and in_p:
            return (
                f"MHS contract {cid} has better price, but input ME contract is premier, "
                f"keep both and ensure the data elements are consistent with each other, "
                f"verify the price difference is due to member entity truely have to pay "
                f"higher price than MHS for the item"
            )
        # mt_p, not in_p
        return (
            f"MHS contract {cid} has better price, verify the price difference is due to "
            f"member entity truely have to pay higher price than MHS for the item, "
            f"otherwise consider keep the matched MHS record and drop the input ME record"
        )

    # IN_BETTER (input ME has better price)
    if mt_p and in_p:
        return (
            "input ME contract has better price, both are premier contract, "
            "keep both and ensure the data elements are consistent with each other, "
            "verify the price difference is due to member entity truely have to pay "
            "lower price than MHS for the item"
        )
    if not mt_p and not in_p:
        return (
            "input ME contract has better price, both are local contract, "
            "verify the price difference is due to member entity truely have to pay "
            "lower price than MHS for the item, keep both and ensure the data elements "
            "are consistent with each other, otherwise consider keep the matched MHS "
            "record and drop the input ME record"
        )
    if not mt_p and in_p:
        return (
            "input ME contract has better price, keep both and ensure the data elements "
            "are consistent with each other, verify the price difference is due to "
            "member entity truely have to pay lower price than MHS for the item"
        )
    # mt_p, not in_p
    return (
        "input ME contract has better price, keep both and ensure the data elements are "
        "consistent with each other, verify the price difference is due to member entity "
        "truely have to pay lower price than MHS for the item, otherwise consider keep "
        "the matched MHS record and drop the input ME record"
    )


def _ceccd_me_mhs(pr: str, mt_p: bool, in_p: bool, cid: str) -> str:
    """matched_org=ME, input_org=MHS."""
    if pr == "EQ":
        if mt_p and in_p:
            return (
                "both contracts have the same price, both are premier contract, "
                "keep both and ensure the data elements are consistent with each other"
            )
        if not mt_p and not in_p:
            return (
                "both contracts have the same price, both are local contract, "
                "consider keep the input MHS record and drop the matched ME record"
            )
        if not mt_p and in_p:
            return (
                "both contracts have the same price, but matched MHS contract is premier, "
                "consider keep the input MHS record and drop the matched ME record"
            )
        # mt_p, not in_p
        return (
            "both contracts have the same price, matched MHS contract is local, "
            "keep both and ensure the data elements are consistent with each other"
        )

    if pr == "MT_BETTER":  # matched ME has better price (lower than MHS)
        if mt_p and in_p:
            return (
                f"member entity contract {cid} has better price, both are premier contract, "
                f"keep both and ensure the data elements are consistent with each other, "
                f"verify the price difference is due to member entity truely have to pay "
                f"lower price than MHS for the item"
            )
        if not mt_p and not in_p:
            return (
                f"member entity contract {cid} has better price, both are local contract, "
                f"verify the price difference is due to member entity truely have to pay "
                f"lower price than MHS for the item, otherwise consider keep the input MHS "
                f"record and drop the matched ME record"
            )
        if not mt_p and in_p:
            return (
                f"member entity contract {cid} has better price, keep both and ensure the "
                f"data elements are consistent with each other, verify the price difference "
                f"is due to member entity truely have to pay lower price than MHS for the "
                f"item, otherwise consider keep the input MHS record and drop the matched "
                f"ME record"
            )
        # mt_p, not in_p
        return (
            f"member entity contract {cid} has better price, keep both and ensure the data "
            f"elements are consistent with each other, verify the price difference is due "
            f"to member entity truely have to pay lower price than MHS for the item"
        )

    # IN_BETTER (input MHS has better price)
    if mt_p and in_p:
        return (
            "input MHS contract has better price, both are premier contract, "
            "keep both and ensure the data elements are consistent with each other, "
            "verify the price difference is due to member entity truely have to pay "
            "higher price than MHS for the item"
        )
    if not mt_p and not in_p:
        return (
            "input MHS contract has better price, both are local contract, "
            "verify the price difference is due to member entity truely have to pay "
            "higher price than MHS for the item, otherwise consider keep the input MHS "
            "record and drop the matched ME record"
        )
    if not mt_p and in_p:
        return (
            "input MHS contract has better price, keep both and ensure the data elements "
            "are consistent with each other, verify the price difference is due to member "
            "entity truely have to pay higher price than MHS for the item, otherwise "
            "consider keep the input MHS record and drop the matched ME record"
        )
    # mt_p, not in_p
    return (
        "input MHS contract has better price, keep both and ensure the data elements are "
        "consistent with each other, verify the price difference is due to member entity "
        "truely have to pay higher price than MHS for the item"
    )
