#!/usr/bin/env python3
"""Dry-run-first migration from the legacy shared SQLite DB to PersonalStore."""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.config import Config
from src.personal_store import PersonalStore


INCOMING = {"income", "credit", "deposit", "received", "salary", "in"}
REFUNDS = {"refund", "reimbursement"}
POCKET_MONEY = {"pocket_money", "pocket money", "allowance"}


def sqlite_path_from_url(database_url: str | None = None) -> Path:
    """Return the legacy SQLite file, rejecting non-SQLite and in-memory URLs."""
    url = database_url or os.getenv("DATABASE_URL") or Config.DATABASE_URL
    parts = urlsplit(url)
    if parts.scheme.split("+", 1)[0] != "sqlite":
        raise ValueError("--source is required when DATABASE_URL is not SQLite")
    marker = ":///"
    if marker not in url:
        raise ValueError("DATABASE_URL must name a SQLite file")
    raw = unquote(url.split(marker, 1)[1].split("?", 1)[0])
    if not raw or raw == ":memory:":
        raise ValueError("DATABASE_URL must name a SQLite file")
    return Path(raw).expanduser().resolve()


def _connect_source(path: Path) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _tables(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _rows(db: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    try:
        return db.execute(f'SELECT rowid AS __legacy_rowid__, * FROM "{table}"').fetchall()
    except sqlite3.OperationalError:
        return db.execute(f'SELECT * FROM "{table}"').fetchall()


def _value(row: sqlite3.Row, *names: str, default: Any = None) -> Any:
    keys = set(row.keys())
    for name in names:
        if name in keys and row[name] is not None:
            return row[name]
    return default


def _minor(value: Any) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("legacy transaction amount is not numeric") from None
    if not amount.is_finite() or amount <= 0:
        raise ValueError("legacy transaction amount must be positive")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _kind(row: sqlite3.Row) -> str:
    value = str(_value(row, "direction", "transaction_type", "type", default="expense")).strip().casefold()
    if value in INCOMING:
        return "income"
    if value in REFUNDS:
        return "refund"
    if value in POCKET_MONEY:
        return "pocket_money"
    return "expense"


def _identity(row: sqlite3.Row) -> tuple[str, str]:
    telegram = str(_value(row, "telegram_id", default="")).strip()
    if telegram:
        return "telegram", telegram
    phone = str(_value(row, "phone", default="")).strip()
    if phone:
        return "phone", phone
    return "legacy", f"legacy:{_value(row, 'id')}"


def _profile(row: sqlite3.Row) -> dict[str, Any]:
    timezone = str(_value(row, "timezone", default=Config.AGENT_TIMEZONE_DEFAULT)).strip()
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        timezone = Config.AGENT_TIMEZONE_DEFAULT
    currency = str(_value(row, "currency", default=Config.AGENT_CURRENCY_DEFAULT)).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        currency = Config.AGENT_CURRENCY_DEFAULT
    return {
        "display_name": _value(row, "name", "display_name"),
        "timezone": timezone,
        "currency": currency,
    }


def _transaction(row: sqlite3.Row, index: int, profile: dict[str, Any]) -> dict[str, Any]:
    source = re.sub(r"[^a-z0-9_-]+", "-", str(_value(row, "source", default="unknown")).casefold())[:32]
    legacy_id = str(_value(row, "id", "uuid", default=_value(row, "__legacy_rowid__", default=index)))
    merchant = _value(row, "merchant")
    notes = _value(row, "description", "notes")
    description = " — ".join(str(value) for value in (merchant, notes) if value not in (None, "")) or None
    amount = Decimal(str(_value(row, "amount")))
    return {
        "legacy_id": legacy_id,
        "kind": _kind(row),
        "amount": amount,
        "amount_minor": _minor(amount),
        "category": str(_value(row, "category", default="other") or "other"),
        "occurred_at": _value(row, "timestamp", "occurred_at", "created_at"),
        "description": description,
        "currency": str(_value(row, "currency", default=profile["currency"]) or profile["currency"]),
        "source_ref": f"legacy:{source or 'unknown'}:transaction:{legacy_id}",
    }


def _signed(kind: str, amount_minor: int) -> int:
    return amount_minor if kind in {"income", "refund", "pocket_money"} else -amount_minor


def _memory_specs(
    db: sqlite3.Connection, tables: set[str], user_id: str, pocket_owners: dict[str, str]
) -> list[tuple[str, str, dict[str, Any]]]:
    specs: list[tuple[str, str, dict[str, Any]]] = []
    if "user_category_preferences" in tables:
        for row in _rows(db, "user_category_preferences"):
            if str(_value(row, "user_id")) != user_id:
                continue
            text, category = _value(row, "transaction_description"), _value(row, "preferred_category")
            if text and category:
                ref = f"legacy:user_category_preferences:{_value(row, 'id', default=_value(row, '__legacy_rowid__'))}"
                specs.append(("preference", f"Categorize {text} as {category}", {"source_ref": ref}))
    if "commitments" in tables:
        for row in _rows(db, "commitments"):
            if str(_value(row, "user_id")) != user_id or not _value(row, "name"):
                continue
            ref = f"legacy:commitments:{_value(row, 'id', default=_value(row, '__legacy_rowid__'))}"
            details = {"source_ref": ref}
            for field in ("type", "amount", "frequency", "day_of_month", "next_date", "status"):
                value = _value(row, field)
                if value is not None:
                    details[field] = str(value)
            specs.append(("goal", f"Commitment: {_value(row, 'name')}", details))
    if "savings_goals" in tables:
        for row in _rows(db, "savings_goals"):
            if pocket_owners.get(str(_value(row, "pocket_id"))) != user_id or not _value(row, "name"):
                continue
            ref = f"legacy:savings_goals:{_value(row, 'id', default=_value(row, '__legacy_rowid__'))}"
            details = {"source_ref": ref}
            for field in ("target_amount", "current_amount", "target_date", "monthly_contribution", "is_active"):
                value = _value(row, field)
                if value is not None:
                    details[field] = str(value)
            specs.append(("goal", f"Savings goal: {_value(row, 'name')}", details))
    return specs


def _existing_memory_refs(store: PersonalStore, user_key: str) -> set[str]:
    import json

    refs: set[str] = set()
    with sqlite3.connect(store.user_db_path(user_key)) as db:
        for (details,) in db.execute("SELECT details FROM memories"):
            try:
                ref = json.loads(details).get("source_ref")
            except (AttributeError, ValueError, TypeError):
                continue
            if ref:
                refs.add(str(ref))
    return refs


def _target_totals(store: PersonalStore, user_key: str, refs: set[str]) -> tuple[int, int]:
    count = total = 0
    with sqlite3.connect(store.user_db_path(user_key)) as db:
        for kind, amount_minor, source_ref in db.execute(
            "SELECT kind, amount_minor, source_ref FROM transactions WHERE deleted_at IS NULL"
        ):
            if source_ref in refs:
                count += 1
                total += _signed(kind, amount_minor)
    return count, total


def migrate(
    source: str | os.PathLike[str], data_dir: str | os.PathLike[str], *, apply: bool = False,
    output: Callable[[str], Any] = print,
) -> list[dict[str, Any]]:
    """Plan or apply the migration. Dry-run mode does not create target files."""
    source_path = Path(source)
    reports: list[dict[str, Any]] = []
    with _connect_source(source_path) as db:
        tables = _tables(db)
        if "users" not in tables:
            raise ValueError("legacy database has no users table")
        users = _rows(db, "users")
        transactions = _rows(db, "transactions") if "transactions" in tables else []
        pockets = _rows(db, "pockets") if "pockets" in tables else []
        pocket_owners = {str(_value(row, "id")): str(_value(row, "user_id")) for row in pockets}
        store = PersonalStore(data_dir) if apply else None

        for user in users:
            legacy_user_id = str(_value(user, "id"))
            profile = _profile(user)
            txs = [
                _transaction(row, index, profile)
                for index, row in enumerate(transactions, 1)
                if str(_value(row, "user_id")) == legacy_user_id
            ]
            limits = [row for row in pockets if str(_value(row, "user_id")) == legacy_user_id]
            memories = _memory_specs(db, tables, legacy_user_id, pocket_owners)
            source_count = len(txs)
            source_total = sum((_signed(tx["kind"], tx["amount_minor"]) for tx in txs), 0)
            target_count, target_total = source_count, source_total

            if apply and store is not None:
                provider, external_id = _identity(user)
                user_key = store.resolve_user(provider, external_id, profile["display_name"])
                store.update_profile(user_key, profile)
                for tx in txs:
                    store.record_transaction(
                        user_key, tx["kind"], tx["amount"], tx["category"],
                        occurred_at=tx["occurred_at"], description=tx["description"],
                        source_ref=tx["source_ref"], currency=tx["currency"],
                    )
                with sqlite3.connect(store.user_db_path(user_key)) as target:
                    for tx in txs:
                        try:
                            target.execute(
                                "UPDATE transactions SET id=? WHERE source_ref=? AND id<>? "
                                "AND NOT EXISTS (SELECT 1 FROM transactions WHERE id=?)",
                                (tx["legacy_id"], tx["source_ref"], tx["legacy_id"], tx["legacy_id"]),
                            )
                        except sqlite3.IntegrityError:
                            pass
                for pocket in limits:
                    store.set_category_limit(
                        user_key, str(_value(pocket, "name", default="other")),
                        Decimal(str(_value(pocket, "monthly_limit", default=0))),
                    )
                existing_refs = _existing_memory_refs(store, user_key)
                for kind, content, details in memories:
                    if details["source_ref"] in existing_refs:
                        continue
                    try:
                        store.remember(user_key, kind, content, details=details)
                    except ValueError:
                        continue
                    existing_refs.add(details["source_ref"])
                target_count, target_total = _target_totals(
                    store, user_key, {tx["source_ref"] for tx in txs}
                )

            report = {
                "legacy_user_id": legacy_user_id,
                "source_count": source_count,
                "source_total_minor": source_total,
                "target_count": target_count,
                "target_total_minor": target_total,
            }
            reports.append(report)
            mode = "target" if apply else "target(projected)"
            output(
                f"user={legacy_user_id} source={source_count}/{Decimal(source_total) / 100:.2f} "
                f"{mode}={target_count}/{Decimal(target_total) / 100:.2f} "
                f"limits={len(limits)} memories={len(memories)}"
            )
            if target_count != source_count or target_total != source_total:
                raise RuntimeError(f"migration verification failed for legacy user {legacy_user_id}")
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="legacy SQLite file")
    parser.add_argument("--data-dir", default=Config.PERSONAL_DATA_DIR, help="PersonalStore data directory")
    parser.add_argument("--apply", action="store_true", help="write the migration (default: dry-run)")
    args = parser.parse_args(argv)
    try:
        source = Path(args.source).expanduser().resolve() if args.source else sqlite_path_from_url()
        print("APPLY" if args.apply else "DRY RUN (no files will be written)")
        migrate(source, args.data_dir, apply=args.apply)
    except (FileNotFoundError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
