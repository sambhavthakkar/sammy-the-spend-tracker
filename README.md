# BudgetBot

Conversational personal finance agent. Chat in natural language (Telegram or CLI); the model uses **tools** so balances and spends always come from your database — never invented.

**Stack:** Python · SQLAlchemy · Ollama Cloud (default **Gemma 4**) · Telegram

## Features

- Log expenses from free text (`lunch 250`, `uber 180 yesterday`)
- Ask date-scoped questions (`food last week?`, `how much today?`)
- Budget snapshot & pockets (starter pockets on first use)
- Fix / delete last expense conversationally
- Telegram bot + local agent CLI
- Rule-parser fallback if the LLM is unreachable

## Quick start

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# On Python 3.14, install what works if pins fail:
# pip install sqlalchemy python-dotenv httpx flask python-telegram-bot pytest python-json-logger

cp .env.example .env
# Edit .env — minimum:
#   OLLAMA_API_KEY=...
#   OLLAMA_MODEL=gemma4:31b-cloud
#   TELEGRAM_BOT_TOKEN=...          # for Telegram
#   TELEGRAM_ALLOWED_USER_IDS=...   # your Telegram numeric id
```

### Agent CLI

```bash
PYTHONPATH=. python main.py agent
```

### Telegram

```bash
PYTHONPATH=. python main.py telegram
```

Leave it running, then message your bot: `/start`, then `lunch 250`.

### Other modes

```bash
PYTHONPATH=. python main.py cli   # legacy command CLI
PYTHONPATH=. python main.py api   # Flask REST API
```

## How it works

```
You (Telegram / CLI)
    → Agent (Gemma 4 via Ollama)
    → Tools (log / query / budget / pockets)
    → SQLite/Postgres ledger
    → Natural language reply grounded in tool results
```

Money truth lives in the DB. The model only interprets language and calls tools.

## Project layout

```
src/
  agent/          # pipeline, runtime, tools, prompts
  adapters/       # Telegram bot
  llm/            # Ollama OpenAI-compatible client
  timeutils/      # date periods (week starts Monday)
  services.py     # business logic
  database.py     # SQLAlchemy models
docs/
  conversational-agent-plan.md
```

## Tests

```bash
PYTHONPATH=. python -m pytest tests/test_dates.py tests/test_tools_and_services.py -q
```

## Docs

See [docs/conversational-agent-plan.md](docs/conversational-agent-plan.md) for full architecture and phases (voice STT next, etc.).

## Privacy

`.env` is gitignored. Ollama Cloud receives message text for inference; your ledger stays in your database.
