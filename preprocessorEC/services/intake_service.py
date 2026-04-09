"""Intake service — Phase 1 business logic.

Handles: file parsing, input standardization, PC1 validation.
Pure Python, no Flask imports. Called by intake/routes.py.
Later: becomes a LangGraph node implementation.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
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
    "CASE": "CS",
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
    """Reduce a catalog number by stripping non-alphanumeric characters and upper-casing."""
    if not part_num:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(part_num).upper())


# ---------------------------------------------------------------------------
# Reference data loaders (cached per precheck run)
# ---------------------------------------------------------------------------
def _load_valid_uoms() -> set[str]:
    """Load valid UOM codes from MDM_EDI_SUB_UOM."""
    engine = get_sqlserver_engine()
    with engine.connect() as conn:
        rows = conn.execute(load_query("intake", "intake", query="get_valid_uoms")).fetchall()
    return {r[0] for r in rows if r[0]}


def _load_valid_vendors() -> set[str]:
    """Load active vendor codes from MDM_SUPPLIER_NAME_INFOR."""
    engine = get_sqlserver_engine()
    with engine.connect() as conn:
        rows = conn.execute(load_query("intake", "intake", query="get_valid_vendors")).fetchall()
    return {r[0] for r in rows if r[0]}


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


# ---------------------------------------------------------------------------
# Duplicate-detection helpers
# ---------------------------------------------------------------------------
def _check_mfg_uom_dup(
    reduced_mfg: str,
    std_uom: str,
    clean_mfg: str,
    row_ref,
    seen: dict,
) -> tuple[str, Optional[tuple[str, str]]]:
    """Check Mfg Cat # + UOM for duplicates against items already seen.

    Returns ('pass'|'warn'|'error', (error_type, detail) | None).
    Registers this item in `seen` when it is the first occurrence.
    """
    if not reduced_mfg or not std_uom:
        return "pass", None
    key = f"{reduced_mfg}|{std_uom}"
    if key in seen:
        prev_row, prev_clean = seen[key]
        if prev_clean == clean_mfg:
            return "error", (
                "DUPLICATE_MFG_UOM",
                f"Duplicate Mfg Cat + UOM — same as file row {prev_row}",
            )
        return "warn", (
            "DUPLICATE_MFG_UOM_REDUCED",
            f"Reduced Mfg Cat + UOM matches file row {prev_row} but full Mfg Cat differs — verify these are not duplicates",
        )
    seen[key] = (row_ref, clean_mfg)
    return "pass", None


def _check_vendor_dup(
    reduced_vendor: str,
    clean_vendor: str,
    row_ref,
    seen: dict,
) -> tuple[str, Optional[tuple[str, str]]]:
    """Check Vendor Cat # for duplicates against items already seen.

    Returns ('pass'|'warn'|'error', (error_type, detail) | None).
    Registers this item in `seen` when it is the first occurrence.
    """
    if not reduced_vendor:
        return "pass", None
    if reduced_vendor in seen:
        prev_row, prev_clean = seen[reduced_vendor]
        if prev_clean == clean_vendor:
            return "error", (
                "DUPLICATE_VENDOR",
                f"Duplicate Vendor Cat # — same as file row {prev_row}",
            )
        return "warn", (
            "DUPLICATE_VENDOR_REDUCED",
            f"Reduced Vendor Cat # matches file row {prev_row} but full Vendor Cat differs — verify these are not duplicates",
        )
    seen[reduced_vendor] = (row_ref, clean_vendor)
    return "pass", None


# ---------------------------------------------------------------------------
# Pre-check PC1 — main entry point
# ---------------------------------------------------------------------------
def run_precheck(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Run Phase 1 pre-check on all UPLOADED items for a task.

    Checks:
      1. Text cleaning + standardization
      2. UOM standardization (alias map) + validation against MDM_EDI_SUB_UOM
      3. QOE parsing + QOE/UOM compatibility
      4. Price parsing
      5. Null field checks (mfg cat, description, UOM)
      6. Duplicate detection (mfg+UOM for manufacturer source; mfg+UOM or vendor for distributor)
      7. Vendor ID validation against MDM_SUPPLIER_NAME_INFOR + InforVendorLocation

    Returns:
        {
            "total": int,
            "passed": int,
            "failed": int,
            "errors": [...],
            "uom_mappings": [...],
        }
    """
    items = task_repo.get_items(task_id, status="UPLOADED")
    if not items:
        return {"total": 0, "passed": 0, "failed": 0, "errors": [], "uom_mappings": []}

    task = task_repo.get_task(task_id)
    state = state_machine.get_state(task_id)

    # Load reference data once
    valid_uoms = _load_valid_uoms()
    valid_vendors = _load_valid_vendors()
    valid_erp_ids = _load_valid_erp_vendor_ids()

    source_type = (task.source_type or "").upper()
    process_type = (task.process_type or "").upper()
    is_distributor = "DISTRIBUTOR" in process_type

    errors = []
    uom_mappings = []
    passed_ids = []
    warned_ids = []
    failed_ids = []
    header_error_count = 0

    # --- Header-level validation (task fields, not item fields) ---
    # Resolve any stale header errors from a previous run before re-checking.
    existing_errors = task_repo.get_precheck_errors(task_id, phase="PC1", resolved=False)
    for _e in existing_errors:
        if _e.item_id is None:
            task_repo.resolve_precheck_error(_e.error_id, resolved_by="RECHECK")

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
            if base_vendor not in valid_vendors:
                task_repo.add_precheck_error(
                    task_id, None, "PC1",
                    "VENDOR_NOT_IN_MDM",
                    f"Vendor base '{base_vendor}' not found in MDM_SUPPLIER_NAME_INFOR",
                )
                errors.append({"item_id": None, "error_type": "VENDOR_NOT_IN_MDM",
                               "error_detail": f"Vendor base '{base_vendor}' not found in MDM_SUPPLIER_NAME_INFOR"})
                header_error_count += 1
            if full_vendor and "-" in full_vendor and full_vendor not in valid_erp_ids:
                task_repo.add_precheck_error(
                    task_id, None, "PC1",
                    "VENDOR_LOCATION_INVALID",
                    f"ERP Vendor ID '{full_vendor}' not found in active InforVendorLocation",
                )
                errors.append({"item_id": None, "error_type": "VENDOR_LOCATION_INVALID",
                               "error_detail": f"ERP Vendor ID '{full_vendor}' not found in active InforVendorLocation"})
                header_error_count += 1

    # For duplicate detection: build indexes as we go
    # Values store (file_row, clean_value) so we can distinguish exact vs reduced-only matches
    seen_mfg_uom: dict[str, tuple[int, str]] = {}   # "reduced_mfg|uom" -> (file_row, clean_mfg)
    seen_vendor: dict[str, tuple[int, str]] = {}     # reduced_vendor    -> (file_row, clean_vendor)

    for item in items:
        item_errors: list[tuple[str, str]] = []       # (type, detail)
        item_warnings: list[tuple[str, str]] = []     # (type, detail)

        # --- Text standardization ---
        clean_desc = _clean_text(item.description)
        clean_mfg = _clean_text(item.mfg_catalog_num) if item.mfg_catalog_num else ""
        clean_vendor = _clean_text(item.vendor_catalog_num) if item.vendor_catalog_num else ""

        # --- UOM standardization ---
        std_uom, uom_note = _standardize_uom(item.uom)
        if uom_note:
            uom_mappings.append({"item_id": item.item_id, "from": item.uom, "to": std_uom})

        # --- UOM validation against MDM ---
        if std_uom and std_uom not in valid_uoms:
            item_errors.append(("INVALID_UOM", f"UOM '{std_uom}' not found in MDM_EDI_SUB_UOM"))

        # --- QOE ---
        qoe_val, qoe_err = _parse_qoe(item.qoe)
        if qoe_err:
            item_errors.append(("INVALID_QOE", qoe_err))

        # --- QOE/UOM compatibility ---
        if qoe_val and std_uom:
            for etype, edetail, severity in _check_qoe_uom_compat(std_uom, qoe_val):
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
        if not std_uom:
            item_errors.append(("NULL_UOM", "UOM is required"))

        # --- Reduced catalog numbers ---
        reduced_mfg = reduce_catalog_number(clean_mfg)
        reduced_vendor = reduce_catalog_number(clean_vendor)

        # --- Duplicate detection ---
        row_ref = item.file_row or item.item_id
        mfg_result, mfg_issue = _check_mfg_uom_dup(
            reduced_mfg, std_uom, clean_mfg, row_ref, seen_mfg_uom
        )

        if is_distributor:
            vendor_result, vendor_issue = _check_vendor_dup(
                reduced_vendor, clean_vendor, row_ref, seen_vendor
            )
            # Gather issues by severity level
            dup_errors = [i for r, i in [(mfg_result, mfg_issue), (vendor_result, vendor_issue)] if r == "error" and i]
            dup_warns  = [i for r, i in [(mfg_result, mfg_issue), (vendor_result, vendor_issue)] if r == "warn"  and i]
            if dup_errors:
                # Any error → whole dup block is ERROR; escalate any concurrent warns too
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
                qoe=qoe_val or item.qoe,
                reduced_mfg_num=reduced_mfg,
                reduced_vendor_num=reduced_vendor,
            )

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
    """Re-run PC1 on specific items (after user fixes in error queue).

    Resets specified items to UPLOADED, clears old errors, then re-runs
    precheck on ALL items that are currently UPLOADED (includes the reset ones).
    """
    from ..db import task_repo as tr

    for iid in item_ids:
        tr.update_item_status(iid, "UPLOADED", error_message=None)
        # Clear unresolved errors for this item
        errors = tr.get_precheck_errors(task_id, phase="PC1", resolved=False)
        for e in errors:
            if e.item_id == iid:
                tr.resolve_precheck_error(e.error_id, resolved_by="RECHECK")

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
