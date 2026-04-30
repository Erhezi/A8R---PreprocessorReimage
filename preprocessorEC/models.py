"""SQLAlchemy declarative models for Contract Atlas.

SQL Server tables: Task, TaskItem, PreCheckError, MatchResult, TaskStatusLog.
User model kept as-is from original (Flask-Login, raw SQL with fallback).
"""

from __future__ import annotations

from typing import Optional

from .common.utils import ny_now

from flask_login import UserMixin
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float,
    ForeignKey, Numeric, Date, Enum as SAEnum, Index,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship
from werkzeug.security import generate_password_hash, check_password_hash

Base = declarative_base()

# ---------------------------------------------------------------------------
# Schema prefix — matches the existing SQL Server schema owner.
# Change this if deploying under a different schema.
# ---------------------------------------------------------------------------
SCHEMA = r"Preprocessor"


# ---------------------------------------------------------------------------
# Task — one row per processing request
# ---------------------------------------------------------------------------
class Task(Base):
    __tablename__ = "PreprocessorTask"
    __table_args__ = {"schema": SCHEMA}

    task_id = Column(String(4), primary_key=True)
    intake_mode = Column(String(10), nullable=False, default="SINGLE")  # SINGLE | BATCH
    contract_number = Column(String(100), nullable=True)
    vendor_id = Column(String(20), nullable=True)
    purchase_from_loc = Column(String(50), nullable=True)
    erp_vendor_name = Column(String(255), nullable=True)
    purchase_from_loc_name = Column(String(255), nullable=True)
    process_type = Column(String(20), nullable=False)  # MANUFACTURER | DISTRIBUTOR
    source_type = Column(String(20), nullable=False)    # PREMIER | LOCAL
    organization = Column(String(50), nullable=False)   # ALL, WHITE PLAINS, etc.
    oem_name = Column(String(255), nullable=True)
    intention = Column(String(10), nullable=False)       # EXPIRE | NEW | UPDATE | MIX
    mixed_intention = Column(Boolean, default=False)
    contract_start_date = Column(Date, nullable=True)
    contract_end_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    wrike_id = Column(String(10), nullable=True)
    contract_manufacturer_infor = Column(String(20), nullable=True)
    contract_manufacturer_name_infor = Column(String(255), nullable=True)

    # Precheck duplicate mode
    precheck_mode = Column(String(20), nullable=True, default="default")  # default|strict|explicit|distributor

    # Phase / status tracking
    phase = Column(String(30), nullable=False, default="INTAKE")
    status = Column(String(50), nullable=False, default="DRAFT")

    # Sub-task lineage — populated when this task was spawned off another
    # (e.g. ERROR_PC1 items split off a parent task at PC1 advance time).
    parent_task_id = Column(
        String(4),
        ForeignKey(f"{SCHEMA}.PreprocessorTask.task_id"),
        nullable=True,
    )
    spawn_reason = Column(String(50), nullable=True)  # e.g. ERROR_PC1_SPLIT

    # Audit
    created_by = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=ny_now)
    updated_at = Column(DateTime, default=ny_now, onupdate=ny_now)

    # Relationships
    items = relationship("TaskItem", back_populates="task", cascade="all, delete-orphan")
    errors = relationship("PreCheckError", back_populates="task", cascade="all, delete-orphan")
    matches = relationship("MatchResult", back_populates="task", cascade="all, delete-orphan")
    item_match_candidates = relationship("ItemMatchCandidate", back_populates="task", cascade="all, delete-orphan")
    status_log = relationship("TaskStatusLog", back_populates="task", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "intake_mode": self.intake_mode,
            "contract_number": self.contract_number,
            "vendor_id": self.vendor_id,
            "purchase_from_loc": self.purchase_from_loc,
            "erp_vendor_name": self.erp_vendor_name,
            "purchase_from_loc_name": self.purchase_from_loc_name,
            "process_type": self.process_type,
            "source_type": self.source_type,
            "organization": self.organization,
            "oem_name": self.oem_name,
            "intention": self.intention,
            "mixed_intention": self.mixed_intention,
            "contract_start_date": str(self.contract_start_date) if self.contract_start_date else None,
            "contract_end_date": str(self.contract_end_date) if self.contract_end_date else None,
            "notes": self.notes,
            "wrike_id": self.wrike_id,
            "contract_manufacturer_infor": self.contract_manufacturer_infor,
            "contract_manufacturer_name_infor": self.contract_manufacturer_name_infor,
            "precheck_mode": self.precheck_mode,
            "phase": self.phase,
            "status": self.status,
            "parent_task_id": self.parent_task_id,
            "spawn_reason": self.spawn_reason,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# TaskItem — individual line items belonging to a task
# ---------------------------------------------------------------------------
class TaskItem(Base):
    __tablename__ = "PreprocessorTaskItem"
    __table_args__ = (
        Index("ix_taskitem_task_id", "task_id"),
        {"schema": SCHEMA},
    )

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(4), ForeignKey(f"{SCHEMA}.PreprocessorTask.task_id"), nullable=False)

    vendor_catalog_num = Column(String(255), nullable=True)
    mfg_catalog_num = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    standardized_description = Column(Text, nullable=True)
    uom = Column(String(50), nullable=False)
    unit_price = Column(Numeric(18, 4), nullable=False)
    qoe = Column(Integer, nullable=False)
    intention = Column(String(10), nullable=True)  # per-item if MIX
    tier_description = Column(String(255), nullable=True)
    tier_level = Column(String(50), nullable=True)

    # Status tracking
    status = Column(String(50), nullable=False, default="UPLOADED")
    error_message = Column(Text, nullable=True)

    # Data source & linkage
    source_dataset = Column(String(10), nullable=False, default="INPUT")  # INPUT | CCX | INFOR
    infor_item_number = Column(String(255), nullable=True)
    contract_line_infor_item_number = Column(String(50), nullable=True)
    infor_sync_flag = Column(String(20), nullable=True)  # SYNCED | UNSYNCED

    # Reduced catalog numbers (for matching)
    reduced_mfg_num = Column(String(255), nullable=True)
    reduced_vendor_num = Column(String(255), nullable=True)

    # Infor manufacturer linkage
    manufacturer_infor = Column(String(20), nullable=True)
    manufacturer_name_infor = Column(String(255), nullable=True)

    # Phase 3 — linkage & Infor item labeling
    input_reference = Column(Integer, nullable=True)  # FK to originating INPUT item_id
    vendor_id_short = Column(String(10), nullable=True)  # left(7) of ERPVendorID or VendorID
    uom_to_match_infor = Column(String(10), nullable=True)  # EDI-translated UOM
    infor_item_1 = Column(String(255), nullable=True)  # Item# from MDM_ITEM (Mfg+MfgNum)
    infor_item_1_active = Column(String(5), nullable=True)
    infor_item_2 = Column(String(255), nullable=True)  # Item# from MDM_VENDORITEM (Vendor+VendorItem)
    infor_item_2_active = Column(String(5), nullable=True)
    infor_item_3 = Column(String(255), nullable=True)  # Item# from TP Infor CL match
    infor_item_3_active = Column(String(30), nullable=True)
    infor_buy_uom_options = Column(String(500), nullable=True)  # e.g. "BX*5, PK*10"
    ccx_pkid = Column(Integer, nullable=True)
    infor_pkid = Column(String(31), nullable=True)
    organization_eid = Column(String(10), nullable=True)
    organization_type = Column(String(10), nullable=True)  # MHS | ENTITY
    contract_manufacturer = Column(String(10), nullable=True)  # 4-digit code, contract level
    mfg_name_infor_line = Column(String(255), nullable=True)
    mfg_name_infor_contract = Column(String(255), nullable=True)
    vendor_name_infor = Column(String(255), nullable=True)
    contract_id = Column(String(100), nullable=True)  # for CCX/INFOR sourced rows
    item_price_start_date = Column(Date, nullable=True)
    item_price_end_date = Column(Date, nullable=True)

    # Row tracking
    file_row = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=ny_now)
    updated_at = Column(DateTime, default=ny_now, onupdate=ny_now)

    task = relationship("Task", back_populates="items")
    item_match_candidates = relationship("ItemMatchCandidate", back_populates="item", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "task_id": self.task_id,
            "vendor_catalog_num": self.vendor_catalog_num,
            "mfg_catalog_num": self.mfg_catalog_num,
            "description": self.description,
            "standardized_description": self.standardized_description,
            "uom": self.uom,
            "unit_price": float(self.unit_price) if self.unit_price is not None else None,
            "qoe": self.qoe,
            "intention": self.intention,
            "tier_description": self.tier_description,
            "tier_level": self.tier_level,
            "status": self.status,
            "error_message": self.error_message,
            "source_dataset": self.source_dataset,
            "infor_item_number": self.infor_item_number,
            "infor_sync_flag": self.infor_sync_flag,
            "manufacturer_infor": self.manufacturer_infor,
            "manufacturer_name_infor": self.manufacturer_name_infor,
            "file_row": self.file_row,
            "input_reference": self.input_reference,
            "vendor_id_short": self.vendor_id_short,
            "uom_to_match_infor": self.uom_to_match_infor,
            "infor_item_1": self.infor_item_1,
            "infor_item_1_active": self.infor_item_1_active,
            "infor_item_2": self.infor_item_2,
            "infor_item_2_active": self.infor_item_2_active,
            "infor_item_3": self.infor_item_3,
            "infor_item_3_active": self.infor_item_3_active,
            "infor_buy_uom_options": self.infor_buy_uom_options,
            "ccx_pkid": self.ccx_pkid,
            "infor_pkid": self.infor_pkid,
            "organization_eid": self.organization_eid,
            "organization_type": self.organization_type,
            "contract_manufacturer": self.contract_manufacturer,
            "mfg_name_infor_line": self.mfg_name_infor_line,
            "mfg_name_infor_contract": self.mfg_name_infor_contract,
            "vendor_name_infor": self.vendor_name_infor,
            "contract_id": self.contract_id,
            "item_price_start_date": str(self.item_price_start_date) if self.item_price_start_date else None,
            "item_price_end_date": str(self.item_price_end_date) if self.item_price_end_date else None,
        }


