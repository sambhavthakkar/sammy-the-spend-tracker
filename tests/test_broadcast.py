"""Telegram broadcast command checks."""
import unittest

from scripts.broadcast import send_broadcast


class Response:
    def __init__(self, ok=True):
        self.ok = ok

    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": self.ok}


class Client:
    def __init__(self):
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))
        return Response(ok=json["chat_id"] != "blocked")


class TestBroadcast(unittest.TestCase):
    def test_sends_only_the_given_message_and_counts_failures(self):
        client = Client()
        sent, failed = send_broadcast(
            client,
            "private-token",
            {"allowed", "blocked"},
            "Service is back online",
        )

        self.assertEqual((sent, failed), (1, 1))
        self.assertEqual({call[1]["chat_id"] for call in client.calls}, {"allowed", "blocked"})
        self.assertTrue(all(call[1]["text"] == "Service is back online" for call in client.calls))
        self.assertTrue(all("private-token" in call[0] for call in client.calls))


if __name__ == "__main__":
    unittest.main()
