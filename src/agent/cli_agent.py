"""Interactive CLI harness for the conversational agent (Phase 1)."""
from __future__ import annotations

import uuid

from src.agent.pipeline import AgentPipeline
from src.config import Config
from src.database import init_db
from src.logging_config import get_logger
from src.services import UserService

logger = get_logger(__name__)


def run_agent_cli():
    """Run a local chat loop against the agent pipeline."""
    init_db()
    print("🤖 BudgetBot Agent CLI")
    print("=" * 50)
    print(f"Model: {Config.OLLAMA_MODEL} @ {Config.OLLAMA_BASE_URL}")
    print(f"Tool mode: {Config.LLM_TOOL_MODE}")
    if not Config.OLLAMA_API_KEY:
        print("⚠️  OLLAMA_API_KEY not set — LLM calls will fail; rule fallback may still log expenses.")
    print("Type 'exit' to quit.\n")

    name = input("Your name (or Enter for Dev User): ").strip() or "Dev User"
    phone = f"cli:{uuid.uuid4().hex[:10]}"

    created = UserService.create_user(phone=phone, name=name)
    if not created.get("success") and created.get("user_id"):
        user_id = created["user_id"]
    else:
        user_id = created.get("user_id") or (created.get("user") or {}).get("id")
    if not user_id:
        # create_user returns user_id on success
        user_id = created.get("user_id")
    if not user_id:
        print(f"Failed to create user: {created}")
        return

    # Ensure timezone fields
    UserService.update_profile(
        user_id,
        timezone=Config.AGENT_TIMEZONE_DEFAULT,
        currency=Config.AGENT_CURRENCY_DEFAULT,
    )

    print(f"\nHi {name}! I'm your finance agent. Try:")
    print("  • lunch 250")
    print("  • how much did I spend today?")
    print("  • set income to 80000")
    print("  • food pocket 5000\n")

    pipeline = AgentPipeline()
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Bye!")
            break
        if not text:
            continue
        if text.lower() in ("exit", "quit", "bye"):
            print("👋 Bye!")
            break
        result = pipeline.handle_text(user_id, text, source="text")
        print(f"Bot: {result.text}\n")
