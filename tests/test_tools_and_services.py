"""Tests for structured expense logging, queries, and tool registry."""
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock

# Isolate DB before imports that touch engine
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["SQLALCHEMY_ECHO"] = "False"

from src.database import init_db  # noqa: E402
from src.services import PocketService, TransactionService, UserService  # noqa: E402
from src.agent.tools.registry import get_default_registry  # noqa: E402
from src.agent.runtime import AgentRuntime  # noqa: E402
from src.llm.schemas import ChatResponse, ToolCall  # noqa: E402


class TestStructuredAndTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db(reset=True)

    def setUp(self):
        created = UserService.create_user(
            phone=f"test{datetime.utcnow().timestamp()}", name="Tester"
        )
        self.user_id = created["user_id"]
        PocketService.create_pocket(self.user_id, "Food", 5000)

    def test_log_expense_structured(self):
        result = TransactionService.log_expense_structured(
            self.user_id,
            amount=250,
            category="food",
            merchant="lunch",
            notes="lunch 250",
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["transaction"]["amount"], 250)
        self.assertEqual(result["transaction"]["category"], "food")

    def test_sum_spending(self):
        TransactionService.log_expense_structured(
            self.user_id, amount=100, category="food", merchant="a"
        )
        TransactionService.log_expense_structured(
            self.user_id, amount=50, category="transport", merchant="b"
        )
        today = datetime.utcnow().strftime("%Y-%m-%d")
        total = TransactionService.sum_spending(self.user_id, today, today)
        self.assertTrue(total["success"])
        self.assertEqual(total["total"], 150)
        food = TransactionService.sum_spending(
            self.user_id, today, today, category="food"
        )
        self.assertEqual(food["total"], 100)

    def test_breakdown_by_category(self):
        TransactionService.log_expense_structured(
            self.user_id, amount=200, category="food", merchant="x"
        )
        TransactionService.log_expense_structured(
            self.user_id, amount=80, category="food", merchant="y"
        )
        today = datetime.utcnow().strftime("%Y-%m-%d")
        bd = TransactionService.spending_breakdown(
            self.user_id, today, today, group_by="category"
        )
        self.assertTrue(bd["success"])
        self.assertGreaterEqual(bd["total"], 280)
        keys = {g["key"] for g in bd["groups"]}
        self.assertIn("food", keys)

    def test_tool_log_and_query(self):
        registry = get_default_registry()
        r = registry.execute(
            "log_expense",
            {"amount": 120, "category": "food", "merchant": "chai"},
            user_id=self.user_id,
        )
        self.assertTrue(r.get("success") or r.get("ok"), r)

        today = datetime.utcnow().strftime("%Y-%m-%d")
        q = registry.execute(
            "query_spending",
            {"from_date": today, "to_date": today, "group_by": "none"},
            user_id=self.user_id,
        )
        self.assertTrue(q.get("success") or q.get("ok"), q)
        self.assertGreaterEqual(float(q.get("total") or 0), 120)

    def test_agent_runtime_with_mock_llm(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        mock_llm = MagicMock()
        # Round 1: tool call log
        mock_llm.chat.side_effect = [
            ChatResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="log_expense",
                        arguments={"amount": 90, "category": "food", "merchant": "idli"},
                    )
                ],
            ),
            ChatResponse(content="Logged ₹90 for idli under food."),
        ]
        runtime = AgentRuntime(llm=mock_llm, max_rounds=4)
        reply = runtime.run(
            user_text="idli 90",
            system_context=f"## Clock\nToday: {today}",
            memory=[],
            user_id=self.user_id,
        )
        self.assertIn("90", reply)
        total = TransactionService.sum_spending(self.user_id, today, today, category="food")
        self.assertGreaterEqual(total["total"], 90)


if __name__ == "__main__":
    unittest.main()
