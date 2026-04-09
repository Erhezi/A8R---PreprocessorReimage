"""SQLite-backed Flask-Session configuration.

Call `init_session(app)` from the app factory.
"""

from __future__ import annotations

import os

from flask import Flask


def init_session(app: Flask) -> None:
    """Configure Flask-Session to use SQLAlchemy/SQLite backend."""
    from flask_session import Session
    from flask_sqlalchemy import SQLAlchemy

    instance_dir = app.config.get("INSTANCE_DIR", os.path.join(app.root_path, "instance"))
    os.makedirs(instance_dir, exist_ok=True)

    session_db_path = app.config.get(
        "SQLITE_SESSION_PATH",
        os.path.join(instance_dir, "session.db"),
    )

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{session_db_path}"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"check_same_thread": False}}

    session_db = SQLAlchemy(app)

    app.config["SESSION_TYPE"] = "sqlalchemy"
    app.config["SESSION_SQLALCHEMY"] = session_db
    app.config["SESSION_SQLALCHEMY_TABLE"] = "sessions"

    Session(app)
