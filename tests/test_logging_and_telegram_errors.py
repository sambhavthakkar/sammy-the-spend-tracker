"""Logging hierarchy and Telegram error-handler classification."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_get_logger_nests_under_budgetbot():
    from src.logging_config import get_logger, setup_logger

    setup_logger()
    root = get_logger()
    child = get_logger("src.adapters.telegram_bot")
    already = get_logger("budgetbot.already")

    assert root.name == "budgetbot"
    assert child.name == "budgetbot.src.adapters.telegram_bot"
    assert already.name == "budgetbot.already"
    node = child
    while node and node.name != "budgetbot":
        node = node.parent
    assert node is root
    assert root.handlers, "budgetbot logger should have handlers"


def test_handle_telegram_error_classifies(monkeypatch):
    from telegram.error import NetworkError, RetryAfter, TelegramError

    from src.adapters import telegram_bot as tb

    warnings: list[str] = []
    errors: list[str] = []

    monkeypatch.setattr(
        tb.logger,
        "warning",
        lambda msg, *args, **kwargs: warnings.append(msg % args if args else str(msg)),
    )
    monkeypatch.setattr(
        tb.logger,
        "error",
        lambda msg, *args, **kwargs: errors.append(msg % args if args else str(msg)),
    )

    async def run():
        await tb.handle_telegram_error(None, SimpleNamespace(error=NetworkError("dns failed")))
        await tb.handle_telegram_error(None, SimpleNamespace(error=RetryAfter(5)))
        await tb.handle_telegram_error(
            SimpleNamespace(update_id=42),
            SimpleNamespace(error=TelegramError("boom")),
        )
        await tb.handle_telegram_error(None, SimpleNamespace(error=None))

    asyncio.run(run())

    assert any("network error" in w.lower() for w in warnings)
    assert any("rate limited" in w.lower() for w in warnings)
    assert len(errors) == 1
    assert "update_id=42" in errors[0]
