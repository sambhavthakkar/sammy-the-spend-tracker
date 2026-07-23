"""Build structured context injected into the agent system prompt."""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.agent.session_store import SessionStore
from src.config import Config
from src.services import BudgetService, PocketService, TransactionService, UserService
from src.timeutils.dates import clock_block, today


class ContextBuilder:
    @staticmethod
    def build(user_id: str) -> Dict[str, Any]:
        user = UserService.get_user(user_id) or {}
        # Enrich with full profile if available
        tz = user.get("timezone") or Config.AGENT_TIMEZONE_DEFAULT
        currency = user.get("currency") or Config.AGENT_CURRENCY_DEFAULT

        # Prefer full row via update_profile path fields — re-fetch via get may lack timezone
        # until get_user is updated; context uses Config defaults as fallback.
        pockets = PocketService.get_user_pockets(user_id)
        recent = TransactionService.get_user_transactions(
            user_id, limit=Config.AGENT_RECENT_TXNS, timezone=tz
        )
        snapshot = BudgetService.get_budget_snapshot(user_id)
        pending = SessionStore.get_pending_action(user_id)
        memory = SessionStore.get_recent_turns(user_id)

        return {
            "user_id": user_id,
            "user": user,
            "timezone": tz,
            "currency": currency,
            "pockets": pockets,
            "recent_transactions": recent,
            "snapshot": snapshot,
            "pending_action": pending,
            "memory": memory,
            "today": today(tz).isoformat(),
        }

    @staticmethod
    def format_system_context(ctx: Dict[str, Any]) -> str:
        user = ctx.get("user") or {}
        tz = ctx.get("timezone") or Config.AGENT_TIMEZONE_DEFAULT
        lines = [clock_block(tz), ""]

        lines.append("## User profile")
        lines.append(f"Name: {user.get('name', 'Friend')}")
        lines.append(f"Income (monthly): {user.get('income', 0)}")
        lines.append(f"Currency: {ctx.get('currency', 'INR')}")
        lines.append(f"Timezone: {tz}")
        lines.append("")

        lines.append("## Pockets (MTD)")
        pockets = ctx.get("pockets") or []
        if not pockets:
            lines.append("(none configured)")
        else:
            for p in pockets:
                lines.append(
                    f"- {p.get('name')}: limit={p.get('monthly_limit')} "
                    f"spent={p.get('spent_mtd')} remaining={p.get('remaining')}"
                )
        lines.append("")

        lines.append("## Recent transactions")
        recent = ctx.get("recent_transactions") or []
        if not recent:
            lines.append("(none yet)")
        else:
            for t in recent:
                tid = (t.get("id") or "")[:8]
                direction = t.get("direction") or "expense"
                lines.append(
                    f"- id={tid}… {direction} date={t.get('timestamp')} "
                    f"amount={t.get('amount')} category={t.get('category')} "
                    f"merchant={t.get('merchant')}"
                )
        lines.append("")
        lines.append(
            "## Smart layer note\n"
            "Income logging is fully supported (log_income / log_money). "
            "If user describes any money-in situation, resolve it with tools — "
            "do not say the feature is missing."
        )
        lines.append("")

        snap_wrap = ctx.get("snapshot") or {}
        snap = snap_wrap.get("snapshot") if isinstance(snap_wrap, dict) and "snapshot" in snap_wrap else snap_wrap
        if snap and isinstance(snap, dict) and snap.get("total_income") is not None:
            lines.append("## Budget snapshot (quick)")
            lines.append(
                f"income={snap.get('total_income')} committed={snap.get('total_committed')} "
                f"spent={snap.get('total_spent')} available={snap.get('available_to_spend')}"
            )
            lines.append("")

        pending = ctx.get("pending_action")
        if pending:
            lines.append("## Pending confirmation")
            lines.append(f"action={pending.get('action_type')} payload={pending.get('payload')}")
            lines.append("If user says yes/confirm/haan, execute; if no/cancel, discard.")
            lines.append("")

        return "\n".join(lines)
