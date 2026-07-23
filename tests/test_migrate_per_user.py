"""Focused tests for the legacy-to-PersonalStore migration."""
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.migrate_per_user import migrate
from src.personal_store import PersonalStore


class TestMigratePerUser(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "legacy.sqlite3"
        with sqlite3.connect(self.source) as db:
            db.executescript(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY, phone TEXT, name TEXT, telegram_id TEXT,
                    timezone TEXT, currency TEXT
                );
                CREATE TABLE transactions (
                    id TEXT PRIMARY KEY, user_id TEXT, amount REAL, currency TEXT,
                    category TEXT, merchant TEXT, direction TEXT, source TEXT,
                    timestamp TEXT, notes TEXT
                );
                CREATE TABLE pockets (
                    id TEXT PRIMARY KEY, user_id TEXT, name TEXT, monthly_limit REAL
                );
                CREATE TABLE commitments (
                    id TEXT PRIMARY KEY, user_id TEXT, name TEXT, type TEXT,
                    amount REAL, frequency TEXT, status TEXT
                );
                """
            )
            db.executemany(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("u1", "+10000000001", "Alice", "1001", "Asia/Kolkata", "INR"),
                    ("u2", "+10000000002", "Bob", None, "UTC", "USD"),
                ],
            )
            db.executemany(
                "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("11111111-1111-1111-1111-111111111111", "u1", 10.10, "INR", "Food", "Cafe", "expense", "TEXT", "2025-01-02 10:00:00", "lunch"),
                    ("22222222-2222-2222-2222-222222222222", "u1", 20.25, "INR", "Salary", None, "income", "VOICE", "2025-01-03 10:00:00", None),
                    ("33333333-3333-3333-3333-333333333333", "u2", 3.33, "USD", "Travel", None, "expense", "BILL", "2025-01-04 10:00:00", "bus"),
                ],
            )
            db.executemany(
                "INSERT INTO pockets VALUES (?, ?, ?, ?)",
                [("p1", "u1", "Food", 100.55), ("p2", "u2", "Travel", 40.00)],
            )
            db.execute(
                "INSERT INTO commitments VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("c1", "u1", "Insurance", "insurance", 50.0, "monthly", "active"),
            )
        self.data_dir = self.root / "personal"

    def tearDown(self):
        self.temp.cleanup()

    def _users(self, store):
        with sqlite3.connect(store.registry_path) as db:
            return {
                (provider, external_id): user_key
                for provider, external_id, user_key in db.execute(
                    "SELECT provider, external_id, user_key FROM identities"
                )
            }

    def test_dry_run_writes_nothing(self):
        messages = []
        reports = migrate(self.source, self.data_dir, output=messages.append)

        self.assertFalse(self.data_dir.exists())
        self.assertEqual([report["source_count"] for report in reports], [2, 1])
        self.assertTrue(all("target(projected)" in message for message in messages))

    def test_dry_run_rejects_invalid_timestamp_before_writing(self):
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE transactions SET timestamp = 'not-a-date' WHERE id = ?", (
                "11111111-1111-1111-1111-111111111111",
            ))
        with self.assertRaises(ValueError):
            migrate(self.source, self.data_dir, output=lambda _: None)
        self.assertFalse(self.data_dir.exists())

    def test_apply_isolated_verified_and_idempotent(self):
        migrate(self.source, self.data_dir, apply=True, output=lambda _: None)
        store = PersonalStore(self.data_dir)
        users = self._users(store)
        self.assertEqual(set(users), {("telegram", "1001"), ("phone", "+10000000002")})
        alice, bob = users[("telegram", "1001")], users[("phone", "+10000000002")]
        self.assertNotEqual(store.user_db_path(alice), store.user_db_path(bob))

        self.assertEqual(store.get_profile(alice)["display_name"], "Alice")
        self.assertEqual(store.get_profile(bob)["currency"], "USD")
        alice_transactions = store.find_transactions(alice)
        self.assertEqual(len(alice_transactions), 2)
        self.assertEqual(len(store.find_transactions(bob)), 1)
        migrated_lunch = next(row for row in alice_transactions if row["category"] == "food")
        self.assertEqual(migrated_lunch["occurred_at"], "2025-01-02T10:00:00.000000+00:00")
        self.assertEqual(store.money_balance(alice), Decimal("10.15"))
        self.assertEqual(store.money_balance(bob), Decimal("-3.33"))
        self.assertEqual(store.category_status(alice, "food", "all")["limit"], Decimal("100.55"))
        self.assertEqual(store.category_status(bob, "travel", "all")["limit"], Decimal("40"))

        with sqlite3.connect(store.user_db_path(alice)) as db:
            self.assertEqual(
                {row[0] for row in db.execute("SELECT id FROM transactions")},
                {
                    "11111111-1111-1111-1111-111111111111",
                    "22222222-2222-2222-2222-222222222222",
                },
            )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 1)
        with sqlite3.connect(store.registry_path) as db:
            self.assertEqual(
                [row[1] for row in db.execute("PRAGMA table_info(identities)")],
                ["provider", "external_id", "user_key", "created_at"],
            )
        registry_bytes = store.registry_path.read_bytes()
        self.assertNotIn(b"Alice", registry_bytes)
        self.assertNotIn(b"Insurance", registry_bytes)

        migrate(self.source, self.data_dir, apply=True, output=lambda _: None)
        self.assertEqual(len(store.find_transactions(alice)), 2)
        self.assertEqual(len(store.find_transactions(bob)), 1)
        with sqlite3.connect(store.user_db_path(alice)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 1)

        with sqlite3.connect(self.source) as db:
            db.execute(
                "UPDATE transactions SET amount = 12.34, category = 'Groceries' WHERE id = ?",
                ("11111111-1111-1111-1111-111111111111",),
            )
        migrate(self.source, self.data_dir, apply=True, output=lambda _: None)
        changed = next(row for row in store.find_transactions(alice) if row["kind"] == "expense")
        self.assertEqual(changed["amount"], Decimal("12.34"))
        self.assertEqual(changed["category"], "groceries")


if __name__ == "__main__":
    unittest.main()
