"""SQL file loader — reads .sql templates from <module>/queries/<file>.sql.

Returns ``sqlalchemy.text()`` objects ready for execution with named params.

A single .sql file may contain multiple named queries using the convention::

    -- name: my_query
    SELECT ...;

    -- name: another_query
    SELECT ...;

Example usage::

    from preprocessorEC.db.sql_loader import load_query

    # Whole file (single query):
    stmt = load_query("intake", "vendor_validation")

    # Named block inside a multi-query file:
    stmt = load_query("intake", "intake", query="get_valid_uoms")

    result = conn.execute(stmt)
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from sqlalchemy import text

# Root of the preprocessorEC package
_PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _parse_named_blocks(sql_text: str) -> dict[str, str]:
    """Split a SQL file into named blocks using ``-- name: <id>`` markers.

    Returns a dict mapping query name → SQL string. If no markers are found
    the whole file is returned under the key ``"__all__"``.
    """
    blocks: dict[str, str] = {}
    pattern = re.compile(r"--\s*name:\s*(\S+)", re.IGNORECASE)
    parts = pattern.split(sql_text)
    # parts alternates: [preamble, name1, body1, name2, body2, ...]
    if len(parts) == 1:
        blocks["__all__"] = sql_text.strip()
    else:
        it = iter(parts[1:])  # skip preamble
        for name, body in zip(it, it):
            # Strip the first comment line that contains the description
            body_lines = body.strip().splitlines()
            if body_lines and body_lines[0].strip().startswith("--"):
                body_lines = body_lines[1:]
            blocks[name.strip()] = "\n".join(body_lines).strip().rstrip(";")
    return blocks


@lru_cache(maxsize=256)
def _load_file(sql_path: str, mtime_ns: int) -> dict[str, str]:
    """Read and parse a SQL file; cached by path and file modification time."""
    with open(sql_path, "r", encoding="utf-8") as f:
        return _parse_named_blocks(f.read())


def load_query(module: str, file: str, query: str | None = None) -> text:
    """Load a named query from a .sql file and return a ``sqlalchemy.text()``.

    Parameters
    ----------
    module : str
        Module name (e.g. ``"intake"``).
        Maps to ``preprocessorEC/<module>/queries/<file>.sql``.
    file : str
        SQL file name without the ``.sql`` extension.
    query : str, optional
        Named block within the file (``-- name: <query>``).
        If omitted the whole file is used (single-query files).
    """
    sql_path = os.path.join(_PACKAGE_ROOT, module, "queries", f"{file}.sql")
    if not os.path.isfile(sql_path):
        raise FileNotFoundError(
            f"SQL query file not found: {sql_path}. "
            f"Expected at preprocessorEC/{module}/queries/{file}.sql"
        )

    blocks = _load_file(sql_path, os.stat(sql_path).st_mtime_ns)

    if query is None:
        key = "__all__" if "__all__" in blocks else next(iter(blocks))
    else:
        if query not in blocks:
            available = ", ".join(blocks)
            raise KeyError(
                f"Query '{query}' not found in {sql_path}. "
                f"Available: {available}"
            )
        key = query

    return text(blocks[key])


def load_query_raw(module: str, file: str, query: str | None = None) -> str:
    """Load a named query and return the raw SQL string (for pyodbc cursors)."""
    sql_path = os.path.join(_PACKAGE_ROOT, module, "queries", f"{file}.sql")
    if not os.path.isfile(sql_path):
        raise FileNotFoundError(f"SQL query file not found: {sql_path}")

    blocks = _load_file(sql_path, os.stat(sql_path).st_mtime_ns)
    if query is None:
        key = "__all__" if "__all__" in blocks else next(iter(blocks))
    else:
        key = query
    return blocks[key]
