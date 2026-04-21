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

from ..db import task_repo, workstate_repo
from ..db.engine import get_sqlserver_engine
from ..db.sql_loader import load_query
from ..state import TaskStateMachine, Phase, Status

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
#   default   — reduced_mfg only (catches aaa-bb = aaabb)
#   strict    — exact Mfg Part Num only (aaa-bb ≠ aaabb)
#   explicit  — exact Mfg Part Num + UOM (aaa-bb BX ≠ aaa-bb CA)
#   distributor — vendor_id_short + reduced_vendor_catalog_num

def _check_mfg_dup(
    reduced_mfg: str,
    std_uom: str,
    clean_mfg: str,
    row_ref,
    item_id: int,
    seen: dict,
    dup_groups: dict,
    precheck_mode: str = "default",
) -> tuple[str, Optional[tuple[str, str]]]:
    """Check Mfg Cat # for duplicates using mode-specific keys.

    When a duplicate ERROR is found the current item is added to the same
    ``dup_groups[key]`` list as the original so every member shares one group.

    Returns ('pass'|'warn'|'error', (error_type, detail) | None).
    """
    if not reduced_mfg and not clean_mfg:
        return "pass", None

    if precheck_mode == "strict":
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
        if reduced_mfg and reduced_mfg != key:
            reduced_key = f"_reduced_{reduced_mfg}"
            if reduced_key in seen:
                prev_row, prev_clean, _ = seen[reduced_key]
                if prev_clean != clean_mfg:
                    return "warn", (
                        "DUPLICATE_MFG_REDUCED_HINT",
                        f"Reduced Mfg Cat matches file row {prev_row} ('{prev_clean}') but exact Mfg Cat differs — strict mode allows this",
                    )
            seen[reduced_key] = (row_ref, clean_mfg, item_id)
        return "pass", None

    elif precheck_mode == "explicit":
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
        if reduced_mfg:
            reduced_key = f"{reduced_mfg}|{std_uom or ''}"
            if reduced_key != key and reduced_key in seen:
                prev_row, prev_clean, _ = seen[reduced_key]
                if prev_clean != clean_mfg:
                    return "warn", (
                        "DUPLICATE_MFG_UOM_REDUCED_HINT",
                        f"Reduced Mfg Cat + UOM matches file row {prev_row} ('{prev_clean}') but exact Mfg Cat differs — explicit mode allows this",
                    )
            if reduced_key != key:
                seen[reduced_key] = (row_ref, clean_mfg, item_id)
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
            return "warn", (
                "DUPLICATE_MFG_REDUCED",
                f"Reduced Mfg Cat matches file row {prev_row} but full Mfg Cat differs — verify these are not duplicates",
            )
        seen[key] = (row_ref, clean_mfg, item_id)
        return "pass", None


