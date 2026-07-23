"""
End-to-end agent pipeline: normalize → context → runtime → memory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.agent.context_builder import ContextBuilder
from src.agent.runtime import AgentRuntime
from src.agent.session_store import SessionStore
from src.config import Config
from src.logging_config import get_logger
from src.services import TransactionService, UserService

logger = get_logger(__name__)

YES_RE = re.compile(r"^\s*(yes|y|haan|ha|ok|okay|confirm|sure|yep|yeah)\s*[.!]*\s*$", re.I)
NO_RE = re.compile(r"^\s*(no|n|nah|nope|cancel|don't|dont)\s*[.!]*\s*$", re.I)
QUESTION_HINT = re.compile(
    r"\b(how|what|when|why|which|kitna|kitne|kya|show|balance|spent|left|budget|total|summary)\b",
    re.I,
)


@dataclass
class PipelineResult:
    text: str
    user_id: str
    used_fallback: bool = False


class AgentPipeline:
    def __init__(self, runtime: Optional[AgentRuntime] = None):
        self.runtime = runtime or AgentRuntime()

    def handle_text(
        self,
        user_id: str,
        text: str,
        source: str = "text",
    ) -> PipelineResult:
        text = (text or "").strip()
        if not text:
            return PipelineResult(text="I didn't catch that — send a short message or voice note.", user_id=user_id)

        # Pending confirmation fast-path
        pending = SessionStore.get_pending_action(user_id)
        if pending and YES_RE.match(text):
            reply = self._execute_pending(user_id, pending)
            SessionStore.append_turn(user_id, "user", text)
            SessionStore.append_turn(user_id, "assistant", reply)
            return PipelineResult(text=reply, user_id=user_id)
        if pending and NO_RE.match(text):
            SessionStore.clear_pending_action(user_id)
            reply = "Okay, cancelled."
            SessionStore.append_turn(user_id, "user", text)
            SessionStore.append_turn(user_id, "assistant", reply)
            return PipelineResult(text=reply, user_id=user_id)

        # Optional rule-parser only mode
        if not Config.ENABLE_AGENT:
            return self._rule_fallback(user_id, text, source)

        # Fast path: skip LLM for obvious "lunch 250" (seconds → milliseconds)
        if Config.AGENT_FAST_PATH and source in ("text", "voice"):
            fast = self._try_fast_expense(user_id, text, source)
            if fast is not None:
                return fast

        ctx = ContextBuilder.build(user_id)
        system_context = ContextBuilder.format_system_context(ctx)
        # Slim memory for lower latency
        memory = (ctx.get("memory") or [])[-Config.AGENT_MEMORY_TURNS :]

        # Hint voice source to the model
        user_payload = text
        if source == "voice":
            user_payload = (
                "[Voice note transcript — if this is an expense, call log_expense "
                "with source=voice]\n"
                f"{text}"
            )

        try:
            reply = self.runtime.run(
                user_text=user_payload,
                system_context=system_context,
                memory=memory,
                user_id=user_id,
            )
            SessionStore.append_turn(user_id, "user", text)
            SessionStore.append_turn(user_id, "assistant", reply)
            return PipelineResult(text=reply, user_id=user_id)
        except Exception as e:
            logger.error(f"Agent pipeline failed: {e}")
            if Config.ENABLE_RULE_PARSER_FALLBACK and not QUESTION_HINT.search(text):
                return self._rule_fallback(user_id, text, source)
            reply = "Something went wrong on my side. Please try again."
            return PipelineResult(text=reply, user_id=user_id, used_fallback=True)

    def _try_fast_expense(
        self, user_id: str, text: str, source: str
    ) -> Optional[PipelineResult]:
        from src.agent.fast_path import try_parse_simple_expense

        parsed = try_parse_simple_expense(text, user_id)
        if not parsed:
            return None
        amount, category, merchant, notes = parsed

        # Still confirm very large amounts
        user = UserService.get_user(user_id) or {}
        income = float(user.get("income") or 0)
        if amount >= Config.AGENT_CONFIRM_AMOUNT_THRESHOLD or (
            income > 0 and amount >= income * Config.AGENT_CONFIRM_INCOME_FRACTION
        ):
            SessionStore.set_pending_action(
                user_id,
                "log_expense",
                {
                    "amount": amount,
                    "category": category,
                    "merchant": merchant,
                    "notes": notes,
                    "mode": "personal",
                    "source": source if source in ("text", "voice", "bill") else "text",
                },
            )
            reply = f"Log ₹{amount:.0f} ({merchant} / {category})? Reply yes or no."
            SessionStore.append_turn(user_id, "user", text)
            SessionStore.append_turn(user_id, "assistant", reply)
            return PipelineResult(text=reply, user_id=user_id, used_fallback=True)

        result = TransactionService.log_expense_structured(
            user_id=user_id,
            amount=amount,
            category=category,
            merchant=merchant,
            notes=notes,
            mode="personal",
            source=source if source in ("text", "voice", "bill") else "text",
        )
        if not result.get("success"):
            return None  # fall through to full agent

        t = result.get("transaction") or {}
        pocket = result.get("pocket_update") or {}
        reply = (
            f"Logged ₹{t.get('amount')} under {t.get('category')} "
            f"({t.get('merchant')})."
        )
        if pocket.get("success") and pocket.get("remaining") is not None:
            reply += f" {pocket.get('pocket_name')} left: ₹{float(pocket['remaining']):.0f}."
        SessionStore.append_turn(user_id, "user", text)
        SessionStore.append_turn(user_id, "assistant", reply)
        logger.info(f"Fast-path expense for user={user_id} amount={amount}")
        return PipelineResult(text=reply, user_id=user_id, used_fallback=True)

    def _execute_pending(self, user_id: str, pending: dict) -> str:
        from src.agent.tools.registry import get_default_registry

        action = pending.get("action_type")
        payload = pending.get("payload") or {}
        SessionStore.clear_pending_action(user_id)
        registry = get_default_registry()

        if action == "log_expense":
            payload = {**payload, "amount": payload.get("amount")}
            # bypass confirm by using structured service directly
            from datetime import datetime
            from src.timeutils.dates import inclusive_datetime_range, parse_absolute_date

            ts = None
            if payload.get("date"):
                d = parse_absolute_date(payload["date"])
                start, _ = inclusive_datetime_range(d, d, _user_tz(user_id))
                ts = start.replace(hour=12)
            result = TransactionService.log_expense_structured(
                user_id=user_id,
                amount=float(payload.get("amount") or 0),
                category=payload.get("category"),
                merchant=payload.get("merchant") or "",
                notes=payload.get("notes") or "",
                mode=payload.get("mode") or "personal",
                source=payload.get("source") or "text",
                timestamp=ts,
            )
            if result.get("success"):
                t = result.get("transaction") or {}
                return (
                    f"Confirmed. Logged ₹{t.get('amount')} "
                    f"({t.get('merchant') or t.get('category')})."
                )
            return result.get("message") or "Could not log expense."

        if action == "delete_transaction":
            result = registry.execute(
                "delete_transaction",
                {"transaction_id": payload.get("transaction_id"), "confirmed": True},
                user_id=user_id,
            )
            if result.get("success") or result.get("ok"):
                return "Deleted."
            return result.get("message") or result.get("error") or "Could not delete."

        return "Nothing pending."

    def _rule_fallback(self, user_id: str, text: str, source: str) -> PipelineResult:
        result = TransactionService.log_expense_text(user_id, text)
        if result.get("success"):
            t = result.get("transaction") or {}
            reply = (
                f"Logged ₹{t.get('amount')} under {t.get('category')} "
                f"({t.get('merchant')})."
            )
        else:
            reply = result.get("message") or "Could not understand that expense."
        SessionStore.append_turn(user_id, "user", text)
        SessionStore.append_turn(user_id, "assistant", reply)
        return PipelineResult(text=reply, user_id=user_id, used_fallback=True)


def _user_tz(user_id: str) -> str:
    user = UserService.get_user(user_id) or {}
    return user.get("timezone") or Config.AGENT_TIMEZONE_DEFAULT
