"""
Telegram bot adapter for BudgetBot.

Uses long polling by default (TELEGRAM_MODE=polling).
Requires: TELEGRAM_BOT_TOKEN and python-telegram-bot installed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Set

from src.adapters.message_types import NormalizedInboundMessage
from src.agent.pipeline import AgentPipeline
from src.agent.session_store import SessionStore
from src.config import Config
from src.database import init_db
from src.logging_config import get_logger
from src.services import PocketService, UserService

logger = get_logger(__name__)


def _allowed_ids() -> Set[str]:
    return Config.telegram_allowlist()


def run_telegram_bot() -> None:
    """Entry point for `python main.py telegram`."""
    token = Config.TELEGRAM_BOT_TOKEN
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Add it to .env and try again."
        )

    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError as e:
        raise SystemExit(
            "python-telegram-bot is not installed. "
            "Run: pip install 'python-telegram-bot>=21.0'\n"
            f"Details: {e}"
        ) from e

    init_db()
    pipeline = AgentPipeline()
    allow = _allowed_ids()

    async def _ensure_user(update: Update) -> Optional[str]:
        user = update.effective_user
        if not user:
            return None
        tid = str(user.id)
        if allow and tid not in allow:
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Sorry, this bot is private."
                )
            return None
        result = UserService.get_or_create_by_telegram(
            tid, name=user.full_name or user.username
        )
        if not result.get("success"):
            return None
        user_id = result["user"]["id"]
        # Existing users created before default pockets still get them once
        try:
            PocketService.seed_default_pockets(user_id)
        except Exception as e:
            logger.warning(f"pocket seed: {e}")
        return user_id

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _ensure_user(update)
        if not user_id or not update.effective_message:
            return
        name = (update.effective_user.full_name if update.effective_user else "there")
        pockets = PocketService.get_user_pockets(user_id)
        pocket_line = ", ".join(p["name"] for p in pockets[:6]) if pockets else "none yet"
        await update.effective_message.reply_text(
            f"Hi {name}! I'm BudgetBot — your personal finance agent.\n\n"
            "Just type naturally (no special commands):\n"
            "• lunch 250\n"
            "• uber 180 yesterday\n"
            "• how much did I spend this week?\n"
            "• how much can I still spend?\n"
            "• change last to transport\n"
            "• delete last\n"
            "• set income to 80000\n\n"
            f"Starter pockets: {pocket_line}\n"
            "Tip: set your monthly income so “how much left?” is meaningful."
        )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message:
            await update.effective_message.reply_text(
                "Examples:\n"
                "• coffee 120\n"
                "• paid Mohit 500\n"
                "• uber 300 yesterday\n"
                "• food last week?\n"
                "• biggest expenses this month\n"
                "• how much can I still spend?\n"
                "• change last to transport\n"
                "• delete last\n"
                "• set food pocket to 10000"
            )

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_message.text:
            return
        user_id = await _ensure_user(update)
        if not user_id:
            return

        update_id = str(update.update_id)
        if not SessionStore.try_mark_processed("telegram", update_id, user_id):
            logger.info(f"Skipping duplicate update {update_id}")
            return

        text = update.effective_message.text
        await update.effective_message.chat.send_action("typing")

        result = await asyncio.to_thread(
            pipeline.handle_text, user_id, text, "text"
        )
        reply = result.text or "…"
        # Telegram message limit ~4096
        for i in range(0, len(reply), 3500):
            await update.effective_message.reply_text(reply[i : i + 3500])

    async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message:
            return
        user_id = await _ensure_user(update)
        if not user_id:
            return

        update_id = str(update.update_id)
        if not SessionStore.try_mark_processed("telegram", update_id, user_id):
            return

        if not Config.ENABLE_VOICE_PROCESSING:
            await update.effective_message.reply_text(
                "Voice is not enabled yet. Type the expense, or set "
                "ENABLE_VOICE_PROCESSING=True and STT_PROVIDER once Phase 4 is ready."
            )
            return

        voice = update.effective_message.voice or update.effective_message.audio
        if not voice:
            return

        await update.effective_message.chat.send_action("typing")
        file = await context.bot.get_file(voice.file_id)
        import os
        from pathlib import Path

        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        dest = Path(Config.UPLOAD_FOLDER) / "voice" / f"{user_id}_{update_id}.ogg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await file.download_to_drive(str(dest))

        from src.media.stt import transcribe

        transcript = await asyncio.to_thread(transcribe, dest)
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass

        if not transcript.strip():
            await update.effective_message.reply_text(
                "I couldn't understand that voice note. Try again or type the amount."
            )
            return

        result = await asyncio.to_thread(
            pipeline.handle_text, user_id, transcript, "voice"
        )
        await update.effective_message.reply_text(result.text or "…")

    app = (
        Application.builder()
        .token(token)
        .build()
    )
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))

    mode = (Config.TELEGRAM_MODE or "polling").lower()
    logger.info(f"Starting Telegram bot mode={mode}")
    print(f"📱 Telegram bot starting (mode={mode})…")
    if mode == "webhook" and Config.TELEGRAM_WEBHOOK_URL:
        # Basic webhook; production should set secrets / paths carefully
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("TELEGRAM_WEBHOOK_PORT", "8443")),
            url_path=token,
            webhook_url=Config.TELEGRAM_WEBHOOK_URL,
        )
    else:
        app.run_polling(allowed_updates=["message"])


# Avoid NameError in webhook branch without top-level import always
import os  # noqa: E402
