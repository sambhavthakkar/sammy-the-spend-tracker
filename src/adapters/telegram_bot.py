"""
Telegram bot adapter for BudgetBot.

Uses long polling by default (TELEGRAM_MODE=polling).
Requires: TELEGRAM_BOT_TOKEN and python-telegram-bot installed.
"""
from __future__ import annotations

import asyncio
import math
import os
from datetime import date
from pathlib import Path
from typing import Optional, Set

from src.config import Config
from src.logging_config import get_logger
from src.media.bill_vision import (
    BillExtraction,
    close_bill_vision_client,
    extract_bill_from_image,
)
from src.personal_store import PersonalStore

logger = get_logger(__name__)


def _allowed_ids() -> Set[str]:
    """Fresh allowlist from .env (comma-separated Telegram user IDs)."""
    return Config.telegram_allowlist()


def _source_ref(update_id: object, source: str) -> str:
    return f"telegram:{update_id}:{source}"


def _user_lock(locks: dict[str, asyncio.Lock], user_id: str) -> asyncio.Lock:
    # ponytail: 200 users make retained locks harmless; prune if this grows to thousands.
    lock = locks.get(user_id)
    if lock is None:
        lock = locks[user_id] = asyncio.Lock()
    return lock


async def _run_limited(limit: asyncio.Semaphore, func, /, *args, **kwargs):
    async with limit:
        work = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            try:
                await work
            except Exception:
                pass
            raise


def _prepare_bill_confirmation(
    store: PersonalStore,
    user_key: str,
    extraction: BillExtraction,
    source_ref: str,
    caption: str = "",
) -> str:
    """Persist a concise bill exchange and stage a private transaction confirmation."""
    if not extraction.is_bill or not math.isfinite(extraction.amount) or extraction.amount <= 0:
        reply = extraction.summary or (
            "I couldn't find a readable bill amount. Try a clearer photo or type it."
        )
    else:
        merchant = extraction.merchant.strip() or "Unknown merchant"
        detail = caption.strip() or extraction.notes.strip()
        description = " — ".join(part for part in (merchant, detail) if part)[:500]
        currency = extraction.currency
        if len(currency) != 3 or not currency.isalpha():
            currency = Config.AGENT_CURRENCY_DEFAULT
        payload = {
            "kind": "expense",
            "amount": str(extraction.amount),
            "category": extraction.category or "other",
            "description": description,
            "source_ref": source_ref,
            "currency": currency,
        }
        if extraction.date:
            try:
                date.fromisoformat(extraction.date)
                payload["occurred_at"] = extraction.date
            except ValueError:
                pass
        store.set_pending_action(
            user_key,
            "confirmation",
            {"tool": "record_transaction", "args": payload},
        )
        reply = (
            f"I found {merchant}: {payload['currency'].upper()} {extraction.amount:g} "
            f"({payload['category']}). Record this expense? Reply yes or no."
        )

    bill_turn = f"[bill photo]{' ' + caption.strip() if caption.strip() else ''}"
    store.append_turn(user_key, "user", bill_turn)
    store.append_turn(user_key, "assistant", reply)
    return reply


