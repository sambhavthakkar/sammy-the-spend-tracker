"""
Fast paths that skip the LLM for common messages.

Simple expense lines like "lunch 250" are handled by the rule parser in
milliseconds instead of multi-second Gemma tool loops.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from src.expense_parser import expense_parser

# Questions / commands must still go to the agent
QUESTION_OR_CMD = re.compile(
    r"\b("
    r"how|what|when|why|which|where|who|"
    r"kitna|kitne|kya|kab|kaise|"
    r"show|list|balance|spent|spend|left|budget|total|summary|"
    r"delete|remove|fix|change|update|set|add pocket|income|"
    r"compare|biggest|top|yesterday|today|week|month|year|"
    r"help|start"
    r")\b",
    re.I,
)

# Looks like a short expense: has a number and is not a long question
HAS_AMOUNT = re.compile(r"\d+(?:[.,]\d+)?")
# Pure yes/no handled elsewhere
YES_NO = re.compile(r"^\s*(yes|y|no|n|haan|ha|nah|ok|okay|confirm|cancel)\s*$", re.I)


def is_simple_expense(text: str) -> bool:
    text = (text or "").strip()
    if not text or len(text) > 80:
        return False
    if YES_NO.match(text):
        return False
    if QUESTION_OR_CMD.search(text):
        return False
    if text.endswith("?"):
        return False
    if not HAS_AMOUNT.search(text):
        return False
    # Prefer short phrases: few words
    if len(text.split()) > 10:
        return False
    return True


def try_parse_simple_expense(text: str, user_id: str) -> Optional[Tuple[float, str, str, str]]:
    """
    Returns (amount, category, merchant, notes) or None if not confident.
    """
    if not is_simple_expense(text):
        return None
    try:
        parsed = expense_parser.parse_expense_text(text, user_id)
    except Exception:
        return None
    if not parsed or not getattr(parsed, "amount", None) or float(parsed.amount) <= 0:
        return None
    return (
        float(parsed.amount),
        (parsed.category or "other").lower(),
        parsed.merchant or "Unknown",
        parsed.notes or text,
    )
