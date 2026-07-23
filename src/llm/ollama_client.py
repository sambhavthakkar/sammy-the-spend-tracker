"""
OpenAI-compatible chat client for Ollama Cloud (or local Ollama /v1).
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Union

import httpx

from src.config import Config
from src.llm.schemas import ChatMessage, ChatResponse, ToolCall
from src.logging_config import get_logger

logger = get_logger(__name__)


class OllamaClient:
    """HTTP client against OpenAI-compatible /chat/completions."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url or Config.OLLAMA_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else Config.OLLAMA_API_KEY
        self.model = model or Config.OLLAMA_MODEL
        self.timeout = timeout if timeout is not None else float(Config.OLLAMA_TIMEOUT_SECONDS)
        self._client = httpx.Client(timeout=self.timeout)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[dict]] = None,
        tool_choice: Union[str, dict] = "auto",
        temperature: float = 0.2,
    ) -> ChatResponse:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_api_dict() for m in messages],
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        url = f"{self.base_url}/chat/completions"
        logger.debug(f"LLM request model={self.model} messages={len(messages)} tools={bool(tools)}")

        last_error: Optional[Exception] = None
        for attempt in range(2):
            try:
                resp = self._client.post(url, headers=self._headers(), json=payload)
                if resp.status_code in (408, 429, 500, 502, 503, 504) and attempt == 0:
                    logger.warning(f"LLM transient status {resp.status_code}, retrying")
                    time.sleep(0.5)
                    continue
                resp.raise_for_status()
                return self._parse_response(resp.json())
            except httpx.TransportError as e:
                last_error = e
                if attempt == 0:
                    logger.warning(f"LLM request failed, retrying: {e}")
                    time.sleep(0.5)
                    continue
                break
            except Exception as e:
                last_error = e
                break

        logger.error(f"LLM request failed: {last_error}")
        raise RuntimeError(f"LLM request failed: {last_error}") from last_error

    def _parse_response(self, data: Dict[str, Any]) -> ChatResponse:
        choices = data.get("choices") or []
        if not choices:
            return ChatResponse(content="", raw=data)

        message = choices[0].get("message") or {}
        content = message.get("content")
        tool_calls_raw = message.get("tool_calls") or []
        tool_calls: List[ToolCall] = []

        for tc in tool_calls_raw:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            args_raw = fn.get("arguments") or "{}"
            if isinstance(args_raw, dict):
                args = args_raw
            else:
                try:
                    args = json.loads(args_raw) if args_raw else {}
                except json.JSONDecodeError:
                    args = {"_raw": args_raw}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{name}",
                    name=name,
                    arguments=args if isinstance(args, dict) else {},
                )
            )

        return ChatResponse(content=content, tool_calls=tool_calls, raw=data)
