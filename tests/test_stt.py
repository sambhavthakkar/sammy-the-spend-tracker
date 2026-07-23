"""STT unit tests with mocked providers."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("STT_PROVIDER", "none")

from src.media import stt as stt_mod  # noqa: E402


class TestSTT(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with patch.object(stt_mod.Config, "STT_PROVIDER", "faster_whisper"):
            self.assertEqual(stt_mod.transcribe("/tmp/does-not-exist-budgetbot.ogg"), "")

    def test_none_provider(self):
        path = Path(tempfile.mkstemp(suffix=".ogg")[1])
        try:
            path.write_bytes(b"fake")
            with patch.object(stt_mod.Config, "STT_PROVIDER", "none"):
                self.assertEqual(stt_mod.transcribe(path), "")
        finally:
            path.unlink(missing_ok=True)

    def test_auto_uses_faster_whisper_when_available(self):
        path = Path(tempfile.mkstemp(suffix=".ogg")[1])
        try:
            path.write_bytes(b"fake-audio")
            with patch.object(stt_mod.Config, "STT_PROVIDER", "auto"), patch.object(
                stt_mod, "_transcribe_faster_whisper", return_value="lunch 250"
            ) as fw:
                text = stt_mod.transcribe(path)
                self.assertEqual(text, "lunch 250")
                fw.assert_called_once()
        finally:
            path.unlink(missing_ok=True)

    def test_auto_falls_back_to_openai(self):
        path = Path(tempfile.mkstemp(suffix=".ogg")[1])
        try:
            path.write_bytes(b"fake-audio")
            with patch.object(stt_mod.Config, "STT_PROVIDER", "auto"), patch.object(
                stt_mod,
                "_transcribe_faster_whisper",
                side_effect=RuntimeError("no fw"),
            ), patch.object(
                stt_mod, "_transcribe_openai_compatible", return_value="uber 180"
            ) as oai:
                text = stt_mod.transcribe(path)
                self.assertEqual(text, "uber 180")
                oai.assert_called_once()
        finally:
            path.unlink(missing_ok=True)

    def test_guess_mime(self):
        self.assertEqual(stt_mod._guess_mime(Path("a.ogg")), "audio/ogg")
        self.assertEqual(stt_mod._guess_mime(Path("a.mp3")), "audio/mpeg")


if __name__ == "__main__":
    unittest.main()
