"""Focused tests for private CLI and bill channel wiring."""
import asyncio
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from telegram.error import TimedOut

from src.adapters.telegram_bot import (
    _format_spending_report,
    _prepare_bill_confirmation,
    _reply_text,
    _run_limited,
    _source_ref,
    _user_lock,
)
from src.agent.cli_agent import resolve_cli_user
from src.config import Config
from src.media.bill_vision import BillExtraction
from src.personal_agent import PersonalAgent
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
        self.assertEqual(pending["action_type"], "confirmation")
        self.assertEqual(pending["payload"]["tool"], "record_transaction")
        args = pending["payload"]["args"]
        self.assertEqual(args["source_ref"], source_ref)
        self.assertEqual(args["description"], "Cafe — team lunch")
        self.assertEqual(self.store.find_transactions(user_key), [])
        self.assertIn("yes or no", reply)

        confirmation = PersonalAgent(self.store, llm=object()).chat(user_key, "yes")
        self.assertIn("recorded", confirmation)
        self.assertEqual(len(self.store.find_transactions(user_key)), 1)
        self.assertIsNone(self.store.get_pending_action(user_key))

    def test_monthly_report_is_clear_and_deterministic(self):
        report = {
            "count": 2,
            "total": Decimal("50"),
            "by_category": [{
                "category": "food", "count": 2,
                "total": Decimal("50"), "percentage": Decimal("100.0"),
            }],
            "max_transaction": {
                "amount": Decimal("35"), "description": "Dinner", "category": "food",
            },
        }

        text = _format_spending_report(report, "INR")

        self.assertIn("Total: INR 50.00", text)
        self.assertIn("Food: INR 50.00 (100.0%)", text)
        self.assertIn("Largest: INR 35.00 — Dinner", text)

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


class TestConcurrency(unittest.IsolatedAsyncioTestCase):
    @patch("src.adapters.telegram_bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_reply_retries_network_timeout(self, sleep):
        message = AsyncMock()
        message.reply_text.side_effect = [TimedOut("timeout"), "sent"]

        result = await _reply_text(message, "hello")

        self.assertEqual(result, "sent")
        self.assertEqual(message.reply_text.await_count, 2)
        sleep.assert_awaited_once_with(1)

    async def test_work_is_bounded_and_user_locks_are_stable(self):
        locks = {}
        self.assertIs(_user_lock(locks, "a"), _user_lock(locks, "a"))
        self.assertIsNot(_user_lock(locks, "a"), _user_lock(locks, "b"))

        active = peak = 0
        guard = threading.Lock()

        def work(value):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with guard:
                active -= 1
            return value

        limit = asyncio.Semaphore(2)
        results = await asyncio.gather(*(
            _run_limited(limit, work, value) for value in range(6)
        ))
        self.assertEqual(results, list(range(6)))
        self.assertEqual(peak, 2)

    async def test_cancellation_keeps_slot_until_thread_finishes(self):
        started = threading.Event()
        release = threading.Event()

        def work():
            started.set()
            release.wait()

        limit = asyncio.Semaphore(1)
        task = asyncio.create_task(_run_limited(limit, work))
        await asyncio.to_thread(started.wait)
        task.cancel()
        await asyncio.sleep(0)
        self.assertTrue(limit.locked())
        self.assertFalse(task.done())

        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(limit.locked())


if __name__ == "__main__":
    unittest.main()
