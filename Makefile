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

DATA_DIR    ?= personal_data
TMUX_SESSION ?= budgetbot

.PHONY: help venv install install-voice env data-init data-reset migrate \
	agent telegram telegram-tmux telegram-attach test clean docker-build docker-up \
	docker-down docker-logs deploy stop status

help: ## Show this help
	@echo "BudgetBot make targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Typical flow (keeps data):"
	@echo "  make install env && make telegram-tmux"
	@echo ""
	@echo "Private data lives in $(DATA_DIR). Back it up before using data-reset."

venv: ## Create virtualenv if missing
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@$(PIP) install -q --upgrade pip

install: venv ## Install Python dependencies
	@$(PIP) install -q -r requirements.txt
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

data-init: ## Create the private registry/users directory (never deletes data)
	@$(PY) -c "from src.personal_store import PersonalStore; s=PersonalStore('$(DATA_DIR)'); print('Private data ready:', s.data_dir)"

data-reset: ## DESTRUCTIVE: wipe every private user database
	@echo "WARNING: removing $(DATA_DIR) and every user's data"
	@rm -rf $(DATA_DIR)
	@$(MAKE) data-init

migrate: ## Dry-run migration from budgetbot.db; add APPLY=1 to write
	@$(PY) scripts/migrate_per_user.py --source budgetbot.db $(if $(APPLY),--apply,)

agent: ## Run conversational agent CLI
	@$(PY) main.py agent

telegram: ## Run Telegram bot in the foreground
	@$(MAKE) stop
	@echo "Starting Telegram bot (Ctrl+C to stop). Only one process may poll this token."
	@$(PY) -u main.py telegram

telegram-tmux: ## Start/restart Telegram bot in a detached tmux session
	@command -v tmux >/dev/null || { echo "tmux is not installed"; exit 1; }
	@$(MAKE) stop
	@tmux new-session -d -s "$(TMUX_SESSION)" "cd '$(CURDIR)' && exec $(PY) -u main.py telegram"
	@echo "Telegram running in tmux session: $(TMUX_SESSION)"
	@echo "Attach with: make telegram-attach"

telegram-attach: ## Attach to the Telegram tmux session
	@tmux attach-session -t "$(TMUX_SESSION)"

test: ## Run all current tests
	@$(PY) -m pytest -q

status: ## Show readiness without printing secrets
	@$(PY) -c "from src.config import Config; \
print('OLLAMA_API_KEY set:', bool(Config.OLLAMA_API_KEY)); \
print('OLLAMA_MODEL:', Config.OLLAMA_MODEL); \
print('TELEGRAM_BOT_TOKEN set:', bool(Config.TELEGRAM_BOT_TOKEN)); \
print('allowlist entries:', len(Config.telegram_allowlist()), '(0 = allow all)'); \
print('private data:', Config.PERSONAL_DATA_DIR); \
print('voice:', Config.ENABLE_VOICE_PROCESSING, Config.STT_PROVIDER, Config.STT_MODEL)"

stop: ## Stop the tmux session and any local Telegram worker
	@-tmux kill-session -t "$(TMUX_SESSION)" 2>/dev/null || true
	@-pkill -f '[p]ython.*[m]ain.py telegram' 2>/dev/null || true
	@echo "Stopped Telegram worker (if any)"

clean: ## Remove caches and logs (not .env)
	@rm -rf __pycache__ src/**/__pycache__ tests/__pycache__ .pytest_cache
	@rm -rf logs/*.log 2>/dev/null || true
	@echo "Cleaned caches/logs"

# ── Docker deploy ──

docker-build: ## Build the Telegram image
	docker compose build

docker-up: ## Start the Telegram assistant with persistent private data
	docker compose up -d --build

docker-down: ## Stop Docker
	docker compose down

docker-logs: ## Tail Docker logs
	docker compose logs -f --tail=100

deploy: env install data-init ## Prepare a local private assistant without deleting data
	@$(MAKE) status
	@echo "Ready: make telegram-tmux or make agent"
