"""Phase 4 dedup — resolution-strategy classifier and default-action matrix.

Pure functions, no DB or Flask coupling. Used by the dedup workspace
populator and any re-classification path. Mirrors the rules in
prompt/design_notes_and_thoughts.txt lines 285-333.
"""

from __future__ import annotations

from typing import Optional

# OrganizationEID for Montefiore Health System (MHS). Anything else is an
# entity (ME). See design notes line 315.
MHS_ORG_EID = "105188574"

# Resolution-strategy group codes
GROUP_SS = "SS"      # Same organization, same vendor, same contract
GROUP_DV = "DV"      # Different vendor
GROUP_ODO = "ODO"    # Same contract + vendor, different organization
GROUP_TCCD = "TCCD"  # Same org + vendor, different contract
GROUP_CECCD = "CECCD"  # Different org, different contract (same vendor)

ALL_GROUPS = (GROUP_SS, GROUP_DV, GROUP_ODO, GROUP_TCCD, GROUP_CECCD)

# Default-action values
ACTION_KEEP = "keep"
ACTION_DROP = "drop"
ACTION_ANY = "any"


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def org_type(org_eid: Optional[str]) -> str:
    """Return 'MHS' if org_eid is the Montefiore EID, else 'ME'."""
    return "MHS" if (org_eid or "").strip() == MHS_ORG_EID else "ME"


def _is_premier(source_type: Optional[str]) -> bool:
    return _norm(source_type) == "PREMIER"


def _orgs_equal(
    a_eid: Optional[str],
    a_name: Optional[str],
    b_eid: Optional[str],
    b_name: Optional[str],
) -> bool:
    """Are two (eid, name) pairs the same organization?

    EID match wins when both sides have one. When either side is missing
    its EID (the input TaskItem currently doesn't carry organization_eid
    in intake), we fall back to comparing organization names. If neither
    signal is fully populated on both sides, declare different so a real
    mismatch surfaces in the resolution group rather than being silently
    swallowed.
    """
    aeid, beid = _norm(a_eid), _norm(b_eid)
    if aeid and beid:
        return aeid == beid
    aname, bname = _norm(a_name), _norm(b_name)
    if aname and bname:
        return aname == bname
    return False


def classify_group(
    input_org_eid: Optional[str],
    input_vendor: Optional[str],
    input_contract: Optional[str],
    matched_org_eid: Optional[str],
    matched_vendor: Optional[str],
    matched_contract: Optional[str],
    input_org_name: Optional[str] = None,
    matched_org_name: Optional[str] = None,
) -> str:
    """Bucket an (input, matched) pair into one of the 5 resolution groups."""
    same_vendor = _norm(input_vendor) == _norm(matched_vendor)
    same_org = _orgs_equal(input_org_eid, input_org_name, matched_org_eid, matched_org_name)
    same_contract = _norm(input_contract) == _norm(matched_contract)

    # DV trumps everything else: different vendor isn't a same-contract dup
    # in the operational sense, so we treat it as its own group.
    if not same_vendor:
        return GROUP_DV

    if same_org and same_contract:
        return GROUP_SS
    if same_contract and not same_org:
        return GROUP_ODO
    if same_org and not same_contract:
        return GROUP_TCCD
    # not same_org and not same_contract
    return GROUP_CECCD


def _ss_actions(intention: str) -> tuple[str, str]:
    if intention == "EXPIRE":
        return ACTION_DROP, ACTION_DROP
    return ACTION_KEEP, ACTION_DROP


def _dv_actions(intention: str) -> tuple[str, str]:
    if intention == "EXPIRE":
        return ACTION_DROP, ACTION_KEEP
    return ACTION_KEEP, ACTION_KEEP


def _odo_actions(intention: str) -> tuple[str, str]:
    if intention == "EXPIRE":
        return ACTION_DROP, ACTION_KEEP
    return ACTION_KEEP, ACTION_KEEP


