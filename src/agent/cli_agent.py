"""Interactive CLI for the private personal assistant."""
from __future__ import annotations

from src.config import Config
from src.personal_store import PersonalStore


def resolve_cli_user(store: PersonalStore) -> str:
    """Resolve the configured CLI identity to its persistent private user key."""
    return store.resolve_user("cli", Config.AGENT_CLI_USER_ID)


def run_agent_cli() -> None:
    """Run a local chat loop against the private personal assistant."""
    from src.personal_agent import PersonalAgent

    store = PersonalStore()
    user_key = resolve_cli_user(store)
    agent = PersonalAgent(store=store)

    print("Personal Assistant CLI")
    print("=" * 50)
    print("Chat naturally. I can remember preferences, goals, and events, and help manage spending.")
    print("Type 'exit' to quit.\n")

    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit", "bye"}:
            print("Bye!")
            break
        reply = agent.chat(user_key, text, source="text")
        print(f"Assistant: {reply}\n")
