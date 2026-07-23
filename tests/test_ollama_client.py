"""Focused tests for the shared Ollama HTTP client."""
import unittest
from unittest.mock import MagicMock, patch

from src.llm.ollama_client import OllamaClient
from src.llm.schemas import ChatMessage


class TestOllamaClient(unittest.TestCase):
    @patch("src.llm.ollama_client.time.sleep")
    @patch("src.llm.ollama_client.httpx.Client")
    def test_reuses_client_and_retries_transient_status(self, client_cls, sleep):
        transient = MagicMock(status_code=429)
        success = MagicMock(status_code=200)
        success.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

        http = client_cls.return_value
        http.post.side_effect = [transient, success, success]
        client = OllamaClient(base_url="https://example.test/v1", timeout=1)

        self.assertEqual(client.chat([ChatMessage("user", "hi")]).content, "ok")
        self.assertEqual(client.chat([ChatMessage("user", "again")]).content, "ok")
        client_cls.assert_called_once_with(timeout=1)
        self.assertEqual(http.post.call_count, 3)
        sleep.assert_called_once_with(0.5)
        client.close()
        http.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
