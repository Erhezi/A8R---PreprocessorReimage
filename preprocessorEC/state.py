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
    # Global
    DRAFT = "DRAFT"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"

    # Phase 1 — Intake
    PENDING_PRECHECK = "PENDING_PRECHECK"
    PENDING_NUVIA = "PENDING_NUVIA"
    ERROR_PC1 = "ERROR_PC1"
    WARN_PC1 = "WARN_PC1"
    MDM_HELP_PC1 = "MDM_HELP_PC1"
    ON_HOLD_PC1 = "ON_HOLD_PC1"

    # Phase 2 — Identity
    PENDING_PREPROCESSOR = "PENDING_PREPROCESSOR"
    ERROR_PC2 = "ERROR_PC2"
    ON_HOLD_PC2 = "ON_HOLD_PC2"

    # Phase 3 — Preprocess
    PREPROCESSING = "PREPROCESSING"
    REVIEW_CONTRACTS = "REVIEW_CONTRACTS"
    REVIEW_ITEMS = "REVIEW_ITEMS"
    LLM_REVIEW = "LLM_REVIEW"
    INFOR_MATCHING = "INFOR_MATCHING"
    INFOR_REVIEW = "INFOR_REVIEW"
    ITEM_LABELING = "ITEM_LABELING"
    BUY_UOM_CHECKING = "BUY_UOM_CHECKING"
    PREPROCESSED = "PREPROCESSED"

    # Phase 3 — item-level statuses
    MATCHING = "MATCHING"
    MATCHED = "MATCHED"
    ITEM_FETCHED = "ITEM_FETCHED"
    REVIEW_PENDING = "REVIEW_PENDING"
    MATCH_CONFIRMED = "MATCH_CONFIRMED"
    ITEM_LABELED = "ITEM_LABELED"
    MULTI_ITEM_ERROR = "MULTI_ITEM_ERROR"
    BUY_UOM_ERROR = "BUY_UOM_ERROR"
    BUY_UOM_WARN = "BUY_UOM_WARN"
    ITEM_PREPROCESSED = "ITEM_PREPROCESSED"

    # Phase 4 — Dedup
    SIMULATING = "SIMULATING"
    REVIEW_DEDUP = "REVIEW_DEDUP"
    DEDUP_COMPLETE = "DEDUP_COMPLETE"

    # Phase 5 — Export
    EXPORTING = "EXPORTING"
    EXPORTED = "EXPORTED"

    # Phase 6 — Monitoring
    MONITORING_ACTIVE = "MONITORING_ACTIVE"
    COMPLETED = "COMPLETED"


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
