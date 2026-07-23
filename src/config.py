"""Environment configuration for the private personal assistant."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
_ROOT = Path(__file__).resolve().parents[1]


class Config:
    # Kept only as the default source for the one-time legacy migration.
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{_ROOT / 'budgetbot.db'}")
    PERSONAL_DATA_DIR: str = os.getenv("PERSONAL_DATA_DIR", str(_ROOT / "personal_data"))

    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
    OLLAMA_API_KEY: Optional[str] = os.getenv("OLLAMA_API_KEY")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
    OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "45"))
    OLLAMA_MAX_TOOL_ROUNDS: int = int(os.getenv("OLLAMA_MAX_TOOL_ROUNDS", "4"))
    OLLAMA_MAX_CONCURRENCY: int = max(1, int(os.getenv("OLLAMA_MAX_CONCURRENCY", "4")))

    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_MODE: str = os.getenv("TELEGRAM_MODE", "polling")
    TELEGRAM_WEBHOOK_URL: Optional[str] = os.getenv("TELEGRAM_WEBHOOK_URL")
    TELEGRAM_ALLOWED_USER_IDS: str = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    TELEGRAM_CONCURRENT_UPDATES: int = max(1, int(os.getenv("TELEGRAM_CONCURRENT_UPDATES", "8")))

    AGENT_CLI_USER_ID: str = os.getenv("AGENT_CLI_USER_ID", "default")
    AGENT_TIMEZONE_DEFAULT: str = os.getenv("AGENT_TIMEZONE_DEFAULT", "Asia/Kolkata")
    AGENT_CURRENCY_DEFAULT: str = os.getenv("AGENT_CURRENCY_DEFAULT", "INR")
    AGENT_CONFIRM_AMOUNT_THRESHOLD: float = float(os.getenv("AGENT_CONFIRM_AMOUNT_THRESHOLD", "10000"))
    AGENT_MEMORY_TURNS: int = int(os.getenv("AGENT_MEMORY_TURNS", "8"))

    ENABLE_VOICE_PROCESSING: bool = os.getenv("ENABLE_VOICE_PROCESSING", "True").lower() == "true"
    STT_PROVIDER: str = os.getenv("STT_PROVIDER", "auto")
    STT_MODEL: str = os.getenv("STT_MODEL", "tiny")
    STT_LANGUAGE: str = os.getenv("STT_LANGUAGE", "")
    STT_DEVICE: str = os.getenv("STT_DEVICE", "cpu")
    STT_BASE_URL: Optional[str] = os.getenv("STT_BASE_URL")
    STT_API_KEY: Optional[str] = os.getenv("STT_API_KEY")
    STT_TIMEOUT_SECONDS: int = int(os.getenv("STT_TIMEOUT_SECONDS", "120"))
    STT_SHOW_TRANSCRIPT: bool = os.getenv("STT_SHOW_TRANSCRIPT", "True").lower() == "true"
    STT_MAX_CONCURRENCY: int = max(1, int(os.getenv("STT_MAX_CONCURRENCY", "1")))

    ENABLE_BILL_VISION: bool = os.getenv("ENABLE_BILL_VISION", "True").lower() == "true"
    BILL_IMAGE_MAX_SIDE: int = int(os.getenv("BILL_IMAGE_MAX_SIDE", "1280"))
    BILL_IMAGE_JPEG_QUALITY: int = int(os.getenv("BILL_IMAGE_JPEG_QUALITY", "75"))
    BILL_VISION_MAX_CONCURRENCY: int = max(1, int(os.getenv("BILL_VISION_MAX_CONCURRENCY", "2")))
    UPLOAD_FOLDER: str = os.getenv("UPLOAD_FOLDER", "./uploads")

    _allowlist_cache: set[str] = set()
    _allowlist_mtime: float = -1.0

    @classmethod
    def telegram_allowlist(cls) -> set[str]:
        env_path = Path.cwd() / ".env"
        try:
            mtime = env_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime == cls._allowlist_mtime and cls._allowlist_mtime >= 0:
            return set(cls._allowlist_cache)
        load_dotenv(override=True)
        cls._allowlist_cache = {
            part.strip()
            for part in (os.getenv("TELEGRAM_ALLOWED_USER_IDS") or "").split(",")
            if part.strip()
        }
        cls._allowlist_mtime = mtime
        return set(cls._allowlist_cache)
