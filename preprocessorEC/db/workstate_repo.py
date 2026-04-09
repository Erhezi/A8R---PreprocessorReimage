"""Working-state repository — SQLite-backed per-task intermediate state.

Stores TaskState dicts as JSON in SQLite. This is the data that will
later be managed by LangGraph's SqliteSaver checkpointer.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, Session

from .engine import get_sqlite_engine
from ..common.utils import ny_now

WorkstateBase = declarative_base()


# ---------------------------------------------------------------------------
# SQLite table definitions (auto-created by init_workstate_tables)
# ---------------------------------------------------------------------------
class TaskWorkingState(WorkstateBase):
    __tablename__ = "task_working_state"

    task_id = Column(String(4), primary_key=True)
    phase = Column(String(30), nullable=False, default="INTAKE")
    state_json = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, default=ny_now, onupdate=ny_now)


class MatchCandidate(WorkstateBase):
    __tablename__ = "match_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(4), nullable=False, index=True)
    input_item_id = Column(Integer, nullable=False)
    matched_ref = Column(String(255), nullable=True)
    source = Column(String(20), nullable=False)  # CCX | INFOR_CL | INFOR_IM
    similarity_score = Column(Integer, nullable=True)
    bucket = Column(String(10), nullable=True)  # HIGH | MED | LOW
    decision = Column(String(20), nullable=True)  # ACCEPT | REJECT | LLM_REVIEW
    decided_by = Column(String(120), nullable=True)


class ReviewQueue(WorkstateBase):
    __tablename__ = "review_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(4), nullable=False, index=True)
    review_type = Column(String(20), nullable=False)  # CONTRACT | ITEM | LLM
    payload_json = Column(Text, nullable=False, default="{}")
    status = Column(String(20), nullable=False, default="PENDING")
    reviewed_by = Column(String(120), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------
def init_workstate_tables() -> None:
    """Create SQLite tables if they don't exist. Call from app factory."""
    engine = get_sqlite_engine()
    WorkstateBase.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# TaskState save / load
# ---------------------------------------------------------------------------
def _session() -> Session:
    return Session(get_sqlite_engine())


def save_state(task_id: str, state: dict) -> None:
    """Persist a TaskState dict to SQLite."""
    with _session() as s:
        row = s.get(TaskWorkingState, task_id)
        serialized = json.dumps(state, default=str)
        if row:
            row.state_json = serialized
            row.phase = state.get("phase", row.phase)
            row.updated_at = ny_now()
        else:
            row = TaskWorkingState(
                task_id=task_id,
                phase=state.get("phase", "INTAKE"),
                state_json=serialized,
            )
            s.add(row)
        s.commit()


def load_state(task_id: str) -> Optional[dict]:
    """Load a TaskState dict from SQLite. Returns None if not found."""
    with _session() as s:
        row = s.get(TaskWorkingState, task_id)
        if row is None:
            return None
        return json.loads(row.state_json)


def delete_state(task_id: str) -> None:
    """Remove working state for a task."""
    with _session() as s:
        row = s.get(TaskWorkingState, task_id)
        if row:
            s.delete(row)
        # Also clean up related match candidates and review queue
        s.query(MatchCandidate).filter(MatchCandidate.task_id == task_id).delete()
        s.query(ReviewQueue).filter(ReviewQueue.task_id == task_id).delete()
        s.commit()


# ---------------------------------------------------------------------------
# Match candidates (used during preprocess phase)
# ---------------------------------------------------------------------------
def save_match_candidates(task_id: str, candidates: list[dict]) -> None:
    """Bulk insert match candidates for a task (replaces existing)."""
    with _session() as s:
        s.query(MatchCandidate).filter(MatchCandidate.task_id == task_id).delete()
        for c in candidates:
            s.add(MatchCandidate(task_id=task_id, **c))
        s.commit()


def get_match_candidates(task_id: str, bucket: Optional[str] = None) -> list[dict]:
    with _session() as s:
        q = s.query(MatchCandidate).filter(MatchCandidate.task_id == task_id)
        if bucket:
            q = q.filter(MatchCandidate.bucket == bucket)
        rows = q.all()
        return [
            {
                "id": r.id,
                "task_id": r.task_id,
                "input_item_id": r.input_item_id,
                "matched_ref": r.matched_ref,
                "source": r.source,
                "similarity_score": r.similarity_score,
                "bucket": r.bucket,
                "decision": r.decision,
                "decided_by": r.decided_by,
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------
def add_review(task_id: str, review_type: str, payload: dict) -> int:
    """Add a review item. Returns the review id."""
    with _session() as s:
        r = ReviewQueue(
            task_id=task_id,
            review_type=review_type,
            payload_json=json.dumps(payload, default=str),
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return r.id


def get_reviews(task_id: str, review_type: Optional[str] = None, status: str = "PENDING") -> list[dict]:
    with _session() as s:
        q = s.query(ReviewQueue).filter(
            ReviewQueue.task_id == task_id,
            ReviewQueue.status == status,
        )
        if review_type:
            q = q.filter(ReviewQueue.review_type == review_type)
        rows = q.all()
        return [
            {
                "id": r.id,
                "task_id": r.task_id,
                "review_type": r.review_type,
                "payload": json.loads(r.payload_json),
                "status": r.status,
                "reviewed_by": r.reviewed_by,
            }
            for r in rows
        ]


def complete_review(review_id: int, reviewed_by: str, decision_status: str = "COMPLETED") -> None:
    with _session() as s:
        r = s.get(ReviewQueue, review_id)
        if r:
            r.status = decision_status
            r.reviewed_by = reviewed_by
            r.reviewed_at = ny_now()
            s.commit()
