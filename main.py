#!/usr/bin/env python3
"""BudgetBot private personal assistant entry point."""
import argparse


def run_agent() -> None:
    from src.agent.cli_agent import run_agent_cli

    run_agent_cli()


def run_telegram() -> None:
    from src.adapters.telegram_bot import run_telegram_bot

    run_telegram_bot()


def main() -> None:
    parser = argparse.ArgumentParser(description="Private conversational personal assistant")
    parser.add_argument(
        "mode",
        choices=["agent", "telegram"],
        nargs="?",
        default="agent",
        help="agent (default) or telegram",
    )
    args = parser.parse_args()
    print("BudgetBot — Private Personal Assistant")
    (run_agent if args.mode == "agent" else run_telegram)()


if __name__ == "__main__":
    main()