# ---------------------------------------------------------------------------
# PreCheckError — validation errors from PC1 / PC2
# ---------------------------------------------------------------------------
class PreCheckError(Base):
    __tablename__ = "PreprocessorPreCheckError"
    __table_args__ = (
        Index("ix_pcerror_task_id", "task_id"),
        {"schema": SCHEMA},
    )

    error_id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(4), ForeignKey(f"{SCHEMA}.PreprocessorTask.task_id"), nullable=False)
    item_id = Column(Integer, ForeignKey(f"{SCHEMA}.PreprocessorTaskItem.item_id"), nullable=True)

    phase = Column(String(5), nullable=False)  # PC1 | PC2
    error_type = Column(String(100), nullable=False)
    error_detail = Column(Text, nullable=True)

    resolved = Column(Boolean, default=False)
    resolved_by = Column(String(120), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=ny_now)

    task = relationship("Task", back_populates="errors")

    def to_dict(self) -> dict:
        return {
            "error_id": self.error_id,
            "task_id": self.task_id,
            "item_id": self.item_id,
            "phase": self.phase,
            "error_type": self.error_type,
            "error_detail": self.error_detail,
            "resolved": self.resolved,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


# ---------------------------------------------------------------------------
# MatchResult — duplicate / item master matching outcomes
# ---------------------------------------------------------------------------
class MatchResult(Base):
    __tablename__ = "PreprocessorMatchResult"
    __table_args__ = (
        Index("ix_match_task_id", "task_id"),
        {"schema": SCHEMA},
    )

    match_id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(4), ForeignKey(f"{SCHEMA}.PreprocessorTask.task_id"), nullable=False)
    input_item_id = Column(Integer, ForeignKey(f"{SCHEMA}.PreprocessorTaskItem.item_id"), nullable=False)

    matched_source = Column(String(20), nullable=False)  # CCX | INFOR_CL | INFOR_IM
    matched_item_ref = Column(String(255), nullable=True)
    similarity_score = Column(Float, nullable=True)
    similarity_bucket = Column(String(10), nullable=True)  # HIGH | MED | LOW

    match_status = Column(String(20), nullable=False, default="PENDING")  # PENDING | ACCEPTED | REJECTED | LLM_REVIEW
    reviewed_by = Column(String(120), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    llm_confidence = Column(Integer, nullable=True)
    llm_reason = Column(Text, nullable=True)
    dedup_decision = Column(String(20), nullable=True)  # UPLOAD | EXPIRE | KEEP_AS_IS
    dedup_decided_by = Column(String(120), nullable=True)
    dedup_decided_at = Column(DateTime, nullable=True)

    # Phase 3 — contract grouping and match details
    contract_number = Column(String(100), nullable=True)
    match_type = Column(String(20), nullable=True)  # EXACT_MFG | REDUCED_MFG | REDUCED_VPN | CROSS_MATCH
    ccx_pkid = Column(Integer, nullable=True)
    ccx_pkids_matched = Column(String(255), nullable=True)
    infor_pkids_matched = Column(String(255), nullable=True)
    infor_pkid = Column(String(31), nullable=True)
    contract_id_matched = Column(String(100), nullable=True)
    organization_eid_matched = Column(String(10), nullable=True)
    organization_matched = Column(String(100), nullable=True)
    manufacturer_number_matched = Column(String(255), nullable=True)
    uom_matched = Column(String(10), nullable=True)
    erp_vendor_id_matched = Column(String(20), nullable=True)
    vendor_item_matched = Column(String(255), nullable=True)
    uom_to_match_infor_matched = Column(String(10), nullable=True)
    qoe_matched = Column(Integer, nullable=True)
    contract_price_matched = Column(Numeric(18, 4), nullable=True)
    item_desc_matched = Column(String(500), nullable=True)

    # Scoring detail columns
    mfn_score = Column(Float, nullable=True)
    mfn_complexity = Column(Float, nullable=True)
    uom_score = Column(Float, nullable=True)
    qoe_score = Column(Float, nullable=True)
    price_score = Column(Float, nullable=True)
    price_diff_pct = Column(Float, nullable=True)
    desc_score = Column(Float, nullable=True)
    weighted_score = Column(Float, nullable=True)
    match_ea_price = Column(Float, nullable=True)
    input_ea_price = Column(Float, nullable=True)
    pair_type = Column(String(1), nullable=True)  # A | B | C | D
    vendor_item_score = Column(Float, nullable=True)
    # 'Yes' when same-contract match has identical QOE but a different UOM
    # (UOM inconsistency for the same pack size). Cascaded from CCX to INFOR_CL.
    uom_nuance = Column(String(3), nullable=True)  # 'Yes' | 'No'

    created_at = Column(DateTime, default=ny_now)

    task = relationship("Task", back_populates="matches")

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "task_id": self.task_id,
            "input_item_id": self.input_item_id,
            "matched_source": self.matched_source,
            "matched_item_ref": self.matched_item_ref,
            "similarity_score": self.similarity_score,
            "similarity_bucket": self.similarity_bucket,
            "match_status": self.match_status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "llm_confidence": self.llm_confidence,
            "llm_reason": self.llm_reason,
            "dedup_decision": self.dedup_decision,
            "dedup_decided_by": self.dedup_decided_by,
            "dedup_decided_at": self.dedup_decided_at.isoformat() if self.dedup_decided_at else None,
            "contract_number": self.contract_number,
            "match_type": self.match_type,
            "ccx_pkid": self.ccx_pkid,
            "ccx_pkids_matched": self.ccx_pkids_matched,
            "infor_pkids_matched": self.infor_pkids_matched,
            "infor_pkid": self.infor_pkid,
            "contract_id_matched": self.contract_id_matched,
            "organization_eid_matched": self.organization_eid_matched,
            "organization_matched": self.organization_matched,
            "manufacturer_number_matched": self.manufacturer_number_matched,
            "uom_matched": self.uom_matched,
            "erp_vendor_id_matched": self.erp_vendor_id_matched,
            "vendor_item_matched": self.vendor_item_matched,
            "uom_to_match_infor_matched": self.uom_to_match_infor_matched,
            "qoe_matched": self.qoe_matched,
            "contract_price_matched": float(self.contract_price_matched) if self.contract_price_matched is not None else None,
            "item_desc_matched": self.item_desc_matched,
            "mfn_score": self.mfn_score,
            "mfn_complexity": self.mfn_complexity,
            "uom_score": self.uom_score,
            "qoe_score": self.qoe_score,
            "price_score": self.price_score,
            "price_diff_pct": self.price_diff_pct,
            "desc_score": self.desc_score,
            "weighted_score": self.weighted_score,
            "match_ea_price": self.match_ea_price,
            "input_ea_price": self.input_ea_price,
            "pair_type": self.pair_type,
            "vendor_item_score": self.vendor_item_score,
            "uom_nuance": self.uom_nuance,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# ItemMatchCandidate — exploded 1-row-per-Infor-item match candidates
# ---------------------------------------------------------------------------
class ItemMatchCandidate(Base):
    __tablename__ = "PreprocessorItemMatching"
    __table_args__ = (
        Index("ix_itemmatch_task_id", "task_id"),
        Index("ix_itemmatch_item_id", "item_id"),
        {"schema": SCHEMA},
    )

    match_item_id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(4), ForeignKey(f"{SCHEMA}.PreprocessorTask.task_id"), nullable=False)
    item_id = Column(Integer, ForeignKey(f"{SCHEMA}.PreprocessorTaskItem.item_id"), nullable=False)
    infor_item_number = Column(String(20), nullable=False)
    item_description = Column(Text, nullable=True)
    infor_buy_uom_options = Column(String(500), nullable=True)
    active_gtin = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=ny_now)
    updated_at = Column(DateTime, default=ny_now, onupdate=ny_now)

    task = relationship("Task", back_populates="item_match_candidates")
    item = relationship("TaskItem", back_populates="item_match_candidates")

    def to_dict(self) -> dict:
        return {
            "match_item_id": self.match_item_id,
            "task_id": self.task_id,
            "item_id": self.item_id,
            "infor_item_number": self.infor_item_number,
            "item_description": self.item_description,
            "infor_buy_uom_options": self.infor_buy_uom_options,
            "active_gtin": self.active_gtin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# PreprocessIssue — per-item issues raised in Phase 3 (BUY_UOM, MULTI_ITEM)
# ---------------------------------------------------------------------------
class PreprocessIssue(Base):
    __tablename__ = "PreprocessorPreprocessIssue"
    __table_args__ = (
        Index("ix_preprocissue_task_id", "task_id"),
        Index("ix_preprocissue_item_id", "item_id"),
        {"schema": SCHEMA},
    )

    issue_id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(4), ForeignKey(f"{SCHEMA}.PreprocessorTask.task_id"), nullable=False)
    item_id = Column(Integer, ForeignKey(f"{SCHEMA}.PreprocessorTaskItem.item_id"), nullable=False)

    issue_type = Column(String(40), nullable=False)   # BUY_UOM_ERROR | MULTI_ITEM_ERROR
    severity = Column(String(10), nullable=False)     # ERROR | WARN
    detail = Column(Text, nullable=True)              # JSON payload

    resolved = Column(Boolean, default=False, nullable=False)
    resolved_by = Column(String(120), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_action = Column(String(40), nullable=True)  # PICK_ITEM | NOTE | RECHECK_PASSED | IGNORE_EXPIRE

    created_at = Column(DateTime, default=ny_now)
    updated_at = Column(DateTime, default=ny_now, onupdate=ny_now)

    def to_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "task_id": self.task_id,
            "item_id": self.item_id,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "detail": self.detail,
            "resolved": self.resolved,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_action": self.resolution_action,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# TaskStatusLog — audit trail: who moved a task between phases/statuses
# ---------------------------------------------------------------------------
class TaskStatusLog(Base):
    __tablename__ = "PreprocessorTaskStatusLog"
    __table_args__ = (
        Index("ix_statuslog_task_id", "task_id"),
        {"schema": SCHEMA},
    )

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(4), ForeignKey(f"{SCHEMA}.PreprocessorTask.task_id"), nullable=False)
    old_phase = Column(String(30), nullable=True)
    new_phase = Column(String(30), nullable=True)
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=True)
    changed_by = Column(String(120), nullable=False)
    changed_at = Column(DateTime, default=ny_now)
    notes = Column(Text, nullable=True)

    task = relationship("Task", back_populates="status_log")