def run_telegram_bot() -> None:
    """Entry point for `python main.py telegram`."""
    token = Config.TELEGRAM_BOT_TOKEN
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Add it to .env and try again."
        )
    if not _allowed_ids():
        raise SystemExit(
            "TELEGRAM_ALLOWED_USER_IDS is required for this private bot. "
            "Add your numeric Telegram user ID to .env."
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

    from src.personal_agent import PersonalAgent

    store = PersonalStore()
    agent = PersonalAgent(store=store)
    user_locks: dict[str, asyncio.Lock] = {}
    llm_slots = asyncio.Semaphore(Config.OLLAMA_MAX_CONCURRENCY)
    stt_slots = asyncio.Semaphore(Config.STT_MAX_CONCURRENCY)
    vision_slots = asyncio.Semaphore(Config.BILL_VISION_MAX_CONCURRENCY)

    def serialized(handler):
        async def wrapper(update, context):
            user = update.effective_user
            if not user:
                return await handler(update, context)
            async with _user_lock(user_locks, str(user.id)):
                return await handler(update, context)
        return wrapper

    async def _shutdown(_application) -> None:
        agent.llm.close()
        close_bill_vision_client()

    async def _ensure_user(update: Update) -> Optional[str]:
        user = update.effective_user
        if not user:
            return None
        tid = str(user.id)
        # Reload allowlist every message so .env edits apply without restart
        allow = _allowed_ids()
        if tid not in allow:
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Sorry, this bot is private."
                )
            return None
        return store.resolve_user(
            "telegram", tid, display_name=user.full_name or user.username
        )

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _ensure_user(update)
        if not user_id or not update.effective_message:
            return
        name = update.effective_user.full_name if update.effective_user else "there"
        await update.effective_message.reply_text(
            f"Hi {name}! I'm your private personal assistant.\n\n"
            "Talk to me naturally. I can remember preferences, goals, and events, "
            "help manage spending, and answer questions using what you've shared.\n\n"
            "You can type, send a voice note, or send a clear bill photo."
        )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_user(update) or not update.effective_message:
            return
        await update.effective_message.reply_text(
            "Chat naturally with your private personal assistant. For example:\n"
            "• remember that I prefer quiet restaurants\n"
            "• my goal is to run a 10K this year\n"
            "• I have a dentist appointment Friday\n"
            "• spent 400 on groceries\n"
            "• how much did I spend this month?\n"
            "You can also send a voice note or a bill photo."
        )

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_message.text:
            return
        user_id = await _ensure_user(update)
        if not user_id:
            return

        update_id = str(update.update_id)
        if store.is_processed(user_id, "telegram", update_id):
            logger.info(f"Skipping duplicate update {update_id}")
            return

        text = update.effective_message.text
        await update.effective_message.chat.send_action("typing")

        reply = await _run_limited(
            llm_slots,
            agent.chat,
            user_id,
            text,
            source="text",
            source_ref=_source_ref(update_id, "text"),
        )
        reply = reply or "…"
        # Telegram message limit ~4096
        for i in range(0, len(reply), 3500):
            await update.effective_message.reply_text(reply[i : i + 3500])
        store.mark_processed(user_id, "telegram", update_id)

    async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message:
            return
        user_id = await _ensure_user(update)
        if not user_id:
            return

        update_id = str(update.update_id)
        if store.is_processed(user_id, "telegram", update_id):
            return

        if not Config.ENABLE_VOICE_PROCESSING:
            await update.effective_message.reply_text(
                "Voice is disabled. Set ENABLE_VOICE_PROCESSING=True in .env "
                "(and install faster-whisper or configure STT_PROVIDER=openai)."
            )
            store.mark_processed(user_id, "telegram", update_id)
            return

        voice = update.effective_message.voice or update.effective_message.audio
        if not voice:
            store.mark_processed(user_id, "telegram", update_id)
            return

        await update.effective_message.chat.send_action("record_voice")
        file = await context.bot.get_file(voice.file_id)

        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        # Telegram voice is typically OGG/Opus
        dest = Path(Config.UPLOAD_FOLDER) / "voice" / f"{user_id}_{update_id}.ogg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await file.download_to_drive(str(dest))

        await update.effective_message.chat.send_action("typing")
        from src.media.stt import transcribe

        try:
            transcript = await _run_limited(stt_slots, transcribe, dest)
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
            store.mark_processed(user_id, "telegram", update_id)
            return

        if Config.STT_SHOW_TRANSCRIPT:
            # Short ack so user knows what we heard before the agent reply
            heard = transcript if len(transcript) <= 200 else transcript[:200] + "…"
            await update.effective_message.reply_text(f"Heard: {heard}")

        await update.effective_message.chat.send_action("typing")
        reply = await _run_limited(
            llm_slots,
            agent.chat,
            user_id,
            transcript,
            source="voice",
            source_ref=_source_ref(update_id, "voice"),
        )
        reply = reply or "…"
        for i in range(0, len(reply), 3500):
            await update.effective_message.reply_text(reply[i : i + 3500])
        store.mark_processed(user_id, "telegram", update_id)

    async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Bill / receipt photo → Gemma vision → private pending action."""
        if not update.effective_message:
            return
        user_id = await _ensure_user(update)
        if not user_id:
            return

        update_id = str(update.update_id)
        if store.is_processed(user_id, "telegram", update_id):
            return

        if not Config.ENABLE_BILL_VISION:
            await update.effective_message.reply_text(
                "Bill photos are disabled. Set ENABLE_BILL_VISION=True in .env."
            )
            store.mark_processed(user_id, "telegram", update_id)
            return

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
            store.mark_processed(user_id, "telegram", update_id)
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
            async with vision_slots:
                extraction = await _run_limited(
                    llm_slots, extract_bill_from_image, dest, mime
                )
            reply = _prepare_bill_confirmation(
                store,
                user_id,
                extraction,
                _source_ref(update_id, "bill"),
                caption,
            )
        except Exception as e:
            logger.error(f"Bill photo failed: {e}")
            reply = "I couldn't read that image. Send a clearer photo or type the amount."
            bill_turn = f"[bill photo]{' ' + caption if caption else ''}"
            store.append_turn(user_id, "user", bill_turn)
            store.append_turn(user_id, "assistant", reply)
        finally:
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass

        for i in range(0, len(reply), 3500):
            await update.effective_message.reply_text(reply[i : i + 3500])
        store.mark_processed(user_id, "telegram", update_id)

    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(Config.TELEGRAM_CONCURRENT_UPDATES)
        .post_shutdown(_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", serialized(start_cmd)))
    app.add_handler(CommandHandler("help", serialized(help_cmd)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, serialized(on_text)))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, serialized(on_voice)))
    app.add_handler(MessageHandler(filters.PHOTO, serialized(on_photo)))
    app.add_handler(
        MessageHandler(filters.Document.IMAGE, serialized(on_photo))
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
            drop_pending_updates=False,
        )
    else:
        # Only one process may poll this token
        app.run_polling(
            allowed_updates=["message"],
            drop_pending_updates=False,
        )


