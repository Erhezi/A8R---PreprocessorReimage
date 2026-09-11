"""Database engine setup — SQL Server (primary) + SQLite (working state & sessions).

Usage from app factory:
    from preprocessorEC.db.engine import init_engines
    init_engines(app)

Then anywhere:
    from preprocessorEC.db.engine import get_sqlserver_engine, get_sqlite_engine
"""

from __future__ import annotations

import logging
import os
import time
from sqlalchemy import create_engine, event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import QueuePool, StaticPool

logger = logging.getLogger(__name__)

_DISCONNECT_ATTEMPTS = 3
_DISCONNECT_BACKOFF_SECONDS = 0.5

# Module-level engine singletons — set by init_engines()
_sqlserver_engine = None
_sqlite_workstate_engine = None


def init_engines(app) -> None:
    """Initialise both database engines from Flask app config.

    Called once during app factory ``create_app()``.
    """
    global _sqlserver_engine, _sqlite_workstate_engine

    # --- SQL Server (primary data store) ---
    # fast_executemany packs executemany() params into one TDS round-trip.
    # Without it, bulk_insert_mappings/bulk_update_mappings still issue one
    # round-trip per row over pyodbc, which is what made PC1 take ~20 min on
    # 5,000-row uploads. Toggle off via DB_FAST_EXECUTEMANY=False if a driver
    # version regression appears.
    _sqlserver_engine = create_engine(
        app.config["DB_CONN_STRING"],
        poolclass=QueuePool,
        pool_size=app.config.get("DB_POOL_SIZE", 10),
        max_overflow=app.config.get("DB_MAX_OVERFLOW", 20),
        pool_pre_ping=app.config.get("DB_POOL_PRE_PING", True),
        # Retire connections before a network device silently drops an idle
        # one. pool_pre_ping catches a corpse at checkout; recycling keeps us
        # from handing out one that is about to die mid-statement.
        pool_recycle=app.config.get("DB_POOL_RECYCLE", 1800),
        fast_executemany=app.config.get("DB_FAST_EXECUTEMANY", True),
    )
    # Keep backward compat: old code reads app.config['DB_ENGINE']
    app.config["DB_ENGINE"] = _sqlserver_engine

    # --- SQLite — working state ---
    instance_dir = app.config.get(
        "INSTANCE_DIR",
        os.path.join(os.path.abspath(os.path.dirname(os.path.dirname(__file__))), "instance"),
    )
    os.makedirs(instance_dir, exist_ok=True)

    workstate_path = os.path.join(instance_dir, "workstate.db")
    _sqlite_workstate_engine = create_engine(
        f"sqlite:///{workstate_path}",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    # Enable WAL mode for better concurrent reads
    @event.listens_for(_sqlite_workstate_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Store on app config for convenience
    app.config["SQLITE_WORKSTATE_ENGINE"] = _sqlite_workstate_engine
    app.config["INSTANCE_DIR"] = instance_dir


def get_sqlserver_engine():
    """Return the SQL Server engine (call after init_engines)."""
    if _sqlserver_engine is None:
        raise RuntimeError("SQL Server engine not initialised. Call init_engines() first.")
    return _sqlserver_engine


def get_sqlite_engine():
    """Return the SQLite working-state engine (call after init_engines)."""
    if _sqlite_workstate_engine is None:
        raise RuntimeError("SQLite engine not initialised. Call init_engines() first.")
    return _sqlite_workstate_engine


def with_disconnect_retry(operation, *, attempts: int = _DISCONNECT_ATTEMPTS):
    """Run ``operation`` again if the SQL Server connection drops under it.

    A reset link surfaces as ODBC 08S01 ("Communication link failure",
    WinSock 10054) and can land mid-statement — while rows are still being
    fetched — which ``pool_pre_ping`` cannot prevent because it only
    validates at checkout. SQLAlchemy invalidates the whole pool generation
    on such an error, so the retry opens a genuinely new connection.

    ``operation`` must open its own session: the one it was running on is
    dead. Only safe for read-only or otherwise idempotent work — a write
    that died mid-flight may or may not have committed.
    """
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except DBAPIError as exc:
            if attempt >= attempts or not exc.connection_invalidated:
                raise
            delay = _DISCONNECT_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "SQL Server connection dropped on attempt %d/%d; "
                "retrying in %.1fs. (%s)",
                attempt,
                attempts,
                delay,
                exc.orig,
            )
            time.sleep(delay)


def get_sqlserver_connection():
    """Get a raw DBAPI connection from the SQL Server pool.

    Caller is responsible for closing it.
    """
    engine = get_sqlserver_engine()
    return engine.raw_connection()
