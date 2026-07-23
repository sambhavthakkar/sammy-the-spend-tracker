"""Tests for isolated private user storage and deterministic finance/memory logic."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from src.personal_store import PersonalStore

UTC = timezone.utc


class TestPersonalStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PersonalStore(self.temp.name)
        self.alice = self.store.resolve_user("telegram", "1001", "Private Alice")

    def tearDown(self):
        self.temp.cleanup()

    def test_two_users_are_physically_isolated(self):
        bob = self.store.resolve_user("telegram", "1002", "Private Bob")
        self.store.record_transaction(self.alice, "expense", "12.34", "food", description="alice only")
        self.store.record_transaction(bob, "expense", "99.00", "travel", description="bob only")

        self.assertNotEqual(self.store.user_db_path(self.alice), self.store.user_db_path(bob))
        with sqlite3.connect(self.store.user_db_path(self.alice)) as db:
            self.assertEqual(db.execute("SELECT description FROM transactions").fetchall(), [("alice only",)])
            columns = {
                row[1]
                for table in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                for row in db.execute(f"PRAGMA table_info({table[0]})").fetchall()
            }
        self.assertNotIn("user_id", columns)
        self.assertEqual(self.store.find_transactions(bob)[0]["description"], "bob only")

    def test_registry_has_identity_mapping_only(self):
        self.store.remember(self.alice, "fact", "Alice owns a blue bicycle")
        with sqlite3.connect(self.store.registry_path) as db:
            self.assertEqual(
                [row[1] for row in db.execute("PRAGMA table_info(identities)")],
                ["provider", "external_id", "user_key", "created_at"],
            )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM identities").fetchone()[0], 1)
        registry_bytes = Path(self.store.registry_path).read_bytes()
        self.assertNotIn(b"Private Alice", registry_bytes)
        self.assertNotIn(b"blue bicycle", registry_bytes)

    def test_paths_are_uuid_only_and_permissions_are_private(self):
        UUID(self.alice)
        for invalid in ("../registry", "not-a-uuid", "", "../../etc/passwd"):
            with self.assertRaises(ValueError):
                self.store.user_db_path(invalid)
        if os.name == "posix":
            self.assertEqual(os.stat(self.store.users_dir).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(self.store.registry_path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(self.store.user_db_path(self.alice)).st_mode & 0o777, 0o600)

    def test_decimal_precision_and_source_ref_idempotency(self):
        first = self.store.record_transaction(
            self.alice, "expense", Decimal("0.10"), "food", source_ref="msg:1"
        )
        duplicate = self.store.record_transaction(
            self.alice, "expense", Decimal("999.99"), "other", source_ref="msg:1"
        )
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(first["amount"], Decimal("0.1"))
        self.assertEqual(self.store.spending_summary(self.alice)["total"], Decimal("0.1"))
        with self.assertRaises(ValueError):
            self.store.record_transaction(self.alice, "expense", "1", "food", currency="USD")
        with self.assertRaises(ValueError):
            self.store.update_profile(self.alice, currency="USD")
        with sqlite3.connect(self.store.user_db_path(self.alice)) as db:
            self.assertEqual(db.execute("SELECT amount_minor, COUNT(*) FROM transactions").fetchone(), (10, 1))
            self.assertEqual(db.execute("SELECT typeof(amount_minor) FROM transactions").fetchone()[0], "integer")

    def test_category_net_remaining_max_and_balance(self):
        self.store.record_transaction(self.alice, "expense", "10.01", "food")
        largest = self.store.record_transaction(self.alice, "expense", "25.00", "food")
        self.store.record_transaction(self.alice, "refund", "5.00", "food")
        self.store.record_transaction(self.alice, "income", "100.00", "salary")
        self.store.record_transaction(self.alice, "pocket_money", "10.00", "allowance")
        self.store.set_category_limit(self.alice, "food", "40.00")

        summary = self.store.spending_summary(self.alice, category="food")
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["total"], Decimal("30.01"))
        self.assertEqual(summary["average"], Decimal("15.01"))
        self.assertEqual(summary["max_transaction"]["id"], largest["id"])
        status = self.store.category_status(self.alice, "food", period="all")
        self.assertEqual(status["spent"], Decimal("30.01"))
        self.assertEqual(status["remaining"], Decimal("9.99"))
        self.assertEqual(self.store.money_balance(self.alice), Decimal("79.99"))

        self.store.update_transaction(self.alice, largest["id"], amount="20.00")
        updated = next(row for row in self.store.find_transactions(self.alice, category="food") if row["id"] == largest["id"])
        self.assertEqual(updated["amount"], Decimal("20"))
        self.assertTrue(self.store.delete_transaction(self.alice, largest["id"]))
        self.assertFalse(self.store.delete_transaction(self.alice, largest["id"]))

    def test_period_boundaries_use_user_local_half_open_utc(self):
        self.store.update_profile(self.alice, timezone="America/Los_Angeles")
        now = datetime(2026, 1, 2, 0, 30, tzinfo=UTC)  # Jan 1, 16:30 local
        self.store.record_transaction(
            self.alice, "expense", "7.00", "food", occurred_at=datetime(2026, 1, 1, 7, 59, 59, tzinfo=UTC)
        )
        self.store.record_transaction(
            self.alice, "expense", "8.00", "food", occurred_at=datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC)
        )
        self.store.record_transaction(
            self.alice, "expense", "9.00", "food", occurred_at=datetime(2026, 1, 2, 8, 0, 0, tzinfo=UTC)
        )
        summary = self.store.spending_summary(self.alice, "today", now=now)
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["total"], Decimal("8"))

    def test_memory_ranking_superseding_forgetting_and_secret_rejection(self):
        learned = datetime(2026, 1, 1, tzinfo=UTC)
        old = self.store.remember(
            self.alice, "preference", "Prefers tea in the morning", salience="0.1", learned_at=learned
        )
        self.store.remember(
            self.alice, "fact", "Enjoys evening walks", salience="1", learned_at=learned + timedelta(days=1)
        )
        replacement = self.store.remember(
            self.alice,
            "preference",
            "Now prefers green tea",
            salience="0.2",
            learned_at=learned + timedelta(days=2),
            supersedes_id=old["id"],
        )
        results = self.store.search_memories(
            self.alice, "tea preference", now=learned + timedelta(days=3)
        )
        self.assertEqual(results[0]["id"], replacement["id"])
        self.assertNotIn(old["id"], {row["id"] for row in results})
        self.assertTrue(self.store.forget_memory(self.alice, replacement["id"]))
        self.assertNotIn(replacement["id"], {row["id"] for row in self.store.search_memories(self.alice)})
        with self.assertRaises(ValueError):
            self.store.remember(self.alice, "fact", "My PIN is 1234")
        with self.assertRaises(ValueError):
            self.store.remember(self.alice, "fact", "Bearer token sk-live-abcdefghijklmnop")

        self.store.append_turn(self.alice, "user", "My recovery code is ABCD-EFGH")
        self.assertEqual(
            self.store.recent_turns(self.alice)[-1]["content"],
            "[sensitive content not stored]",
        )

    def test_pending_turns_and_message_dedupe(self):
        self.store.append_turn(self.alice, "user", "hello")
        self.store.append_turn(self.alice, "assistant", "hi", tool_payload={"ok": True})
        self.assertEqual([row["content"] for row in self.store.recent_turns(self.alice)], ["hello", "hi"])
        self.assertFalse(self.store.is_processed(self.alice, "telegram", "update-1"))
        self.assertTrue(self.store.mark_processed(self.alice, "telegram", "update-1"))
        self.assertTrue(self.store.is_processed(self.alice, "telegram", "update-1"))
        self.assertFalse(self.store.mark_processed(self.alice, "telegram", "update-1"))

        action_id = self.store.set_pending_action(self.alice, "delete", {"transaction_id": "x"}, ttl_minutes=5)
        self.assertEqual(self.store.get_pending_action(self.alice)["id"], action_id)
        replacement = self.store.set_pending_action(self.alice, "update", {"amount": "1.00"})
        self.assertEqual(self.store.get_pending_action(self.alice)["id"], replacement)
        self.assertIsNone(
            self.store.get_pending_action(self.alice, now=datetime.now(UTC) + timedelta(hours=1))
        )
        self.assertFalse(self.store.clear_pending_action(self.alice))


if __name__ == "__main__":
    unittest.main()