def _tccd_actions(
    intention: str,
    input_premier: bool,
    matched_premier: bool,
) -> tuple[str, str]:
    if intention == "EXPIRE":
        return ACTION_DROP, ACTION_KEEP
    if not input_premier and not matched_premier:
        return ACTION_ANY, ACTION_ANY
    if not input_premier and matched_premier:
        return ACTION_ANY, ACTION_KEEP
    if input_premier and not matched_premier:
        return ACTION_KEEP, ACTION_ANY
    return ACTION_KEEP, ACTION_KEEP  # both premier


def _ceccd_actions(
    intention: str,
    input_premier: bool,
    matched_premier: bool,
    input_org_type_v: str,
    matched_org_type_v: str,
) -> tuple[str, str]:
    if intention == "EXPIRE":
        return ACTION_DROP, ACTION_KEEP

    both_me = input_org_type_v == "ME" and matched_org_type_v == "ME"
    input_me_matched_mhs = input_org_type_v == "ME" and matched_org_type_v == "MHS"
    input_mhs_matched_me = input_org_type_v == "MHS" and matched_org_type_v == "ME"

    # Source-type quadrant
    if not input_premier and not matched_premier:
        if both_me:
            return ACTION_KEEP, ACTION_KEEP
        if input_me_matched_mhs:
            return ACTION_ANY, ACTION_KEEP
        if input_mhs_matched_me:
            return ACTION_KEEP, ACTION_ANY
    elif not input_premier and matched_premier:
        if both_me:
            return ACTION_KEEP, ACTION_KEEP
        if input_me_matched_mhs:
            return ACTION_ANY, ACTION_KEEP
        if input_mhs_matched_me:
            return ACTION_KEEP, ACTION_KEEP
    elif input_premier and not matched_premier:
        if both_me:
            return ACTION_KEEP, ACTION_KEEP
        if input_me_matched_mhs:
            return ACTION_KEEP, ACTION_KEEP
        if input_mhs_matched_me:
            return ACTION_KEEP, ACTION_ANY
    else:  # both premier
        if both_me:
            return ACTION_KEEP, ACTION_KEEP
        if input_me_matched_mhs:
            return ACTION_KEEP, ACTION_KEEP
        if input_mhs_matched_me:
            return ACTION_KEEP, ACTION_KEEP

    # Fallback (e.g. both MHS — design doesn't enumerate, but be safe).
    return ACTION_KEEP, ACTION_KEEP


def default_actions(
    group: str,
    intention: Optional[str],
    input_source_type: Optional[str],
    matched_source_type: Optional[str],
    input_org_eid: Optional[str] = None,
    matched_org_eid: Optional[str] = None,
) -> tuple[str, str]:
    """Return (default_action_input, default_action_matched) for a row.

    Caller is responsible for normalizing intention to one of
    {EXPIRE, NEW, UPDATE}; everything not 'EXPIRE' is treated as upsert.
    LOCATE follows the NEW path, so it is folded into NEW here.
    """
    intent = _norm(intention)
    if intent == "LOCATE":
        intent = "NEW"
    if intent not in {"EXPIRE", "NEW", "UPDATE"}:
        # Default to upsert if the task intention is missing/unknown so that
        # the user still sees sensible defaults instead of empty cells.
        intent = "UPDATE"

    input_premier = _is_premier(input_source_type)
    matched_premier = _is_premier(matched_source_type)
    input_t = org_type(input_org_eid)
    matched_t = org_type(matched_org_eid)

    if group == GROUP_SS:
        return _ss_actions(intent)
    if group == GROUP_DV:
        return _dv_actions(intent)
    if group == GROUP_ODO:
        return _odo_actions(intent)
    if group == GROUP_TCCD:
        return _tccd_actions(intent, input_premier, matched_premier)
    if group == GROUP_CECCD:
        return _ceccd_actions(intent, input_premier, matched_premier, input_t, matched_t)
    # Unknown group — fall back to keep/keep so the user sees the row.
    return ACTION_KEEP, ACTION_KEEP


def editable_for_side(source_type: Optional[str]) -> bool:
    """A side (input or matched) is editable only when its contract is LOCAL.

    Premier contracts cannot be edited at the line level per current system
    constraints; LOCAL contracts allow edits limited to the field allowlist
    enforced in the API layer (manufacturer #, vendor item, UOM, QOE, desc).
    """
    return not _is_premier(source_type)
