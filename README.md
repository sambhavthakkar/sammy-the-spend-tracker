# BudgetBot

A private AI assistant that chats normally, remembers personal context, and manages spending when relevant.

## What changed

- Normal conversation is the default; finance is not a forced workflow.
- Every identity gets a physically separate SQLite database under `personal_data/users/`.
- The central `registry.sqlite3` stores only provider identity → opaque user UUID routing.
- Flexible timestamped memories cover facts, events, preferences, and goals.
- SQLite FTS5 recalls relevant memories and 30-day conversation snippets while only sending the latest eight turns by default.
- Exact spending, balances, category limits, refunds, and largest purchases come from deterministic tools—not model guesses.
- Sensitive writes use confirmation and the model never receives user IDs, paths, SQL, or another user's context.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add OLLAMA_API_KEY; add TELEGRAM_BOT_TOKEN for Telegram.
python main.py agent
```

The CLI identity is stable through `AGENT_CLI_USER_ID`, so conversations survive restarts.

### Telegram

```bash
python main.py telegram
```

Set `TELEGRAM_ALLOWED_USER_IDS` in `.env`; the bot refuses to start without an allowlist. Text, voice notes, and bill photos all use the same private user database.

## Example conversations

- “How was your day?”
- “Remember that I prefer quiet restaurants.”
- “My goal is to save ₹20,000 for a laptop.”
- “My monthly pocket money is ₹5,000.”
- “I received ₹5,000 pocket money today.”
- “Food should stay under ₹3,000 this month.”
- “What was my largest food expense?”

An expected monthly allowance is remembered; money is added to the ledger only when the user says it was actually received.

## Private data layout

```text
personal_data/
├── registry.sqlite3
└── users/
    ├── <opaque-user-uuid>.sqlite3
    └── <another-user-uuid>.sqlite3
```

Each user database contains only that user's profile, transactions, category limits, memories, conversation turns, pending confirmations, and message dedupe records. Files are created with private permissions where the OS supports them.

Back up the entire `personal_data/` directory. Filesystem separation is not encryption against someone who controls the host.

## Migrating the old shared database

Dry run first:

```bash
python scripts/migrate_per_user.py --source budgetbot.db
```

Apply after the report looks correct:

```bash
python scripts/migrate_per_user.py --source budgetbot.db --apply
```

The migration never changes or deletes `budgetbot.db`, verifies per-user counts and signed totals, and is safe to rerun.

## Tests

```bash
python -m pytest -q
```

The focused checks cover physical user isolation, money precision, category limits, FTS memory/chat retrieval, 90-day chat pruning, tool confirmations, channel wiring, and migration idempotency.

## Docker

```bash
docker compose up -d --build
```

The Compose volume persists `/app/personal_data`; no Postgres, Redis, graph database, or vector database is required.

See [`docs/conversational-agent-plan.md`](docs/conversational-agent-plan.md) for the design boundaries.
