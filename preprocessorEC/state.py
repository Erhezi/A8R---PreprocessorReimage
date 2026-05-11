"""Task state machine — explicit phase transitions.

TaskState is the TypedDict that will become the LangGraph State.
TaskStateMachine enforces valid transitions with guards.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Phases & Statuses
# ---------------------------------------------------------------------------
class Phase:
    INTAKE = "INTAKE"
    IDENTITY = "IDENTITY"
    PREPROCESS = "PREPROCESS"
    DEDUP = "DEDUP"
    EXPORT = "EXPORT"
    MONITORING = "MONITORING"

    ALL = [INTAKE, IDENTITY, PREPROCESS, DEDUP, EXPORT, MONITORING]


class Status:
    """Workflow statuses for tasks and individual items.

    Conventions:
      - Substrings ``ERROR`` / ``WARN`` / ``REVIEW`` / ``PENDING`` / ``HOLD``
        are pattern-matched by UI badges and finalize gates — keep new names
        consistent with this convention so substring scans don't need hard-
        coded lists.
      - Suffixes ``_PC1`` / ``_PC2`` denote intake / identity precheck stages.
      - Item-level statuses live on ``PreprocessorTaskItem.status``; everything
        else lives on the task record (and mirrors into TaskState).
    """

    # ---- Global (any phase) -------------------------------------------------
    DRAFT     = "DRAFT"      # Task created, no work started.
    ON_HOLD   = "ON_HOLD"    # Generic hold (phase-specific holds preferred).
    CANCELLED = "CANCELLED"  # Task abandoned; no further transitions.

    # =========================================================================
    # Phase 1 — Intake
    # =========================================================================
    # --- Task-level ---
    PENDING_PRECHECK = "PENDING_PRECHECK"  # Items uploaded; PC1 not yet run.
    PENDING_NUVIA    = "PENDING_NUVIA"     # PC1 passed; awaiting Nuvia identity sync.
    MDM_HELP_PC1     = "MDM_HELP_PC1"      # Reserved: not currently set by code.
    ON_HOLD_PC1      = "ON_HOLD_PC1"       # PC1 found blocking errors; user must resolve in /intake.

    # --- Item-level ---
    UPLOADED    = "UPLOADED"    # Default state on row creation; reset back to this when PC1 is re-run.
    # Set per row by run_pc1():
    ERROR_PC1   = "ERROR_PC1"   # Row failed PC1 validation (or is a duplicate); blocks advance unless split off.
    WARN_PC1    = "WARN_PC1"    # Row has a non-blocking warning; user must fix or manually pass before advancing.
    PASSED_PC1  = "PASSED_PC1"  # Row passed PC1; carries forward to Identity.
    DELETED_PC1 = "DELETED_PC1" # User soft-deleted a row in /intake; excluded from all later phases.

    # =========================================================================
    # Phase 2 — Identity
    # =========================================================================
    # --- Task-level ---
    PENDING_PREPROCESSOR = "PENDING_PREPROCESSOR"  # PC2 passed; ready for preprocess.
    ERROR_PC2            = "ERROR_PC2"             # PC2 validation failed (also written on items — same string).
    ON_HOLD_PC2          = "ON_HOLD_PC2"           # Reserved: not currently set by code.

    # --- Item-level ---
    # Set per row by run_pc2() — ERROR_PC2 above is also written on items.
    PASSED_PC2 = "PASSED_PC2"  # Row passed PC2; carries forward to Preprocess.

    # =========================================================================
    # Phase 3 — Preprocess
    # =========================================================================
    # --- Task-level (sub-step indicators driven by run_full_preprocess) ---
    PREPROCESSING        = "PREPROCESSING"         # CCX SKU matching started.
    REVIEW_CONTRACTS     = "REVIEW_CONTRACTS"      # Contract-level decisions awaiting user.
    REVIEW_ITEMS         = "REVIEW_ITEMS"          # Reserved: not currently set by code.
    LLM_REVIEW           = "LLM_REVIEW"            # MED/LOW CCX matches sent to LLM for triage.
    INFOR_MATCHING       = "INFOR_MATCHING"        # Infor cascade running.
    INFOR_REVIEW         = "INFOR_REVIEW"          # Reserved: not currently set by code.
    ITEM_LABELING        = "ITEM_LABELING"         # 3-source labeling step running.
    BUY_UOM_CHECKING     = "BUY_UOM_CHECKING"      # Buy-UOM validation step running.
    PENDING_FINALIZATION = "PENDING_FINALIZATION"  # Pipeline complete; waiting on user to finalize.
    PREPROCESSED         = "PREPROCESSED"          # Preprocess done; advancing to Dedup.
    ON_HOLD_PREPROCESS   = "ON_HOLD_PREPROCESS"    # Finalize called but unresolved item issues remain.

    # --- Item-level (PreprocessorTaskItem.status) ---
    # Written by 3-source labeling:
    ITEM_FETCHED         = "ITEM_FETCHED"          # Labeling found 0 Infor item# candidates.
    ITEM_LABELED         = "ITEM_LABELED"          # Labeling reached exactly 1 consensus item#.
    MULTI_ITEM_ERROR     = "MULTI_ITEM_ERROR"      # Labeling found 2+ candidates; user must Pick.
    # Written by buy-UOM check / Pick / Noted:
    BUY_UOM_ERROR        = "BUY_UOM_ERROR"         # Expected UOM*QOE absent from Infor options (non-EXPIRE intent).
    BUY_UOM_WARN         = "BUY_UOM_WARN"          # Same as above but EXPIRE intent (auto-WARN) or demoted via "Noted".
    # Written by explicit-mode duplicate detection (via _derive_item_status):
    DUPLICATE_ITEM_ERROR = "DUPLICATE_ITEM_ERROR"  # Two rows share the clean_mfg + uom_to_match_infor key.
    # Terminal:
    ITEM_PREPROCESSED    = "ITEM_PREPROCESSED"     # Item passed all checks; ready for Dedup.
    DELETED_PREPROCESS   = "DELETED_PREPROCESS"    # User soft-deleted in /preprocess; excluded from later phases.

    # Soft-deleted item statuses — _live_input_items() filters these out so
    # they cannot be resurrected or re-matched on a pipeline rerun.
    DELETED_STATUSES = frozenset({DELETED_PC1, DELETED_PREPROCESS})

    # =========================================================================
    # Phase 4 — Dedup
    # =========================================================================
    # --- Task-level ---
    SIMULATING     = "SIMULATING"      # Dedup simulation running against existing catalog.
    REVIEW_DEDUP   = "REVIEW_DEDUP"    # User reviewing simulation conflicts.
    DEDUP_COMPLETE = "DEDUP_COMPLETE"  # Dedup decisions finalized; ready for Export.

    # (Phase 4 does not write any item-level statuses.)

    # =========================================================================
    # Phase 5 — Export
    # =========================================================================
    # --- Task-level ---
    EXPORTING = "EXPORTING"  # Export files being generated.
    EXPORTED  = "EXPORTED"   # Export complete; advancing to Monitoring.

    # (Phase 5 does not write any item-level statuses.)

    # =========================================================================
    # Phase 6 — Monitoring
    # =========================================================================
    # --- Task-level ---
    MONITORING_ACTIVE = "MONITORING_ACTIVE"  # Post-export monitoring window.
    COMPLETED         = "COMPLETED"          # Terminal: task fully finished.


# ---------------------------------------------------------------------------
# Reason — audit-trail codes for non-status events.
# Lives on PreprocessorTask.spawn_reason (and similar audit fields). Kept
# separate from Status so the two namespaces can't be confused.
# ---------------------------------------------------------------------------
class Reason:
    REASON_ERROR_PC1_SPLIT = "REASON_ERROR_PC1_SPLIT"  # Sub-task spawned to carry ERROR_PC1 items split off the parent at PC1 advance.


# ---------------------------------------------------------------------------
# TaskState — the dict that becomes LangGraph State later.
# ---------------------------------------------------------------------------
class TaskState(TypedDict, total=False):
    task_id: str
    phase: str
    status: str

    # Phase 1 — Intake
    header: dict
    raw_items: list[dict]
    clean_items: list[dict]
    pc1_errors: list[dict]
    pc1_passed: bool
    # Modes that have finished PC1 with a fully clean outcome since the last
    # data change. Drives the DISTRIBUTOR auto-chain (default → distributor)
    # and is surfaced to the UI as "what's already been validated". Cleared
    # on upload / re-upload / item edit / soft-delete; advance no longer
    # gates on this list (the user's manual pass / fix actions are the
    # authority on whether the data is ready to move forward).
    pc1_passed_modes: list[str]

    # Phase 2 — Identity
    standardized_items: list[dict]
    manufacturer_code: str
    vendor_verified: bool
    sync_changes: list[dict]
    pc2_passed: bool

    # Phase 3 — Preprocess Core
    ccx_matches: list[dict]
    infor_cl_matches: list[dict]
    infor_im_matches: list[dict]
    infor_residue_matches: list[dict]
    contract_review: list[dict]
    item_review: list[dict]
    ccx_decisions_done: bool
    infor_decisions_done: bool
    item_labeling_done: bool
    buy_uom_check_done: bool
    preprocessed_dataset: list[dict]

    # Phase 4 — Dedup
    simulation_results: list[dict]
    integrity_issues: list[dict]

    # Phase 5+
    export_files: list[str]

    # Meta
    messages: list[dict]
    pending_human_input: dict | None


def empty_task_state(task_id: str) -> TaskState:
    """Create a blank TaskState for a newly created task."""
    return TaskState(
        task_id=task_id,
        phase=Phase.INTAKE,
        status=Status.DRAFT,
        header={},
        raw_items=[],
        clean_items=[],
        pc1_errors=[],
        pc1_passed=False,
        pc1_passed_modes=[],
        standardized_items=[],
        manufacturer_code="",
        vendor_verified=False,
        sync_changes=[],
        pc2_passed=False,
        ccx_matches=[],
        infor_cl_matches=[],
        infor_im_matches=[],
        infor_residue_matches=[],
        contract_review=[],
        item_review=[],
        ccx_decisions_done=False,
        infor_decisions_done=False,
        item_labeling_done=False,
        buy_uom_check_done=False,
        preprocessed_dataset=[],
        simulation_results=[],
        integrity_issues=[],
        export_files=[],
        messages=[],
        pending_human_input=None,
    )


# ---------------------------------------------------------------------------
# Transition rules
# ---------------------------------------------------------------------------
# Maps (current_phase) → list of allowed (next_phase, guard_fn) tuples.
# guard_fn(state) → bool; must return True for transition to be allowed.

def _pc1_passed(state: TaskState) -> bool:
    return state.get("pc1_passed", False)

def _pc2_passed(state: TaskState) -> bool:
    return state.get("pc2_passed", False)

def _preprocessed(state: TaskState) -> bool:
    return state.get("status") == Status.PREPROCESSED

def _dedup_complete(state: TaskState) -> bool:
    return state.get("status") == Status.DEDUP_COMPLETE

def _exported(state: TaskState) -> bool:
    return state.get("status") == Status.EXPORTED

def _always(_state: TaskState) -> bool:
    return True


_TRANSITIONS: dict[str, list[tuple[str, callable]]] = {
    Phase.INTAKE:     [(Phase.IDENTITY,   _pc1_passed)],
    Phase.IDENTITY:   [(Phase.PREPROCESS, _pc2_passed)],
    Phase.PREPROCESS: [(Phase.DEDUP,      _preprocessed)],
    Phase.DEDUP:      [(Phase.EXPORT,     _dedup_complete)],
    Phase.EXPORT:     [(Phase.MONITORING,  _exported)],
    Phase.MONITORING: [],  # terminal
}


# ---------------------------------------------------------------------------
# TaskStateMachine — enforces transitions, logs changes.
# Pure-Python, no Flask dependency. Repos injected via constructor.
# ---------------------------------------------------------------------------
class TaskStateMachine:
    """Manages task phase transitions with guard validation.

    Parameters
    ----------
    task_repo : db.task_repo module or compatible object with
        ``get_task()``, ``update_task()``, ``add_status_log()`` methods.
    workstate_repo : db.workstate_repo module or compatible object with
        ``load_state()``, ``save_state()`` methods.
    """

    def __init__(self, task_repo, workstate_repo):
        self.task_repo = task_repo
        self.workstate_repo = workstate_repo

    def get_state(self, task_id: str) -> TaskState:
        """Load current TaskState from working-state store."""
        state = self.workstate_repo.load_state(task_id)
        if state is None:
            return empty_task_state(task_id)
        return state

    def save_state(self, task_id: str, state: TaskState) -> None:
        self.workstate_repo.save_state(task_id, state)

    def can_advance(self, state: TaskState, target_phase: str) -> bool:
        """Check if transition from current phase to *target_phase* is allowed."""
        current = state.get("phase", Phase.INTAKE)
        allowed = _TRANSITIONS.get(current, [])
        for next_phase, guard in allowed:
            if next_phase == target_phase and guard(state):
                return True
        return False

    def advance(
        self,
        task_id: str,
        target_phase: str,
        changed_by: str,
        notes: Optional[str] = None,
    ) -> TaskState:
        """Advance a task to the next phase.

        Raises ValueError if the transition is invalid.
        Returns the updated TaskState.
        """
        state = self.get_state(task_id)
        current_phase = state.get("phase", Phase.INTAKE)

        if not self.can_advance(state, target_phase):
            raise ValueError(
                f"Cannot transition task {task_id} from {current_phase} to {target_phase}. "
                f"Guard check failed."
            )

        old_phase = current_phase
        old_status = state.get("status", "")

        # Update state
        state["phase"] = target_phase
        # Reset status to a sensible default for the new phase
        phase_default_status = {
            Phase.IDENTITY: Status.PENDING_NUVIA,
            Phase.PREPROCESS: Status.PENDING_PREPROCESSOR,
            Phase.DEDUP: Status.SIMULATING,
            Phase.EXPORT: Status.EXPORTING,
            Phase.MONITORING: Status.MONITORING_ACTIVE,
        }
        state["status"] = phase_default_status.get(target_phase, state["status"])

        # Persist
        self.save_state(task_id, state)

        # Update SQL Server task record
        self.task_repo.update_task_phase(task_id, target_phase, state["status"])

        # Log transition
        self.task_repo.add_status_log(
            task_id=task_id,
            old_phase=old_phase,
            new_phase=target_phase,
            old_status=old_status,
            new_status=state["status"],
            changed_by=changed_by,
            notes=notes,
        )

        return state

    def update_status(
        self,
        task_id: str,
        new_status: str,
        changed_by: str,
        notes: Optional[str] = None,
    ) -> TaskState:
        """Update status within the current phase (no phase change)."""
        state = self.get_state(task_id)
        old_status = state.get("status", "")

        state["status"] = new_status
        self.save_state(task_id, state)
        self.task_repo.update_task_phase(task_id, state["phase"], new_status)
        self.task_repo.add_status_log(
            task_id=task_id,
            old_phase=state["phase"],
            new_phase=state["phase"],
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by,
            notes=notes,
        )
        return state

    def get_pending_human_input(self, task_id: str) -> dict | None:
        """Return what the system is waiting for, if anything.

        Maps to LangGraph interrupt() payload in the future.
        """
        state = self.get_state(task_id)
        return state.get("pending_human_input")
