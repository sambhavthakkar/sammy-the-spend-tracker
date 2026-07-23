"""Speech-to-text providers (Phase 4). Phase 1 stub."""
from __future__ import annotations

from pathlib import Path

from src.config import Config
from src.logging_config import get_logger

logger = get_logger(__name__)


def transcribe(audio_path: Path, language: str | None = None) -> str:
    """
    Transcribe audio file to text.
    Phase 1: not implemented — returns empty and logs.
    """
    provider = (Config.STT_PROVIDER or "none").lower()
    if provider in ("none", "", "off"):
        logger.warning("STT disabled (STT_PROVIDER=none)")
        return ""

    # Phase 4: Ollama / faster-whisper
    logger.warning(f"STT provider '{provider}' not fully wired yet for {audio_path}")
    return ""
