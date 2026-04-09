"""Preprocess service â€” Phase 3 business logic.

Unified duplicate detection + item master matching.
Handles: SKU matching, similarity scoring, contract-level checks,
Infor CL/IM matching, CCX-Infor sync marking.

Pure Python, no Flask imports.
This is the most complex service â€” will be the first agentic node.
"""

from __future__ import annotations

from typing import Optional

from ..db import task_repo, workstate_repo
from ..state import TaskStateMachine, Phase, Status


# ---------------------------------------------------------------------------
# SKU Matching â€” 3 strategies by contract type
# ---------------------------------------------------------------------------
def run_sku_matching(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Run SKU matching against CCX contract items.

    Strategy depends on contract type:
    - MANUFACTURER: match reduced mfg # â†’ reduced mfg # on all CCX items
    - DISTRIBUTOR PREMIER: match reduced mfg # + union reduced vendor # â†’ all CCX
    - DISTRIBUTOR LOCAL: match reduced mfg # + reduced vendor # â†’ mfg # cross-match

    Returns summary dict.
    """
    # TODO: Extract matching logic from original duplicate_detection/routes.py
    # and common/utils.py. Queries will come from preprocess/queries/dup_detection.sql
    state = state_machine.get_state(task_id)
    state["status"] = Status.PREPROCESSING
    state_machine.save_state(task_id, state)
    task_repo.update_task_phase(task_id, Phase.PREPROCESS, Status.PREPROCESSING)

    return {"status": "not_implemented", "message": "SKU matching logic to be extracted from original"}


# ---------------------------------------------------------------------------
# Similarity Calculation
# ---------------------------------------------------------------------------
def compute_similarity(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Compute matching similarity for each matched pair.

    Uses rules + local sentence transformer (all-MiniLM-L6-v2).
    Tags each pair as HIGH / MED / LOW by final score.
    """
    # TODO: Extract from original common/utils.py scoring functions
    return {"status": "not_implemented"}


# ---------------------------------------------------------------------------
# Contract-Level Check
# ---------------------------------------------------------------------------
def run_contract_check(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Aggregate matches by contract and determine review routing.

    If items_matched / contracts > 3 and contracts < 30: review by contract first.
    Else: review directly by item.
    """
    # TODO: Implement per design.txt contract check logic
    state = state_machine.get_state(task_id)
    state["status"] = Status.REVIEW_CONTRACTS
    state_machine.save_state(task_id, state)
    return {"status": "not_implemented"}


# ---------------------------------------------------------------------------
# Item Matching â€” Infor CL + IM
# ---------------------------------------------------------------------------
def run_item_matching(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Match items to Infor Contract Lines and Item Master.

    Inherits TP/FP flags from CCX matching results.
    Adds Infor Item # and buyUOM/buyUOMMultiplier.
    """
    # TODO: Extract from original item_matching/routes.py
    return {"status": "not_implemented"}


# ---------------------------------------------------------------------------
# Sync Status Marking
# ---------------------------------------------------------------------------
def mark_sync_status(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Mark CCX items as synced/unsynced vs Infor.

    Compares (vendor_id, contract_number, mfg_catalog_num, UOM_EDI) tuples.
    """
    # TODO: Implement CCX-Infor sync comparison
    return {"status": "not_implemented"}


# ---------------------------------------------------------------------------
# Full Pipeline Orchestration
# ---------------------------------------------------------------------------
def run_full_preprocess(task_id: str, state_machine: TaskStateMachine) -> dict:
    """Run the complete preprocess pipeline: SKU match â†’ similarity â†’ contract check â†’ IM match â†’ sync.

    This is the main entry point called by the route.
    """
    results = {}
    results["sku_matching"] = run_sku_matching(task_id, state_machine)
    results["similarity"] = compute_similarity(task_id, state_machine)
    results["contract_check"] = run_contract_check(task_id, state_machine)
    results["item_matching"] = run_item_matching(task_id, state_machine)
    results["sync_status"] = mark_sync_status(task_id, state_machine)
    return results


# ---------------------------------------------------------------------------
# Review decisions
# ---------------------------------------------------------------------------
def submit_contract_decision(
    task_id: str,
    contract_number: str,
    include: bool,
    decided_by: str,
    state_machine: TaskStateMachine,
) -> dict:
    """Include or exclude a contract from matching results."""
    # TODO: Update workstate match candidates
    return {"contract_number": contract_number, "included": include}


def submit_item_decision(
    task_id: str,
    match_id: int,
    decision: str,
    decided_by: str,
    state_machine: TaskStateMachine,
) -> dict:
    """Keep, drop, or send-to-LLM for an individual match.

    decision: 'ACCEPT' | 'REJECT' | 'LLM_REVIEW'
    """
    task_repo.update_match_decision(match_id, decision, decided_by)
    return {"match_id": match_id, "decision": decision}


def finalize_preprocess(task_id: str, state_machine: TaskStateMachine, user: str) -> dict:
    """Finalize preprocess results and advance to DEDUP phase."""
    state = state_machine.get_state(task_id)
    state["status"] = Status.PREPROCESSED
    state_machine.save_state(task_id, state)

    new_state = state_machine.advance(
        task_id, Phase.DEDUP, changed_by=user, notes="Preprocess complete, advancing to Dedup"
    )
    return {"phase": new_state["phase"], "status": new_state["status"]}

