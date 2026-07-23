# BudgetBot — common tasks
# Usage: make help

SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON      ?= python3
VENV        := .venv
BIN         := $(VENV)/bin
PY          := $(BIN)/python
PIP         := $(BIN)/pip
export PYTHONPATH := .

# SQLite path used by default DATABASE_URL
DB_FILE     ?= budgetbot.db

.PHONY: help venv install install-voice env db-init db-reset db-shell \
	agent telegram api cli test clean docker-build docker-up docker-down \
	docker-logs deploy stop status

help: ## Show this help
	@echo "BudgetBot make targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Typical flow:"
	@echo "  make install env db-reset telegram"

venv: ## Create virtualenv if missing
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@$(PIP) install -q --upgrade pip

install: venv ## Install Python dependencies
	@$(PIP) install -q sqlalchemy python-dotenv python-json-logger httpx \
		requests python-dateutil flask flask-cors pytest \
		'python-telegram-bot>=21.0' || true
	@# Prefer requirements.txt when it resolves on this Python
	@$(PIP) install -q -r requirements.txt 2>/dev/null || \
		echo "Note: full requirements.txt had issues; core deps installed."
	@echo "OK: dependencies ready"

install-voice: install ## Install local Whisper STT (faster-whisper)
	@$(PIP) install -q 'faster-whisper>=1.0.0'
	@echo "OK: faster-whisper installed (first voice note downloads model)"

env: ## Create .env from example if missing
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env — add OLLAMA_API_KEY and TELEGRAM_BOT_TOKEN"; \
	else \
		echo ".env already exists"; \
	fi

db-init: ## Create tables (keeps existing data)
	@$(PY) -c "from src.database import init_db, get_database_url; init_db(reset=True); print('DB ready:', get_database_url())"

db-reset: ## Wipe local SQLite DB and recreate empty schema
	@echo "Resetting database..."
	@rm -f $(DB_FILE) ./budgetbot.db *.db-journal *.db-wal *.db-shm 2>/dev/null || true
	@$(PY) -c "import src.database as db; \
from sqlalchemy import inspect; \
db.init_db(reset=True); \
tables = inspect(db.engine).get_table_names(); \
print('Wiped and recreated DB:', db.get_database_url()); \
print('Tables:', ', '.join(sorted(tables)))"
	@rm -rf uploads/voice/* uploads/bills/* 2>/dev/null || true
	@echo "Voice/bill cache cleared"

db-fresh-notify: ## Notify all Telegram users, then wipe DB (fresh start)
	@echo "Stopping local bot so DB file can be wiped..."
	@-pkill -f 'main.py telegram' 2>/dev/null || true
	@sleep 1
	@$(PY) scripts/reset_and_notify.py
	@echo "Start bot again with: make telegram"

db-shell: ## Open sqlite3 on local DB (if present)
	@sqlite3 $(DB_FILE)

agent: ## Run conversational agent CLI
	@$(PY) main.py agent

telegram: ## Run Telegram bot (stops other local instances first)
	@echo "Stopping any other local bot instances..."
	@-pkill -f 'python main.py telegram' 2>/dev/null || true
	@-pkill -f 'main.py telegram' 2>/dev/null || true
	@sleep 1
	@echo "Starting Telegram bot (Ctrl+C to stop)..."
	@echo "Tip: only ONE process may poll this bot token."
	@$(PY) main.py telegram

api: ## Run Flask API on :5000
	@$(PY) main.py api

cli: ## Run legacy CLI
	@$(PY) main.py cli

test: ## Run unit tests
	@$(PY) -m pytest tests/test_dates.py tests/test_tools_and_services.py tests/test_stt.py tests/test_bill_vision.py -q

status: ## Show env/bot readiness (no secrets printed)
	@$(PY) -c "from src.config import Config; \
print('OLLAMA_API_KEY set:', bool(Config.OLLAMA_API_KEY)); \
print('OLLAMA_MODEL:', Config.OLLAMA_MODEL); \
print('TELEGRAM_BOT_TOKEN set:', bool(Config.TELEGRAM_BOT_TOKEN)); \
print('allowlist:', Config.telegram_allowlist() or '(empty = allow all)'); \
print('VOICE:', Config.ENABLE_VOICE_PROCESSING, 'STT:', Config.STT_PROVIDER, Config.STT_MODEL); \
print('DATABASE_URL:', __import__('os').getenv('DATABASE_URL') or Config.DATABASE_URL)"

stop: ## Stop local telegram/api processes started in background (best-effort)
	@-pkill -f 'python main.py telegram' 2>/dev/null || true
	@-pkill -f 'python main.py api' 2>/dev/null || true
	@echo "Stopped matching local bot/api processes (if any)"

clean: ## Remove caches and logs (not .env)
	@rm -rf __pycache__ src/**/__pycache__ tests/__pycache__ .pytest_cache
	@rm -rf logs/*.log 2>/dev/null || true
	@echo "Cleaned caches/logs"

# ── Docker deploy (API + Postgres; optional telegram profile) ──

docker-build: ## Build Docker images
	docker compose build

docker-up: ## Start API + Postgres + Redis
	docker compose up -d --build
	@echo "API: http://localhost:5000  Adminer: http://localhost:8080"

docker-telegram: ## Start stack including Telegram worker
	docker compose --profile telegram up -d --build
	@echo "Telegram worker + API stack started"

docker-down: ## Stop Docker stack
	docker compose --profile telegram down

docker-logs: ## Tail Docker logs
	docker compose logs -f --tail=100

deploy: env install db-reset ## Local deploy: install, reset DB, show status
	@$(MAKE) status
	@echo ""
	@echo "Local deploy ready. Next:"
	@echo "  make telegram     # run bot"
	@echo "  make agent        # CLI agent"
	@echo "  make docker-up    # containerized API+DB"
	@echo "  make docker-telegram  # containers + telegram worker"
