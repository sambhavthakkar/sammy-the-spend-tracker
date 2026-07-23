#!/usr/bin/env python3
"""Broadcast one plain-text Telegram message to configured allowlisted users."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Config


def send_broadcast(client: httpx.Client, token: str, recipients: set[str], message: str) -> tuple[int, int]:
    sent = failed = 0
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in recipients:
        try:
            response = client.post(url, json={"chat_id": chat_id, "text": message})
            response.raise_for_status()
            if not response.json().get("ok"):
                raise RuntimeError("Telegram rejected the message")
            sent += 1
        except Exception:
            failed += 1
    return sent, failed


def main() -> int:
    token = Config.TELEGRAM_BOT_TOKEN
    recipients = Config.telegram_allowlist()
    if not token:
        print("TELEGRAM_BOT_TOKEN is missing")
        return 1
    if not recipients:
        print("TELEGRAM_ALLOWED_USER_IDS is empty; nobody will be contacted")
        return 1

    message = input("Broadcast message: ").strip()
    if not message:
        print("Cancelled: empty message")
        return 1
    if len(message) > 4096:
        print("Message is longer than Telegram's 4096-character limit")
        return 1
    if input(f"Send to {len(recipients)} users? Type SEND: ").strip() != "SEND":
        print("Cancelled")
        return 1

    with httpx.Client(timeout=20) as client:
        sent, failed = send_broadcast(client, token, recipients, message)
    print(f"Sent: {sent}; failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
