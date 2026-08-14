import os
from pathlib import Path
from datetime import timedelta
from dotenv import dotenv_values, load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_ENV_FILE_VALUES = dotenv_values(_ENV_PATH)

load_dotenv(_ENV_PATH)


def _config_env(name: str, default: str = "") -> str:
    value = _ENV_FILE_VALUES.get(name)
    if value is not None:
        return value
    return os.environ.get(name, default)


def _env_flag(name: str, default: str = "false") -> bool:
    return _config_env(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")

    # ── SQL Server ──────────────────────────────────────────────────
    DB_POOL_SIZE = 10
    DB_MAX_OVERFLOW = 20
    DB_POOL_PRE_PING = True

    @property
    def DB_CONN_STRING(self):
        return (
            "mssql+pyodbc:///?odbc_connect="
            "DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=MISCPrdAdhocDB;"
            "DATABASE=PRIME;"
            "Trusted_Connection=yes;"
        )

    # ── SQLite (working state + sessions) ───────────────────────────
    INSTANCE_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "instance")
    SQLITE_WORKSTATE_PATH = os.path.join(INSTANCE_DIR, "workstate.db")
    SQLITE_SESSION_PATH = os.path.join(INSTANCE_DIR, "session.db")

    # ── Flask-Session (SQLite-backed) ───────────────────────────────
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_REFRESH_EACH_REQUEST = False

    # ── Sentence Transformer ────────────────────────────────────────
    MODEL_NAME = "all-MiniLM-L6-v2"

    # ── LLM / OpenAI ───────────────────────────────────────────────
    OPENAI_API_KEY = _config_env("OPENAI_API_KEY", "")
    OPENAI_MODEL = _config_env("OPENAI_MODEL", "gpt-5.4-mini")
    OPENAI_BASE_URL = _config_env("OPENAI_BASE_URL", "").strip().rstrip("/")
    OPENAI_TIMEOUT_SECONDS = float(_config_env("OPENAI_TIMEOUT_SECONDS", "30"))
    OPENAI_MAX_RETRIES = int(_config_env("OPENAI_MAX_RETRIES", "2"))
    OPENAI_CA_BUNDLE = _config_env("OPENAI_CA_BUNDLE", "").strip()
    OPENAI_USE_SYSTEM_CA_STORE = _env_flag(
        "OPENAI_USE_SYSTEM_CA_STORE",
        "true" if os.name == "nt" else "false",
    )
    OPENAI_DISABLE_SSL_VERIFY = _env_flag("OPENAI_DISABLE_SSL_VERIFY")
    OPENAI_ORGANIZATION = _config_env("OPENAI_ORGANIZATION", "").strip()
    OPENAI_PROJECT = _config_env("OPENAI_PROJECT", "").strip()
    AZURE_OPENAI_ENDPOINT = _config_env("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
    AZURE_OPENAI_API_VERSION = _config_env("AZURE_OPENAI_API_VERSION", "").strip()
    LLM_MAX_TOKENS = int(_config_env("LLM_MAX_TOKENS", "1024"))
    LLM_TEMPERATURE = float(_config_env("LLM_TEMPERATURE", "0.0"))

    # ── Quick Discovery ────────────────────────────────────────────
    # Hard cap on rows per uploaded discovery set.
    DISCOVERY_MAX_ROWS = int(_config_env("DISCOVERY_MAX_ROWS", "5000"))
    # Pairs judged per /llm/run-slice call. Keep the slice short enough that a
    # single HTTP request finishes well inside any proxy timeout.
    DISCOVERY_LLM_SLICE = int(_config_env("DISCOVERY_LLM_SLICE", "50"))
    # Concurrent LLM calls within one slice.
    DISCOVERY_LLM_WORKERS = int(_config_env("DISCOVERY_LLM_WORKERS", "8"))

    # ── URL Prefix ─────────────────────────────────────────────────
    URL_PREFIX = os.environ.get("URL_PREFIX", "")


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    DEBUG = False
    TESTING = True

    @property
    def SQLITE_WORKSTATE_PATH(self):
        import tempfile
        return os.path.join(tempfile.gettempdir(), "test_workstate.db")


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False

    @property
    def SECRET_KEY(self):
        return os.environ.get("SECRET_KEY", super().SECRET_KEY)

    @property
    def URL_PREFIX(self):
        return os.environ.get("URL_PREFIX", "/preprocessor")

    @property
    def DB_CONN_STRING(self):
        driver = os.environ.get("DB_DRIVER", "ODBC Driver 17 for SQL Server")
        server = os.environ.get("DB_SERVER", "MISCPrdAdhocDB")
        database = os.environ.get("DB_NAME", "PRIME")
        return (
            "mssql+pyodbc:///?odbc_connect="
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            "Trusted_Connection=yes;"
        )


def get_config(config_name="default"):
    config_map = {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "production": ProductionConfig,
        "default": DevelopmentConfig,
    }
    return config_map.get(config_name, DevelopmentConfig)()
