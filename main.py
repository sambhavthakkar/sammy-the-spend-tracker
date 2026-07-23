#!/usr/bin/env python3
"""
BudgetBot Main Entry Point

Modes:
  cli      — legacy command-style CLI
  agent    — conversational agent CLI (Ollama + tools)
  api      — Flask REST API
  telegram — Telegram bot (Phase 2)
"""
import os
import argparse


def run_cli():
    """Run the CLI interface for testing"""
    from src.cli_interface import BudgetBotCLI
    cli = BudgetBotCLI()
    cli.start()


def run_agent():
    """Run conversational agent CLI harness"""
    from src.agent.cli_agent import run_agent_cli
    run_agent_cli()


def run_api():
    """Run the API server for production"""
    from src.api import create_app
    from src.config import Config
    from src.database import init_db

    init_db()
    app = create_app()

    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = Config.DEBUG

    print(f"🚀 Starting BudgetBot API server on {host}:{port}")
    print(f"📊 Environment: {os.getenv('FLASK_ENV', 'production')}")
    print(f"🔧 Debug mode: {debug}")

    app.run(host=host, port=port, debug=debug)


def run_telegram():
    """Run Telegram bot (Phase 2)."""
    try:
        from src.adapters.telegram_bot import run_telegram_bot
    except ImportError as e:
        print("Telegram adapter not ready yet (Phase 2).")
        print(f"Details: {e}")
        print("Use: python main.py agent")
        return
    run_telegram_bot()


def main():
    """Main application entry point"""
    parser = argparse.ArgumentParser(
        description='BudgetBot — conversational personal finance agent'
    )
    parser.add_argument(
        'mode',
        choices=['cli', 'agent', 'api', 'telegram'],
        nargs='?',
        default='agent',
        help='Run mode: agent (default), cli, api, or telegram',
    )

    args = parser.parse_args()

    print("🤖 BudgetBot — Personal Finance Agent")
    print("=" * 50)

    if args.mode == 'cli':
        print("Starting legacy CLI interface...")
        run_cli()
    elif args.mode == 'agent':
        print("Starting conversational agent CLI...")
        run_agent()
    elif args.mode == 'api':
        print("Starting API server...")
        run_api()
    elif args.mode == 'telegram':
        print("Starting Telegram bot...")
        run_telegram()


if __name__ == "__main__":
    main()