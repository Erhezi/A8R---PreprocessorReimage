"""Phase 4D — post-dedup integrity validation.

Runs three checks against the *kept-set* (workspace rows where the user
has decided ``keep`` for the relevant side). All checks key off
``input_item_id`` per design clarification; the spec's "same item" means
"same input_item_id", not "same Infor item number".

Issues are rewritten on every run (cleared, then re-inserted) — there is
no per-issue resolution flow, the user resolves by editing values and
re-running.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from ..db.engine import get_sqlserver_engine
from ..models import IntegrityIssue, TaskItemForDecision

logger = logging.getLogger(__name__)

CHECK_MFG_CONSISTENCY = 1   # same input_item_id -> single manufacturer_number
CHECK_QOE_PER_UOM = 2       # (input_item_id, vendor, uom) -> single QOE
CHECK_UOM_PER_VPN = 3       # (vendor, vendor_part_number) [infor_item present] -> single UOM


def _session() -> Session:
    return Session(get_sqlserver_engine())


def _norm(value) -> str:
    return (str(value).strip().upper()) if value not in (None, "") else ""


@dataclass
class KeptEntry:
    """One row in the kept-set, normalized across input vs matched sides."""
    dedup_id: int
    side: str  # 'input' | 'matched'
    input_item_id: int
    manufacturer_number: Optional[str]
    vendor: Optional[str]            # ERP vendor id (input or matched)
    vendor_item: Optional[str]
    uom: Optional[str]               # uom_to_match_infor preferred (post-EDI substitution)
    qoe: Optional[int]
    infor_item: Optional[str]


def _build_kept_set(rows: list[TaskItemForDecision]) -> list[KeptEntry]:
    """Project workspace rows into one KeptEntry per kept side.

    The INPUT side is uniform across all rows sharing an input_item_id,
    so it contributes at most once per group regardless of how many
    matched rows the user kept.
    """
    kept: list[KeptEntry] = []
    seen_input_groups: set[int] = set()

    for r in rows:
        if (r.input_decision or "").lower() == "keep" and r.input_item_id not in seen_input_groups:
            kept.append(KeptEntry(
                dedup_id=r.dedup_id,
                side="input",
                input_item_id=r.input_item_id,
                manufacturer_number=r.manufacturer_number_input,
                vendor=r.erp_vendor_id_input,
                vendor_item=r.vendor_item_input,
                uom=r.uom_to_match_infor_input or r.uom_input,
                qoe=r.qoe_input,
                infor_item=(r.infor_item_number or None),
            ))
            seen_input_groups.add(r.input_item_id)

        if (r.matched_decision or "").lower() == "keep":
            kept.append(KeptEntry(
                dedup_id=r.dedup_id,
                side="matched",
                input_item_id=r.input_item_id,
                manufacturer_number=r.manufacturer_number_matched,
                vendor=r.erp_vendor_id_matched,
                vendor_item=r.vendor_item_matched,
                uom=r.uom_to_match_infor_matched or r.uom_matched,
                qoe=r.qoe_matched,
                infor_item=(r.infor_item_matched or None),
            ))

    return kept


def _check_mfg_consistency(kept: list[KeptEntry]) -> list[dict]:
    """Same input_item_id (i.e. same item) must have one manufacturer_number."""
    issues: list[dict] = []
    by_input: dict[int, list[KeptEntry]] = defaultdict(list)
    for e in kept:
        by_input[e.input_item_id].append(e)

    for input_item_id, entries in by_input.items():
        mfn_set = {_norm(e.manufacturer_number) for e in entries if e.manufacturer_number}
        if len(mfn_set) > 1:
            issues.append({
                "check_id": CHECK_MFG_CONSISTENCY,
                "group_keys": {"input_item_id": input_item_id},
                "affected": [
                    {"dedup_id": e.dedup_id, "side": e.side, "value": e.manufacturer_number}
                    for e in entries
                ],
                "detail": (
                    f"Inconsistent manufacturer_number across kept rows for "
                    f"input_item_id={input_item_id}: found {sorted(mfn_set)}"
                ),
            })
    return issues


def _check_qoe_per_uom(kept: list[KeptEntry]) -> list[dict]:
    """Same item + same vendor + same UOM must have one QOE."""
    issues: list[dict] = []
    by_key: dict[tuple, list[KeptEntry]] = defaultdict(list)
    for e in kept:
        if not e.vendor or not e.uom:
            continue
        by_key[(e.input_item_id, _norm(e.vendor), _norm(e.uom))].append(e)

    for (input_item_id, vendor, uom), entries in by_key.items():
        qoe_set = {e.qoe for e in entries if e.qoe is not None}
        if len(qoe_set) > 1:
            issues.append({
                "check_id": CHECK_QOE_PER_UOM,
                "group_keys": {
                    "input_item_id": input_item_id,
                    "vendor": vendor,
                    "uom": uom,
                },
                "affected": [
                    {"dedup_id": e.dedup_id, "side": e.side, "value": e.qoe}
                    for e in entries
                ],
                "detail": (
                    f"Inconsistent QOE for input_item_id={input_item_id}, "
                    f"vendor={vendor}, uom={uom}: found {sorted(qoe_set)}"
                ),
            })
    return issues


def _check_uom_per_vpn(kept: list[KeptEntry]) -> list[dict]:
    """Same vendor + same vendor_part_number (where infor_item is set)
    must have one UOM. Gated on infor_item being non-empty per design.
    """
    issues: list[dict] = []
    by_key: dict[tuple, list[KeptEntry]] = defaultdict(list)
    for e in kept:
        if not (e.infor_item and str(e.infor_item).strip()):
            continue
        if not e.vendor or not e.vendor_item:
            continue
        by_key[(_norm(e.vendor), _norm(e.vendor_item))].append(e)

    for (vendor, vendor_item), entries in by_key.items():
        uom_set = {_norm(e.uom) for e in entries if e.uom}
        if len(uom_set) > 1:
            issues.append({
                "check_id": CHECK_UOM_PER_VPN,
                "group_keys": {"vendor": vendor, "vendor_item": vendor_item},
                "affected": [
                    {"dedup_id": e.dedup_id, "side": e.side, "value": e.uom}
                    for e in entries
                ],
                "detail": (
                    f"Inconsistent UOM for vendor={vendor}, "
                    f"vendor_item={vendor_item}: found {sorted(uom_set)}"
                ),
            })
    return issues


def run_integrity_validation(task_id: str) -> dict:
    """Run all 3 checks against the kept-set, rewrite IntegrityIssue rows.

    Returns a summary dict with counts per check + the issue payloads.
    """
    with _session() as s:
        rows = (
            s.query(TaskItemForDecision)
            .filter(TaskItemForDecision.task_id == task_id)
            .all()
        )

        # Clear prior issues — validator output is a snapshot of the
        # current workspace, not a long-lived ticket queue.
        s.query(IntegrityIssue).filter(
            IntegrityIssue.task_id == task_id
        ).delete(synchronize_session=False)

        kept = _build_kept_set(rows)
        all_issues = (
            _check_mfg_consistency(kept)
            + _check_qoe_per_uom(kept)
            + _check_uom_per_vpn(kept)
        )

        if all_issues:
            s.bulk_save_objects([
                IntegrityIssue(
                    task_id=task_id,
                    check_id=item["check_id"],
                    severity="ERROR",
                    group_keys=json.dumps(item["group_keys"]),
                    affected=json.dumps(item["affected"]),
                    detail=item["detail"],
                )
                for item in all_issues
            ])
        s.commit()

    return {
        "task_id": task_id,
        "kept_count": len(kept),
        "check_1_issues": sum(1 for i in all_issues if i["check_id"] == CHECK_MFG_CONSISTENCY),
        "check_2_issues": sum(1 for i in all_issues if i["check_id"] == CHECK_QOE_PER_UOM),
        "check_3_issues": sum(1 for i in all_issues if i["check_id"] == CHECK_UOM_PER_VPN),
        "total_issues": len(all_issues),
        "issues": all_issues,
    }


def get_open_issues(task_id: str) -> list[dict]:
    """Read persisted issues for the task (used by the UI on page load)."""
    with _session() as s:
        rows = (
            s.query(IntegrityIssue)
            .filter(IntegrityIssue.task_id == task_id)
            .order_by(IntegrityIssue.check_id.asc(), IntegrityIssue.issue_id.asc())
            .all()
        )
        return [row.to_dict() for row in rows]
