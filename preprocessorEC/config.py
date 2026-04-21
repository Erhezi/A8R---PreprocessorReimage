import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _env_flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


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

    # ── Sentence Transformer ────────────────────────────────────────
    MODEL_NAME = "all-MiniLM-L6-v2"

    # ── LLM / OpenAI ───────────────────────────────────────────────
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    OPENAI_TIMEOUT_SECONDS = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "30"))
    OPENAI_MAX_RETRIES = int(os.environ.get("OPENAI_MAX_RETRIES", "2"))
    OPENAI_DISABLE_SSL_VERIFY = _env_flag("OPENAI_DISABLE_SSL_VERIFY")
    OPENAI_ORGANIZATION = os.environ.get("OPENAI_ORGANIZATION", "").strip()
    OPENAI_PROJECT = os.environ.get("OPENAI_PROJECT", "").strip()
    AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
    AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "").strip()
    LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1024"))
    LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.0"))

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
