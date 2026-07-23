SHELL := /bin/bash
.DEFAULT_GOAL := help

PY := .venv/bin/python
SESSION := budgetbot
DATA_DIR := personal_data

.PHONY: help setup bot logs stop reset broadcast test status

help: ## Show commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

setup: ## Install dependencies and create .env
	@test -d .venv || python3 -m venv .venv
	@$(PY) -m pip install -q -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo "Ready. Add your keys to .env, then run: make bot"

bot: ## Start or restart the Telegram bot in tmux
	@command -v tmux >/dev/null || { echo "tmux is not installed"; exit 1; }
	@test -x $(PY) || { echo "Run 'make setup' first"; exit 1; }
	@$(MAKE) stop
	@mkdir -p logs
	@: > logs/telegram.log
	@tmux new-session -d -s $(SESSION) "cd '$(CURDIR)' && $(PY) -u main.py telegram 2>&1 | tee logs/telegram.log"
	@sleep 2
	@if tmux has-session -t $(SESSION) 2>/dev/null; then \
		echo "Bot started. View it with: make logs"; \
	else \
		echo "Bot failed to start:"; tail -n 30 logs/telegram.log; exit 1; \
	fi

logs: ## Attach to the bot's tmux session
	@if tmux has-session -t $(SESSION) 2>/dev/null; then \
		tmux attach-session -t $(SESSION); \
	else \
		echo "Bot is not running. Last output:"; tail -n 30 logs/telegram.log 2>/dev/null || true; \
	fi

stop: ## Stop the Telegram bot
	@-tmux kill-session -t $(SESSION) 2>/dev/null || true
	@-pkill -f '[p]ython.*[m]ain.py telegram' 2>/dev/null || true
	@echo "Bot stopped"

reset: ## Delete every user database and create a fresh store
	@read -r -p "Delete ALL user data? Type RESET: " answer; \
		test "$$answer" = "RESET" || { echo "Cancelled"; exit 1; }
	@$(MAKE) stop
	@rm -rf "$(DATA_DIR)"
	@$(PY) -c "from src.personal_store import PersonalStore; PersonalStore('$(DATA_DIR)')"
	@echo "Database reset. Run: make bot"

broadcast: ## Send a prompted message to all allowlisted users
	@$(PY) scripts/broadcast.py

test: ## Run tests
	@$(PY) -m pytest -q

status: ## Show bot and configuration readiness
	@tmux has-session -t $(SESSION) 2>/dev/null && echo "Bot: running" || echo "Bot: stopped"
	@$(PY) -c "from src.config import Config; print('Telegram token:', 'set' if Config.TELEGRAM_BOT_TOKEN else 'missing'); print('Allowlisted users:', len(Config.telegram_allowlist())); print('LLM key:', 'set' if Config.OLLAMA_API_KEY else 'missing')"
