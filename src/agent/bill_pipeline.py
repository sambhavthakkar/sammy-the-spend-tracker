"""Handle bill/receipt images: Gemma vision → optional confirm → log expense."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.agent.pipeline import PipelineResult
from src.agent.session_store import SessionStore
from src.config import Config
from src.logging_config import get_logger
from src.media.bill_vision import BillExtraction, extract_bill_from_image
from src.services import TransactionService, UserService
from src.timeutils.dates import inclusive_datetime_range, parse_absolute_date

logger = get_logger(__name__)


def handle_bill_image(
    user_id: str,
    image_path: Path | str,
    mime: str = "image/jpeg",
) -> PipelineResult:
    """
    Read a bill image with Gemma and log (or ask confirmation).
    """
    if not Config.ENABLE_BILL_VISION:
        return PipelineResult(
            text=(
                "Bill photos are disabled. Set ENABLE_BILL_VISION=True in .env "
                "(uses your Gemma model on Ollama)."
            ),
            user_id=user_id,
        )

    extraction = extract_bill_from_image(image_path, mime=mime)
    logger.info(f"Bill extraction: {extraction.to_dict()}")

    SessionStore.append_turn(
        user_id,
        "user",
        f"[bill image] {extraction.summary}",
    )

    if not extraction.is_bill:
        reply = (
            extraction.summary
            or "That doesn't look like a bill or receipt. Send a clearer photo of the total, or type the amount."
        )
        SessionStore.append_turn(user_id, "assistant", reply)
        return PipelineResult(text=reply, user_id=user_id)

    if extraction.amount <= 0:
        reply = (
            f"I looked at the image ({extraction.summary}) but couldn't find a clear total. "
            "Reply with the amount, e.g. `bill 450`."
        )
        SessionStore.append_turn(user_id, "assistant", reply)
        return PipelineResult(text=reply, user_id=user_id)

    # Large amount / low confidence → confirm via pending_actions (same as agent)
    user = UserService.get_user(user_id) or {}
    income = float(user.get("income") or 0)
    large = extraction.amount >= Config.AGENT_CONFIRM_AMOUNT_THRESHOLD or (
        income > 0 and extraction.amount >= income * Config.AGENT_CONFIRM_INCOME_FRACTION
    )
    if extraction.needs_confirmation or large or extraction.confidence < 0.75:
        payload = {
            "amount": extraction.amount,
            "category": extraction.category,
            "merchant": extraction.merchant,
            "notes": extraction.notes or extraction.summary,
            "mode": "personal",
            "source": "bill",
            "date": extraction.date,
        }
        SessionStore.set_pending_action(user_id, "log_expense", payload)
        reply = (
            f"From the bill I see:\n"
            f"• ₹{extraction.amount:.0f} at {extraction.merchant}\n"
            f"• category: {extraction.category}\n"
            f"• confidence: {extraction.confidence:.0%}\n"
            f"{extraction.summary}\n\n"
            f"Log this? Reply yes or no."
        )
        SessionStore.append_turn(user_id, "assistant", reply)
        return PipelineResult(text=reply, user_id=user_id)

    result = _log_extraction(user_id, extraction)
    SessionStore.append_turn(user_id, "assistant", result)
    return PipelineResult(text=result, user_id=user_id)


def _log_extraction(user_id: str, extraction: BillExtraction) -> str:
    ts = None
    if extraction.date:
        try:
            user = UserService.get_user(user_id) or {}
            tz = user.get("timezone") or Config.AGENT_TIMEZONE_DEFAULT
            d = parse_absolute_date(extraction.date)
            start, _ = inclusive_datetime_range(d, d, tz)
            ts = start.replace(hour=12, minute=0, second=0, microsecond=0)
        except Exception:
            ts = None

    logged = TransactionService.log_expense_structured(
        user_id=user_id,
        amount=extraction.amount,
        category=extraction.category,
        merchant=extraction.merchant,
        notes=extraction.notes or extraction.summary,
        mode="personal",
        source="bill",
        timestamp=ts or datetime.utcnow(),
        currency=extraction.currency,
    )
    if not logged.get("success"):
        return logged.get("message") or "Could not save the bill expense."

    t = logged.get("transaction") or {}
    pocket = logged.get("pocket_update") or {}
    parts = [
        f"Logged bill: ₹{t.get('amount')} at {t.get('merchant')} ({t.get('category')}).",
    ]
    if pocket.get("success") and pocket.get("pocket_name"):
        parts.append(
            f"{pocket.get('pocket_name')} pocket remaining: ₹{pocket.get('remaining', 0):.0f}."
        )
    parts.append(f"({extraction.summary})")
    return " ".join(parts)
