"""Tool registry: OpenAI-compatible schemas + execution."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.agent.session_store import SessionStore
from src.config import Config
from src.logging_config import get_logger
from src.services import (
    BudgetService,
    CategoryPreferenceService,
    PocketService,
    TransactionService,
    UserService,
)
from src.timeutils.dates import inclusive_datetime_range, parse_absolute_date

logger = get_logger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[[str, Dict[str, Any]], Dict[str, Any]]

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: Optional[List[ToolSpec]] = None):
        self._tools: Dict[str, ToolSpec] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> List[dict]:
        return [t.openai_schema() for t in self._tools.values()]

    def execute(self, name: str, arguments: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        tool = self._tools.get(name)
        if not tool:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        args = dict(arguments or {})
        # Never trust model-supplied user_id
        args.pop("user_id", None)
        try:
            result = tool.handler(user_id, args)
            if not isinstance(result, dict):
                result = {"ok": True, "result": result}
            if "ok" not in result:
                # Map service success flags
                if "success" in result:
                    result = {**result, "ok": bool(result.get("success"))}
                else:
                    result = {"ok": True, **result}
            return result
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return {"ok": False, "error": str(e)}


def _resolve_txn_timestamp(date_str: Optional[str], timezone: str) -> Optional[datetime]:
    if not date_str:
        return None
    d = parse_absolute_date(date_str)
    start, _ = inclusive_datetime_range(d, d, timezone)
    # midday local to avoid edge TZ issues when stored naive
    return start.replace(hour=12, minute=0, second=0, microsecond=0)


def _user_tz(user_id: str) -> str:
    user = UserService.get_user(user_id) or {}
    return user.get("timezone") or Config.AGENT_TIMEZONE_DEFAULT


def _maybe_confirm_amount(user_id: str, amount: float, action_type: str, payload: dict) -> Optional[dict]:
    user = UserService.get_user(user_id) or {}
    income = float(user.get("income") or 0)
    threshold = Config.AGENT_CONFIRM_AMOUNT_THRESHOLD
    frac = Config.AGENT_CONFIRM_INCOME_FRACTION
    needs = amount >= threshold or (income > 0 and amount >= income * frac)
    if not needs:
        return None
    SessionStore.set_pending_action(user_id, action_type, payload)
    return {
        "ok": True,
        "needs_confirmation": True,
        "preview": payload,
        "message": f"Confirm logging ₹{amount:.0f}? Reply yes or no.",
    }


def handle_log_expense(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    amount = float(args.get("amount") or 0)
    if amount <= 0:
        return {"ok": False, "error": "amount must be > 0"}

    tz = _user_tz(user_id)
    date_str = args.get("date")
    ts = _resolve_txn_timestamp(date_str, tz)
    source = args.get("source") or "text"
    payload = {
        "amount": amount,
        "category": args.get("category"),
        "merchant": args.get("merchant") or "",
        "notes": args.get("notes") or "",
        "mode": args.get("mode") or "personal",
        "source": source,
        "date": date_str,
        "direction": "expense",
    }
    confirm = _maybe_confirm_amount(user_id, amount, "log_expense", payload)
    if confirm:
        return confirm

    result = TransactionService.log_expense_structured(
        user_id=user_id,
        amount=amount,
        category=args.get("category"),
        merchant=args.get("merchant") or "",
        notes=args.get("notes") or "",
        mode=args.get("mode") or "personal",
        source=source,
        timestamp=ts,
        direction="expense",
    )
    return result


def handle_log_income(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Money received / refund / transfer in / any unmanaged inflow.

    Smart layer should call this for ANY money-in intent, even if the
    category/source is unusual — capture it with notes rather than failing.
    """
    amount = float(args.get("amount") or 0)
    if amount <= 0:
        return {"ok": False, "error": "amount must be > 0 — ask user for the amount"}

    tz = _user_tz(user_id)
    date_str = args.get("date")
    ts = _resolve_txn_timestamp(date_str, tz)
    source = args.get("source") or "text"

    merchant = (
        args.get("merchant")
        or args.get("from")
        or args.get("payer")
        or args.get("source_name")
        or "Received"
    )
    category = (
        args.get("category")
        or args.get("against")
        or args.get("pocket")
        or "other"
    )
    category = str(category).strip().lower() or "other"
    notes = (args.get("notes") or args.get("raw_text") or "").strip()
    income_type = (args.get("income_type") or "received").strip().lower()
    # gift | refund | salary | transfer | cashback | reimbursement | other
    if income_type and income_type not in notes.lower():
        notes = f"[{income_type}] {notes}".strip() if notes else f"[{income_type}]"

    credit_pocket = args.get("credit_pocket")
    if credit_pocket is None:
        # Default: credit pocket when category is a real bucket, not generic "other"
        credit_pocket = category not in ("other", "misc", "general", "income", "salary")

    # Ensure pocket exists so "against X" always works as a feature
    pocket_ensured = None
    if credit_pocket and category not in ("other", "misc", "general", "income", "salary"):
        pockets = PocketService.get_user_pockets(user_id)
        names = {p["name"].lower() for p in pockets}
        if category not in names:
            # Title-case pocket name from category
            pocket_name = category.replace("_", " ").strip().title()
            limit = float(args.get("pocket_limit") or 5000)
            pocket_ensured = PocketService.upsert_pocket(user_id, pocket_name, limit)
            category = pocket_name.lower()

    payload = {
        "amount": amount,
        "category": category,
        "merchant": merchant,
        "notes": notes,
        "mode": args.get("mode") or "personal",
        "source": source,
        "date": date_str,
        "direction": "income",
        "credit_pocket": bool(credit_pocket),
    }
    confirm = _maybe_confirm_amount(user_id, amount, "log_income", payload)
    if confirm:
        confirm["message"] = (
            f"Confirm received ₹{amount:.0f} from {merchant}"
            + (f" (against {category})" if credit_pocket else "")
            + "? Reply yes or no."
        )
        return confirm

    # If not crediting pocket, force category path that won't reverse pocket spend badly:
    # still store category for filtering; pocket credit only when credit_pocket
    direction_category = category if credit_pocket else "other"
    # Keep user's category in notes if we collapse to other for pocket logic
    final_notes = notes
    if not credit_pocket and category not in ("other", "misc"):
        final_notes = f"{notes} | tag:{category}".strip(" |")

    result = TransactionService.log_expense_structured(
        user_id=user_id,
        amount=amount,
        category=direction_category if credit_pocket else category,
        merchant=merchant,
        notes=final_notes,
        mode=args.get("mode") or "personal",
        source=source,
        timestamp=ts,
        direction="income",
    )
    if isinstance(result, dict):
        result["pocket_ensured"] = pocket_ensured
        result["income_type"] = income_type
        result["credit_pocket"] = bool(credit_pocket)
    return result


