"""
Speech-to-text for BudgetBot voice notes.

Providers:
  auto            — try faster_whisper, then openai-compatible HTTP
  faster_whisper  — local Whisper (pip install faster-whisper)
  openai          — OpenAI-compatible POST /v1/audio/transcriptions
  none            — disabled

Telegram voice is usually OGG/Opus; faster-whisper (via PyAV) and OpenAI both accept it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from src.config import Config
from src.logging_config import get_logger

logger = get_logger(__name__)

_fw_model = None  # cached faster-whisper model


def transcribe(audio_path: Path | str, language: str | None = None) -> str:
    """
    Transcribe an audio file to plain text.
    Returns empty string on failure / disabled.
    """
    path = Path(audio_path)
    if not path.exists() or path.stat().st_size == 0:
        logger.error(f"STT: missing or empty audio file {path}")
        return ""

    lang = language if language is not None else (Config.STT_LANGUAGE or None)
    if lang == "":
        lang = None

    provider = (Config.STT_PROVIDER or "auto").strip().lower()
    if provider in ("none", "off", "disabled"):
        logger.warning("STT disabled (STT_PROVIDER=none)")
        return ""

    order: list[str]
    if provider == "auto":
        order = ["faster_whisper", "openai"]
    elif provider in ("faster_whisper", "faster-whisper", "whisper", "local"):
        order = ["faster_whisper"]
    elif provider in ("openai", "http", "api", "whisper_api"):
        order = ["openai"]
    else:
        logger.warning(f"Unknown STT_PROVIDER={provider}, trying auto")
        order = ["faster_whisper", "openai"]

    last_err: Optional[Exception] = None
    for name in order:
        try:
            if name == "faster_whisper":
                text = _transcribe_faster_whisper(path, lang)
            else:
                text = _transcribe_openai_compatible(path, lang)
            text = (text or "").strip()
            if text:
                logger.info(f"STT ok via {name}: {text[:80]!r}...")
                return text
            logger.warning(f"STT {name} returned empty transcript")
        except Exception as e:
            last_err = e
            logger.warning(f"STT provider {name} failed: {e}")

    if last_err:
        logger.error(f"STT all providers failed: {last_err}")
    return ""


def _transcribe_faster_whisper(path: Path, language: Optional[str]) -> str:
    global _fw_model
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper not installed. Run: pip install faster-whisper"
        ) from e

    model_size = Config.STT_MODEL or "base"
    # Map OpenAI-style names to local sizes
    alias = {
        "whisper": "base",
        "whisper-1": "base",
        "whisper-tiny": "tiny",
        "whisper-base": "base",
        "whisper-small": "small",
        "whisper-medium": "medium",
    }
    model_size = alias.get(model_size.lower(), model_size)

    device = (os.getenv("STT_DEVICE") or Config.STT_DEVICE or "cpu").lower()
    compute_type = "int8" if device == "cpu" else "float16"

    if _fw_model is None or getattr(_fw_model, "_budgetbot_size", None) != model_size:
        logger.info(f"Loading faster-whisper model={model_size} device={device}")
        _fw_model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _fw_model._budgetbot_size = model_size  # type: ignore[attr-defined]

    segments, info = _fw_model.transcribe(
        str(path),
        language=language,
        beam_size=5,
        vad_filter=True,
    )
    parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
    text = " ".join(parts).strip()
    logger.debug(
        f"faster-whisper lang={getattr(info, 'language', None)} "
        f"prob={getattr(info, 'language_probability', None)}"
    )
    return text


def _transcribe_openai_compatible(path: Path, language: Optional[str]) -> str:
    """
    OpenAI-style audio transcriptions endpoint.
    Uses STT_BASE_URL / STT_API_KEY, falling back to OpenAI or Ollama key/url.
    """
    import httpx

    base = (
        Config.STT_BASE_URL
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    api_key = (
        Config.STT_API_KEY
        or os.getenv("OPENAI_API_KEY")
        or Config.OLLAMA_API_KEY
    )
    if not api_key:
        raise RuntimeError(
            "No STT_API_KEY / OPENAI_API_KEY / OLLAMA_API_KEY for HTTP transcription"
        )

    model = Config.STT_MODEL or "whisper-1"
    # Local whisper model sizes are not valid for OpenAI API
    if model in ("tiny", "base", "small", "medium", "large", "large-v2", "large-v3"):
        model = "whisper-1"

    url = f"{base}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = {"model": model, "response_format": "json"}
    if language:
        data["language"] = language

    mime = _guess_mime(path)
    with path.open("rb") as f:
        files = {"file": (path.name, f, mime)}
        with httpx.Client(timeout=float(Config.STT_TIMEOUT_SECONDS)) as client:
            resp = client.post(url, headers=headers, data=data, files=files)
    if resp.status_code >= 400:
        raise RuntimeError(f"STT HTTP {resp.status_code}: {resp.text[:300]}")

    payload = resp.json()
    if isinstance(payload, dict):
        return (payload.get("text") or "").strip()
    return str(payload).strip()


def _guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".opus": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".webm": "audio/webm",
        ".mp4": "audio/mp4",
    }.get(ext, "application/octet-stream")
