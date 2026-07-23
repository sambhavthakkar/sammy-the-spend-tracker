#!/usr/bin/env python3
"""
Wipe the database and notify all known Telegram users.

Order:
  1) Collect telegram_ids (before wipe)
  2) Send broadcast message
  3) Delete SQLite file / recreate schema

Usage:
  PYTHONPATH=. python scripts/reset_and_notify.py
  make db-fresh-notify
"""
from __future__ import annotations

import os
import sys

# project root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(override=True)

NOTIFY_TEXT = (
    "🔄 Data refreshed and now start logging.\n\n"
    "Previous expenses, budgets, and history were cleared.\n"
    "Send /start or just type something like `lunch 250`."
)


def main() -> int:
    from src.config import Config
    from src.database import init_db, get_db, User, get_database_url

    token = (Config.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        return 1

    init_db(reset=False)
    db = get_db()
    try:
        users = (
            db.query(User)
            .filter(User.telegram_id.isnot(None), User.telegram_id != "")
            .all()
        )
        recipients = [
            {"telegram_id": str(u.telegram_id), "name": u.name or ""}
            for u in users
        ]
    finally:
        db.close()

    print(f"Found {len(recipients)} Telegram user(s) to notify")
    print(f"DB before wipe: {get_database_url()}")

    # 1) Notify while we still know who they are
    sent, failed = _broadcast(token, recipients, NOTIFY_TEXT)
    print(f"Notify: sent={sent} failed={failed}")

    # 2) Wipe DB
    _wipe_sqlite()
    init_db(reset=True)
    print(f"DB wiped and recreated: {get_database_url()}")
    print("Done. Users will re-onboard on next message (/start).")
    return 0


def _broadcast(token: str, recipients: list, text: str) -> tuple[int, int]:
    import httpx

    sent = 0
    failed = 0
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with httpx.Client(timeout=30) as client:
        for r in recipients:
            chat_id = r["telegram_id"]
            try:
                resp = client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                    },
                )
                data = resp.json()
                if data.get("ok"):
                    sent += 1
                    print(f"  ✓ notified {chat_id} ({r.get('name')})")
                else:
                    failed += 1
                    print(f"  ✗ {chat_id}: {data}")
            except Exception as e:
                failed += 1
                print(f"  ✗ {chat_id}: {e}")
    return sent, failed


def _wipe_sqlite() -> None:
    from src.database import get_database_url
    import src.database as dbmod

    url = get_database_url()
    # dispose engine so file can be deleted
    if dbmod.engine is not None:
        try:
            dbmod.engine.dispose()
        except Exception:
            pass
        dbmod.engine = None
        dbmod.SessionLocal = None

    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
        # relative path
        if not os.path.isabs(path):
            path = os.path.join(ROOT, path)
        for p in (path, path + "-wal", path + "-shm", path + "-journal"):
            if os.path.isfile(p):
                os.remove(p)
                print(f"  removed {p}")
    else:
        print(
            f"  Non-SQLite URL ({url}): tables will be dropped via create_all only. "
            "For Postgres, truncate manually if needed."
        )


if __name__ == "__main__":
    raise SystemExit(main())