def handle_update_transaction(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    txn_id = args.get("transaction_id") or "last"
    # Allow short id prefix match or "last"
    full_id = _resolve_transaction_id(user_id, str(txn_id))
    if not full_id:
        return {"ok": False, "error": "transaction not found"}

    fields = {}
    for key in ("amount", "category", "merchant", "notes", "direction"):
        if key in args and args[key] is not None:
            fields[key] = args[key]

    if "date" in args and args["date"]:
        fields["timestamp"] = _resolve_txn_timestamp(args["date"], _user_tz(user_id))

    # Learn category preference when category corrected
    if fields.get("category"):
        notes_hint = fields.get("notes") or fields.get("merchant") or ""
        if notes_hint:
            CategoryPreferenceService.add_or_update_preference(
                user_id, str(notes_hint), str(fields["category"])
            )

    result = TransactionService.update_transaction(full_id, **fields)
    return result


def handle_delete_transaction(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    txn_id = args.get("transaction_id") or "last"
    full_id = _resolve_transaction_id(user_id, str(txn_id))
    if not full_id:
        return {"ok": False, "error": "transaction not found"}

    # Soft confirm large deletes
    recent = TransactionService.get_user_transactions(user_id, limit=50)
    match = next((t for t in recent if t["id"] == full_id), None)
    if match and float(match.get("amount") or 0) >= Config.AGENT_CONFIRM_AMOUNT_THRESHOLD:
        if not args.get("confirmed"):
            SessionStore.set_pending_action(
                user_id,
                "delete_transaction",
                {"transaction_id": full_id, "amount": match.get("amount")},
            )
            return {
                "ok": True,
                "needs_confirmation": True,
                "message": f"Delete ₹{match.get('amount')} ({match.get('merchant')})? Reply yes or no.",
            }

    return TransactionService.delete_transaction(full_id)


def _resolve_transaction_id(user_id: str, txn_id: str) -> Optional[str]:
    """Resolve full id, short prefix, or aliases like 'last' / 'latest'."""
    key = (txn_id or "").strip().lower()
    txns = TransactionService.get_user_transactions(user_id, limit=100)
    if not txns:
        return None
    if key in ("last", "latest", "previous", "recent", "that", "it", "last_one", "last one"):
        return txns[0]["id"]
    for t in txns:
        if t["id"] == txn_id or t["id"].startswith(txn_id):
            return t["id"]
    return None


def handle_list_recent(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit") or Config.AGENT_RECENT_TXNS)
    txns = TransactionService.get_user_transactions(user_id, limit=limit, timezone=_user_tz(user_id))
    return {"ok": True, "transactions": txns}


def handle_find_transactions(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    tz = _user_tz(user_id)
    on_date = args.get("on_date")
    from_date = args.get("from_date")
    to_date = args.get("to_date")
    if on_date:
        from_date = on_date
        to_date = on_date
    txns = TransactionService.get_user_transactions(
        user_id,
        limit=int(args.get("limit") or 20),
        from_date=from_date,
        to_date=to_date,
        category=args.get("category"),
        merchant=args.get("merchant"),
        timezone=tz,
    )
    return {"ok": True, "transactions": txns, "count": len(txns)}


def handle_query_spending(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    from_date = args.get("from_date")
    to_date = args.get("to_date")
    if not from_date or not to_date:
        return {"ok": False, "error": "from_date and to_date (YYYY-MM-DD) are required"}
    group_by = (args.get("group_by") or "none").lower()
    category = args.get("category")
    direction = (args.get("direction") or "expense").lower()
    tz = _user_tz(user_id)
    if group_by in ("none", "", "total"):
        return TransactionService.sum_spending(
            user_id,
            from_date,
            to_date,
            category=category,
            timezone=tz,
            direction=direction,
        )
    return TransactionService.spending_breakdown(
        user_id,
        from_date,
        to_date,
        group_by=group_by,
        category=category,
        timezone=tz,
    )


def handle_budget_snapshot(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return BudgetService.get_budget_snapshot(user_id)


def handle_list_pockets(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "pockets": PocketService.get_user_pockets(user_id)}


def handle_create_or_update_pocket(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name required"}
    limit = float(args.get("monthly_limit") or 0)
    return PocketService.upsert_pocket(user_id, name, limit)


def handle_top_expenses(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    from_date = args.get("from_date")
    to_date = args.get("to_date")
    if not from_date or not to_date:
        return {"ok": False, "error": "from_date and to_date required (YYYY-MM-DD)"}
    return TransactionService.top_expenses(
        user_id,
        from_date,
        to_date,
        limit=int(args.get("limit") or 5),
        timezone=_user_tz(user_id),
    )


def handle_get_profile(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    user = UserService.get_user(user_id)
    if not user:
        return {"ok": False, "error": "user not found"}
    return {"ok": True, "user": user}


def handle_set_income(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    income = float(args.get("income") or 0)
    return UserService.update_income(user_id, income)


def handle_ask_user(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "ask": True,
        "question": args.get("question") or "Could you clarify?",
        "choices": args.get("choices"),
    }


def get_default_registry() -> ToolRegistry:
    tools = [
        ToolSpec(
            name="log_expense",
            description=(
                "Log money OUT (spent/paid/bought). Use for expenses only — NOT for money received. "
                "category: food|transport|shopping|utilities|health|entertainment|education|other. "
                "date YYYY-MM-DD optional (default today)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "category": {"type": "string"},
                    "merchant": {"type": "string"},
                    "notes": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "mode": {"type": "string", "enum": ["personal", "business"]},
                    "source": {"type": "string", "enum": ["text", "voice", "bill"]},
                },
                "required": ["amount"],
            },
            handler=handle_log_expense,
        ),
        ToolSpec(
            name="log_income",
            description=(
                "Log ANY money IN (received/got/refund/cashback/gift/freelance/salary credit/"
                "transfer from someone/reimbursement). Use this whenever money came TO the user, "
                "even if the case is unusual — capture it; do not refuse. "
                "Examples: 'received 5000 from mom', 'got refund 200 amazon', "
                "'received 1500 against food', 'cousin sent 800 for dinner share'. "
                "merchant/from = who/what source. category/against/pocket = bucket to credit if any. "
                "notes/raw_text = full meaning. income_type: gift|refund|salary|transfer|cashback|"
                "reimbursement|freelance|other. credit_pocket true/false."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "merchant": {
                        "type": "string",
                        "description": "Who/what the money came from",
                    },
                    "from": {"type": "string"},
                    "payer": {"type": "string"},
                    "category": {
                        "type": "string",
                        "description": "Pocket/category if relevant (food, rent share, etc.)",
                    },
                    "against": {"type": "string"},
                    "pocket": {"type": "string"},
                    "notes": {"type": "string"},
                    "raw_text": {
                        "type": "string",
                        "description": "Original user message for searchability",
                    },
                    "income_type": {
                        "type": "string",
                        "description": "gift|refund|salary|transfer|cashback|reimbursement|freelance|other",
                    },
                    "credit_pocket": {
                        "type": "boolean",
                        "description": "If true, credit matching budget pocket (creates pocket if missing)",
                    },
                    "pocket_limit": {
                        "type": "number",
                        "description": "Monthly limit if creating a new pocket (default 5000)",
                    },
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "source": {"type": "string", "enum": ["text", "voice", "bill"]},
                },
                "required": ["amount"],
            },
            handler=handle_log_income,
        ),
        ToolSpec(
            name="log_money",
            description=(
                "Universal money logger when intent is mixed or you need one call. "
                "direction must be 'expense' or 'income'. Prefer log_expense / log_income when clear; "
                "use this as a smart catch-all so nothing money-related is dropped."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["expense", "income"]},
                    "amount": {"type": "number"},
                    "merchant": {"type": "string"},
                    "category": {"type": "string"},
                    "notes": {"type": "string"},
                    "raw_text": {"type": "string"},
                    "date": {"type": "string"},
                    "source": {"type": "string", "enum": ["text", "voice", "bill"]},
                    "credit_pocket": {"type": "boolean"},
                },
                "required": ["direction", "amount"],
            },
            handler=lambda uid, args: (
                handle_log_income(uid, args)
                if (args.get("direction") or "").lower() == "income"
                else handle_log_expense(uid, args)
            ),
        ),
        ToolSpec(
            name="update_transaction",
            description=(
                "Update an existing transaction. Use transaction_id='last' for the most recent "
                "expense, or a full/short id."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "Transaction id, short prefix, or 'last'",
                    },
                    "amount": {"type": "number"},
                    "category": {"type": "string"},
                    "merchant": {"type": "string"},
                    "notes": {"type": "string"},
                    "date": {"type": "string"},
                },
            },
            handler=handle_update_transaction,
        ),
        ToolSpec(
            name="delete_transaction",
            description="Delete a transaction. Use transaction_id='last' for the most recent expense.",
            parameters={
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "Transaction id, short prefix, or 'last'",
                    },
                    "confirmed": {"type": "boolean"},
                },
            },
            handler=handle_delete_transaction,
        ),
        ToolSpec(
            name="top_expenses",
            description="List the largest expenses in an inclusive date range (YYYY-MM-DD).",
            parameters={
                "type": "object",
                "properties": {
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["from_date", "to_date"],
            },
            handler=handle_top_expenses,
        ),
        ToolSpec(
            name="list_recent_transactions",
            description="List the most recent transactions.",
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
            handler=handle_list_recent,
        ),
        ToolSpec(
            name="find_transactions",
            description="Find transactions filtered by date range, single day, category, or merchant.",
            parameters={
                "type": "object",
                "properties": {
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"},
                    "on_date": {"type": "string"},
                    "category": {"type": "string"},
                    "merchant": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            handler=handle_find_transactions,
        ),
        ToolSpec(
            name="query_spending",
            description=(
                "Sum money movements for a date range (absolute YYYY-MM-DD). "
                "Default direction=expense (spending). Use direction=income for money received. "
                "group_by: none|category|day|merchant."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"},
                    "group_by": {
                        "type": "string",
                        "enum": ["none", "category", "day", "merchant"],
                    },
                    "category": {"type": "string"},
                    "direction": {
                        "type": "string",
                        "enum": ["expense", "income", "all"],
                    },
                },
                "required": ["from_date", "to_date"],
            },
            handler=handle_query_spending,
        ),
        ToolSpec(
            name="get_budget_snapshot",
            description="Get income, committed spend, total spent, available to spend, and pocket details.",
            parameters={"type": "object", "properties": {}},
            handler=handle_budget_snapshot,
        ),
        ToolSpec(
            name="list_pockets",
            description="List budget pockets and remaining amounts.",
            parameters={"type": "object", "properties": {}},
            handler=handle_list_pockets,
        ),
        ToolSpec(
            name="create_or_update_pocket",
            description="Create a budget pocket with a monthly limit.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "monthly_limit": {"type": "number"},
                },
                "required": ["name", "monthly_limit"],
            },
            handler=handle_create_or_update_pocket,
        ),
        ToolSpec(
            name="get_profile",
            description="Get user profile including income and timezone.",
            parameters={"type": "object", "properties": {}},
            handler=handle_get_profile,
        ),
        ToolSpec(
            name="set_income",
            description="Set the user's monthly income.",
            parameters={
                "type": "object",
                "properties": {"income": {"type": "number"}},
                "required": ["income"],
            },
            handler=handle_set_income,
        ),
        ToolSpec(
            name="ask_user",
            description="Ask the user a clarifying question when blocked.",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question"],
            },
            handler=handle_ask_user,
        ),
    ]
    return ToolRegistry(tools)
