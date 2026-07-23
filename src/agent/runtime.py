"""Agent tool-calling runtime loop."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from src.agent.prompts import build_system_prompt
from src.agent.tools.registry import ToolRegistry, get_default_registry
from src.config import Config
from src.llm.ollama_client import OllamaClient
from src.llm.schemas import ChatMessage, ChatResponse
from src.logging_config import get_logger

logger = get_logger(__name__)


class AgentRuntime:
    def __init__(
        self,
        llm: Optional[OllamaClient] = None,
        registry: Optional[ToolRegistry] = None,
        max_rounds: Optional[int] = None,
        tool_mode: Optional[str] = None,
    ):
        self.llm = llm or OllamaClient()
        self.registry = registry or get_default_registry()
        self.max_rounds = max_rounds or Config.OLLAMA_MAX_TOOL_ROUNDS
        self.tool_mode = (tool_mode or Config.LLM_TOOL_MODE or "native").lower()

    def run(
        self,
        user_text: str,
        system_context: str,
        memory: Optional[List[Dict[str, str]]] = None,
        user_id: str = "",
    ) -> str:
        system_prompt = build_system_prompt(system_context)
        messages: List[ChatMessage] = [ChatMessage(role="system", content=system_prompt)]

        for turn in memory or []:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append(ChatMessage(role=role, content=content))

        messages.append(ChatMessage(role="user", content=user_text))

        if self.tool_mode == "json":
            return self._run_json_planner(messages, user_id)

        return self._run_native_tools(messages, user_id)

    def _run_native_tools(self, messages: List[ChatMessage], user_id: str) -> str:
        tools = self.registry.schemas()
        for round_i in range(self.max_rounds):
            try:
                response = self.llm.chat(messages, tools=tools, tool_choice="auto")
            except Exception as e:
                logger.error(f"LLM error round {round_i}: {e}")
                return self._fallback_message(str(e))

            if response.has_tool_calls:
                # Assistant message with tool_calls
                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=response.content or "",
                        tool_calls=response.tool_calls,
                    )
                )
                for call in response.tool_calls:
                    result = self.registry.execute(call.name, call.arguments, user_id=user_id)
                    # Surface ask_user immediately
                    if result.get("ask") and result.get("question"):
                        return str(result["question"])
                    if result.get("needs_confirmation") and result.get("message"):
                        return str(result["message"])
                    messages.append(
                        ChatMessage(
                            role="tool",
                            tool_call_id=call.id,
                            name=call.name,
                            content=json.dumps(result, default=str),
                        )
                    )
                continue

            # Final text
            text = (response.content or "").strip()
            if text:
                return text
            return "Done."

        return "I got stuck processing that — try rephrasing in a shorter message?"

    def _run_json_planner(self, messages: List[ChatMessage], user_id: str) -> str:
        """Fallback when model lacks native tools: model returns JSON action plan."""
        tool_names = [s["function"]["name"] for s in self.registry.schemas()]
        planner_hint = (
            "\n\nRespond with ONLY JSON, either:\n"
            '{"tool": "<name>", "args": {...}}\n'
            "or\n"
            '{"reply": "<final natural language answer>"}\n'
            f"Available tools: {', '.join(tool_names)}"
        )
        # Augment last user message
        if messages and messages[-1].role == "user":
            messages[-1] = ChatMessage(
                role="user", content=(messages[-1].content or "") + planner_hint
            )

        for round_i in range(self.max_rounds):
            try:
                response = self.llm.chat(messages, tools=None)
            except Exception as e:
                logger.error(f"JSON planner LLM error: {e}")
                return self._fallback_message(str(e))

            raw = (response.content or "").strip()
            parsed = _extract_json_object(raw)
            if not parsed:
                # Treat as final reply if it looks like prose
                if raw and not raw.startswith("{"):
                    return raw
                messages.append(ChatMessage(role="assistant", content=raw))
                messages.append(
                    ChatMessage(
                        role="user",
                        content='Return valid JSON only: {"tool":...} or {"reply":...}',
                    )
                )
                continue

            if "reply" in parsed and not parsed.get("tool"):
                return str(parsed["reply"])

            tool_name = parsed.get("tool")
            args = parsed.get("args") or parsed.get("arguments") or {}
            if not tool_name:
                return str(parsed.get("reply") or raw)

            result = self.registry.execute(str(tool_name), args, user_id=user_id)
            if result.get("ask") and result.get("question"):
                return str(result["question"])
            if result.get("needs_confirmation") and result.get("message"):
                return str(result["message"])

            messages.append(ChatMessage(role="assistant", content=raw))
            messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        f"Tool {tool_name} result: {json.dumps(result, default=str)}\n"
                        "Continue: either call another tool via JSON or finish with "
                        '{"reply": "..."} grounded in the tool result.'
                    ),
                )
            )

        return "I got stuck processing that — try rephrasing?"

    def _fallback_message(self, error: str) -> str:
        if Config.ENABLE_RULE_PARSER_FALLBACK:
            return (
                "I'm having trouble reaching the AI right now. "
                "You can still try a simple expense like `lunch 250`, or try again in a moment."
            )
        return "I'm having trouble reaching the AI right now. Please try again shortly."


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    # Strip markdown fences
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    # Find first {...}
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None
