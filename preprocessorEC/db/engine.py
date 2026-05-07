"""Database engine setup — SQL Server (primary) + SQLite (working state & sessions).

Usage from app factory:
    from preprocessorEC.db.engine import init_engines
    init_engines(app)

Then anywhere:
    from preprocessorEC.db.engine import get_sqlserver_engine, get_sqlite_engine
"""

from __future__ import annotations

import os
from sqlalchemy import create_engine, event
from sqlalchemy.pool import QueuePool, StaticPool

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
        connect_args={"check_same_thread": False},
    )

    # Enable WAL mode for better concurrent reads
    @event.listens_for(_sqlite_workstate_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
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


def get_sqlserver_connection():
    """Get a raw DBAPI connection from the SQL Server pool.

    Caller is responsible for closing it.
    """
    engine = get_sqlserver_engine()
    return engine.raw_connection()
