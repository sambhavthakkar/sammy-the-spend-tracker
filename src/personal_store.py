"""Private per-user SQLite storage for deterministic finance and memory data."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.config import Config

UTC = timezone.utc
KINDS = {"expense", "income", "refund", "pocket_money"}
MEMORY_KINDS = {"fact", "event", "preference", "goal"}
PERIODS = {
    "today", "yesterday", "this_week", "last_week", "this_month",
    "last_month", "this_year", "all",
}
_SECRET_RE = re.compile(
    r"(?i)\b(?:password|passwd|pwd|pin|secret|cvv|recovery[_ -]?code|backup[_ -]?code|"
    r"seed[_ -]?phrase|private[_ -]?key|bearer[_ -]?token|access[_ -]?token|refresh[_ -]?token|"
    r"api[_ -]?key|auth[_ -]?token|client[_ -]?secret)\b"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:sk-[A-Za-z0-9_-]{12,}|(?:sk|pk)_(?:live|test)_[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,})\b"
    r"|\b(?:card|account|acct)(?:\s+number|\s+no\.?|\s*#)?\b.{0,12}\b\d[\d -]{6,}\d\b"
    r"|(?<!\d)\d(?:[ -]?\d){11,18}(?!\d)"
)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "a", "an", "and", "are", "did", "do", "for", "from", "i", "in", "is",
    "it", "me", "my", "of", "on", "the", "to", "was", "we", "what", "when",
    "where", "which", "who", "with", "you", "your",
}


def _words(value: Any) -> list[str]:
    return [
        word for word in _WORD_RE.findall(str(value).casefold())
        if len(word) > 1 and word not in _STOP_WORDS
    ]


def _query_words(value: Any) -> list[str]:
    return _words(value)[:20]


def _fts_query(value: Any) -> str:
    return " OR ".join(f'"{word}"' for word in _query_words(value))


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _money(minor: int | None) -> Decimal:
    return Decimal(minor or 0) / Decimal(100)


def _minor(value: Any, *, allow_zero: bool = False) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("amount must be a decimal number") from None
    if not amount.is_finite() or amount < 0 or (not allow_zero and amount == 0):
        raise ValueError("amount must be positive")
    minor = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if minor < 0 or (not allow_zero and minor == 0) or minor > 9_000_000_000_000:
        raise ValueError("amount is outside the supported range")
    return minor


def _json(value: Any, limit: int = 8192) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        raise ValueError("value must be JSON serializable") from None
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError("JSON value is too large")
    return encoded


def _category(value: str) -> str:
    result = str(value).strip().casefold()
    if not result or len(result) > 100:
        raise ValueError("category must be 1..100 characters")
    return result


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError(f"unknown timezone: {name}") from None


def _utc_value(value: datetime | date | str | None, tz_name: str) -> str:
    if value is None:
        parsed = _now()
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("timestamp must be ISO-8601") from None
    else:
        raise ValueError("timestamp must be a datetime, date, or ISO-8601 string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_timezone(tz_name))
    return _iso(parsed)


def _period_bounds(label: str, tz_name: str, now: datetime | None) -> tuple[str | None, str | None]:
    key = str(label or "all").strip().lower().replace(" ", "_").replace("-", "_")
    if key not in PERIODS:
        raise ValueError(f"unknown period: {label}")
    if key == "all":
        return None, None
    tz = _timezone(tz_name)
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)
    day = current.date()
    if key == "today":
        start, end = day, day + timedelta(days=1)
    elif key == "yesterday":
        start, end = day - timedelta(days=1), day
    elif key == "this_week":
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=7)
    elif key == "last_week":
        end = day - timedelta(days=day.weekday())
        start = end - timedelta(days=7)
    elif key == "this_month":
        start = day.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    elif key == "last_month":
        end = day.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    else:  # this_year
        start, end = date(day.year, 1, 1), date(day.year + 1, 1, 1)
    local_start = datetime.combine(start, time.min, tzinfo=tz)
    local_end = datetime.combine(end, time.min, tzinfo=tz)
    return _iso(local_start), _iso(local_end)


class PersonalStore:
    """One identity registry plus one SQLite database per opaque user UUID."""

    def __init__(self, data_dir: str | os.PathLike[str] | None = None):
        self.data_dir = Path(data_dir or Config.PERSONAL_DATA_DIR).expanduser().resolve()
        self.users_dir = self.data_dir / "users"
        self.registry_path = self.data_dir / "registry.sqlite3"
        self._mkdir(self.data_dir)
        self._mkdir(self.users_dir)
        with self._connect(self.registry_path) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS identities (
                       provider TEXT NOT NULL,
                       external_id TEXT NOT NULL,
                       user_key TEXT NOT NULL UNIQUE,
                       created_at TEXT NOT NULL,
                       PRIMARY KEY (provider, external_id)
                   )"""
            )

    @staticmethod
    def _mkdir(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass

    @staticmethod
    def _protect_file(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _connect(self, path: Path) -> sqlite3.Connection:
        db = sqlite3.connect(path, timeout=5)
        self._protect_file(path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _init_fts(db: sqlite3.Connection) -> None:
        memory_exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'memory_fts'"
        ).fetchone()
        conversation_exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'conversation_fts'"
        ).fetchone()
        try:
            db.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    content, details, content='memories', content_rowid='rowid'
                );
                CREATE TRIGGER IF NOT EXISTS memories_fts_insert AFTER INSERT ON memories BEGIN
                    INSERT INTO memory_fts(rowid, content, details)
                    VALUES (new.rowid, new.content, new.details);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_fts_delete AFTER DELETE ON memories BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, content, details)
                    VALUES ('delete', old.rowid, old.content, old.details);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_fts_update AFTER UPDATE ON memories BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, content, details)
                    VALUES ('delete', old.rowid, old.content, old.details);
                    INSERT INTO memory_fts(rowid, content, details)
                    VALUES (new.rowid, new.content, new.details);
                END;
                CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
                    content, content='conversation_turns', content_rowid='rowid'
                );
                CREATE TRIGGER IF NOT EXISTS conversation_fts_insert AFTER INSERT ON conversation_turns BEGIN
                    INSERT INTO conversation_fts(rowid, content) VALUES (new.rowid, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS conversation_fts_delete AFTER DELETE ON conversation_turns BEGIN
                    INSERT INTO conversation_fts(conversation_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS conversation_fts_update AFTER UPDATE ON conversation_turns BEGIN
                    INSERT INTO conversation_fts(conversation_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
                    INSERT INTO conversation_fts(rowid, content) VALUES (new.rowid, new.content);
                END;
                """
            )
        except sqlite3.OperationalError as exc:
            if "fts5" in str(exc).casefold():
                return
            raise
        if not memory_exists:
            db.execute("INSERT INTO memory_fts(memory_fts) VALUES ('rebuild')")
        if not conversation_exists:
            db.execute("INSERT INTO conversation_fts(conversation_fts) VALUES ('rebuild')")

    def user_db_path(self, user_key: str) -> Path:
        try:
            key = str(UUID(str(user_key)))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("user_key must be a valid UUID") from None
        return self.users_dir / f"{key}.sqlite3"

    def _user_db(self, user_key: str) -> sqlite3.Connection:
        path = self.user_db_path(user_key)
        if not path.is_file():
            raise KeyError("unknown user_key")
        return self._connect(path)

    def resolve_user(self, provider: str, external_id: str, display_name: str | None = None) -> str:
        provider, external_id = str(provider).strip(), str(external_id).strip()
        if not provider or not external_id or len(provider) > 64 or len(external_id) > 255:
            raise ValueError("provider and external_id are required and bounded")
        candidate = str(uuid4())
        with self._connect(self.registry_path) as db:
            db.execute(
                "INSERT OR IGNORE INTO identities(provider, external_id, user_key, created_at) VALUES (?, ?, ?, ?)",
                (provider, external_id, candidate, _iso(_now())),
            )
            row = db.execute(
                "SELECT user_key FROM identities WHERE provider = ? AND external_id = ?",
                (provider, external_id),
            ).fetchone()
        user_key = row["user_key"]
        self._init_user_db(user_key, display_name)
        return user_key

    def _init_user_db(self, user_key: str, display_name: str | None) -> None:
        path = self.user_db_path(user_key)
        with self._connect(path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    display_name TEXT,
                    timezone TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('expense','income','refund','pocket_money')),
                    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
                    currency TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT,
                    occurred_at TEXT NOT NULL,
                    source_ref TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS transactions_occurred ON transactions(occurred_at);
                CREATE INDEX IF NOT EXISTS transactions_category ON transactions(category);
                CREATE TABLE IF NOT EXISTS category_limits (
                    category TEXT PRIMARY KEY,
                    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('fact','event','preference','goal')),
                    content TEXT NOT NULL,
                    details TEXT NOT NULL,
                    occurred_at TEXT,
                    learned_at TEXT NOT NULL,
                    salience REAL NOT NULL CHECK (salience >= 0 AND salience <= 1),
                    status TEXT NOT NULL CHECK (status IN ('active','superseded','forgotten')),
                    supersedes_id TEXT REFERENCES memories(id)
                );
                CREATE INDEX IF NOT EXISTS memories_active_learned ON memories(status, learned_at DESC);
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_name TEXT,
                    tool_payload TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversation_turns_created ON conversation_turns(created_at DESC);
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_messages (
                    provider TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY (provider, external_id)
                );
                """
            )
            self._init_fts(db)
            stamp = _iso(_now())
            db.execute(
                """INSERT OR IGNORE INTO profile
                   (id, display_name, timezone, currency, created_at, updated_at)
                   VALUES (1, ?, ?, ?, ?, ?)""",
                (display_name, Config.AGENT_TIMEZONE_DEFAULT, Config.AGENT_CURRENCY_DEFAULT, stamp, stamp),
            )
            if display_name is not None:
                db.execute(
                    "UPDATE profile SET display_name = ?, updated_at = ? WHERE id = 1",
                    (str(display_name)[:200], stamp),
                )

    @staticmethod
    def _profile_row(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys() if key != "id"}

    def get_profile(self, user_key: str) -> dict[str, Any]:
        with self._user_db(user_key) as db:
            return self._profile_row(db.execute("SELECT * FROM profile WHERE id = 1").fetchone())

    def update_profile(self, user_key: str, values: dict[str, Any] | None = None, **changes: Any) -> dict[str, Any]:
        changes = {**(values or {}), **changes}
        unknown = set(changes) - {"display_name", "timezone", "currency"}
        if unknown:
            raise ValueError(f"unsupported profile fields: {', '.join(sorted(unknown))}")
        with self._user_db(user_key) as db:
            current = self._profile_row(db.execute("SELECT * FROM profile WHERE id = 1").fetchone())
            display_name = changes.get("display_name", current["display_name"])
            timezone_name = changes.get("timezone", current["timezone"])
            currency = str(changes.get("currency", current["currency"])).strip().upper()
            _timezone(timezone_name)
            if currency != current["currency"] and db.execute(
                "SELECT 1 FROM transactions WHERE deleted_at IS NULL LIMIT 1"
            ).fetchone():
                raise ValueError("currency cannot change after transactions exist")
            if display_name is not None and len(str(display_name)) > 200:
                raise ValueError("display_name is too long")
            if len(currency) != 3 or not currency.isalpha():
                raise ValueError("currency must be a three-letter code")
            db.execute(
                """UPDATE profile SET display_name = ?, timezone = ?, currency = ?, updated_at = ?
                   WHERE id = 1""",
                (display_name, timezone_name, currency, _iso(_now())),
            )
        return self.get_profile(user_key)

    def append_turn(
        self, user_key: str, role: str, content: str, tool_name: str | None = None,
        tool_payload: Any = None,
    ) -> str:
        if role not in {"user", "assistant", "tool", "system"}:
            raise ValueError("invalid conversation role")
        turn_id, stamp = str(uuid4()), _iso(_now())
        content = str(content)
        if _SECRET_RE.search(content):
            content = "[sensitive content not stored]"
        payload = None if tool_payload is None else _json(tool_payload)
        with self._user_db(user_key) as db:
            db.execute(
                """INSERT INTO conversation_turns
                   (id, role, content, tool_name, tool_payload, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (turn_id, role, content, tool_name, payload, stamp),
            )
        return turn_id

    def recent_turns(self, user_key: str, limit: int | None = None) -> list[dict[str, Any]]:
        count = Config.AGENT_MEMORY_TURNS if limit is None else max(0, min(int(limit), 200))
        with self._user_db(user_key) as db:
            rows = db.execute(
                "SELECT * FROM conversation_turns ORDER BY created_at DESC, rowid DESC LIMIT ?", (count,)
            ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            item["tool_payload"] = json.loads(item["tool_payload"]) if item["tool_payload"] else None
            result.append(item)
        return result

    def recent_conversation_turns(
        self, user_key: str, limit: int | None = None,
    ) -> list[dict[str, Any]]:
        count = Config.AGENT_MEMORY_TURNS if limit is None else max(0, min(int(limit), 200))
        with self._user_db(user_key) as db:
            rows = db.execute(
                """SELECT * FROM conversation_turns
                   WHERE role IN ('user', 'assistant')
                   ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                (count,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def search_conversation(
        self,
        user_key: str,
        query: str,
        days: int = 30,
        limit: int = 3,
        exclude_ids: set[str] | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        count = max(0, min(int(limit), 10))
        expression = _fts_query(query)
        if not expression or count == 0:
            return []
        current = now or _now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        cutoff = _iso(current.astimezone(UTC) - timedelta(days=max(1, int(days))))
        excluded = set(exclude_ids or ())
        with self._user_db(user_key) as db:
            has_fts = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'conversation_fts'"
            ).fetchone()
            if has_fts:
                rows = db.execute(
                    """SELECT t.* FROM conversation_fts
                       JOIN conversation_turns AS t ON t.rowid = conversation_fts.rowid
                       WHERE conversation_fts MATCH ?
                         AND t.role IN ('user', 'assistant') AND t.created_at >= ?
                       ORDER BY bm25(conversation_fts), t.created_at DESC LIMIT 100""",
                    (expression, cutoff),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT * FROM conversation_turns
                       WHERE role IN ('user', 'assistant') AND created_at >= ?
                       ORDER BY created_at DESC""",
                    (cutoff,),
                ).fetchall()
        query_words = set(_query_words(query))
        ranked = []
        for row in rows:
            if row["id"] in excluded:
                continue
            words = set(_words(row["content"]))
            score = len(query_words & words) / max(1, len(query_words))
            if score:
                ranked.append((score, row["created_at"], row))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            {"id": item[2]["id"], "role": item[2]["role"], "content": item[2]["content"],
             "created_at": item[2]["created_at"]}
            for item in ranked[:count]
        ]

    def prune_conversation(
        self,
        user_key: str,
        days: int = 90,
        keep_recent: int | None = None,
        now: datetime | None = None,
    ) -> int:
        count = Config.AGENT_MEMORY_TURNS if keep_recent is None else max(0, int(keep_recent))
        current = now or _now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        cutoff = _iso(current.astimezone(UTC) - timedelta(days=max(1, int(days))))
        with self._user_db(user_key) as db:
            cursor = db.execute(
                """DELETE FROM conversation_turns
                   WHERE role IN ('user', 'assistant') AND created_at < ?
                     AND id NOT IN (
                         SELECT id FROM conversation_turns
                         WHERE role IN ('user', 'assistant')
                         ORDER BY created_at DESC, rowid DESC LIMIT ?
                     )""",
                (cutoff, count),
            )
            return cursor.rowcount

    def is_processed(self, user_key: str, provider: str, external_id: str) -> bool:
        with self._user_db(user_key) as db:
            return db.execute(
                "SELECT 1 FROM processed_messages WHERE provider = ? AND external_id = ?",
                (str(provider), str(external_id)),
            ).fetchone() is not None

    def mark_processed(self, user_key: str, provider: str, external_id: str) -> bool:
        with self._user_db(user_key) as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO processed_messages(provider, external_id, processed_at) VALUES (?, ?, ?)",
                (str(provider), str(external_id), _iso(_now())),
            )
            return cursor.rowcount == 1

    def set_pending_action(
        self, user_key: str, action_type: str, payload: Any, ttl_minutes: int = 15,
    ) -> str:
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be positive")
        action_id, created = str(uuid4()), _now()
        with self._user_db(user_key) as db:
            db.execute("DELETE FROM pending_actions")
            db.execute(
                """INSERT INTO pending_actions(id, action_type, payload, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (action_id, str(action_type), _json(payload), _iso(created + timedelta(minutes=ttl_minutes)), _iso(created)),
            )
        return action_id

    def get_pending_action(self, user_key: str, now: datetime | None = None) -> dict[str, Any] | None:
        current = _utc_value(now, "UTC")
        with self._user_db(user_key) as db:
            db.execute("DELETE FROM pending_actions WHERE expires_at <= ?", (current,))
            row = db.execute("SELECT * FROM pending_actions ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            return None
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        return item

    def clear_pending_action(self, user_key: str) -> bool:
        with self._user_db(user_key) as db:
            return db.execute("DELETE FROM pending_actions").rowcount > 0

    def _user_timezone(self, db: sqlite3.Connection) -> str:
        return db.execute("SELECT timezone FROM profile WHERE id = 1").fetchone()["timezone"]

    @staticmethod
    def _transaction(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["amount"] = _money(result.pop("amount_minor"))
        return result

    def record_transaction(
        self, user_key: str, kind: str, amount: Any, category: str,
        occurred_at: datetime | date | str | None = None, description: str | None = None,
        source_ref: str | None = None, currency: str | None = None,
    ) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {sorted(KINDS)}")
        transaction_id, stamp = str(uuid4()), _iso(_now())
        with self._user_db(user_key) as db:
            profile = db.execute("SELECT timezone, currency FROM profile WHERE id = 1").fetchone()
            tx_currency = str(currency or profile["currency"]).upper()
            if len(tx_currency) != 3 or not tx_currency.isalpha():
                raise ValueError("currency must be a three-letter code")
            if tx_currency != profile["currency"]:
                raise ValueError("transaction currency must match the user profile")
            db.execute(
                """INSERT OR IGNORE INTO transactions
                   (id, kind, amount_minor, currency, category, description, occurred_at,
                    source_ref, created_at, updated_at, deleted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    transaction_id, kind, _minor(amount), tx_currency, _category(category),
                    description, _utc_value(occurred_at, profile["timezone"]), source_ref, stamp, stamp,
                ),
            )
            row = db.execute(
                "SELECT * FROM transactions WHERE id = ? OR (source_ref IS NOT NULL AND source_ref = ?)",
                (transaction_id, source_ref),
            ).fetchone()
        return self._transaction(row)

    def find_transactions(
        self, user_key: str, period: str = "all", category: str | None = None,
        kind: str | None = None, limit: int = 100, now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if kind is not None and kind not in KINDS:
            raise ValueError("invalid transaction kind")
        count = max(0, min(int(limit), 500))
        with self._user_db(user_key) as db:
            start, end = _period_bounds(period, self._user_timezone(db), now)
            rows = db.execute(
                """SELECT * FROM transactions
                   WHERE deleted_at IS NULL
                     AND (? IS NULL OR occurred_at >= ?)
                     AND (? IS NULL OR occurred_at < ?)
                     AND (? IS NULL OR category = ?)
                     AND (? IS NULL OR kind = ?)
                   ORDER BY occurred_at DESC, created_at DESC LIMIT ?""",
                (
                    start, start, end, end,
                    None if category is None else _category(category),
                    None if category is None else _category(category),
                    kind, kind, count,
                ),
            ).fetchall()
        return [self._transaction(row) for row in rows]

    def update_transaction(
        self, user_key: str, transaction_id: str, values: dict[str, Any] | None = None, **changes: Any,
    ) -> dict[str, Any]:
        changes = {**(values or {}), **changes}
        allowed = {"kind", "amount", "category", "occurred_at", "description", "source_ref", "currency"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported transaction fields: {', '.join(sorted(unknown))}")
        with self._user_db(user_key) as db:
            row = db.execute(
                "SELECT * FROM transactions WHERE id = ? AND deleted_at IS NULL", (transaction_id,)
            ).fetchone()
            if not row:
                raise KeyError("transaction not found")
            kind = changes.get("kind", row["kind"])
            if kind not in KINDS:
                raise ValueError("invalid transaction kind")
            amount_minor = _minor(changes["amount"]) if "amount" in changes else row["amount_minor"]
            category = _category(changes.get("category", row["category"]))
            tz_name = self._user_timezone(db)
            occurred_at = (
                _utc_value(changes["occurred_at"], tz_name)
                if "occurred_at" in changes else row["occurred_at"]
            )
            currency = str(changes.get("currency", row["currency"])).upper()
            if len(currency) != 3 or not currency.isalpha():
                raise ValueError("currency must be a three-letter code")
            profile_currency = db.execute("SELECT currency FROM profile WHERE id = 1").fetchone()["currency"]
            if currency != profile_currency:
                raise ValueError("transaction currency must match the user profile")
            db.execute(
                """UPDATE transactions SET kind = ?, amount_minor = ?, currency = ?, category = ?,
                   description = ?, occurred_at = ?, source_ref = ?, updated_at = ? WHERE id = ?""",
                (
                    kind, amount_minor, currency, category,
                    changes.get("description", row["description"]), occurred_at,
                    changes.get("source_ref", row["source_ref"]), _iso(_now()), transaction_id,
                ),
            )
            updated = db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        return self._transaction(updated)

    def delete_transaction(self, user_key: str, transaction_id: str) -> bool:
        stamp = _iso(_now())
        with self._user_db(user_key) as db:
            return db.execute(
                """UPDATE transactions SET deleted_at = ?, updated_at = ?
                   WHERE id = ? AND deleted_at IS NULL""",
                (stamp, stamp, transaction_id),
            ).rowcount == 1

    def spending_summary(
        self, user_key: str, period: str = "all", category: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        category_value = None if category is None else _category(category)
        with self._user_db(user_key) as db:
            start, end = _period_bounds(period, self._user_timezone(db), now)
            params = (start, start, end, end, category_value, category_value)
            row = db.execute(
                """SELECT
                       SUM(CASE WHEN kind = 'expense' THEN 1 ELSE 0 END) AS count,
                       COALESCE(SUM(CASE WHEN kind = 'expense' THEN amount_minor
                                         WHEN kind = 'refund' THEN -amount_minor ELSE 0 END), 0) AS total_minor
                   FROM transactions
                   WHERE deleted_at IS NULL
                     AND kind IN ('expense', 'refund')
                     AND (? IS NULL OR occurred_at >= ?)
                     AND (? IS NULL OR occurred_at < ?)
                     AND (? IS NULL OR category = ?)""",
                params,
            ).fetchone()
            maximum = db.execute(
                """SELECT * FROM transactions
                   WHERE deleted_at IS NULL AND kind = 'expense'
                     AND (? IS NULL OR occurred_at >= ?)
                     AND (? IS NULL OR occurred_at < ?)
                     AND (? IS NULL OR category = ?)
                   ORDER BY amount_minor DESC, occurred_at DESC LIMIT 1""",
                params,
            ).fetchone()
        count, total = int(row["count"] or 0), _money(row["total_minor"])
        average = (total / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if count else Decimal("0")
        return {
            "count": count,
            "total": total,
            "average": average,
            "max_transaction": self._transaction(maximum),
        }

    def money_balance(self, user_key: str) -> Decimal:
        with self._user_db(user_key) as db:
            row = db.execute(
                """SELECT COALESCE(SUM(CASE
                       WHEN kind IN ('income','refund','pocket_money') THEN amount_minor
                       WHEN kind = 'expense' THEN -amount_minor ELSE 0 END), 0) AS balance_minor
                   FROM transactions WHERE deleted_at IS NULL"""
            ).fetchone()
        return _money(row["balance_minor"])

    def set_category_limit(self, user_key: str, category: str, amount: Any) -> dict[str, Any]:
        category_value, amount_minor = _category(category), _minor(amount, allow_zero=True)
        with self._user_db(user_key) as db:
            db.execute(
                """INSERT INTO category_limits(category, amount_minor, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(category) DO UPDATE SET amount_minor = excluded.amount_minor,
                                                       updated_at = excluded.updated_at""",
                (category_value, amount_minor, _iso(_now())),
            )
        return {"category": category_value, "limit": _money(amount_minor)}

    def category_status(
        self, user_key: str, category: str, period: str = "this_month",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        category_value = _category(category)
        summary = self.spending_summary(user_key, period, category_value, now)
        with self._user_db(user_key) as db:
            row = db.execute(
                "SELECT amount_minor FROM category_limits WHERE category = ?", (category_value,)
            ).fetchone()
        limit = _money(row["amount_minor"]) if row else None
        return {
            "category": category_value,
            "period": period,
            "limit": limit,
            "spent": summary["total"],
            "remaining": None if limit is None else limit - summary["total"],
        }

    @staticmethod
    def _memory(row: sqlite3.Row, score: float | None = None) -> dict[str, Any]:
        result = dict(row)
        result["details"] = json.loads(result["details"])
        if score is not None:
            result["score"] = score
        return result

    def remember(
        self, user_key: str, kind: str, content: str, details: Any = None,
        occurred_at: datetime | date | str | None = None, learned_at: datetime | date | str | None = None,
        salience: float | Decimal = 0.5, supersedes_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in MEMORY_KINDS:
            raise ValueError(f"kind must be one of {sorted(MEMORY_KINDS)}")
        content = str(content).strip()
        if not content or len(content) > 4000:
            raise ValueError("memory content must be 1..4000 characters")
        details_json = _json({} if details is None else details)
        if _SECRET_RE.search(content) or _SECRET_RE.search(details_json):
            raise ValueError("secrets and financial account numbers cannot be remembered")
        try:
            salience_decimal = Decimal(str(salience))
            if not salience_decimal.is_finite():
                raise ValueError
            salience_value = float(max(Decimal(0), min(Decimal(1), salience_decimal)))
        except (InvalidOperation, ValueError):
            raise ValueError("salience must be numeric") from None
        memory_id = str(uuid4())
        with self._user_db(user_key) as db:
            tz_name = self._user_timezone(db)
            if supersedes_id is not None:
                changed = db.execute(
                    "UPDATE memories SET status = 'superseded' WHERE id = ? AND status = 'active'",
                    (supersedes_id,),
                ).rowcount
                if not changed:
                    raise KeyError("active superseded memory not found")
            db.execute(
                """INSERT INTO memories
                   (id, kind, content, details, occurred_at, learned_at, salience, status, supersedes_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
                (
                    memory_id, kind, content, details_json,
                    None if occurred_at is None else _utc_value(occurred_at, tz_name),
                    _utc_value(learned_at, tz_name), salience_value, supersedes_id,
                ),
            )
            row = db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._memory(row)

    def search_memories(
        self, user_key: str, query: str = "", limit: int = 10, now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        count = max(0, min(int(limit), 50))
        expression = _fts_query(query)
        with self._user_db(user_key) as db:
            has_fts = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'memory_fts'"
            ).fetchone()
            if expression and has_fts:
                matched = db.execute(
                    """SELECT m.* FROM memory_fts
                       JOIN memories AS m ON m.rowid = memory_fts.rowid
                       WHERE memory_fts MATCH ? AND m.status = 'active'
                       ORDER BY bm25(memory_fts) LIMIT ?""",
                    (expression, max(50, count * 10)),
                ).fetchall()
                evergreen = db.execute(
                    """SELECT * FROM memories WHERE status = 'active'
                       ORDER BY salience DESC, learned_at DESC LIMIT 20"""
                ).fetchall()
                rows_by_id = {row["id"]: row for row in evergreen}
                rows_by_id.update({row["id"]: row for row in matched})
                rows = list(rows_by_id.values())
            else:
                rows = db.execute(
                    """SELECT * FROM memories WHERE status = 'active'
                       ORDER BY learned_at DESC, rowid DESC"""
                ).fetchall()
        query_words = set(_query_words(query))
        current = now or _now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
        ranked = []
        for row in rows:
            words = set(_words(row["kind"] + " " + row["content"] + " " + row["details"]))
            lexical = len(query_words & words) / max(1, len(query_words))
            learned = datetime.fromisoformat(row["learned_at"])
            age_days = max(0.0, (current - learned).total_seconds() / 86400)
            recency = 1 / (1 + age_days / 30)
            score = lexical * 3 + float(row["salience"]) + recency
            ranked.append((score, row["learned_at"], row["id"], row))
        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [self._memory(item[3], round(item[0], 6)) for item in ranked[:count]]

    def forget_memory(self, user_key: str, memory_id: str) -> bool:
        with self._user_db(user_key) as db:
            return db.execute(
                "UPDATE memories SET status = 'forgotten' WHERE id = ? AND status = 'active'",
                (memory_id,),
            ).rowcount == 1
