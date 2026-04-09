"""Application Factory for preprocessorEC — task-centric, LangGraph-ready.

Replaces the original StepManager-based factory.
Registers new phase-based blueprints, initialises SQLite engines,
and configures Flask-Session with SQLAlchemy/SQLite backend.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask, redirect, url_for, render_template
from flask_login import LoginManager, current_user


def create_app(config_name: str | None = None, test_config: dict | None = None) -> Flask:
    """Create and configure the Flask application."""

    # ── Determine URL prefix ────────────────────────────────────────
    if config_name == "production":
        url_prefix = os.environ.get("URL_PREFIX", "/preprocessor")
    else:
        url_prefix = ""

    app = Flask(__name__, static_url_path=f"{url_prefix}/static")

    # ── Load configuration ──────────────────────────────────────────
    if test_config is None:
        from .config import get_config

        config = get_config(config_name)
        app.config.from_object(config)
    else:
        app.config.from_mapping(test_config)

    app.config["URL_PREFIX"] = url_prefix

    # ── Ensure instance directory ───────────────────────────────────
    instance_dir = app.config.get("INSTANCE_DIR", os.path.join(app.root_path, "instance"))
    os.makedirs(instance_dir, exist_ok=True)

    # ── Logging (production) ────────────────────────────────────────
    if config_name == "production":
        os.makedirs("logs", exist_ok=True)
        handler = RotatingFileHandler("logs/preprocessor.log", maxBytes=10_240_000, backupCount=10)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]")
        )
        handler.setLevel(logging.INFO)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info("Preprocessor startup")

    # ── Flask-Session (SQLite) ──────────────────────────────────────
    from .common.session import init_session

    init_session(app)

    # ── Database engines ────────────────────────────────────────────
    from .db.engine import init_engines

    init_engines(app)

    # ── SQLite working-state tables ─────────────────────────────────
    from .db.workstate_repo import init_workstate_tables

    init_workstate_tables()

    # ── Login manager ───────────────────────────────────────────────
    login_manager = LoginManager()
    login_manager.login_view = "auth.landing"
    login_manager.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.get(user_id)

    # ── Register blueprints ─────────────────────────────────────────
    from .auth import auth_blueprint
    from .tasks import tasks_bp
    from .intake import intake_bp
    from .identity import identity_bp
    from .preprocess import preprocess_bp
    from .dedup import dedup_bp
    from .export import export_bp
    from .monitoring import monitoring_bp
    from .admin import admin_blueprint

    app.register_blueprint(auth_blueprint, url_prefix=f"{url_prefix}/auth")
    app.register_blueprint(tasks_bp, url_prefix=url_prefix)
    app.register_blueprint(intake_bp, url_prefix=url_prefix)
    app.register_blueprint(identity_bp, url_prefix=url_prefix)
    app.register_blueprint(preprocess_bp, url_prefix=url_prefix)
    app.register_blueprint(dedup_bp, url_prefix=url_prefix)
    app.register_blueprint(export_bp, url_prefix=url_prefix)
    app.register_blueprint(monitoring_bp, url_prefix=url_prefix)
    app.register_blueprint(admin_blueprint, url_prefix=url_prefix)

    # ── Context processors ──────────────────────────────────────────
    @app.context_processor
    def inject_url_prefix():
        return {"url_prefix": app.config.get("URL_PREFIX", "")}

    # ── Root redirect ───────────────────────────────────────────────
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("tasks.task_list"))
        return redirect(url_for("auth.landing"))

    # ── Sentence Transformer (lazy) ─────────────────────────────────
    app.config["TRANSFORMER_MODEL_LOADING"] = False
    app.config["TRANSFORMER_MODEL_LOADED"] = False

    with app.app_context():
        _load_transformer_model(app)

    return app


def _load_transformer_model(app: Flask) -> None:
    """Load sentence transformer model — best-effort, non-blocking."""
    try:
        app.config["TRANSFORMER_MODEL_LOADING"] = True
        model_name = app.config.get("MODEL_NAME", "all-MiniLM-L6-v2")
        local_path = os.path.join(app.root_path, "models", model_name)

        from sentence_transformers import SentenceTransformer

        if os.path.exists(local_path):
            model = SentenceTransformer(local_path)
        else:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            # Disable SSL verification for corporate networks with self-signed certs
            _old_env = {k: os.environ.get(k) for k in ("CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE")}
            os.environ["CURL_CA_BUNDLE"] = ""
            os.environ["REQUESTS_CA_BUNDLE"] = ""
            try:
                model = SentenceTransformer(model_name)
                model.save(local_path)
            finally:
                for k, v in _old_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

        app.config["TRANSFORMER_MODEL"] = model
        app.config["TRANSFORMER_MODEL_LOADED"] = True
    except ImportError:
        app.logger.warning("sentence-transformers not installed; fallback similarity will be used.")
        app.config["TRANSFORMER_MODEL"] = None
        app.config["TRANSFORMER_MODEL_LOADED"] = False
    except Exception as exc:
        app.logger.error(f"Error loading transformer model: {exc}")
        app.config["TRANSFORMER_MODEL"] = None
        app.config["TRANSFORMER_MODEL_LOADED"] = False
    finally:
        app.config["TRANSFORMER_MODEL_LOADING"] = False
