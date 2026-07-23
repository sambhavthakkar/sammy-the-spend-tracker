"""Scripted tests for the private conversational/tool agent."""
import tempfile
import unittest
from decimal import Decimal

from src.llm.schemas import ChatResponse, ToolCall
from src.personal_agent import PersonalAgent
from src.personal_store import PersonalStore


class ScriptedLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None, tool_choice="auto", temperature=0.2):
        self.calls.append({"messages": messages, "tools": tools})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TestPersonalAgent(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PersonalStore(self.temp.name)
        self.alice = self.store.resolve_user("test", "alice", "Alice")

    def tearDown(self):
        self.temp.cleanup()

    def test_normal_chat_is_warm_and_persisted(self):
        llm = ScriptedLLM(ChatResponse(content="Hi Alice — lovely to hear from you."))
        answer = PersonalAgent(self.store, llm).chat(self.alice, "hello")

        self.assertEqual(answer, "Hi Alice — lovely to hear from you.")
        turns = self.store.recent_turns(self.alice)
        self.assertEqual([(row["role"], row["content"]) for row in turns], [
            ("user", "hello"), ("assistant", answer),
        ])
        self.assertIn("Normal chat is allowed", llm.calls[0]["messages"][0].content)
        self.assertNotIn("user_id", {name for tool in llm.calls[0]["tools"] for name in tool["function"]["parameters"]["properties"]})

    def test_remember_is_retrieved_in_later_context(self):
        llm = ScriptedLLM(
            ChatResponse(tool_calls=[ToolCall("remember-1", "remember", {
                "kind": "preference", "content": "Alice prefers jasmine tea", "salience": 0.8,
            })]),
            ChatResponse(content="I’ll remember that you prefer jasmine tea."),
            ChatResponse(content="Jasmine tea sounds like your kind of drink."),
        )
        agent = PersonalAgent(self.store, llm)
        agent.chat(self.alice, "Please remember that I prefer jasmine tea")
        answer = agent.chat(self.alice, "What tea should I make?")

        self.assertIn("Jasmine", answer)
        self.assertIn("Alice prefers jasmine tea", llm.calls[2]["messages"][0].content)
        tool_turn = next(row for row in self.store.recent_turns(self.alice) if row["role"] == "tool")
        self.assertEqual(tool_turn["tool_name"], "remember")
        self.assertEqual(tool_turn["tool_payload"]["arguments"]["salience"], 0.8)

    def test_finance_write_and_summary_are_grounded_and_decimal_safe(self):
        llm = ScriptedLLM(
            ChatResponse(tool_calls=[ToolCall("write-1", "record_transaction", {
                "kind": "expense", "amount": "12.34", "category": "food", "description": "lunch",
            })]),
            ChatResponse(tool_calls=[ToolCall("sum-1", "spending_summary", {
                "period": "today", "category": "food",
            })]),
            ChatResponse(content="Recorded lunch. Today’s food spending is INR 12.34."),
        )
        answer = PersonalAgent(self.store, llm).chat(
            self.alice, "Lunch was 12.34; what did I spend today?", source_ref="message-7"
        )

        self.assertIn("12.34", answer)
        self.assertEqual(self.store.spending_summary(self.alice, "today")["total"], Decimal("12.34"))
        transaction = self.store.find_transactions(self.alice)[0]
        self.assertEqual(transaction["source_ref"], "message-7:1")
        events = [row for row in self.store.recent_turns(self.alice) if row["role"] == "tool"]
        self.assertEqual([row["tool_name"] for row in events], ["record_transaction", "spending_summary"])
        self.assertEqual(events[1]["tool_payload"]["result"]["total"], "12.34")

    def test_high_value_confirmation_executes_once(self):
        llm = ScriptedLLM(
            ChatResponse(tool_calls=[ToolCall("large-1", "record_transaction", {
                "kind": "expense", "amount": "10000", "category": "travel",
            })]),
            ChatResponse(content="That amount needs confirmation. Yes or no?"),
            ChatResponse(content="There is no pending action now."),
        )
        agent = PersonalAgent(self.store, llm)
        prompt = agent.chat(self.alice, "Record 10000 for travel", source_ref="message-8")
        self.assertIn("confirmation", prompt)
        self.assertEqual(self.store.find_transactions(self.alice), [])

        self.assertIn("recorded", agent.chat(self.alice, "yes"))
        self.assertEqual(len(self.store.find_transactions(self.alice)), 1)
        agent.chat(self.alice, "yes")
        self.assertEqual(len(self.store.find_transactions(self.alice)), 1)
        self.assertIsNone(self.store.get_pending_action(self.alice))

    def test_rounded_threshold_requires_confirmation(self):
        llm = ScriptedLLM(
            ChatResponse(tool_calls=[ToolCall("round-1", "record_transaction", {
                "kind": "expense", "amount": "9999.999", "category": "travel",
            })]),
            ChatResponse(content="Please confirm yes or no."),
        )
        answer = PersonalAgent(self.store, llm).chat(self.alice, "Record 9999.999 for travel")
        self.assertIn("confirm", answer.lower())
        self.assertEqual(self.store.find_transactions(self.alice), [])

    def test_delete_and_forget_always_require_confirmation(self):
        transaction = self.store.record_transaction(self.alice, "expense", "5", "food")
        memory = self.store.remember(self.alice, "fact", "Alice owns a bicycle")
        llm = ScriptedLLM(
            ChatResponse(tool_calls=[ToolCall("delete-1", "delete_transaction", {"transaction_id": transaction["id"]})]),
            ChatResponse(content="Delete it? Please answer yes or no."),
            ChatResponse(tool_calls=[ToolCall("forget-1", "forget_memory", {"memory_id": memory["id"]})]),
            ChatResponse(content="Forget it? Please answer yes or no."),
        )
        agent = PersonalAgent(self.store, llm)

        agent.chat(self.alice, "Delete that transaction")
        self.assertEqual(len(self.store.find_transactions(self.alice)), 1)
        agent.chat(self.alice, "yes")
        self.assertEqual(self.store.find_transactions(self.alice), [])

        agent.chat(self.alice, "Forget the bicycle fact")
        self.assertEqual(len(self.store.search_memories(self.alice, "bicycle")), 1)
        agent.chat(self.alice, "yes")
        self.assertEqual(self.store.search_memories(self.alice, "bicycle"), [])

    def test_false_success_without_tool_write_is_blocked(self):
        llm = ScriptedLLM(
            ChatResponse(content="I’ve recorded that expense successfully."),
            ChatResponse(content="I remembered that preference."),
        )
        agent = PersonalAgent(self.store, llm)
        answer = agent.chat(self.alice, "I spent 8 on snacks")
        memory_answer = agent.chat(self.alice, "I prefer tea")

        self.assertIn("did not make it", answer)
        self.assertIn("did not make it", memory_answer)
        self.assertEqual(self.store.find_transactions(self.alice), [])
        self.assertEqual(self.store.search_memories(self.alice), [])

    def test_successful_write_survives_final_llm_failure(self):
        llm = ScriptedLLM(
            ChatResponse(tool_calls=[ToolCall("write-1", "record_transaction", {
                "kind": "expense", "amount": "7.50", "category": "food",
            })]),
            RuntimeError("offline after write"),
        )
        answer = PersonalAgent(self.store, llm).chat(
            self.alice, "Record 7.50 for food", source_ref="message-9"
        )

        self.assertIn("was recorded", answer)
        self.assertEqual(len(self.store.find_transactions(self.alice)), 1)
        self.assertEqual(self.store.find_transactions(self.alice)[0]["source_ref"], "message-9:1")
        self.assertEqual(self.store.recent_turns(self.alice)[-1]["content"], answer)

    def test_failed_confirmed_action_stays_pending(self):
        self.store.set_pending_action(self.alice, "confirmation", {
            "tool": "record_transaction",
            "args": {"kind": "expense", "amount": "invalid", "category": "food"},
        })
        answer = PersonalAgent(self.store, llm=object()).chat(self.alice, "yes")
        self.assertIn("still pending", answer)
        self.assertIsNotNone(self.store.get_pending_action(self.alice))

    def test_two_users_never_mix_context_or_turns(self):
        bob = self.store.resolve_user("test", "bob", "Bob")
        self.store.remember(self.alice, "fact", "Alice has a blue bicycle")
        llm = ScriptedLLM(
            ChatResponse(content="Alice answer"), ChatResponse(content="Bob answer"),
        )
        agent = PersonalAgent(self.store, llm)
        agent.chat(self.alice, "Tell me about my bicycle")
        agent.chat(bob, "What do you know about me?")

        self.assertIn("blue bicycle", llm.calls[0]["messages"][0].content)
        self.assertNotIn("blue bicycle", llm.calls[1]["messages"][0].content)
        self.assertEqual([row["content"] for row in self.store.recent_turns(bob)], [
            "What do you know about me?", "Bob answer",
        ])

    def test_tool_errors_and_llm_failures_do_not_crash_or_fake_writes(self):
        llm = ScriptedLLM(
            ChatResponse(tool_calls=[ToolCall("bad-1", "record_transaction", {
                "kind": "expense", "amount": "not-money", "category": "food",
            })]),
            ChatResponse(content="I couldn’t record that amount."),
            RuntimeError("offline"),
        )
        agent = PersonalAgent(self.store, llm)
        self.assertIn("couldn’t record", agent.chat(self.alice, "Record an invalid amount"))
        before = list(self.store.recent_turns(self.alice))
        self.assertIn("try again", agent.chat(self.alice, "hello again").lower())
        self.assertEqual(self.store.recent_turns(self.alice), before)
        self.assertEqual(self.store.find_transactions(self.alice), [])


if __name__ == "__main__":
    unittest.main()
