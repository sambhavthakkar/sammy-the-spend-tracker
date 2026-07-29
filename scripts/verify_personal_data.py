#!/usr/bin/env python3
"""
Pre-start gate for deploy: confirm registry + per-user DBs look intact.

Usage:
  PYTHONPATH=. python scripts/verify_personal_data.py
  PYTHONPATH=. python scripts/verify_personal_data.py --min-users 1
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify personal_data integrity")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override PERSONAL_DATA_DIR (default: from Config)",
    )
    parser.add_argument(
        "--min-users",
        type=int,
        default=1,
        help="Fail if fewer than this many user DB files (default 1)",
    )
    parser.add_argument(
        "--expect-identities",
        type=int,
        default=None,
        help="Fail if identity row count != this value",
    )
    args = parser.parse_args()

    from src.config import Config
    from src.personal_store import PersonalStore

    store = PersonalStore(args.data_dir or Config.PERSONAL_DATA_DIR)
    data_dir = store.data_dir
    registry = store.registry_path
    users_dir = store.users_dir

    print(f"data_dir: {data_dir}")
    if not data_dir.is_dir():
        print("FAIL: personal_data directory missing")
        return 1
    if not registry.is_file():
        print("FAIL: registry.sqlite3 missing — Telegram IDs will not map to users")
        return 1

    identities = []
    with sqlite3.connect(registry) as db:
        db.row_factory = sqlite3.Row
        try:
            identities = list(
                db.execute(
                    "SELECT provider, external_id, user_key FROM identities ORDER BY provider, external_id"
                )
            )
        except sqlite3.Error as e:
            print(f"FAIL: cannot read registry: {e}")
            return 1

    user_files = sorted(p for p in users_dir.glob("*.sqlite3") if p.is_file())
    print(f"registry: {registry} ({registry.stat().st_size} bytes)")
    print(f"identities: {len(identities)}")
    for row in identities:
        print(f"  {row['provider']}:{row['external_id']} → {row['user_key']}")
    print(f"user_dbs: {len(user_files)}")

    keys_from_registry = {row["user_key"] for row in identities}
    keys_from_files = {p.stem for p in user_files}
    missing_files = keys_from_registry - keys_from_files
    orphan_files = keys_from_files - keys_from_registry

    if missing_files:
        print(f"FAIL: registry points to missing user DBs: {sorted(missing_files)}")
        return 1
    if orphan_files:
        print(f"WARN: user DBs with no registry row: {sorted(orphan_files)}")

    # Per-user rough health
    for path in user_files:
        try:
            with sqlite3.connect(path) as db:
                tables = {
                    r[0]
                    for r in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                txns = 0
                mems = 0
                if "transactions" in tables:
                    txns = db.execute(
                        "SELECT COUNT(*) FROM transactions WHERE deleted_at IS NULL"
                    ).fetchone()[0]
                if "memories" in tables:
                    mems = db.execute(
                        "SELECT COUNT(*) FROM memories WHERE status='active'"
                    ).fetchone()[0]
                print(f"  {path.name}: transactions={txns} active_memories={mems}")
        except sqlite3.Error as e:
            print(f"FAIL: cannot open {path.name}: {e}")
            return 1

    if len(user_files) < args.min_users:
        print(f"FAIL: expected at least {args.min_users} user DB(s), found {len(user_files)}")
        return 1
    if args.expect_identities is not None and len(identities) != args.expect_identities:
        print(
            f"FAIL: expected {args.expect_identities} identities, found {len(identities)}"
        )
        return 1

    print("OK: personal_data looks consistent — safe to start Telegram (single poller).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
