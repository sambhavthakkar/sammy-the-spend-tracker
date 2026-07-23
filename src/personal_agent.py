"""Conversational tool agent backed only by a user's private PersonalStore database."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from src.config import Config
from src.llm.ollama_client import OllamaClient
from src.llm.schemas import ChatMessage, ToolCall
from src.personal_store import PersonalStore

_RETRY = "I’m having trouble responding right now. Please try again."
_CONFIRM = {"yes", "y", "confirm", "yes please", "go ahead", "do it"}
_CANCEL = {"no", "n", "cancel", "no thanks", "never mind", "nevermind"}
_WRITE_TOOLS = {
    "record_transaction", "update_transaction", "delete_transaction",
    "set_category_limit", "remember", "forget_memory", "update_profile",
}
_CONFIRM_TOOLS = {"record_transaction", "update_transaction", "delete_transaction", "forget_memory"}


def _schema(name: str, description: str, properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict:
    parameters: dict[str, Any] = {
        "type": "object", "properties": properties, "additionalProperties": False,
    }
    if required:
        parameters["required"] = list(required)
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


_AMOUNT = {"description": "Decimal money amount", "anyOf": [{"type": "number"}, {"type": "string"}]}
_PERIOD = {"type": "string", "enum": [
    "today", "yesterday", "this_week", "last_week", "this_month",
    "last_month", "this_year", "all",
]}
_KIND = {"type": "string", "enum": ["expense", "income", "refund", "pocket_money"]}
TOOLS = [
    _schema("record_transaction", "Record money actually paid or received.", {
        "kind": _KIND, "amount": _AMOUNT, "category": {"type": "string"},
        "occurred_at": {"type": "string"}, "description": {"type": "string"},
        "currency": {"type": "string"},
    }, ("kind", "amount", "category")),
    _schema("find_transactions", "Find recorded transactions.", {
        "period": _PERIOD, "category": {"type": "string"}, "kind": _KIND,
        "limit": {"type": "integer", "minimum": 0, "maximum": 500},
    }),
    _schema("update_transaction", "Update one recorded transaction by id.", {
        "transaction_id": {"type": "string"}, "kind": _KIND, "amount": _AMOUNT,
        "category": {"type": "string"}, "occurred_at": {"type": "string"},
        "description": {"type": ["string", "null"]}, "currency": {"type": "string"},
    }, ("transaction_id",)),
    _schema("delete_transaction", "Delete one recorded transaction by id.", {
        "transaction_id": {"type": "string"},
    }, ("transaction_id",)),
    _schema("spending_summary", "Calculate authoritative expense totals from transactions.", {
        "period": _PERIOD, "category": {"type": "string"},
    }),
    _schema("money_balance", "Calculate the authoritative transaction balance.", {}),
    _schema("set_category_limit", "Set a planned category spending limit.", {
        "category": {"type": "string"}, "amount": _AMOUNT,
    }, ("category", "amount")),
    _schema("category_status", "Compare category spending with its configured limit.", {
        "category": {"type": "string"}, "period": _PERIOD,
    }, ("category",)),
    _schema("remember", "Remember an explicit durable non-secret fact, event, preference, or goal.", {
        "kind": {"type": "string", "enum": ["fact", "event", "preference", "goal"]},
        "content": {"type": "string"}, "details": {}, "occurred_at": {"type": "string"},
        "learned_at": {"type": "string"}, "salience": {"type": "number", "minimum": 0, "maximum": 1},
        "supersedes_id": {"type": "string"},
    }, ("kind", "content")),
    _schema("search_memory", "Search durable memories for relevant context.", {
        "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 0, "maximum": 50},
    }),
    _schema("forget_memory", "Forget one memory by id.", {"memory_id": {"type": "string"}}, ("memory_id",)),
    _schema("update_profile", "Update display name, timezone, or currency.", {
        "display_name": {"type": ["string", "null"]}, "timezone": {"type": "string"},
        "currency": {"type": "string"},
    }),
]

_ALLOWED = {
    tool["function"]["name"]: set(tool["function"]["parameters"]["properties"])
    for tool in TOOLS
}

_SYSTEM = """You are a warm personal conversational assistant. Normal chat is allowed and is the default; do not force tools.
Use memories naturally when relevant, without announcing database retrieval. Only call remember for an explicit durable fact, event, preference, or goal. Never store passwords, PINs, tokens, keys, card/account numbers, or other secrets; refuse that memory request.
Transactions are the sole truth for money actually paid or received, so use finance tools before stating finance facts. Expected pocket money is a memory; pocket money actually received is a pocket_money transaction. A category limit is a planned cap and is not the largest historical spend.
When required details are genuinely ambiguous, ask one concise clarification question. Never claim that anything was recorded, logged, updated, deleted, remembered, or otherwise written unless the corresponding tool succeeded. If a tool reports an error or asks for confirmation, say so honestly.
Tools are server-bound to the current user. Never request or invent user IDs, file paths, database paths, SQL, or source references."""


class PersonalAgent:
    def __init__(self, store: PersonalStore | None = None, llm: OllamaClient | None = None, max_rounds: int | None = None):
        self.store = store or PersonalStore()
        self.llm = llm or OllamaClient()
        self.max_rounds = max(1, int(max_rounds or Config.OLLAMA_MAX_TOOL_ROUNDS))

    def chat(self, user_key: str, text: str, source: str = "text", source_ref: str | None = None) -> str:
        text = str(text).strip()
        pending = self.store.get_pending_action(user_key)
        answer = text.casefold().strip(" .!?")
        if pending and answer in _CONFIRM:
            return self._resolve_pending(user_key, text, pending, True)
        if pending and answer in _CANCEL:
            return self._resolve_pending(user_key, text, pending, False)

        profile = self.store.get_profile(user_key)
        memories = self.store.search_memories(user_key, text, limit=5)
        turns = [turn for turn in self.store.recent_turns(user_key) if turn["role"] in {"user", "assistant"}]
        local_now = datetime.now(ZoneInfo(profile["timezone"])).isoformat(timespec="seconds")
        context = _SYSTEM + "\n\nCurrent private context:\n" + _dumps({
            "profile": profile, "local_clock": local_now, "relevant_memories": memories,
            "input_source": str(source),
        })
        messages = [ChatMessage("system", context)]
        messages.extend(ChatMessage(turn["role"], turn["content"]) for turn in turns)
        messages.append(ChatMessage("user", text))
        events: list[tuple[str, dict[str, Any], Any]] = []
        successful_writes: set[str] = set()
        transaction_index = 0

        try:
            for _ in range(self.max_rounds):
                response = self.llm.chat(messages, tools=TOOLS, tool_choice="auto", temperature=0.2)
                if response.has_tool_calls:
                    messages.append(ChatMessage("assistant", response.content, tool_calls=response.tool_calls))
                    for call in response.tool_calls:
                        call_source_ref = None
                        if source_ref is not None and call.name == "record_transaction":
                            transaction_index += 1
                            call_source_ref = f"{source_ref}:{transaction_index}"
                        result, event = self._execute(user_key, call, call_source_ref)
                        messages.append(ChatMessage("tool", _dumps(result), name=call.name, tool_call_id=call.id))
                        if event:
                            events.append(event)
                            if call.name in _WRITE_TOOLS:
                                successful_writes.add(call.name)
                    continue
                content = str(response.content or "").strip()
                if not content:
                    raise RuntimeError("empty LLM response")
                content = self._block_false_write_claim(content, successful_writes)
                self._persist(user_key, text, content, events)
                return content
        except Exception:
            if successful_writes:
                content = self._completed_write_reply(events)
                try:
                    self._persist(user_key, text, content, events)
                except Exception:
                    pass
                return content
            return _RETRY

        content = (
            self._completed_write_reply(events)
            if successful_writes
            else "I couldn’t complete that safely. Please try again."
        )
        self._persist(user_key, text, content, events)
        return content

    def _execute(
        self, user_key: str, call: ToolCall, source_ref: str | None,
    ) -> tuple[dict[str, Any], tuple[str, dict[str, Any], Any] | None]:
        if call.name not in _ALLOWED:
            return {"ok": False, "error": "unknown tool"}, None
        try:
            args = dict(call.arguments or {})
        except (TypeError, ValueError):
            return {"ok": False, "error": "tool arguments must be an object"}, None
        unknown = set(args) - _ALLOWED[call.name]
        if unknown:
            return {"ok": False, "error": f"unsupported arguments: {', '.join(sorted(unknown))}"}, None
        if call.name == "record_transaction" and source_ref is not None:
            args["source_ref"] = source_ref
        if self._needs_confirmation(call.name, args):
            try:
                self.store.set_pending_action(user_key, "confirmation", {"tool": call.name, "args": _safe(args)})
            except Exception as exc:
                return {"ok": False, "error": str(exc) or exc.__class__.__name__}, None
            return {
                "ok": True, "pending_confirmation": True,
                "message": "Ask the user for a simple yes or no confirmation; no write has happened.",
            }, None
        return self._dispatch(user_key, call.name, args)

    def _dispatch(
        self, user_key: str, name: str, args: dict[str, Any],
    ) -> tuple[dict[str, Any], tuple[str, dict[str, Any], Any] | None]:
        try:
            if name == "record_transaction":
                value = self.store.record_transaction(user_key, **args)
            elif name == "find_transactions":
                value = self.store.find_transactions(user_key, **args)
            elif name == "update_transaction":
                changes = dict(args)
                transaction_id = changes.pop("transaction_id")
                value = self.store.update_transaction(user_key, transaction_id, changes)
            elif name == "delete_transaction":
                value = self.store.delete_transaction(user_key, **args)
            elif name == "spending_summary":
                value = self.store.spending_summary(user_key, **args)
            elif name == "money_balance":
                value = self.store.money_balance(user_key)
            elif name == "set_category_limit":
                value = self.store.set_category_limit(user_key, **args)
            elif name == "category_status":
                value = self.store.category_status(user_key, **args)
            elif name == "remember":
                value = self.store.remember(user_key, **args)
            elif name == "search_memory":
                value = self.store.search_memories(user_key, **args)
            elif name == "forget_memory":
                value = self.store.forget_memory(user_key, **args)
            elif name == "update_profile":
                value = self.store.update_profile(user_key, args)
            else:
                return {"ok": False, "error": "unknown tool"}, None
            if value is False:
                return {"ok": False, "error": "target was not found or was already changed"}, None
            safe_value = _safe(value)
            return {"ok": True, "result": safe_value}, (name, _safe(args), safe_value)
        except Exception as exc:
            return {"ok": False, "error": str(exc) or exc.__class__.__name__}, None

    def _needs_confirmation(self, name: str, args: dict[str, Any]) -> bool:
        if name in {"delete_transaction", "forget_memory"}:
            return True
        if name not in {"record_transaction", "update_transaction"} or "amount" not in args:
            return False
        try:
            amount = Decimal(str(args["amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return amount.is_finite() and amount >= Decimal(str(Config.AGENT_CONFIRM_AMOUNT_THRESHOLD))
        except (InvalidOperation, ValueError):
            return False

    def _resolve_pending(self, user_key: str, text: str, pending: dict[str, Any], confirmed: bool) -> str:
        if not confirmed:
            self.store.clear_pending_action(user_key)
            answer = "Cancelled."
            self._persist(user_key, text, answer, [])
            return answer
        payload = pending.get("payload")
        if (
            not isinstance(payload, dict) or set(payload) != {"tool", "args"}
            or payload.get("tool") not in _CONFIRM_TOOLS or not isinstance(payload.get("args"), dict)
        ):
            self.store.clear_pending_action(user_key)
            answer = "I couldn’t verify that pending action, so I did not run it."
            self._persist(user_key, text, answer, [])
            return answer
        name, args = payload["tool"], payload["args"]
        allowed = _ALLOWED[name] | ({"source_ref"} if name == "record_transaction" else set())
        if set(args) - allowed:
            self.store.clear_pending_action(user_key)
            answer = "I couldn’t verify that pending action, so I did not run it."
            self._persist(user_key, text, answer, [])
            return answer
        result, event = self._dispatch(user_key, name, args)
        if result["ok"]:
            self.store.clear_pending_action(user_key)
            verb = {
                "record_transaction": "recorded the transaction",
                "update_transaction": "updated the transaction",
                "delete_transaction": "deleted the transaction",
                "forget_memory": "forgot that memory",
            }[name]
            answer = f"Confirmed — {verb}."
            self._persist(user_key, text, answer, [event] if event else [])
            return answer
        answer = f"I couldn’t complete that action: {result['error']}. The confirmation is still pending."
        self._persist(user_key, text, answer, [])
        return answer

    def _persist(
        self, user_key: str, user_text: str, assistant_text: str,
        events: list[tuple[str, dict[str, Any], Any]],
    ) -> None:
        self.store.append_turn(user_key, "user", user_text)
        for name, args, result in events:
            self.store.append_turn(
                user_key, "tool", _dumps(result), tool_name=name,
                tool_payload={"arguments": args, "result": result},
            )
        self.store.append_turn(user_key, "assistant", assistant_text)

    @staticmethod
    def _completed_write_reply(events: list[tuple[str, dict[str, Any], Any]]) -> str:
        name = next((event[0] for event in reversed(events) if event[0] in _WRITE_TOOLS), "")
        return {
            "record_transaction": "The transaction was recorded, but I couldn’t finish the explanation.",
            "update_transaction": "The transaction was updated, but I couldn’t finish the explanation.",
            "delete_transaction": "The transaction was deleted, but I couldn’t finish the explanation.",
            "set_category_limit": "The category limit was set, but I couldn’t finish the explanation.",
            "remember": "I saved that memory, but I couldn’t finish the explanation.",
            "forget_memory": "I forgot that memory, but I couldn’t finish the explanation.",
            "update_profile": "Your profile was updated, but I couldn’t finish the explanation.",
        }.get(name, "The requested change completed, but I couldn’t finish the explanation.")

    @staticmethod
    def _block_false_write_claim(content: str, writes: set[str]) -> str:
        checks = (
            (r"\b(?:i(?:['’]ve| have)?|we(?:['’]ve| have)?|successfully|done[,!: -]*)\s*(?:recorded|logged)\b|\b(?:recorded|logged)\s+(?:it|that|this|successfully|your (?:expense|income|transaction)|the (?:expense|income|transaction))\b|\b(?:expense|income|transaction)\s+(?:(?:is|was|has been)\s+)?(?:recorded|logged)\b|\b(?:recorded|logged)[.!]", {"record_transaction"}),
            (r"\b(?:i(?:['’]ve| have)?|we(?:['’]ve| have)?|successfully|done[,!: -]*)\s*updated\b|\bupdated\s+(?:it|that|this|successfully|your (?:profile|transaction)|the transaction)\b|\btransaction\s+(?:(?:is|was|has been)\s+)?updated\b|\bupdated[.!]", {"update_transaction", "update_profile"}),
            (r"\b(?:i(?:['’]ve| have)?|we(?:['’]ve| have)?|successfully|done[,!: -]*)\s*deleted\b|\bdeleted\s+(?:it|that|this|successfully|your transaction|the transaction)\b|\btransaction\s+(?:(?:is|was|has been)\s+)?deleted\b|\bdeleted[.!]", {"delete_transaction"}),
            (r"\b(?:i(?:['’]ll| will)?\s+)?remembered\b|\bi(?:['’]ll| will) remember that\b|\bsaved (?:that|this) (?:memory|preference|goal|event|fact)\b", {"remember"}),
            (r"\b(?:i(?:['’]ve| have)?\s+)?forgot(?:ten)?\b", {"forget_memory"}),
            (r"\b(?:set|updated|changed) (?:your |the )?(?:category )?(?:budget|limit)\b", {"set_category_limit"}),
            (r"\b(?:updated|changed|set) (?:your )?(?:profile|timezone|currency|display name)\b", {"update_profile"}),
        )
        lowered = re.sub(
            r"\b(?:not|never|didn['’]t|couldn['’]t|wasn['’]t|isn['’]t|haven['’]t|hasn['’]t)\b[^.!?]{0,40}\b(?:recorded|logged|updated|deleted)\b",
            "", content.casefold(),
        )
        if any(re.search(pattern, lowered) and not (needed & writes) for pattern, needed in checks):
            return "I couldn’t verify that change, so I did not make it. Please try again."
        return content


def _safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def _dumps(value: Any) -> str:
    return json.dumps(_safe(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
