"""Application configuration.

All secrets and machine-specific values come from environment variables
(loaded from the ".env" file). Nothing sensitive is written in the code.
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    """Settings shared by every environment."""

    APP_NAME = "SiteForge AI"
    APP_VERSION = "0.1.0"

    # Used for sessions and CSRF tokens. A random fallback is fine for
    # development, but ProductionConfig refuses to start without a real one.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    # Reject request bodies larger than 1 MB (prompts and JSON are small).
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024
    JSON_SORT_KEYS = False

    # Folder where exported websites are stored.
    GENERATED_WEBSITES_DIR = BASE_DIR / "generated_websites"

    # MySQL (connected in Phase 9).
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "siteforge_ai")
    DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
    DB_CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "5"))
    # Set DATABASE_ENABLED=0 to run without saving projects.
    DATABASE_ENABLED = os.environ.get("DATABASE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")

    # Ollama (connected in Phase 4).
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
    OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    # Tests must never reach a real Ollama. Port 9 is closed on normal machines.
    OLLAMA_BASE_URL = "http://127.0.0.1:9"
    OLLAMA_TIMEOUT = 2
    # Tests must never touch a real database either.
    DATABASE_ENABLED = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    @classmethod
    def validate(cls):
        if not os.environ.get("SECRET_KEY"):
            raise RuntimeError("SECRET_KEY must be set in the environment for production.")


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name=None):
    """Return the config class for the given name (or FLASK_ENV)."""
    name = (name or os.environ.get("FLASK_ENV", "development")).lower()
    config_class = CONFIG_MAP.get(name, DevelopmentConfig)
    if hasattr(config_class, "validate"):
        config_class.validate()
    return config_class
