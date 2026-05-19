"""Phase 4E — item-master (IM) consequence checks.

Three checks that surface as WARNINGS only (they don't block the
finalize gate). Every finding is persisted so it can be exported to MDM
along with the task. Stubs return ``status='scaffolded'`` with a list
of missing data sources; the candidate-set selection and persistence
plumbing are real today and the lookups will be filled in once the
data sources are confirmed.

  Check 1 — SOLE_COVERAGE
    For each kept-as-DROP matched row that has an Infor item number,
    determine whether removing this contract leaves the item without
    any other active contract coverage.

  Check 2 — AFFECTED_LOCATION
    For each kept-as-DROP matched row that has an Infor item number,
    list the locations (PO from-locations / facilities) impacted by
    dropping the line.

  Check 3 — VENDOR_LOCATION_ALIGNMENT
    For each kept-as-KEEP input row whose intention is NEW or UPDATE
    and whose Infor item number is set, verify that the input's ERP
    Vendor ID matches the inventory replenishment vendor on the
    contracted location.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..db.engine import get_sqlserver_engine
from ..models import IMCheckResult, TaskItemForDecision

logger = logging.getLogger(__name__)

CHECK_SOLE_COVERAGE = (1, "SOLE_COVERAGE")
CHECK_AFFECTED_LOCATION = (2, "AFFECTED_LOCATION")
CHECK_VENDOR_LOCATION_ALIGNMENT = (3, "VENDOR_LOCATION_ALIGNMENT")


def _session() -> Session:
    return Session(get_sqlserver_engine())


def _im_check_result_table_exists() -> bool:
    return inspect(get_sqlserver_engine()).has_table(
        "PreprocessorIMCheckResult",
        schema="Preprocessor",
    )


def _missing_table_payload(
    task_id: str,
    drop_count: int = 0,
    new_line_count: int = 0,
    findings: list[dict] | None = None,
) -> dict:
    findings = findings or []
    return {
        "task_id": task_id,
        "status": "missing_table",
        "drop_candidates": drop_count,
        "new_line_candidates": new_line_count,
        "check_1_warnings": sum(1 for f in findings if f["check_id"] == CHECK_SOLE_COVERAGE[0]),
        "check_2_warnings": sum(1 for f in findings if f["check_id"] == CHECK_AFFECTED_LOCATION[0]),
        "check_3_warnings": sum(1 for f in findings if f["check_id"] == CHECK_VENDOR_LOCATION_ALIGNMENT[0]),
        "total_warnings": len(findings),
        "findings": findings,
        "error": (
            "Missing table Preprocessor.PreprocessorIMCheckResult. "
            "Apply migrations/025_add_im_check_result.sql."
        ),
    }


@dataclass
class _DropCandidate:
    dedup_id: int
    input_item_id: int
    infor_item: str
    contract_id: Optional[str]
    organization: Optional[str]
    organization_eid: Optional[str]
    erp_vendor_id: Optional[str]


@dataclass
class _NewLineCandidate:
    dedup_id: int
    input_item_id: int
    infor_item: str
    contract_id: Optional[str]
    organization: Optional[str]
    organization_eid: Optional[str]
    erp_vendor_id: Optional[str]
    intention: Optional[str]


def _drop_candidates(rows: list[TaskItemForDecision]) -> list[_DropCandidate]:
    """Matched rows the user has decided to drop AND that link to an Infor IM item."""
    out: list[_DropCandidate] = []
    for r in rows:
        if (r.matched_decision or "").lower() != "drop":
            continue
        infor_item = (r.infor_item_matched or "").strip()
        if not infor_item:
            continue
        out.append(_DropCandidate(
            dedup_id=r.dedup_id,
            input_item_id=r.input_item_id,
            infor_item=infor_item,
            contract_id=r.contract_id_matched,
            organization=r.organization_matched,
            organization_eid=r.organization_eid_matched,
            erp_vendor_id=r.erp_vendor_id_matched,
        ))
    return out


def _new_line_candidates(rows: list[TaskItemForDecision]) -> list[_NewLineCandidate]:
    """Input rows kept by the user that link to an Infor IM item and have
    NEW/UPDATE intention. Deduped per input_item_id since the input snapshot
    is uniform across the match group.
    """
    out: list[_NewLineCandidate] = []
    seen: set[int] = set()
    for r in rows:
        if r.input_item_id in seen:
            continue
        if (r.input_decision or "").lower() != "keep":
            continue
        intent = (r.task_intention or "").upper()
        if intent not in {"NEW", "UPDATE"}:
            continue
        infor_item = (r.infor_item_number or "").strip()
        if not infor_item:
            continue
        seen.add(r.input_item_id)
        out.append(_NewLineCandidate(
            dedup_id=r.dedup_id,
            input_item_id=r.input_item_id,
            infor_item=infor_item,
            contract_id=r.contract_id_input,
            organization=r.organization_input,
            organization_eid=r.organization_eid_input,
            erp_vendor_id=r.erp_vendor_id_input,
            intention=intent,
        ))
    return out


# ---------------------------------------------------------------------------
# Check stubs — replace each function body with the real lookup once the
# data source is confirmed. Until then they return a "scaffolded" finding
# per candidate so the rest of the pipeline (UI + export) can be wired up
# and exercised end-to-end.
# ---------------------------------------------------------------------------
_SOLE_COVERAGE_MISSING = [
    "Active-contract coverage table for an Infor item across organizations",
    "Definition of 'sole coverage' (org-scoped vs system-wide?)",
]
_AFFECTED_LOCATION_MISSING = [
    "Mapping from Infor item -> PO from-locations / facilities currently sourcing from the dropped contract",
]
_VENDOR_LOCATION_MISSING = [
    "Inventory replenishment vendor per (Infor item, location) pair",
    "Whether 'contracted location' = task organization or specific facility",
]


def _check_sole_coverage(candidates: list[_DropCandidate]) -> list[dict]:
    findings: list[dict] = []
    check_id, check_code = CHECK_SOLE_COVERAGE
    for c in candidates:
        findings.append({
            "check_id": check_id,
            "check_code": check_code,
            "dedup_id": c.dedup_id,
            "input_item_id": c.input_item_id,
            "subject": {
                "infor_item": c.infor_item,
                "contract_id": c.contract_id,
                "organization": c.organization,
            },
            "detail": (
                f"[scaffolded] Verify whether dropping contract {c.contract_id or '?'} "
                f"for org {c.organization or '?'} leaves Infor item {c.infor_item} "
                f"without contract coverage. Awaiting data source."
            ),
            "missing_spec": _SOLE_COVERAGE_MISSING,
        })
    return findings


def _check_affected_location(candidates: list[_DropCandidate]) -> list[dict]:
    findings: list[dict] = []
    check_id, check_code = CHECK_AFFECTED_LOCATION
    for c in candidates:
        findings.append({
            "check_id": check_id,
            "check_code": check_code,
            "dedup_id": c.dedup_id,
            "input_item_id": c.input_item_id,
            "subject": {
                "infor_item": c.infor_item,
                "contract_id": c.contract_id,
                "organization": c.organization,
            },
            "detail": (
                f"[scaffolded] List facilities impacted by dropping Infor item "
                f"{c.infor_item} on contract {c.contract_id or '?'} "
                f"(org {c.organization or '?'}). Awaiting data source."
            ),
            "missing_spec": _AFFECTED_LOCATION_MISSING,
        })
    return findings


def _check_vendor_location_alignment(candidates: list[_NewLineCandidate]) -> list[dict]:
    findings: list[dict] = []
    check_id, check_code = CHECK_VENDOR_LOCATION_ALIGNMENT
    for c in candidates:
        findings.append({
            "check_id": check_id,
            "check_code": check_code,
            "dedup_id": c.dedup_id,
            "input_item_id": c.input_item_id,
            "subject": {
                "infor_item": c.infor_item,
                "contract_id": c.contract_id,
                "organization": c.organization,
                "erp_vendor_id": c.erp_vendor_id,
                "intention": c.intention,
            },
            "detail": (
                f"[scaffolded] Verify input vendor {c.erp_vendor_id or '?'} matches "
                f"the replenishment vendor for Infor item {c.infor_item} at the "
                f"contracted location ({c.organization or '?'}). Awaiting data source."
            ),
            "missing_spec": _VENDOR_LOCATION_MISSING,
        })
    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def run_im_checks(task_id: str) -> dict:
    """Run all 3 IM checks and rewrite IMCheckResult rows for the task.

    Findings are WARN-level — they do not block finalize. Returns a
    summary plus the finding payloads (so the UI can render without a
    second fetch).
    """
    with _session() as s:
        rows = (
            s.query(TaskItemForDecision)
            .filter(TaskItemForDecision.task_id == task_id)
            .all()
        )

        drop_set = _drop_candidates(rows)
        new_set = _new_line_candidates(rows)

        findings = (
            _check_sole_coverage(drop_set)
            + _check_affected_location(drop_set)
            + _check_vendor_location_alignment(new_set)
        )

        if not _im_check_result_table_exists():
            logger.warning(
                "Skipping IM-check persistence for task %s because Preprocessor.PreprocessorIMCheckResult is missing.",
                task_id,
            )
            return _missing_table_payload(task_id, len(drop_set), len(new_set), findings)

        s.query(IMCheckResult).filter(
            IMCheckResult.task_id == task_id
        ).delete(synchronize_session=False)

        if findings:
            s.bulk_save_objects([
                IMCheckResult(
                    task_id=task_id,
                    check_id=f["check_id"],
                    check_code=f["check_code"],
                    dedup_id=f.get("dedup_id"),
                    input_item_id=f.get("input_item_id"),
                    severity="WARN",
                    subject=json.dumps(f.get("subject") or {}),
                    detail=f["detail"],
                )
                for f in findings
            ])
        s.commit()

    return {
        "task_id": task_id,
        "status": "scaffolded",
        "drop_candidates": len(drop_set),
        "new_line_candidates": len(new_set),
        "check_1_warnings": sum(1 for f in findings if f["check_id"] == CHECK_SOLE_COVERAGE[0]),
        "check_2_warnings": sum(1 for f in findings if f["check_id"] == CHECK_AFFECTED_LOCATION[0]),
        "check_3_warnings": sum(1 for f in findings if f["check_id"] == CHECK_VENDOR_LOCATION_ALIGNMENT[0]),
        "total_warnings": len(findings),
        "findings": findings,
    }


def get_im_check_results(task_id: str) -> list[dict]:
    """Read persisted IM check results (page-load hydrate + MDM export)."""
    if not _im_check_result_table_exists():
        logger.warning(
            "Skipping IM-check result hydrate for task %s because Preprocessor.PreprocessorIMCheckResult is missing.",
            task_id,
        )
        return []

    with _session() as s:
        rows = (
            s.query(IMCheckResult)
            .filter(IMCheckResult.task_id == task_id)
            .order_by(IMCheckResult.check_id.asc(), IMCheckResult.result_id.asc())
            .all()
        )
        return [row.to_dict() for row in rows]
