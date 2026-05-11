"""Intake service — Phase 1 business logic.

Handles: file parsing, input standardization, PC1 validation.
Pure Python, no Flask imports. Called by intake/routes.py.
Later: becomes a LangGraph node implementation.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..common.utils import ny_now
from ..db import task_repo, workstate_repo
from ..db.engine import get_sqlserver_engine
from ..db.sql_loader import load_query
from ..state import TaskStateMachine, Phase, Status, Reason

# ---------------------------------------------------------------------------
# UOM substitution map (common short forms → standard EDI codes)
# ---------------------------------------------------------------------------
UOM_MAP = {
    "BOX": "BX",
    "CASE": "CA",
    "EACH": "EA",
    "DOZEN": "DZ",
    "PACK": "PK",
    "PACKAGE": "PK",
    "PAIR": "PR",
    "SET": "ST",
    "BOTTLE": "BT",
    "BAG": "BG",
    "ROLL": "RL",
    "CARTON": "CT",
    "PALLET": "PL",
    "TUBE": "TB",
    "VIAL": "VI",
    "GALLON": "GL",
    "OUNCE": "OZ",
    "POUND": "LB",
    "LITER": "LT",
}


# ---------------------------------------------------------------------------
# Text standardization helpers
# ---------------------------------------------------------------------------
def _clean_text(value: str) -> str:
    """Strip, remove non-printable chars, normalise to UTF-8 upper case."""
    if not isinstance(value, str):
        return str(value).strip().upper()
    # Normalise unicode
    normalized = unicodedata.normalize("NFKD", value)
    # Remove non-printable control characters (keep \n \t for now)
    cleaned = re.sub(r"[^\x20-\x7E\n\t]", "", normalized)
    return cleaned.strip().upper()


def _standardize_uom(uom: str) -> tuple[str, Optional[str]]:
    """Return (standardized_uom, mapping_note_or_None)."""
    upper = uom.strip().upper()
    if upper in UOM_MAP:
        return UOM_MAP[upper], f"{uom} → {UOM_MAP[upper]}"
    return upper, None


def _parse_qoe(value) -> tuple[Optional[int], Optional[str]]:
    """Convert QOE to int. Returns (value, error_or_None)."""
    try:
        v = int(float(str(value)))
        if v <= 0:
            return None, "QOE must be positive"
        return v, None
    except (ValueError, TypeError):
        return None, f"Invalid QOE: {value}"


def _parse_price(value) -> tuple[Optional[Decimal], Optional[str]]:
    """Convert price to Decimal. Returns (value, error_or_None)."""
    try:
        d = Decimal(str(value).replace(",", "").replace("$", "").strip())
        if d < 0:
            return None, "Price cannot be negative"
        return d, None
    except (InvalidOperation, ValueError, TypeError):
        return None, f"Invalid price: {value}"


def reduce_catalog_number(part_num: str) -> str:
    """Reduce a catalog number by stripping non-alphanumeric characters and upper-casing.
    If the result is purely numeric, leading zeros are removed (but "0" is kept if that's all there is)."""
    if not part_num:
        return ""
    reduced = re.sub(r"[^A-Z0-9]", "", str(part_num).upper())
    if reduced.isdigit():
        reduced = reduced.lstrip('0') or '0'
    return reduced


# ---------------------------------------------------------------------------
# Reference data loaders (cached per precheck run)
# ---------------------------------------------------------------------------
def _load_valid_uoms() -> set[str]:
    """Load valid UOM codes from MDM_EDI_SUB_UOM."""
    engine = get_sqlserver_engine()
    with engine.connect() as conn:
        rows = conn.execute(load_query("intake", "intake", query="get_valid_uoms")).fetchall()
    return {r[0] for r in rows if r[0]}


def _load_uom_to_match_infor_map() -> dict[str, str]:
    """Load standardized UOM to Lawson UOM translations from MDM_EDI_SUB_UOM."""
    engine = get_sqlserver_engine()
    with engine.connect() as conn:
        rows = conn.execute(load_query("intake", "intake", query="get_uom_to_match_infor_map")).fetchall()
    return {external_value: lawson_value for external_value, lawson_value in rows if external_value and lawson_value}


# def _load_valid_vendors() -> set[str]:
#     """Load active vendor IDs from PurchaseVendorLocation (both 0000000 and 0000000-B000 forms)."""
#     return _load_valid_erp_vendor_ids()


def _load_valid_erp_vendor_ids() -> set[str]:
    """Load active vendor-location combos from InforVendorLocation."""
    engine = get_sqlserver_engine()
    with engine.connect() as conn:
        rows = conn.execute(load_query("intake", "intake", query="get_valid_erp_vendor_ids")).fetchall()
    return {r[0] for r in rows if r[0]}


# ---------------------------------------------------------------------------
# Vendor ID helpers
# ---------------------------------------------------------------------------
_VENDOR_ID_RE = re.compile(r"^(\d{7})(-B\d{3})?$")


def _parse_vendor_id(vendor_id: str) -> tuple[Optional[str], Optional[str]]:
    """Parse vendor_id into (base_7digit, full_id_or_None).

    Returns (base, full) where base is the 7-digit vendor code and
    full includes the optional -B### location suffix.
    """
    vid = str(vendor_id).strip()
    m = _VENDOR_ID_RE.match(vid)
    if not m:
        return None, None
    return m.group(1), vid


# ---------------------------------------------------------------------------
# QOE / UOM compatibility checks
# ---------------------------------------------------------------------------
def _check_qoe_uom_compat(uom: str, qoe: int) -> list[tuple[str, str, str]]:
    """Return list of (error_type, detail, severity) tuples for QOE/UOM issues."""
    issues = []
    if uom == "EA" and qoe != 1:
        issues.append(("QOE_UOM_MISMATCH", f"UOM is EA but QOE is {qoe} (expected 1)", "ERROR"))
    if uom in ("PK", "BX", "CA", "CS", "PR") and qoe == 1:
        issues.append(("QOE_UOM_WARNING", f"UOM is {uom} but QOE is 1 — verify packaging quantity", "WARNING"))
    return issues


def _translate_uom_to_match_infor(std_uom: str, uom_map: dict[str, str]) -> str:
    """Translate a standardized input UOM to the Lawson UOM used for Infor matching."""
    if not std_uom:
        return ""
    return uom_map.get(std_uom, std_uom)


# ---------------------------------------------------------------------------
# Duplicate-detection helpers (mode-aware)
# ---------------------------------------------------------------------------
# Precheck modes:
#   default   — reduced_mfg only (catches aaa-bb = aaabb) - warn if reduced_mfg matches but clean_mfg differs
#   strict    — exact Mfg Part Num only (aaa-bb ≠ aaabb)
#   explicit  — exact Mfg Part Num + UOM (aaa-bb BX ≠ aaa-bb CA)
#   distributor — vendor_id_short + reduced_vendor_catalog_num - warn if reduced_vendor matches but clean_vendor differs

def _check_mfg_dup(
    reduced_mfg: str,
    std_uom: str,
    clean_mfg: str,
    row_ref,
    item_id: int,
    seen: dict,
    dup_groups: dict,
    dup_warn_groups: dict,
    precheck_mode: str = "default",
) -> tuple[str, Optional[tuple[str, str]]]:
    """Check Mfg Cat # for duplicates using mode-specific keys.

    When a duplicate ERROR is found the current item is added to the same
    ``dup_groups[key]`` list as the original so every member shares one group.
    Warning duplicates are tracked the same way in ``dup_warn_groups`` so the UI
    can focus every row participating in a reduced-but-not-exact match.

    Returns ('pass'|'warn'|'error', (error_type, detail) | None).
    """
    if not reduced_mfg and not clean_mfg:
        return "pass", None

    if precheck_mode == "strict":
        # Strict: exact Mfg Cat # only. Reduced matches are deliberately NOT
        # flagged so users can re-run in strict after confirming default-mode
        # warnings are real distinct items.
        key = clean_mfg.upper() if clean_mfg else ""
        if not key:
            return "pass", None
        if key in seen:
            prev_row, _, prev_id = seen[key]
            dup_groups.setdefault(key, [prev_id])
            dup_groups[key].append(item_id)
            return "error", (
                "DUPLICATE_MFG_STRICT",
                f"Exact Mfg Cat # duplicate — rows {', '.join(str(r) for _, _, r in [(prev_row, None, prev_id)] if False) or ', '.join(str(mid) for mid in dup_groups[key])}",
            )
        seen[key] = (row_ref, clean_mfg, item_id)
        return "pass", None

    elif precheck_mode == "explicit":
        # Explicit: exact Mfg Cat # + UOM only. Same rationale as strict —
        # reduced matches don't surface here.
        if not clean_mfg:
            return "pass", None
        key = f"{clean_mfg.upper()}|{std_uom or ''}"
        if key in seen:
            prev_row, _, prev_id = seen[key]
            dup_groups.setdefault(key, [prev_id])
            dup_groups[key].append(item_id)
            return "error", (
                "DUPLICATE_MFG_UOM_EXPLICIT",
                f"Exact Mfg Cat + UOM duplicate — dup group {dup_groups[key]}",
            )
        seen[key] = (row_ref, clean_mfg, item_id)
        return "pass", None

    else:
        if not reduced_mfg:
            return "pass", None
        key = reduced_mfg
        if key in seen:
            prev_row, prev_clean, prev_id = seen[key]
            if prev_clean == clean_mfg:
                dup_groups.setdefault(key, [prev_id])
                dup_groups[key].append(item_id)
                return "error", (
                    "DUPLICATE_MFG_DEFAULT",
                    f"Duplicate Mfg Cat (reduced) — dup group {dup_groups[key]}",
                )
            wkey = f"_warn_default_{reduced_mfg}"
            members = dup_warn_groups.setdefault(wkey, [prev_id])
            if item_id not in members:
                members.append(item_id)
            return "warn", (
                "DUPLICATE_MFG_REDUCED",
                f"Reduced Mfg Cat matches file row {prev_row} but full Mfg Cat differs — verify these are not duplicates",
            )
        seen[key] = (row_ref, clean_mfg, item_id)
        return "pass", None


# Friendly display segment for a DUPLICATE_* error_type used inside the unified
# detail string ("Duplicate Vendor Item - row 5, 9"). Default falls back to a
# Title-cased version of the type body; overrides catch acronyms/compound words
# that don't title-case cleanly.
_DUP_TYPE_DISPLAY_OVERRIDES = {
    "VENDORITEM": "Vendor Item",
}


def _dup_type_display(dup_type: str) -> str:
    body = (dup_type or "").replace("DUPLICATE_", "").replace("_REDUCED", "")
    return _DUP_TYPE_DISPLAY_OVERRIDES.get(body, body.replace("_", " ").title())


def _check_vendor_dup(
    reduced_vendor: str,
    clean_vendor: str,
    row_ref,
    item_id: int,
    seen: dict,
    dup_groups: dict,
    dup_warn_groups: dict,
) -> tuple[str, Optional[tuple[str, str]]]:
    """Check Vendor Cat # for duplicates against items already seen.

    Returns ('pass'|'warn'|'error', (error_type, detail) | None).
    Registers this item in ``seen`` when it is the first occurrence. Warning
    duplicates are tracked in ``dup_warn_groups`` so every reduced-match row
    can be focused together in the UI.
    """
    if not reduced_vendor:
        return "pass", None
    if reduced_vendor in seen:
        prev_row, prev_clean, prev_id = seen[reduced_vendor]
        if prev_clean == clean_vendor:
            vkey = f"_vendor_{reduced_vendor}"
            dup_groups.setdefault(vkey, [prev_id])
            dup_groups[vkey].append(item_id)
            return "error", (
                "DUPLICATE_VENDORITEM",
                f"Duplicate Vendor Item — dup group {dup_groups[vkey]}",
            )
        wkey = f"_warn_vendor_{reduced_vendor}"
        members = dup_warn_groups.setdefault(wkey, [prev_id])
        if item_id not in members:
            members.append(item_id)
        return "warn", (
            "DUPLICATE_VENDORITEM_REDUCED",
            f"Reduced Vendor Item matches file row {prev_row} but full Vendor Item differs — verify these are not duplicates",
        )
    seen[reduced_vendor] = (row_ref, clean_vendor, item_id)
    return "pass", None


# ---------------------------------------------------------------------------
# Required PC1 modes per task type
# ---------------------------------------------------------------------------
def required_pc1_modes(task) -> list[str]:
    """Modes the system targets as the *terminal* PC1 mode for this task.

    Used by the UI / auto-chain to know which mode finishes PC1 — NOT as a
    hard gate inside ``proceed_with_passing`` any more (the user's manual
    pass / fix actions already establish that the data is acceptable).

    - DISTRIBUTOR: ``distributor`` is terminal. ``default`` runs first to
      catch mfg-side dups, then auto-chains into ``distributor`` for the
      vendor-side check. Once ``distributor`` is in ``pc1_passed_modes``
      there is no reason to re-run ``default``.
    - MANUFACTURER / everything else: no terminal mode. The user picks
      default / strict / explicit and decides when to advance.
    """
    process_type = (getattr(task, "process_type", "") or "").upper()
    if "DISTRIBUTOR" in process_type:
        return ["distributor"]
    return []


# Warning-severity error_type codes — kept in sync with the codes emitted by
# _check_qoe_uom_compat / _check_mfg_dup / _check_vendor_dup. The "_REDUCED"
# and "_WARNING" suffix fallbacks catch any future additions.
_WARNING_TYPES = {"QOE_UOM_WARNING", "DUPLICATE_MFG_REDUCED", "DUPLICATE_VENDORITEM_REDUCED"}


def _is_warning_type(error_type: str) -> bool:
    code = (error_type or "").upper()
    if code in _WARNING_TYPES:
        return True
    return code.endswith("_WARNING") or code.endswith("_REDUCED")


def cleanup_dup_groups_after_delete(task_id: str) -> int:
    """Resolve duplicate error/warning records whose group no longer has
    enough active members to constitute a duplicate.

    ``soft_delete_item`` already clears the deleted item's own error rows,
    but the *other* members of the same dup group keep their records — even
    when only one active member is left and the duplication is no longer
    real under the current pre-check mode. This function performs that
    follow-up cleanup so the Pre-Check Errors table consistently drops
    entries that are no longer duplicates.

    Re-evaluates each affected item's status: if its only outstanding issue
    was the now-resolved dup record, it's demoted back to PASSED_PC1; if
    only warning records remain, WARN_PC1.

    Returns the number of error rows resolved.
    """
    items = task_repo.get_items(task_id)
    deleted_ids = {i.item_id for i in items if (i.status or "") in Status.DELETED_STATUSES}

    errors = task_repo.get_precheck_errors(task_id, phase="PC1", resolved=False)

    # Group unresolved DUPLICATE_* records by (error_type, error_detail).
    # Active members = item_ids whose unresolved error shares the key and
    # whose item is not soft-deleted.
    by_group: dict[tuple[str, str], list] = {}
    member_ids: dict[tuple[str, str], set[int]] = {}
    for e in errors:
        if not (e.error_type and e.error_type.startswith("DUPLICATE")):
            continue
        if e.item_id is None or e.item_id in deleted_ids:
            continue
        key = (e.error_type, e.error_detail or "")
        by_group.setdefault(key, []).append(e)
        member_ids.setdefault(key, set()).add(e.item_id)

    resolved_count = 0
    affected_items: set[int] = set()
    for key, group_errors in by_group.items():
        if len(member_ids[key]) <= 1:
            for e in group_errors:
                task_repo.resolve_precheck_error(e.error_id, resolved_by="DUP_CLEANUP")
                resolved_count += 1
                if e.item_id is not None:
                    affected_items.add(e.item_id)

    # Re-evaluate the lone-member items so a stale ERROR_PC1 status doesn't
    # linger after its only error was the now-resolved dup record.
    if affected_items:
        remaining = task_repo.get_precheck_errors(task_id, phase="PC1", resolved=False)
        by_item: dict[int, list] = {}
        for r in remaining:
            if r.item_id is not None:
                by_item.setdefault(r.item_id, []).append(r)
        for item_id in affected_items:
            recs = by_item.get(item_id, [])
            if not recs:
                task_repo.update_item_status(item_id, Status.PASSED_PC1)
            else:
                has_error = any(not _is_warning_type(r.error_type) for r in recs)
                new_status = Status.ERROR_PC1 if has_error else Status.WARN_PC1
                task_repo.update_item_status(item_id, new_status)

    return resolved_count


def clear_pc1_passed_modes(task_id: str, state_machine: TaskStateMachine) -> None:
    """Wipe the list of cleanly-passed PC1 modes.

    Called whenever the data backing a task changes (upload, re-upload, item
    edit, soft-delete). Stale mode passes would otherwise let the gate close
    against rows that haven't actually been re-validated.
    """
    state = state_machine.get_state(task_id)
    state["pc1_passed_modes"] = []
    state["pc1_passed"] = False
    state_machine.save_state(task_id, state)


# ---------------------------------------------------------------------------
# Pre-check PC1 — main entry point
# ---------------------------------------------------------------------------
def run_precheck(
    task_id: str,
    state_machine: TaskStateMachine,
    mode_override: Optional[str] = None,
) -> dict:
    """Run Phase 1 pre-check on ALL items for a task.

    Every run resets all items to UPLOADED first so duplicate detection always
    operates across the full set — partial runs would silently dissolve duplicate
    flags as items get retried one at a time.

    Checks:
      1. Text cleaning + standardization
        2. UOM standardization (alias map) + validation against MDM_EDI_SUB_UOM
            plus Lawson translation into uom_to_match_infor
      3. QOE parsing + QOE/UOM compatibility
      4. Price parsing
      5. Null field checks (mfg cat, description, UOM)
      6. Duplicate detection (mode-aware; always full-set)
      7. Vendor ID validation against PurchaseVendorLocation

    Returns:
        {
            "total": int,
            "passed": int,
            "failed": int,
            "errors": [...],
            "uom_mappings": [...],
        }
    """
    # Load ALL items for the task regardless of current status
    all_items = task_repo.get_items(task_id)
    # Exclude DELETED_PC1 items — soft-deleted by user, should not participate
    items = [i for i in all_items if i.status != Status.DELETED_PC1]
    if not items:
        return {"total": 0, "passed": 0, "failed": 0, "errors": [], "uom_mappings": []}

    # Reset active items to UPLOADED and clear unresolved PC1 errors so we start
    # from a clean slate every time (prevents dissolving duplicate detection).
    # Bulk versions — large uploads were issuing one round-trip per row here.
    task_repo.bulk_reset_items_to_uploaded(task_id)
    task_repo.bulk_resolve_precheck_errors(task_id, phase="PC1", resolved_by="RECHECK")

    task = task_repo.get_task(task_id)
    state = state_machine.get_state(task_id)

    # Load reference data once
    valid_uoms = _load_valid_uoms()
    uom_to_match_infor_map = _load_uom_to_match_infor_map()
    valid_erp_ids = _load_valid_erp_vendor_ids()

    source_type = (task.source_type or "").upper()
    process_type = (task.process_type or "").upper()
    is_distributor = "DISTRIBUTOR" in process_type

    errors = []
    # Aggregate UOM mappings by (from, to) so the precheck summary shows
    # "CS → CA (50)" instead of repeating "CS → CA" once per affected item.
    uom_mapping_counts: dict[tuple[str, str], int] = {}
    uom_to_match_mapping_counts: dict[tuple[str, str], int] = {}
    passed_ids = []
    warned_ids = []
    failed_ids = []
    header_error_count = 0

    # Write buffers — every per-item DB call below appends to one of these
    # and we flush them in three bulk calls at the end. On a 5,000-row file
    # this turns ~25k round-trips into ~5.
    pending_status_updates: dict[int, dict] = {}   # item_id → {item_id, status, error_message}
    pending_field_updates: list[dict] = []         # rows for update_items_bulk
    pending_error_records: list[dict] = []         # rows for add_precheck_errors_bulk

    def _record_issue(item_id, error_type, error_detail):
        """Buffer one PreCheckError row and mirror it into the in-memory errors list.

        ``resolved`` and ``created_at`` are set explicitly because
        ``bulk_insert_mappings`` skips Python-side ``default=`` callables.
        """
        pending_error_records.append({
            "task_id": task_id,
            "item_id": item_id,
            "phase": "PC1",
            "error_type": error_type,
            "error_detail": error_detail,
            "resolved": False,
            "created_at": ny_now(),
        })
        errors.append({"item_id": item_id, "error_type": error_type, "error_detail": error_detail})

    # --- Header-level validation (task fields) ---
    if task.vendor_id:
        base_vendor, full_vendor = _parse_vendor_id(task.vendor_id)
        if not base_vendor:
            _record_issue(
                None,
                "INVALID_VENDOR_FORMAT",
                f"Task vendor ID '{task.vendor_id}' does not match format NNNNNNN or NNNNNNN-BNNN",
            )
            header_error_count += 1
        else:
            # Check the full vendor ID (or base if no location suffix) against PurchaseVendorLocation
            check_id = full_vendor if full_vendor and "-" in full_vendor else base_vendor
            if check_id not in valid_erp_ids:
                _record_issue(
                    None,
                    "VENDOR_NOT_FOUND",
                    f"ERP Vendor ID '{check_id}' not found in active PurchaseVendorLocation",
                )
                header_error_count += 1

    # For duplicate detection: build indexes as we go
    # Values store (file_row, clean_value, item_id) so we can back-patch the original on a hit
    seen_mfg: dict[str, tuple[int, str, int]] = {}        # key depends on precheck_mode
    seen_vendor: dict[str, tuple[int, str, int]] = {}     # reduced_vendor -> (file_row, clean_vendor, item_id)
    # dup_groups maps a dup-key to the list of ALL item_ids that share that key.
    # After the per-item loop we do a single pass to mark every member ERROR_PC1.
    dup_groups: dict[str, list[int]] = {}
    # dup_warn_groups tracks the same idea for *warning* duplicates (reduced
    # match but exact differs). Members are back-patched to WARN_PC1 in a
    # post-loop pass so the front-end can focus every participating row.
    dup_warn_groups: dict[str, list[int]] = {}

    # mode_override is set by the auto-chain path below so distributor can
    # run without us writing "distributor" to task.precheck_mode (which would
    # surface in the dropdown as the saved selection on the next page load).
    precheck_mode = (mode_override or task.precheck_mode or "default").lower()
    if precheck_mode == "distributor" and not is_distributor:
        precheck_mode = "default"

    for item in items:
        item_errors: list[tuple[str, str]] = []       # (type, detail)
        item_warnings: list[tuple[str, str]] = []     # (type, detail)

        # --- Text standardization ---
        clean_desc = _clean_text(item.description)
        clean_mfg = _clean_text(item.mfg_catalog_num) if item.mfg_catalog_num else ""
        clean_vendor = _clean_text(item.vendor_catalog_num) if item.vendor_catalog_num else ""

        # --- UOM standardization ---
        std_uom, uom_note = _standardize_uom(item.uom)
        uom_to_match_infor = _translate_uom_to_match_infor(std_uom, uom_to_match_infor_map)
        validated_uom = uom_to_match_infor or std_uom
        if uom_note:
            key = (item.uom, std_uom)
            uom_mapping_counts[key] = uom_mapping_counts.get(key, 0) + 1
        if std_uom and uom_to_match_infor and uom_to_match_infor != std_uom:
            key = (std_uom, uom_to_match_infor)
            uom_to_match_mapping_counts[key] = uom_to_match_mapping_counts.get(key, 0) + 1

        # --- UOM validation against MDM ---
        if validated_uom and validated_uom not in valid_uoms:
            item_errors.append(("INVALID_UOM", f"UOM to match Infor '{validated_uom}' not found in valid UOM reference"))

        # --- QOE ---
        qoe_val, qoe_err = _parse_qoe(item.qoe)
        if qoe_err:
            item_errors.append(("INVALID_QOE", qoe_err))

        # --- QOE/UOM compatibility ---
        if qoe_val and validated_uom:
            for etype, edetail, severity in _check_qoe_uom_compat(validated_uom, qoe_val):
                if severity == "ERROR":
                    item_errors.append((etype, edetail))
                else:
                    item_warnings.append((etype, edetail))

        # --- Price ---
        price_val, price_err = _parse_price(item.unit_price)
        if price_err:
            item_errors.append(("INVALID_PRICE", price_err))

        # --- Null checks ---
        if not clean_mfg:
            item_errors.append(("NULL_MFG_NUM", "Manufacturer catalog number is required"))
        if not clean_desc:
            item_errors.append(("NULL_DESCRIPTION", "Description is required"))
        if not validated_uom:
            item_errors.append(("NULL_UOM", "UOM is required"))

        # --- Reduced catalog numbers ---
        reduced_mfg = reduce_catalog_number(clean_mfg)
        reduced_vendor = reduce_catalog_number(clean_vendor)

        # --- Duplicate detection ---
        row_ref = item.file_row or item.item_id
        mfg_result, mfg_issue = "pass", None
        if precheck_mode != "distributor":
            mfg_result, mfg_issue = _check_mfg_dup(
                reduced_mfg, validated_uom, clean_mfg, row_ref, item.item_id, seen_mfg,
                dup_groups, dup_warn_groups, precheck_mode=precheck_mode,
            )

        if precheck_mode == "distributor":
            vendor_result, vendor_issue = _check_vendor_dup(
                reduced_vendor, clean_vendor, row_ref, item.item_id, seen_vendor,
                dup_groups, dup_warn_groups,
            )
            dup_errors = [i for r, i in [(vendor_result, vendor_issue)] if r == "error" and i]
            dup_warns  = [i for r, i in [(vendor_result, vendor_issue)] if r == "warn" and i]
            if dup_errors:
                item_errors.extend(dup_errors)
                item_errors.extend(dup_warns)
            elif dup_warns:
                item_warnings.extend(dup_warns)
        else:
            # Manufacturer: only mfg+UOM check
            if mfg_result == "error":
                item_errors.append(mfg_issue)
            elif mfg_result == "warn":
                item_warnings.append(mfg_issue)

        # --- Record errors/warnings and buffer the writes ---
        all_issues = item_errors + item_warnings
        # Cleaned fields are written for every item regardless of outcome.
        pending_field_updates.append({
            "item_id": item.item_id,
            "description": clean_desc,
            "mfg_catalog_num": clean_mfg,
            "vendor_catalog_num": clean_vendor,
            "uom": std_uom,
            "uom_to_match_infor": uom_to_match_infor or None,
            "qoe": qoe_val or item.qoe,
            "reduced_mfg_num": reduced_mfg,
            "reduced_vendor_num": reduced_vendor,
        })

        if item_errors:
            failed_ids.append(item.item_id)
            pending_status_updates[item.item_id] = {
                "item_id": item.item_id,
                "status": Status.ERROR_PC1,
                "error_message": "; ".join(e[1] for e in item_errors),
            }
            for err_type, err_detail in all_issues:
                _record_issue(item.item_id, err_type, err_detail)
        elif item_warnings:
            warned_ids.append(item.item_id)
            pending_status_updates[item.item_id] = {
                "item_id": item.item_id,
                "status": Status.WARN_PC1,
                "error_message": None,
            }
            for wtype, wdetail in item_warnings:
                _record_issue(item.item_id, wtype, wdetail)
        else:
            passed_ids.append(item.item_id)
            pending_status_updates[item.item_id] = {
                "item_id": item.item_id,
                "status": Status.PASSED_PC1,
                "error_message": None,
            }

    # --- Post-loop: mark ALL members of each dup group as ERROR_PC1 ---
    # The second+ occurrence already got ERROR_PC1 in the per-item loop above.
    # This pass catches the **first** occurrence (originally PASSED/WARN)
    # and then unifies the error_detail for every member so they all show
    # the same "row X, Y, Z" listing.
    item_by_id = {i.item_id: i for i in items}

    for _gkey, group_ids in dup_groups.items():
        # Find the error_type used for items already in this group
        dup_type = None
        for eid in group_ids:
            for e in errors:
                if e["item_id"] == eid and e["error_type"].startswith("DUPLICATE"):
                    dup_type = e["error_type"]
                    break
            if dup_type:
                break
        dup_type = dup_type or "DUPLICATE"

        # Build the unified detail with file rows
        sorted_ids = sorted(group_ids)
        file_rows = []
        for mid in sorted_ids:
            obj = item_by_id.get(mid)
            file_rows.append(str(obj.file_row if obj and obj.file_row else mid))
        unified_detail = f"Duplicate {_dup_type_display(dup_type)} - row {', '.join(file_rows)}"

        # Ensure every member has at least one dup error record. The records
        # haven't been written to the DB yet — we mutate the buffers in place.
        for mid in group_ids:
            if any(e["item_id"] == mid and e["error_type"].startswith("DUPLICATE") for e in errors):
                continue
            _record_issue(mid, dup_type, unified_detail)
            pending_status_updates[mid] = {
                "item_id": mid,
                "status": Status.ERROR_PC1,
                "error_message": unified_detail,
            }
            if mid in passed_ids:
                passed_ids.remove(mid)
            elif mid in warned_ids:
                warned_ids.remove(mid)
            if mid not in failed_ids:
                failed_ids.append(mid)

        # Unify ALL dup details (in-memory error list + pending DB records)
        for e in errors:
            if e["item_id"] in group_ids and e["error_type"].startswith("DUPLICATE"):
                e["error_detail"] = unified_detail
        for r in pending_error_records:
            if r["item_id"] in group_ids and (r.get("error_type") or "").startswith("DUPLICATE"):
                r["error_detail"] = unified_detail

    # --- Post-loop: back-patch dup-WARNING groups so every participating row
    # carries the same warning record. Errors take precedence — any member
    # already promoted to ERROR_PC1 above is excluded so we never overwrite an
    # error record or downgrade a status. The unified detail enumerates the
    # warn-only members so the API groups them by (error_type, error_detail).
    error_member_ids: set[int] = set()
    for ids in dup_groups.values():
        error_member_ids.update(ids)

    for _wkey, warn_ids in dup_warn_groups.items():
        warn_only_ids = [wid for wid in dict.fromkeys(warn_ids) if wid not in error_member_ids]
        if len(warn_only_ids) < 2:
            # Single-member groups offer no navigation value and would only
            # introduce a stray back-patched record on the first occurrence.
            continue

        warn_type = None
        for wid in warn_only_ids:
            for e in errors:
                if (
                    e["item_id"] == wid
                    and (e["error_type"] or "").startswith("DUPLICATE")
                    and e["error_type"] not in {"DUPLICATE_MFG_DEFAULT", "DUPLICATE_MFG_STRICT",
                                                  "DUPLICATE_MFG_UOM_EXPLICIT", "DUPLICATE_VENDORITEM"}
                ):
                    warn_type = e["error_type"]
                    break
            if warn_type:
                break
        if not warn_type:
            continue

        sorted_warn_ids = sorted(warn_only_ids)
        warn_file_rows = []
        for wid in sorted_warn_ids:
            obj = item_by_id.get(wid)
            warn_file_rows.append(str(obj.file_row if obj and obj.file_row else wid))
        unified_warn_detail = (
            f"Reduced {_dup_type_display(warn_type)} - "
            f"rows {', '.join(warn_file_rows)} (full catalog values differ — verify these are not duplicates)"
        )

        for wid in sorted_warn_ids:
            has_warn_record = any(
                e["item_id"] == wid and e["error_type"] == warn_type for e in errors
            )
            if not has_warn_record:
                _record_issue(wid, warn_type, unified_warn_detail)
                # Promote PASSED → WARN; never overwrite an existing error.
                if wid in passed_ids:
                    passed_ids.remove(wid)
                if wid not in warned_ids and wid not in failed_ids:
                    warned_ids.append(wid)
                    pending_status_updates[wid] = {
                        "item_id": wid,
                        "status": Status.WARN_PC1,
                        "error_message": None,
                    }

        for e in errors:
            if e["item_id"] in sorted_warn_ids and e["error_type"] == warn_type:
                e["error_detail"] = unified_warn_detail
        for r in pending_error_records:
            if r["item_id"] in sorted_warn_ids and r.get("error_type") == warn_type:
                r["error_detail"] = unified_warn_detail

    # --- Flush all buffered writes ---
    # Three round-trips replace the per-row writes that previously dominated
    # PC1 runtime on large files (~25k → 3 calls for a 5k-row task).
    task_repo.update_items_bulk(pending_field_updates)
    task_repo.bulk_update_item_statuses(list(pending_status_updates.values()))
    task_repo.add_precheck_errors_bulk(pending_error_records)

    # Build dup_groups summary for the response (UI uses it for click-to-filter)
    dup_groups_out = []
    for _gkey, group_ids in dup_groups.items():
        dup_type = None
        for eid in group_ids:
            for e in errors:
                if e["item_id"] == eid and e["error_type"].startswith("DUPLICATE"):
                    dup_type = e["error_type"]
                    break
            if dup_type:
                break
        dup_groups_out.append({"error_type": dup_type or "DUPLICATE", "item_ids": sorted(group_ids)})

    # Tallies
    total = len(items)
    passed = len(passed_ids)
    warned = len(warned_ids)
    failed = len(failed_ids)

    state["clean_items"] = [{"item_id": i} for i in passed_ids]
    state["warned_items"] = [{"item_id": i} for i in warned_ids]
    state["pc1_errors"] = errors

    # ----- Update pc1_passed_modes based on this run's outcome -----
    # The list records every PC1 mode that has finished with a fully clean
    # outcome since the last data change. Used by the UI to know what's
    # already been validated and by the DISTRIBUTOR auto-chain to decide
    # whether the distributor pass still needs to run.
    passed_modes = list(state.get("pc1_passed_modes") or [])
    clean_run = (failed == 0 and warned == 0 and passed == total and total > 0)
    if clean_run:
        if precheck_mode not in passed_modes:
            passed_modes.append(precheck_mode)
    else:
        passed_modes = [m for m in passed_modes if m != precheck_mode]
    state["pc1_passed_modes"] = passed_modes

    required_modes = required_pc1_modes(task)
    missing_modes = [m for m in required_modes if m not in passed_modes]

    # ----- DISTRIBUTOR auto-chain -----
    # A clean default pass on a DISTRIBUTOR contract has only validated
    # mfg-side dups. Vendor-side dups need the distributor mode pass too,
    # but that's a system concern, not the user's — chain straight into it
    # so they see one combined outcome from a single click. Guarded on
    # ``precheck_mode == "default"`` so we never recurse out of distributor
    # mode (preventing infinite loops if vendor checks fail).
    if (clean_run
            and is_distributor
            and precheck_mode == "default"
            and "distributor" not in passed_modes):
        state_machine.save_state(task_id, state)
        # Persist distributor as the task's saved mode so the dropdown
        # reflects what was actually last validated, and so an audit / log
        # reader can tell that vendor-side checks ran. mode_override drives
        # the recursion regardless, but keeping the two in sync avoids
        # surprises on the next page load.
        task_repo.update_task_fields(task_id, precheck_mode="distributor")
        return run_precheck(task_id, state_machine, mode_override="distributor")

    # ----- Determine task status + auto-advance logic -----
    # Auto-advance only fires for DISTRIBUTOR when the *terminal* distributor
    # mode finishes clean (typically as the second half of the default →
    # distributor chain above). MANUFACTURER tasks never auto-advance — the
    # user explicitly chooses whether to proceed after default or to drill
    # into strict / explicit first, so we leave them in PENDING_NUVIA and
    # let them click "Advance to Identity" themselves.
    should_auto_advance = (
        clean_run
        and is_distributor
        and precheck_mode == "distributor"
    )
    state["pc1_passed"] = should_auto_advance
    if should_auto_advance:
        state_machine.save_state(task_id, state)
        state_machine.advance(task_id, Phase.IDENTITY, changed_by="system",
                              notes=f"DISTRIBUTOR PC1 clean (modes {passed_modes}) — auto-advanced")
        task_status = "AUTO_ADVANCED"
    elif clean_run:
        # Clean PC1 run but no auto-advance — user picks the next move.
        # Hits in two cases:
        #   - MANUFACTURER on any clean run (default / strict / explicit).
        #   - DISTRIBUTOR running distributor when default-side hasn't been
        #     run yet (rare; UI normally chains from default).
        state["status"] = Status.PENDING_NUVIA
        state_machine.save_state(task_id, state)
        task_repo.update_task_phase(task_id, Phase.INTAKE, Status.PENDING_NUVIA)
        task_status = Status.PENDING_NUVIA
    elif failed == 0 and warned > 0:
        # Only warnings, no errors → PENDING_NUVIA (user must manually pass or fix)
        state["status"] = Status.PENDING_NUVIA
        state_machine.save_state(task_id, state)
        task_repo.update_task_phase(task_id, Phase.INTAKE, Status.PENDING_NUVIA)
        task_status = Status.PENDING_NUVIA
    elif passed > 0 or warned > 0:
        # Mixed: some passed/warned + some failed → ON_HOLD_PC1
        state["status"] = Status.ON_HOLD_PC1
        state_machine.save_state(task_id, state)
        task_repo.update_task_phase(task_id, Phase.INTAKE, Status.ON_HOLD_PC1)
        task_status = Status.ON_HOLD_PC1
    else:
        # All failed
        state["status"] = Status.ON_HOLD_PC1
        state_machine.save_state(task_id, state)
        task_repo.update_task_phase(task_id, Phase.INTAKE, Status.ON_HOLD_PC1)
        task_status = Status.ON_HOLD_PC1

    uom_mappings = [
        {"from": k[0], "to": k[1], "count": v}
        for k, v in sorted(uom_mapping_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    uom_to_match_mappings = [
        {"from": k[0], "to": k[1], "count": v}
        for k, v in sorted(uom_to_match_mapping_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    return {
        "total": total,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "header_errors": header_error_count,
        "task_status": task_status,
        "errors": errors,
        "uom_mappings": uom_mappings,
        "uom_to_match_mappings": uom_to_match_mappings,
        "dup_groups": dup_groups_out,
        "precheck_mode": precheck_mode,
        "required_modes": required_modes,
        "pc1_passed_modes": passed_modes,
        "missing_modes": missing_modes,
    }


def _spawn_error_pc1_subtask(parent_task, error_items: list, user: str) -> str:
    """Create a sub-task for ERROR_PC1 items split off the parent at advance time.

    Items keep their item_id and ERROR_PC1 status; their PC1 PreCheckError
    rows are re-tasked alongside them so the new task surfaces the existing
    diagnoses. The sub-task starts in INTAKE / ON_HOLD_PC1 so the user can fix
    and re-run PC1 inside it.
    """
    parent_notes = parent_task.notes or ""
    sub_notes = f"Split from {parent_task.task_id} due to PC1 errors at advance time."
    if parent_notes:
        sub_notes = sub_notes + "\n\n" + parent_notes

    sub_task = task_repo.create_task(
        intake_mode=parent_task.intake_mode,
        contract_number=parent_task.contract_number,
        vendor_id=parent_task.vendor_id,
        purchase_from_loc=parent_task.purchase_from_loc,
        erp_vendor_name=parent_task.erp_vendor_name,
        purchase_from_loc_name=parent_task.purchase_from_loc_name,
        process_type=parent_task.process_type,
        source_type=parent_task.source_type,
        organization=parent_task.organization,
        oem_name=parent_task.oem_name,
        intention=parent_task.intention,
        mixed_intention=parent_task.mixed_intention,
        contract_start_date=parent_task.contract_start_date,
        contract_end_date=parent_task.contract_end_date,
        notes=sub_notes,
        wrike_id=parent_task.wrike_id,
        created_by=user,
        parent_task_id=parent_task.task_id,
        spawn_reason=Reason.REASON_ERROR_PC1_SPLIT,
        phase=Phase.INTAKE,
        status=Status.ON_HOLD_PC1,
    )

    error_ids = [i.item_id for i in error_items]
    task_repo.move_items_to_task(error_ids, sub_task.task_id, move_pc1_errors=True)

    task_repo.add_status_log(
        task_id=sub_task.task_id,
        old_phase=None,
        new_phase=Phase.INTAKE,
        old_status=None,
        new_status=Status.ON_HOLD_PC1,
        changed_by=user,
        notes=f"Spawned from {parent_task.task_id} carrying {len(error_ids)} {Status.ERROR_PC1} item(s).",
    )
    return sub_task.task_id


def proceed_with_passing(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """User explicitly chooses to advance passing items to Phase 2.

    Rules:
      - WARN_PC1 items must be resolved (manually pass or fix to PASSED_PC1)
        before advance is allowed, regardless of contract source type.
      - PREMIER contracts: blocked if any ERROR_PC1 items remain.
      - LOCAL contracts: ERROR_PC1 items are split off into a new sub-task
        (see _spawn_error_pc1_subtask). Only PASSED_PC1 items carry forward.

    Items reaching IDENTITY are guaranteed to be in PASSED_PC1 status.
    """
    task = task_repo.get_task(task_id)
    if not task:
        raise ValueError("Task not found")

    all_items = task_repo.get_items(task_id)
    live_items = [i for i in all_items if (i.status or "") not in Status.DELETED_STATUSES]

    # Zero-viable guard takes precedence over the "no passed items" message —
    # a task whose every row was soft-deleted has nothing to advance, period.
    if not live_items:
        state = state_machine.get_state(task_id)
        msg = "Cannot advance to Identity: task has 0 viable items to move forward (all rows soft-deleted)."
        task_repo.add_status_log(
            task_id=task_id,
            old_phase=Phase.INTAKE,
            new_phase=Phase.INTAKE,
            old_status=state.get("status"),
            new_status=state.get("status"),
            changed_by=user,
            notes=msg,
        )
        raise ValueError(msg)

    passed_items = [i for i in live_items if i.status == Status.PASSED_PC1]
    error_items = [i for i in live_items if i.status == Status.ERROR_PC1]
    warn_items = [i for i in live_items if i.status == Status.WARN_PC1]

    if not passed_items:
        raise ValueError(
            f"No items have passed PC1 yet "
            f"({len(error_items)} error(s), {len(warn_items)} warning(s) outstanding). "
            "Resolve or pass them before advancing."
        )

    if warn_items:
        raise ValueError(
            f"{len(warn_items)} item(s) still in {Status.WARN_PC1}. Resolve every warning "
            f"(fix the item or manually pass it) before advancing to Identity."
        )

    source_type = (task.source_type or "").upper()
    if source_type == "PREMIER" and error_items:
        raise ValueError(
            f"PREMIER contracts require all items to pass PC1. "
            f"{len(error_items)} item(s) still have errors."
        )

    # The mode-pass gate was removed deliberately: the user has already
    # cleared every error and manually accepted every warning, which is the
    # contract for advancing. The DISTRIBUTOR auto-chain in ``run_precheck``
    # still runs ``distributor`` automatically on a clean default, so the
    # typical happy path validates vendor-side dups before this point. When
    # a user advances after manually passing warnings they are explicitly
    # taking that decision; we don't second-guess it here.

    sub_task_id = None
    if error_items and source_type != "PREMIER":
        sub_task_id = _spawn_error_pc1_subtask(task, error_items, user)

    state = state_machine.get_state(task_id)
    state["pc1_passed"] = True
    # Refresh clean_items so it reflects only items still on this task.
    state["clean_items"] = [{"item_id": i.item_id} for i in passed_items]
    state_machine.save_state(task_id, state)

    new_state = state_machine.advance(
        task_id,
        Phase.IDENTITY,
        changed_by=user,
        notes=(
            f"PC1 passed, advancing to Identity (split {len(error_items)} {Status.ERROR_PC1} "
            f"item(s) into sub-task {sub_task_id})"
            if sub_task_id
            else "PC1 passed, advancing to Identity"
        ),
    )
    return {
        "phase": new_state["phase"],
        "status": new_state["status"],
        "passed_count": len(passed_items),
        "split_count": len(error_items) if sub_task_id else 0,
        "sub_task_id": sub_task_id,
    }


def recheck_items(task_id: str, item_ids: list[int], state_machine: TaskStateMachine) -> dict:
    """Re-run PC1 on the full item set.

    ``item_ids`` is accepted for backward-compatibility but ignored — run_precheck
    always resets and processes all items so duplicate detection is never partial.
    """
    return run_precheck(task_id, state_machine)


def manually_pass_item(task_id: str, item_id: int, user: str) -> dict:
    """Manually pass a WARN_PC1 item, logging who approved it and when.

    Resolves all associated PreCheckErrors and sets item status to PASSED_PC1.
    """
    item = None
    items = task_repo.get_items(task_id)
    for i in items:
        if i.item_id == item_id:
            item = i
            break
    if not item:
        raise ValueError(f"Item {item_id} not found in task {task_id}")
    if item.status != Status.WARN_PC1:
        raise ValueError(f"Item {item_id} is not in {Status.WARN_PC1} status (current: {item.status})")

    # Mark item as passed
    task_repo.update_item_status(item_id, Status.PASSED_PC1)

    # Resolve all unresolved warnings for this item
    errors = task_repo.get_precheck_errors(task_id, phase="PC1", resolved=False)
    for e in errors:
        if e.item_id == item_id:
            task_repo.resolve_precheck_error(e.error_id, resolved_by=user)

    return {"item_id": item_id, "new_status": Status.PASSED_PC1, "approved_by": user}


def bulk_manually_pass_items(task_id: str, item_ids: list[int], user: str) -> dict:
    """Manually pass several WARN_PC1 items at once.

    Validates that every requested item is currently in WARN_PC1; if any
    aren't, raises ValueError listing the offenders so the caller can show a
    coherent message rather than partially-applying the change.

    Bulk-updates statuses + resolves all unresolved PC1 errors for the
    affected items in two queries instead of N per-item round-trips.
    """
    if not item_ids:
        raise ValueError("No item_ids supplied")
    # De-dupe while preserving order so the response message reflects what
    # the user actually clicked.
    unique_ids: list[int] = []
    seen: set[int] = set()
    for i in item_ids:
        if i not in seen:
            unique_ids.append(int(i))
            seen.add(int(i))

    items = task_repo.get_items(task_id)
    by_id = {i.item_id: i for i in items}

    not_found = [i for i in unique_ids if i not in by_id]
    if not_found:
        raise ValueError(f"Item(s) not found in task {task_id}: {not_found}")

    bad_status = [i for i in unique_ids if by_id[i].status != Status.WARN_PC1]
    if bad_status:
        raise ValueError(
            f"Bulk-pass requires every selected item to be in {Status.WARN_PC1}. "
            f"These were not: {bad_status}"
        )

    status_updates = [
        {"item_id": iid, "status": Status.PASSED_PC1, "error_message": None}
        for iid in unique_ids
    ]
    task_repo.bulk_update_item_statuses(status_updates)
    task_repo.bulk_resolve_precheck_errors_for_items(
        task_id, phase="PC1", item_ids=unique_ids, resolved_by=user,
    )

    return {
        "passed_count": len(unique_ids),
        "item_ids": unique_ids,
        "approved_by": user,
    }


def update_item_fields(task_id: str, item_id: int, fields: dict) -> dict:
    """Update editable fields on an ERROR_PC1 or WARN_PC1 item (in-place editing).

    Allowed fields: mfg_catalog_num, vendor_catalog_num, description, uom, qoe, unit_price.
    """
    ALLOWED_FIELDS = {"mfg_catalog_num", "vendor_catalog_num", "description", "uom", "qoe", "unit_price"}
    EDITABLE_STATUSES = {Status.ERROR_PC1, Status.WARN_PC1}
    filtered = {k: v for k, v in fields.items() if k in ALLOWED_FIELDS}
    if not filtered:
        raise ValueError("No valid fields to update")

    item = None
    items = task_repo.get_items(task_id)
    for i in items:
        if i.item_id == item_id:
            item = i
            break
    if not item:
        raise ValueError(f"Item {item_id} not found in task {task_id}")
    if item.status not in EDITABLE_STATUSES:
        raise ValueError(f"Item {item_id} is not in an editable status (current: {item.status})")

    task_repo.update_items_bulk([item_id], **filtered)
    return {"item_id": item_id, "updated_fields": list(filtered.keys())}