def _check_vendor_dup(
    reduced_vendor: str,
    clean_vendor: str,
    row_ref,
    item_id: int,
    seen: dict,
    dup_groups: dict,
) -> tuple[str, Optional[tuple[str, str]]]:
    """Check Vendor Cat # for duplicates against items already seen.

    Returns ('pass'|'warn'|'error', (error_type, detail) | None).
    Registers this item in ``seen`` when it is the first occurrence.
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
                "DUPLICATE_VENDOR",
                f"Duplicate Vendor Cat # — dup group {dup_groups[vkey]}",
            )
        return "warn", (
            "DUPLICATE_VENDOR_REDUCED",
            f"Reduced Vendor Cat # matches file row {prev_row} but full Vendor Cat differs — verify these are not duplicates",
        )
    seen[reduced_vendor] = (row_ref, clean_vendor, item_id)
    return "pass", None


# ---------------------------------------------------------------------------
# Pre-check PC1 — main entry point
# ---------------------------------------------------------------------------
def run_precheck(task_id: str, state_machine: TaskStateMachine) -> dict:
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
    items = [i for i in all_items if i.status != "DELETED_PC1"]
    if not items:
        return {"total": 0, "passed": 0, "failed": 0, "errors": [], "uom_mappings": []}

    # Reset active items to UPLOADED and clear unresolved PC1 errors so we start
    # from a clean slate every time (prevents dissolving duplicate detection).
    all_ids = [i.item_id for i in items]
    for iid in all_ids:
        task_repo.update_item_status(iid, "UPLOADED", error_message=None)

    existing_errors = task_repo.get_precheck_errors(task_id, phase="PC1", resolved=False)
    for e in existing_errors:
        task_repo.resolve_precheck_error(e.error_id, resolved_by="RECHECK")

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
    uom_mappings = []
    uom_to_match_mappings = []
    passed_ids = []
    warned_ids = []
    failed_ids = []
    header_error_count = 0

    # --- Header-level validation (task fields) ---
    if task.vendor_id:
        base_vendor, full_vendor = _parse_vendor_id(task.vendor_id)
        if not base_vendor:
            task_repo.add_precheck_error(
                task_id, None, "PC1",
                "INVALID_VENDOR_FORMAT",
                f"Task vendor ID '{task.vendor_id}' does not match format NNNNNNN or NNNNNNN-BNNN",
            )
            errors.append({"item_id": None, "error_type": "INVALID_VENDOR_FORMAT",
                           "error_detail": f"Task vendor ID '{task.vendor_id}' does not match format NNNNNNN or NNNNNNN-BNNN"})
            header_error_count += 1
        else:
            # Check the full vendor ID (or base if no location suffix) against PurchaseVendorLocation
            check_id = full_vendor if full_vendor and "-" in full_vendor else base_vendor
            if check_id not in valid_erp_ids:
                task_repo.add_precheck_error(
                    task_id, None, "PC1",
                    "VENDOR_NOT_FOUND",
                    f"ERP Vendor ID '{check_id}' not found in active PurchaseVendorLocation",
                )
                errors.append({"item_id": None, "error_type": "VENDOR_NOT_FOUND",
                               "error_detail": f"ERP Vendor ID '{check_id}' not found in active PurchaseVendorLocation"})
                header_error_count += 1

    # For duplicate detection: build indexes as we go
    # Values store (file_row, clean_value, item_id) so we can back-patch the original on a hit
    seen_mfg: dict[str, tuple[int, str, int]] = {}        # key depends on precheck_mode
    seen_vendor: dict[str, tuple[int, str, int]] = {}     # reduced_vendor -> (file_row, clean_vendor, item_id)
    # dup_groups maps a dup-key to the list of ALL item_ids that share that key.
    # After the per-item loop we do a single pass to mark every member ERROR_PC1.
    dup_groups: dict[str, list[int]] = {}

    precheck_mode = (task.precheck_mode or "default").lower()
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
            uom_mappings.append({"item_id": item.item_id, "from": item.uom, "to": std_uom})
        if std_uom and uom_to_match_infor and uom_to_match_infor != std_uom:
            uom_to_match_mappings.append({"item_id": item.item_id, "from": std_uom, "to": uom_to_match_infor})

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
                dup_groups, precheck_mode=precheck_mode,
            )

        if precheck_mode == "distributor":
            vendor_result, vendor_issue = _check_vendor_dup(
                reduced_vendor, clean_vendor, row_ref, item.item_id, seen_vendor,
                dup_groups,
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

        # --- Record errors/warnings and update item ---
        all_issues = item_errors + item_warnings
        if item_errors:
            failed_ids.append(item.item_id)
            task_repo.update_item_status(item.item_id, "ERROR_PC1", "; ".join(e[1] for e in item_errors))
            task_repo.update_items_bulk(
                [item.item_id],
                description=clean_desc,
                mfg_catalog_num=clean_mfg,
                vendor_catalog_num=clean_vendor,
                uom=std_uom,
                uom_to_match_infor=uom_to_match_infor or None,
                qoe=qoe_val or item.qoe,
                reduced_mfg_num=reduced_mfg,
                reduced_vendor_num=reduced_vendor,
            )
            for err_type, err_detail in all_issues:
                task_repo.add_precheck_error(task_id, item.item_id, "PC1", err_type, err_detail)
                errors.append({"item_id": item.item_id, "error_type": err_type, "error_detail": err_detail})
        elif item_warnings:
            warned_ids.append(item.item_id)
            task_repo.update_item_status(item.item_id, "WARN_PC1")
            for wtype, wdetail in item_warnings:
                task_repo.add_precheck_error(task_id, item.item_id, "PC1", wtype, wdetail)
                errors.append({"item_id": item.item_id, "error_type": wtype, "error_detail": wdetail})
            # Still update cleaned fields for warned items
            task_repo.update_items_bulk(
                [item.item_id],
                description=clean_desc,
                mfg_catalog_num=clean_mfg,
                vendor_catalog_num=clean_vendor,
                uom=std_uom,
                uom_to_match_infor=uom_to_match_infor or None,
                qoe=qoe_val or item.qoe,
                reduced_mfg_num=reduced_mfg,
                reduced_vendor_num=reduced_vendor,
            )
        else:
            passed_ids.append(item.item_id)
            task_repo.update_item_status(item.item_id, "PASSED_PC1")
            # Update cleaned fields
            task_repo.update_items_bulk(
                [item.item_id],
                description=clean_desc,
                mfg_catalog_num=clean_mfg,
                vendor_catalog_num=clean_vendor,
                uom=std_uom,
                uom_to_match_infor=uom_to_match_infor or None,
                qoe=qoe_val or item.qoe,
                reduced_mfg_num=reduced_mfg,
                reduced_vendor_num=reduced_vendor,
            )

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
        unified_detail = f"Duplicate {dup_type.replace('DUPLICATE_', '').replace('_', ' ').title()} - row {', '.join(file_rows)}"

        # Ensure every member has at least one dup error record
        for mid in group_ids:
            if any(e["item_id"] == mid and e["error_type"].startswith("DUPLICATE") for e in errors):
                continue
            task_repo.add_precheck_error(task_id, mid, "PC1", dup_type, unified_detail)
            errors.append({"item_id": mid, "error_type": dup_type, "error_detail": unified_detail})
            task_repo.update_item_status(mid, "ERROR_PC1", unified_detail)
            if mid in passed_ids:
                passed_ids.remove(mid)
            elif mid in warned_ids:
                warned_ids.remove(mid)
            if mid not in failed_ids:
                failed_ids.append(mid)

        # Unify ALL dup error details (in-memory + DB) to the same string
        for e in errors:
            if e["item_id"] in group_ids and e["error_type"].startswith("DUPLICATE"):
                e["error_detail"] = unified_detail
        task_repo.update_dup_error_details(task_id, list(group_ids), unified_detail)

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
    state["pc1_passed"] = (failed == 0 and warned == 0 and passed == total and total > 0)

    # ----- Determine task status + auto-advance logic -----
    if passed == total and total > 0:
        # All items passed cleanly → auto-advance to IDENTITY
        state["pc1_passed"] = True
        state_machine.save_state(task_id, state)
        state_machine.advance(task_id, Phase.IDENTITY, changed_by="system",
                              notes="All items passed PC1 — auto-advanced")
        task_status = "AUTO_ADVANCED"
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
    }


def proceed_with_passing(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """User explicitly chooses to advance passing items to Phase 2.

    LOCAL contracts: allowed to proceed even if some items failed/warned.
    PREMIER contracts: blocked unless all items passed (no errors/warnings).
    """
    task = task_repo.get_task(task_id)
    if not task:
        raise ValueError("Task not found")

    state = state_machine.get_state(task_id)
    passed_count = len(state.get("clean_items", []))
    if passed_count == 0:
        raise ValueError("No items passed PC1. Cannot proceed.")

    # PREMIER contracts must have ALL items passed before advancing
    source_type = (task.source_type or "").upper()
    all_items = task_repo.get_items(task_id)
    failed_or_warned = [i for i in all_items if i.status in ("ERROR_PC1", "WARN_PC1")]
    if source_type == "PREMIER" and failed_or_warned:
        raise ValueError(
            f"PREMIER contracts require all items to pass PC1. "
            f"{len(failed_or_warned)} item(s) still have errors or warnings."
        )

    state["pc1_passed"] = True
    state_machine.save_state(task_id, state)

    # Advance to IDENTITY phase
    new_state = state_machine.advance(task_id, Phase.IDENTITY, changed_by=user, notes="PC1 passed, advancing to Identity")
    return {"phase": new_state["phase"], "status": new_state["status"], "passed_count": passed_count}


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
    if item.status != "WARN_PC1":
        raise ValueError(f"Item {item_id} is not in WARN_PC1 status (current: {item.status})")

    # Mark item as passed
    task_repo.update_item_status(item_id, "PASSED_PC1")

    # Resolve all unresolved warnings for this item
    errors = task_repo.get_precheck_errors(task_id, phase="PC1", resolved=False)
    for e in errors:
        if e.item_id == item_id:
            task_repo.resolve_precheck_error(e.error_id, resolved_by=user)

    return {"item_id": item_id, "new_status": "PASSED_PC1", "approved_by": user}


def update_item_fields(task_id: str, item_id: int, fields: dict) -> dict:
    """Update editable fields on an ERROR_PC1 or WARN_PC1 item (in-place editing).

    Allowed fields: mfg_catalog_num, vendor_catalog_num, description, uom, qoe, unit_price.
    """
    ALLOWED_FIELDS = {"mfg_catalog_num", "vendor_catalog_num", "description", "uom", "qoe", "unit_price"}
    EDITABLE_STATUSES = {"ERROR_PC1", "WARN_PC1"}
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
