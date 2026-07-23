"""Conversation memory and pending-action helpers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.config import Config
from src.database import ConversationTurn, PendingAction, ProcessedMessage, get_db
from src.logging_config import get_logger

logger = get_logger(__name__)


class SessionStore:
    @staticmethod
    def append_turn(
        user_id: str,
        role: str,
        content: str,
        tool_name: Optional[str] = None,
        tool_payload: Optional[Dict[str, Any]] = None,
        max_turns: Optional[int] = None,
    ) -> None:
        db = get_db()
        try:
            turn = ConversationTurn(
                user_id=user_id,
                role=role,
                content=content,
                tool_name=tool_name,
                tool_payload=json.dumps(tool_payload) if tool_payload is not None else None,
            )
            db.add(turn)
            db.commit()

            # Prune occasionally (not every message) to keep writes fast
            keep = max_turns or Config.AGENT_MEMORY_TURNS
            import random

            if random.random() < 0.15:
                ids = [
                    r.id
                    for r in db.query(ConversationTurn.id)
                    .filter(ConversationTurn.user_id == user_id)
                    .order_by(ConversationTurn.created_at.desc())
                    .offset(keep * 2)
                    .all()
                ]
                if ids:
                    db.query(ConversationTurn).filter(ConversationTurn.id.in_(ids)).delete(
                        synchronize_session=False
                    )
                    db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"append_turn failed: {e}")
        finally:
            db.close()

    @staticmethod
    def get_recent_turns(user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        db = get_db()
        try:
            n = limit or Config.AGENT_MEMORY_TURNS
            rows = (
                db.query(ConversationTurn)
                .filter(ConversationTurn.user_id == user_id)
                .order_by(ConversationTurn.created_at.desc())
                .limit(n)
                .all()
            )
            rows = list(reversed(rows))
            return [
                {
                    "role": r.role,
                    "content": r.content or "",
                    "tool_name": r.tool_name,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
                if r.role in ("user", "assistant") and r.content
            ]
        finally:
            db.close()

    @staticmethod
    def try_mark_processed(provider: str, external_id: str, user_id: Optional[str] = None) -> bool:
        """Return True if this is the first time we process this message."""
        db = get_db()
        try:
            existing = (
                db.query(ProcessedMessage)
                .filter(
                    ProcessedMessage.provider == provider,
                    ProcessedMessage.external_id == str(external_id),
                )
                .first()
            )
            if existing:
                return False
            db.add(
                ProcessedMessage(
                    provider=provider,
                    external_id=str(external_id),
                    user_id=user_id,
                )
            )
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    @staticmethod
    def set_pending_action(
        user_id: str,
        action_type: str,
        payload: Dict[str, Any],
        ttl_minutes: int = 15,
    ) -> str:
        db = get_db()
        try:
            # Clear existing
            db.query(PendingAction).filter(PendingAction.user_id == user_id).delete()
            action = PendingAction(
                user_id=user_id,
                action_type=action_type,
                payload=json.dumps(payload),
                expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),
            )
            db.add(action)
            db.commit()
            db.refresh(action)
            return action.id
        except Exception as e:
            db.rollback()
            logger.error(f"set_pending_action: {e}")
            raise
        finally:
            db.close()

    @staticmethod
    def get_pending_action(user_id: str) -> Optional[Dict[str, Any]]:
        db = get_db()
        try:
            row = (
                db.query(PendingAction)
                .filter(PendingAction.user_id == user_id)
                .order_by(PendingAction.created_at.desc())
                .first()
            )
            if not row:
                return None
            if row.expires_at and row.expires_at < datetime.utcnow():
                db.delete(row)
                db.commit()
                return None
            return {
                "id": row.id,
                "action_type": row.action_type,
                "payload": json.loads(row.payload or "{}"),
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
        finally:
            db.close()

    @staticmethod
    def clear_pending_action(user_id: str) -> None:
        db = get_db()
        try:
            db.query(PendingAction).filter(PendingAction.user_id == user_id).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
