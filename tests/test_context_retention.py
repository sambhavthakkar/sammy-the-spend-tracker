"""Month-long context retrieval and retention checks."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.llm.schemas import ChatResponse
from src.personal_agent import PersonalAgent
from src.personal_store import PersonalStore

UTC = timezone.utc


class FakeLLM:
    def __init__(self, response="Okay."):
        self.response = response
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return ChatResponse(content=self.response)


class TestContextRetention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PersonalStore(self.temp.name)
        self.user = self.store.resolve_user("test", "context-user")

    def tearDown(self):
        self.temp.cleanup()

    def _set_turn_time(self, turn_id, value):
        with sqlite3.connect(self.store.user_db_path(self.user)) as db:
            db.execute(
                "UPDATE conversation_turns SET created_at = ? WHERE id = ?",
                (value.isoformat(timespec="microseconds"), turn_id),
            )

    def test_fts_searches_memories_older_than_latest_200(self):
        target = self.store.remember(
            self.user,
            "fact",
            "The hiking boots are stored in the cedar closet",
            learned_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        for index in range(205):
            self.store.remember(self.user, "fact", f"Routine note number {index}")

        results = self.store.search_memories(self.user, "cedar hiking boots", limit=3)
        self.assertEqual(results[0]["id"], target["id"])
        with sqlite3.connect(self.store.user_db_path(self.user)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
        self.assertIn("memory_fts", tables)
        self.assertIn("conversation_fts", tables)

    def test_retrieves_relevant_conversation_from_last_30_days(self):
        now = datetime.now(UTC)
        target = self.store.append_turn(
            self.user, "user", "The Kyoto hotel we liked was Sakura House"
        )
        too_old = self.store.append_turn(
            self.user, "user", "An older Kyoto hotel was Maple Inn"
        )
        self._set_turn_time(target, now - timedelta(days=20))
        self._set_turn_time(too_old, now - timedelta(days=40))
        for index in range(10):
            self.store.append_turn(self.user, "assistant", f"Recent unrelated chat {index}")

        recent = self.store.recent_conversation_turns(self.user)
        snippets = self.store.search_conversation(
            self.user,
            "Which Kyoto hotel did we like?",
            days=30,
            exclude_ids={turn["id"] for turn in recent},
            now=now,
        )
        self.assertEqual([item["id"] for item in snippets], [target])

    def test_prunes_old_chat_but_keeps_latest_eight_and_durable_data(self):
        now = datetime.now(UTC)
        memory = self.store.remember(self.user, "goal", "Save for a bicycle")
        transaction = self.store.record_transaction(self.user, "expense", "12", "food")
        turn_ids = []
        for index in range(12):
            turn_id = self.store.append_turn(self.user, "user", f"archiveitem{index}")
            self._set_turn_time(turn_id, now - timedelta(days=100, seconds=-index))
            turn_ids.append(turn_id)
        tool_id = self.store.append_turn(self.user, "tool", "durable tool event")
        self._set_turn_time(tool_id, now - timedelta(days=120))

        self.assertEqual(self.store.prune_conversation(self.user, days=90, now=now), 4)
        remaining = self.store.recent_conversation_turns(self.user, limit=20)
        self.assertEqual(len(remaining), 8)
        self.assertEqual({row["id"] for row in remaining}, set(turn_ids[-8:]))
        self.assertEqual(self.store.search_conversation(self.user, "archiveitem0", days=365), [])
        self.assertEqual(len(self.store.find_transactions(self.user)), 1)
        self.assertEqual(self.store.search_memories(self.user, "bicycle")[0]["id"], memory["id"])
        self.assertEqual(self.store.find_transactions(self.user)[0]["id"], transaction["id"])
        with sqlite3.connect(self.store.user_db_path(self.user)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM conversation_turns WHERE role = 'tool'").fetchone()[0],
                1,
            )

    def test_agent_injects_snippets_and_only_eight_recent_turns(self):
        now = datetime.now(UTC)
        target = self.store.append_turn(
            self.user, "user", "We planned the Kyoto trip around Sakura House"
        )
        self._set_turn_time(target, now - timedelta(days=20))
        for index in range(10):
            self.store.append_turn(self.user, "assistant", f"Recent chat {index}")
        llm = FakeLLM()

        PersonalAgent(self.store, llm).chat(self.user, "What was our Kyoto plan?")

        messages = llm.calls[0]
        self.assertIn("Sakura House", messages[0].content)
        history = [message for message in messages[1:-1] if message.role in {"user", "assistant"}]
        self.assertEqual(len(history), 8)


if __name__ == "__main__":
    unittest.main()
