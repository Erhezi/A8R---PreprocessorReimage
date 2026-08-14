"""Shared utility functions — truly cross-module helpers only.

Domain-specific logic lives in services/.
"""

from __future__ import annotations

from functools import wraps
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import flash, redirect, url_for
from flask_login import current_user

_NY = ZoneInfo("America/New_York")

# SQL Server caps a single statement at 2100 parameters, so any IN (...) clause
# built from a large collection must be issued in batches. Row-wise executemany
# (bulk_insert_mappings and friends) is exempt — this bounds expanding binds only.
SQLSERVER_IN_CHUNK = 1000


def ny_now() -> datetime:
    """Return the current wall-clock time in America/New_York (naive-style, no tzinfo stored)."""
    return datetime.now(_NY).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Organization mapping (display label → DB value → Infor company codes)
# ---------------------------------------------------------------------------
ORG_CHOICES = [
    # (db_value, display_label)
    ("Montefiore Health System (INFOR)", "ALL - Montefiore Health System (INFOR)"),
    ("Montefiore Nyack Hospital (NEW)", "Nyack - Montefiore Nyack Hospital (NEW)"),
    ("White Plains Hospital Center (NEW)", "White Plains - White Plains Hospital Center (NEW)"),
    ("Saint Lukes Cornwall Hospital (NEW)", "St. Luke's - Saint Lukes Cornwall Hospital (NEW)"),
    ("Burke Rehabilitation Hospital (NEW)", "Burke - Burke Rehabilitation Hospital (NEW)"),
    ("Montefiore New Rochelle Hospital Inc (NEW)", "New Rochelle - Montefiore New Rochelle Hospital Inc (NEW)"),
    ("Montefiore Mount Vernon Hospital Inc. (NEW)", "Mount Vernon - Montefiore Mount Vernon Hospital Inc. (NEW)"),
    ("Schaffer Extended Care Center Inc. (NEW)", "Schaffer - Schaffer Extended Care Center Inc. (NEW)"),
]

ORG_MAP = {
    "Montefiore Health System (INFOR)": ["ALL"],
    "Montefiore Nyack Hospital (NEW)": ["Nyack"],
    "White Plains Hospital Center (NEW)": ["White Plains"],
    "Saint Lukes Cornwall Hospital (NEW)": ["St. Luke's"],
    "Burke Rehabilitation Hospital (NEW)": ["Burke"],
    "Montefiore New Rochelle Hospital Inc (NEW)": ["New Rochelle"],
    "Montefiore Mount Vernon Hospital Inc. (NEW)": ["Mount Vernon"],
    "Schaffer Extended Care Center Inc. (NEW)": ["Schaffer"],
}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def clean_text(value: str) -> str:
    """Clean a text value for storage: strip Excel artifacts, control chars,
    special symbols, URL-encoded sequences, combining marks, and non-ASCII
    characters, then collapse whitespace and upper-case."""
    if not isinstance(value, str):
        value = str(value)

    # Remove invisible / zero-width characters common in Excel exports
    value = (
        value
        .replace('\u200b', '')   # zero-width space
        .replace('\u200c', '')   # zero-width non-joiner
        .replace('\u200d', '')   # zero-width joiner
        .replace('\u00a0', ' ')  # non-breaking space → regular space
        .replace('\ufeff', '')   # BOM
        .replace('\u00ad', '')   # soft hyphen
    )

    # Strip URL-encoded sequences (e.g. %09, %02 left by Excel)
    value = re.sub(r'%[0-9A-Fa-f]{2}', '', value)

    # Remove C0/C1 control characters (except ordinary space/tab/newline)
    value = ''.join(ch for ch in value if unicodedata.category(ch)[0] != 'C')

    # Remove common symbol characters (trademark, registered, copyright, etc.)
    value = value.replace('\u2122', '').replace('\u00ae', '').replace('\u00a9', '')

    # Unicode NFKD decomposition + strip combining marks
    value = unicodedata.normalize('NFKD', value)
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))

    # Keep only printable ASCII: letters, digits, space, and common punctuation
    value = ''.join(
        ch for ch in value
        if ch.isascii() and (
            ch.isalpha() or ch.isdigit() or ch.isspace()
            or ch in r"-_.,;:()[]{}#@!+=/\%&'"
        )
    )

    # Collapse all whitespace runs to a single space, strip edges, upper-case
    value = re.sub(r'\s+', ' ', value).strip().upper()
    return value


def reduce_catalog_number(part_num: str) -> str:
    """Reduce a catalog number for matching.

    Decimal-looking values get a leading "." marker after their decimal point
    and trailing zeroes are removed, so Excel-style numeric SKUs stay distinct
    from ordinary numeric catalog numbers.
    """
    if not part_num:
        return ""

    value = str(part_num).strip().upper()
    if re.fullmatch(r"\d+\.\d+", value):
        reduced_decimal = value.rstrip("0").rstrip(".").replace(".", "")
        reduced_decimal = reduced_decimal.lstrip("0") or "0"
        return f".{reduced_decimal}"

    reduced = re.sub(r"[^A-Z0-9]", "", value)
    if reduced.isdigit():
        reduced = reduced.lstrip('0') or '0'
    return reduced


def role_required(*allowed_roles: str):
    """Restrict a route to one or more user roles."""
    allowed = {role.strip().lower() for role in allowed_roles if role and role.strip()}

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            user_role = (getattr(current_user, "role", "") or "").lower()
            if user_role not in allowed:
                flash("You do not have access to that page.", "warning")
                return redirect(url_for("tasks.task_list"))
            return view_func(*args, **kwargs)

        return wrapped

    return decorator
