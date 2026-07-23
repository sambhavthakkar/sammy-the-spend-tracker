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
    """Fresh allowlist from .env (comma-separated Telegram user IDs)."""
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

    async def _ensure_user(update: Update) -> Optional[str]:
        user = update.effective_user
        if not user:
            return None
        tid = str(user.id)
        # Reload allowlist every message so .env edits apply without restart
        allow = _allowed_ids()
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
        # Only seed pockets when user was just created (avoid DB hit every message)
        if result.get("created"):
            try:
                PocketService.seed_default_pockets(user_id)
            except Exception as e:
                logger.warning(f"pocket seed: {e}")
        return user_id

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _ensure_user(update)
        if not user_id or not update.effective_message:
            return
        # Backfill pockets once on /start for older users
        try:
            PocketService.seed_default_pockets(user_id)
        except Exception as e:
            logger.warning(f"pocket seed on start: {e}")
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
            "Tip: set your monthly income so “how much left?” is meaningful.\n"
            "Voice: say “lunch two hundred fifty”.\n"
            "Bills: send a clear photo of the receipt — Gemma reads it."
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
                "• set food pocket to 10000\n"
                "• voice note: “spent 400 on petrol”\n"
                "• photo of a bill / receipt / UPI screenshot"
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
                "Voice is disabled. Set ENABLE_VOICE_PROCESSING=True in .env "
                "(and install faster-whisper or configure STT_PROVIDER=openai)."
            )
            return

        voice = update.effective_message.voice or update.effective_message.audio
        if not voice:
            return

        await update.effective_message.chat.send_action("record_voice")
        file = await context.bot.get_file(voice.file_id)
        import os
        from pathlib import Path

        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        # Telegram voice is typically OGG/Opus
        dest = Path(Config.UPLOAD_FOLDER) / "voice" / f"{user_id}_{update_id}.ogg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await file.download_to_drive(str(dest))

        await update.effective_message.chat.send_action("typing")
        from src.media.stt import transcribe

        try:
            transcript = await asyncio.to_thread(transcribe, dest)
        except Exception as e:
            logger.error(f"STT error: {e}")
            transcript = ""
        finally:
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass

        if not transcript.strip():
            await update.effective_message.reply_text(
                "I couldn't understand that voice note. "
                "Speak clearly with an amount (e.g. “lunch two hundred fifty”), "
                "or type it instead.\n"
                f"(STT provider: {Config.STT_PROVIDER})"
            )
            return

        if Config.STT_SHOW_TRANSCRIPT:
            # Short ack so user knows what we heard before the agent reply
            heard = transcript if len(transcript) <= 200 else transcript[:200] + "…"
            await update.effective_message.reply_text(f"Heard: {heard}")

        await update.effective_message.chat.send_action("typing")
        result = await asyncio.to_thread(
            pipeline.handle_text, user_id, transcript, "voice"
        )
        reply = result.text or "…"
        for i in range(0, len(reply), 3500):
            await update.effective_message.reply_text(reply[i : i + 3500])

    async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Bill / receipt photo → Gemma vision → log expense."""
        if not update.effective_message:
            return
        user_id = await _ensure_user(update)
        if not user_id:
            return

        update_id = str(update.update_id)
        if not SessionStore.try_mark_processed("telegram", update_id, user_id):
            return

        if not Config.ENABLE_BILL_VISION:
            await update.effective_message.reply_text(
                "Bill photos are disabled. Set ENABLE_BILL_VISION=True in .env."
            )
            return

        import os
        from pathlib import Path

        from src.agent.bill_pipeline import handle_bill_image

        # Prefer highest resolution photo; also accept image documents
        mime = "image/jpeg"
        file_id = None
        if update.effective_message.photo:
            file_id = update.effective_message.photo[-1].file_id
            mime = "image/jpeg"
        elif update.effective_message.document and (
            update.effective_message.document.mime_type or ""
        ).startswith("image/"):
            file_id = update.effective_message.document.file_id
            mime = update.effective_message.document.mime_type or "image/jpeg"
        else:
            return

        await update.effective_message.chat.send_action("upload_photo")
        tg_file = await context.bot.get_file(file_id)
        dest = Path(Config.UPLOAD_FOLDER) / "bills" / f"{user_id}_{update_id}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await tg_file.download_to_drive(str(dest))

        caption = (update.effective_message.caption or "").strip()
        await update.effective_message.reply_text(
            "Reading bill with Gemma… (a few seconds)"
        )
        await update.effective_message.chat.send_action("typing")

        try:
            result = await asyncio.to_thread(
                handle_bill_image, user_id, dest, mime
            )
            reply = result.text or "…"
            # If user added a caption like "this was transport", fold into follow-up
            if caption and result.text and "Log this?" not in (result.text or ""):
                # Optional: pass caption to agent as correction hint next turn
                SessionStore.append_turn(user_id, "user", f"[bill caption] {caption}")
        except Exception as e:
            logger.error(f"Bill photo failed: {e}")
            reply = (
                "I couldn't read that image with Gemma. "
                "Send a clearer photo of the total, or type e.g. `swiggy 450`."
            )
        finally:
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass

        for i in range(0, len(reply), 3500):
            await update.effective_message.reply_text(reply[i : i + 3500])

    app = (
        Application.builder()
        .token(token)
        .build()
    )
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(
        MessageHandler(filters.Document.IMAGE, on_photo)
    )

    mode = (Config.TELEGRAM_MODE or "polling").lower()
    logger.info(f"Starting Telegram bot mode={mode}")
    print(f"📱 Telegram bot starting (mode={mode})…")
    if mode == "webhook" and Config.TELEGRAM_WEBHOOK_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("TELEGRAM_WEBHOOK_PORT", "8443")),
            url_path=token,
            webhook_url=Config.TELEGRAM_WEBHOOK_URL,
            drop_pending_updates=True,
        )
    else:
        # Only one process may poll this token
        app.run_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
        )


# Avoid NameError in webhook branch without top-level import always
import os  # noqa: E402

