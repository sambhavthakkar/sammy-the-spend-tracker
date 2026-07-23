"""Focused tests for private CLI and bill channel wiring."""
import tempfile
import unittest
from unittest.mock import patch

from src.adapters.telegram_bot import _prepare_bill_confirmation, _source_ref
from src.agent.cli_agent import resolve_cli_user
from src.config import Config
from src.media.bill_vision import BillExtraction
from src.personal_store import PersonalStore


def bill(**changes):
    values = {
        "is_bill": True,
        "amount": 450.0,
        "merchant": "Cafe",
        "category": "food",
        "date": "2026-03-01",
        "currency": "INR",
        "notes": "lunch",
        "confidence": 0.9,
        "needs_confirmation": False,
        "summary": "Cafe bill",
    }
    values.update(changes)
    return BillExtraction(**values)


class TestChannelIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PersonalStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_cli_identity_is_stable(self):
        with patch.object(Config, "AGENT_CLI_USER_ID", "owner"):
            first = resolve_cli_user(self.store)
            second = resolve_cli_user(self.store)
        self.assertEqual(first, second)
        self.assertEqual(self.store.get_profile(first)["currency"], Config.AGENT_CURRENCY_DEFAULT)

    def test_bill_stages_private_confirmation_without_recording(self):
        user_key = self.store.resolve_user("telegram", "42")
        source_ref = _source_ref(123, "bill")

        reply = _prepare_bill_confirmation(
            self.store, user_key, bill(), source_ref, "team lunch"
        )

        pending = self.store.get_pending_action(user_key)
        self.assertEqual(pending["action_type"], "record_transaction")
        self.assertEqual(pending["payload"]["source_ref"], source_ref)
        self.assertEqual(pending["payload"]["description"], "Cafe — team lunch")
        self.assertEqual(self.store.find_transactions(user_key), [])
        self.assertIn("yes or no", reply)
        self.assertEqual(len(self.store.recent_turns(user_key)), 2)

    def test_unreadable_bill_only_records_conversation(self):
        user_key = self.store.resolve_user("telegram", "42")

        reply = _prepare_bill_confirmation(
            self.store,
            user_key,
            bill(is_bill=False, amount=0, summary="Not a receipt"),
            _source_ref(124, "bill"),
        )

        self.assertEqual(reply, "Not a receipt")
        self.assertIsNone(self.store.get_pending_action(user_key))
        self.assertEqual(self.store.find_transactions(user_key), [])
        self.assertEqual(len(self.store.recent_turns(user_key)), 2)


if __name__ == "__main__":
    unittest.main()
