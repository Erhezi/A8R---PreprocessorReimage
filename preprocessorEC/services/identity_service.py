"""Identity service — Phase 2 business logic.

Handles: standardized descriptions (copy from description for now),
manufacturer code verification/selection, contract number entry, PC2 validation.
Pure Python, no Flask imports.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text as sa_text

from ..db import task_repo, workstate_repo
from ..db.engine import get_sqlserver_engine
from ..db.sql_loader import load_query
from ..state import TaskStateMachine, Phase, Status


# ---------------------------------------------------------------------------
# Standardized Description — copy from description (bypass Nuvia for now)
# ---------------------------------------------------------------------------
def copy_descriptions_from_input(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Copy description → standardized_description for all PASSED_PC1 items.

    Future: integrate with Nuvia, LLM, or manual cleanse upload.
    """
    items = task_repo.get_items(task_id, status=Status.PASSED_PC1)
    updated = 0
    for item in items:
        std_desc = (item.description or "").strip().upper()
        if std_desc:
            task_repo.update_items_bulk([item.item_id], standardized_description=std_desc)
            updated += 1

    state = state_machine.get_state(task_id)
    state["standardized_items"] = [{"item_id": i.item_id, "description": (i.description or "").strip().upper()} for i in items]
    state_machine.save_state(task_id, state)

    return {"updated": updated, "total": len(items)}


def apply_standardized_descriptions(
    task_id: str,
    descriptions: dict[int, str],
    state_machine: TaskStateMachine,
) -> dict:
    """Apply manually provided standardized descriptions to task items.

    Parameters
    ----------
    descriptions : dict mapping item_id → standardized description string
    """
    for item_id, desc in descriptions.items():
        task_repo.update_items_bulk([item_id], standardized_description=desc.strip().upper())

    state = state_machine.get_state(task_id)
    state["standardized_items"] = [{"item_id": k, "description": v} for k, v in descriptions.items()]
    state_machine.save_state(task_id, state)

    return {"updated": len(descriptions)}


# ---------------------------------------------------------------------------
# Manufacturer Code — UPDATE: fetch from CCXInforSyncedContractHeader
# ---------------------------------------------------------------------------
def get_manufacturer_info(organization: str, contract_id: str) -> dict:
    """Fetch manufacturer info from CCXInforSyncedContractHeader for UPDATE contracts."""
    engine = get_sqlserver_engine()
    stmt = load_query("identity", "identity", query="get_contract_header_manufacturer")
    with engine.connect() as conn:
        row = conn.execute(stmt, {"organization": organization.strip().upper(), "contract_id": contract_id.strip().upper()}).fetchone()
    if row:
        return {
            "found": True,
            "manufacturer_code": row[0] or "",
            "manufacturer_name": row[1] or "",
        }
    return {"found": False, "manufacturer_code": "", "manufacturer_name": ""}


def confirm_manufacturer(task_id: str, code: str, name: str, state_machine: TaskStateMachine) -> dict:
    """Confirm manufacturer code for a task — writes to task and ALL task items."""
    clean_code = code.strip().upper()
    clean_name = name.strip().upper()
    # Write to task header
    task_repo.update_task_fields(
        task_id,
        contract_manufacturer_infor=clean_code,
        contract_manufacturer_name_infor=clean_name,
    )
    # Write to ALL task items
    all_items = task_repo.get_items(task_id)
    if all_items:
        task_repo.update_items_bulk(
            [i.item_id for i in all_items],
            manufacturer_infor=clean_code,
            manufacturer_name_infor=clean_name,
        )
    # Update working state
    state = state_machine.get_state(task_id)
    state["manufacturer_code"] = clean_code
    state["manufacturer_name"] = clean_name
    state["manufacturer_confirmed"] = True
    state_machine.save_state(task_id, state)
    return {"manufacturer_code": clean_code, "manufacturer_name": clean_name, "confirmed": True}


# ---------------------------------------------------------------------------
# Manufacturer Code — NEW: search MDM_MANUFACTURER_NAME_INFOR
# ---------------------------------------------------------------------------
def search_manufacturers(search_term: str) -> list[dict]:
    """Search available manufacturers by code or name for NEW contracts."""
    engine = get_sqlserver_engine()
    stmt = load_query("identity", "identity", query="search_manufacturers")
    like_term = f"%{search_term.strip().upper()}%"
    with engine.connect() as conn:
        rows = conn.execute(stmt, {"search_term": like_term}).fetchall()
    return [
        {"manufacturer_code": r[0], "manufacturer_name": r[1], "active": r[2]}
        for r in rows
    ]


def set_manufacturer_code(task_id: str, code: str, name: str, state_machine: TaskStateMachine) -> dict:
    """Set manufacturer code for a NEW/MIX contract (selected from search modal)."""
    return confirm_manufacturer(task_id, code, name, state_machine)


