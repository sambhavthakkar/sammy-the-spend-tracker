"""Normalized inbound/outbound messages across channels."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class NormalizedInboundMessage:
    provider: str
    external_user_id: str
    external_chat_id: str
    external_message_id: str
    update_id: str
    text: Optional[str] = None
    audio_path: Optional[Path] = None
    audio_mime: Optional[str] = None
    source: str = "text"  # text | voice
    raw_username: Optional[str] = None
    received_at: Optional[datetime] = None


@dataclass
class OutboundReply:
    text: str
    parse_mode: Optional[str] = None
