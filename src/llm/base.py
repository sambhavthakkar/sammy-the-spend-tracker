"""Abstract LLM client protocol."""
from __future__ import annotations

from typing import List, Optional, Protocol, Union

from src.llm.schemas import ChatMessage, ChatResponse


class LLMClient(Protocol):
    def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[dict]] = None,
        tool_choice: Union[str, dict] = "auto",
    ) -> ChatResponse:
        ...