# ---------------------------------------------------------------------------
# User — maps to [Preprocessor].[users] on SQL Server.
# Falls back to in-memory dict when DB is unavailable.
# ---------------------------------------------------------------------------
VALID_ROLES = {"sourcing", "mdm", "preprocessor"}


# ---------------------------------------------------------------------------
# InforVendorLocation — read-only reference table
# ---------------------------------------------------------------------------
class InforVendorLocation(Base):
    __tablename__ = "InforVendorLocation"
    __table_args__ = {"schema": SCHEMA}

    Vendor = Column("Vendor", String(10), primary_key=True)
    VendorName = Column("VendorName", String(255), nullable=False)
    VendorLocation = Column("VendorLocation", String(10), primary_key=True)
    VendorLocationText = Column("VendorLocationText", String(255), nullable=False)
    Status = Column("Status", String(40), nullable=False)
    LocationType = Column("LocationType", String(40), nullable=False)


_USERS: dict[str, dict] = {
    "admin": {
        "user_id": 0,
        "email": "admin@example.com",
        "name": "Administrator",
        "pw_hash": generate_password_hash("admin"),
        "user_role": "preprocessor",
        "is_active": True,
    },
}


class User(UserMixin):
    """User model backed by [Preprocessor].[users] with in-memory fallback."""

    def __init__(
        self,
        email: str,
        name: str = "",
        pw_hash: str = "",
        user_role: str = "sourcing",
        user_id: Optional[int] = None,
        is_active: bool = True,
    ):
        self.user_id = user_id
        self.email = email
        self.name = name or ""
        self.pw_hash = pw_hash
        self.user_role = user_role if user_role in VALID_ROLES else "sourcing"
        self._is_active = is_active
        # Flask-Login uses self.id for session tracking
        self.id = email

    @property
    def is_active(self):
        return self._is_active

    @property
    def role(self):
        return self.user_role

    @property
    def username(self):
        """Backward-compat alias — other blueprints use current_user.username."""
        return self.email

    # --- helpers ---
    @staticmethod
    def _get_connection():
        from flask import current_app

        try:
            engine = current_app.config.get("DB_ENGINE")
            if not engine:
                return None
            return engine.raw_connection()
        except Exception as e:
            print(f"User model DB connection error: {e}")
            return None

    @classmethod
    def _from_row(cls, columns, row):
        """Build a User from a cursor row + column names."""
        if not row:
            return None
        d = dict(zip(columns, row))
        return cls(
            user_id=d.get("user_id"),
            email=d.get("email", ""),
            name=d.get("name", ""),
            pw_hash=d.get("pw_hash", ""),
            user_role=d.get("user_role", "sourcing"),
            is_active=bool(d.get("is_active", True)),
        )

    @classmethod
    def _from_dict(cls, d: dict):
        return cls(
            user_id=d.get("user_id"),
            email=d["email"],
            name=d.get("name", ""),
            pw_hash=d.get("pw_hash", ""),
            user_role=d.get("user_role", "sourcing"),
            is_active=d.get("is_active", True),
        )

    # --- CRUD ---
    @classmethod
    def create(cls, email: str, password: str, name: str = "", role: str = "sourcing", **_kw):
        """Insert a new user. Returns (success: bool, message: str)."""
        role = role.lower().strip()
        if role not in VALID_ROLES:
            return False, "Invalid role selected"

        # Check for duplicate
        if cls.get_by_email(email):
            return False, "A user with that email already exists"

        pw_hash = generate_password_hash(password)

        conn = cls._get_connection()
        if conn is None:
            # In-memory fallback
            _USERS[email.lower()] = {
                "email": email,
                "name": name,
                "pw_hash": pw_hash,
                "user_role": role,
                "is_active": True,
            }
            return True, "Registration successful"

        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                INSERT INTO [{SCHEMA}].[users]
                    (email, name, user_role, pw_hash, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, GETDATE())
                """,
                (email, name, role, pw_hash),
            )
            conn.commit()
            return True, "Registration successful"
        except Exception as e:
            print(f"User.create DB error: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return False, f"Registration failed: {e}"
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @classmethod
    def get(cls, user_id: str):
        """Lookup by email (used by Flask-Login's user_loader)."""
        conn = cls._get_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT user_id, email, name, pw_hash, user_role, is_active "
                    f"FROM [{SCHEMA}].[users] WHERE email = ?",
                    (user_id,),
                )
                row = cursor.fetchone()
                if row:
                    cols = [c[0] for c in cursor.description]
                    return cls._from_row(cols, row)
            except Exception as e:
                print(f"User.get DB error: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        d = _USERS.get(user_id) or _USERS.get(str(user_id).lower())
        if d:
            return cls._from_dict(d)
        return None

    @classmethod
    def get_by_email(cls, email: str):
        """Lookup by email address."""
        conn = cls._get_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT user_id, email, name, pw_hash, user_role, is_active "
                    f"FROM [{SCHEMA}].[users] WHERE email = ?",
                    (email,),
                )
                row = cursor.fetchone()
                if row:
                    cols = [c[0] for c in cursor.description]
                    return cls._from_row(cols, row)
            except Exception as e:
                print(f"User.get_by_email DB error: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        for u in _USERS.values():
            if u["email"].lower() == email.lower():
                return cls._from_dict(u)
        return None

    @classmethod
    def get_by_username(cls, username: str):
        """Alias — with the new schema the identifier is email."""
        return cls.get_by_email(username)

    @classmethod
    def check_password(cls, email: str, password: str):
        """Verify credentials. Returns (success: bool, message: str)."""
        user = cls.get_by_email(email)
        if not user:
            return False, "Invalid email or password"
        if not user._is_active:
            return False, "Account is disabled. Contact an administrator."
        if check_password_hash(user.pw_hash, password):
            # Update last_login_at
            conn = cls._get_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        f"UPDATE [{SCHEMA}].[users] SET last_login_at = GETDATE() WHERE email = ?",
                        (email,),
                    )
                    conn.commit()
                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
            return True, "Login successful"
        return False, "Invalid email or password"

    @classmethod
    def get_all(cls):
        """Return all users (for admin panel)."""
        conn = cls._get_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT user_id, email, name, pw_hash, user_role, is_active "
                    f"FROM [{SCHEMA}].[users] ORDER BY created_at DESC",
                )
                cols = [c[0] for c in cursor.description]
                return [cls._from_row(cols, r) for r in cursor.fetchall()]
            except Exception as e:
                print(f"User.get_all DB error: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        return [cls._from_dict(d) for d in _USERS.values()]

    @staticmethod
    def hash_password(password: str) -> str:
        return generate_password_hash(password)