def auto_confirm_expire_manufacturer(task_id: str, state_machine: TaskStateMachine) -> dict:
    """For EXPIRE contracts: auto-fetch manufacturer from Infor and confirm.

    No user interaction required — pulls ContractManufacturer_Infor and
    ManufacturerName_Infor from CCXInforSyncedContractHeader and writes them
    to the task header and all task items immediately.
    """
    task = task_repo.get_task(task_id)
    if not task:
        return {"found": False, "error": "Task not found"}
    org = (task.organization or "").strip().upper()
    contract_id = (task.contract_number or "").strip().upper()
    if not org or not contract_id:
        return {"found": False, "error": "Organization or contract number missing"}
    info = get_manufacturer_info(org, contract_id)
    if info["found"]:
        result = confirm_manufacturer(task_id, info["manufacturer_code"], info["manufacturer_name"], state_machine)
        result["auto_confirmed"] = True
        return result
    return {"found": False, "auto_confirmed": False, "error": "No manufacturer found in Infor for this contract"}


# ---------------------------------------------------------------------------
# Contract Number — NEW contracts only
# ---------------------------------------------------------------------------
def enter_contract_number(task_id: str, contract_number: str, state_machine: TaskStateMachine) -> dict:
    """MDM enters the acquired contract number for NEW contracts."""
    clean_num = contract_number.strip().upper()
    task_repo.update_task_fields(task_id, contract_number=clean_num)
    state = state_machine.get_state(task_id)
    if "header" not in state or not isinstance(state.get("header"), dict):
        state["header"] = {}
    state["header"]["contract_number"] = clean_num
    state_machine.save_state(task_id, state)
    return {"contract_number": clean_num}


# ---------------------------------------------------------------------------
# Pre-Check PC2
# ---------------------------------------------------------------------------
def run_precheck2(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Run Phase 2 pre-check (PC2) on items in PASSED_PC1 status.

    Current checks:
    - Manufacturer confirmed (UPDATE/NEW/MIX must have manufacturer confirmed before PC2)
    - Standardized description not null/empty for every item
    """
    task = task_repo.get_task(task_id)
    intention = (task.intention or "").upper() if task else ""
    state = state_machine.get_state(task_id)
    mfg_confirmed = state.get("manufacturer_confirmed", False)

    # Gate: manufacturer must be confirmed for UPDATE, NEW, and MIX
    if intention in ("UPDATE", "NEW", "MIX") and not mfg_confirmed:
        return {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": [{
                "item_id": None,
                "error_type": "MFG_NOT_CONFIRMED",
                "error_detail": (
                    "Manufacturer must be confirmed before running PC2. "
                    "Use the Manufacturer Code card to confirm (UPDATE) or select (NEW) a manufacturer."
                ),
            }],
            "warnings": [],
            "blocked": True,
        }

    items = task_repo.get_items(task_id, status=Status.PASSED_PC1)
    errors = []
    warnings = []

    for item in items:
        std_desc = (item.standardized_description or "").strip().upper()

        if not std_desc:
            errors.append({
                "item_id": item.item_id,
                "error_type": "NULL_STD_DESCRIPTION",
                "error_detail": "Standardized description is required",
            })
            task_repo.add_precheck_error(task_id, item.item_id, "PC2", "NULL_STD_DESCRIPTION", "Standardized description is required")
            task_repo.update_item_status(item.item_id, Status.ERROR_PC2)
            continue

        # Ensure upper case
        task_repo.update_items_bulk([item.item_id], standardized_description=std_desc)
        task_repo.update_item_status(item.item_id, Status.PASSED_PC2)

    passed_count = len(items) - len(errors)

    if errors:
        state["pc2_passed"] = False
        state["status"] = Status.ERROR_PC2
    else:
        state["pc2_passed"] = True
        state["status"] = Status.PENDING_PREPROCESSOR

    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.IDENTITY, state["status"])

    return {
        "total": len(items),
        "passed": passed_count,
        "failed": len(errors),
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Advance to Preprocess
# ---------------------------------------------------------------------------
def advance_to_preprocess(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """Advance task from IDENTITY → PREPROCESS after PC2 passes."""
    # Zero-viable guard: every row was soft-deleted upstream.
    all_items = task_repo.get_items(task_id)
    if not any((i.status or "") not in Status.DELETED_STATUSES for i in all_items):
        state = state_machine.get_state(task_id)
        msg = "Cannot advance to Preprocess: task has 0 viable items to move forward (all rows soft-deleted)."
        task_repo.add_status_log(
            task_id=task_id,
            old_phase=Phase.IDENTITY,
            new_phase=Phase.IDENTITY,
            old_status=state.get("status"),
            new_status=state.get("status"),
            changed_by=user,
            notes=msg,
        )
        raise ValueError(msg)

    new_state = state_machine.advance(
        task_id, Phase.PREPROCESS, changed_by=user, notes="PC2 passed, advancing to Preprocess"
    )
    return {"phase": new_state["phase"], "status": new_state["status"]}
