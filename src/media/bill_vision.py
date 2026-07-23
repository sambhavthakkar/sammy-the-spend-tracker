"""
Bill / receipt understanding via Gemma vision (Ollama Cloud only).

No Tesseract / Google Vision — the multimodal LLM reads the image and
returns structured expense fields as JSON.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from src.config import Config
from src.logging_config import get_logger

logger = get_logger(__name__)

EXTRACT_PROMPT = """You are reading a photo of a bill, receipt, invoice, or payment screenshot for personal expense tracking in India (INR).

Look at the image carefully and extract the MAIN total amount the user paid (prefer grand total / amount paid, not subtotal-only if a final total exists).

Return ONLY valid JSON (no markdown fences, no commentary) with this exact shape:
{
  "is_bill": true,
  "amount": 0.0,
  "merchant": "store or payee name",
  "category": "food|transport|shopping|utilities|health|entertainment|education|other",
  "date": "YYYY-MM-DD or null if not visible",
  "currency": "INR",
  "notes": "short note, e.g. items or bill type",
  "confidence": 0.0,
  "needs_confirmation": false,
  "summary": "one short human sentence of what you see"
}

Rules:
- amount must be a positive number if this is a payment/bill; use 0 if unreadable.
- confidence 0.0–1.0 how sure you are about the total amount.
- needs_confirmation true if the total is ambiguous, multiple totals, or confidence < 0.75.
- category: best guess from merchant/items (food, transport, shopping, utilities, health, entertainment, education, other).
- If the image is NOT a bill/receipt/payment (e.g. random selfie), set is_bill false, amount 0, explain in summary.
"""


@dataclass
class BillExtraction:
    is_bill: bool
    amount: float
    merchant: str
    category: str
    date: Optional[str]
    currency: str
    notes: str
    confidence: float
    needs_confirmation: bool
    summary: str
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_bill": self.is_bill,
            "amount": self.amount,
            "merchant": self.merchant,
            "category": self.category,
            "date": self.date,
            "currency": self.currency,
            "notes": self.notes,
            "confidence": self.confidence,
            "needs_confirmation": self.needs_confirmation,
            "summary": self.summary,
        }


def _prepare_image_bytes(path: Path, mime: str) -> tuple[bytes, str]:
    """
    Downscale and JPEG-compress for faster vision uploads.
    Falls back to raw bytes if Pillow is unavailable.
    """
    raw = path.read_bytes()
    max_side = Config.BILL_IMAGE_MAX_SIDE
    quality = Config.BILL_IMAGE_JPEG_QUALITY
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")
        w, h = img.size
        scale = min(1.0, float(max_side) / max(w, h))
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        logger.info(f"Bill image prepared {w}x{h} → {img.size[0]}x{img.size[1]} bytes={len(raw)}→{len(out)}")
        return out, "image/jpeg"
    except Exception as e:
        logger.warning(f"Pillow resize skipped: {e}")
        if len(raw) > 8 * 1024 * 1024:
            return b"", mime
        return raw, mime


def extract_bill_from_image(
    image_path: Path | str,
    mime: str = "image/jpeg",
    model: Optional[str] = None,
) -> BillExtraction:
    """Send image to Gemma (Ollama vision) and parse structured bill fields."""
    path = Path(image_path)
    if not path.exists() or path.stat().st_size == 0:
        return BillExtraction(
            is_bill=False,
            amount=0.0,
            merchant="",
            category="other",
            date=None,
            currency="INR",
            notes="",
            confidence=0.0,
            needs_confirmation=True,
            summary="Image file missing or empty.",
        )

    # Resize/compress before upload — large photos are the main vision latency cost
    data, mime = _prepare_image_bytes(path, mime)
    if not data:
        return BillExtraction(
            is_bill=False,
            amount=0.0,
            merchant="",
            category="other",
            date=None,
            currency="INR",
            notes="",
            confidence=0.0,
            needs_confirmation=True,
            summary="Could not process image. Try another photo.",
        )

    b64 = base64.b64encode(data).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    vision_model = model or Config.OLLAMA_MODEL

    base_url = Config.OLLAMA_BASE_URL.rstrip("/")
    api_key = Config.OLLAMA_API_KEY
    timeout = float(Config.OLLAMA_TIMEOUT_SECONDS)
    # Vision can be slower
    timeout = max(timeout, 90.0)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": vision_model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACT_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
        ],
    }

    url = f"{base_url}/chat/completions"
    logger.info(f"Bill vision request model={vision_model} bytes={len(data)}")

    last_err: Optional[Exception] = None
    content = ""
    for attempt in range(2):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code in (429, 500, 502, 503) and attempt == 0:
                continue
            resp.raise_for_status()
            body = resp.json()
            choices = body.get("choices") or []
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
            break
        except Exception as e:
            last_err = e
            logger.warning(f"Bill vision attempt failed: {e}")
            if attempt == 0:
                continue
            return BillExtraction(
                is_bill=False,
                amount=0.0,
                merchant="",
                category="other",
                date=None,
                currency="INR",
                notes="",
                confidence=0.0,
                needs_confirmation=True,
                summary=f"Could not read image with Gemma ({e}). Try again or type the amount.",
            )

    if not content and last_err:
        return BillExtraction(
            is_bill=False,
            amount=0.0,
            merchant="",
            category="other",
            date=None,
            currency="INR",
            notes="",
            confidence=0.0,
            needs_confirmation=True,
            summary=f"Could not read image with Gemma ({last_err}).",
        )

    parsed = _parse_json_content(content)
    return _to_extraction(parsed, content)


def _parse_json_content(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {}
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _to_extraction(data: Dict[str, Any], raw_content: str) -> BillExtraction:
    if not data:
        return BillExtraction(
            is_bill=False,
            amount=0.0,
            merchant="",
            category="other",
            date=None,
            currency="INR",
            notes=raw_content[:200] if raw_content else "",
            confidence=0.0,
            needs_confirmation=True,
            summary="Gemma did not return structured bill data. Type the amount instead.",
        )

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0

    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    category = (data.get("category") or "other").strip().lower()
    allowed = {
        "food",
        "transport",
        "shopping",
        "utilities",
        "health",
        "entertainment",
        "education",
        "other",
    }
    if category not in allowed:
        category = "other"

    date_val = data.get("date")
    if date_val in ("", "null", "None"):
        date_val = None
    if date_val is not None:
        date_val = str(date_val)[:10]

    is_bill = bool(data.get("is_bill", True))
    needs = bool(data.get("needs_confirmation")) or confidence < 0.75 or amount <= 0
    if not is_bill:
        needs = True

    return BillExtraction(
        is_bill=is_bill,
        amount=amount,
        merchant=(data.get("merchant") or "Unknown").strip() or "Unknown",
        category=category,
        date=date_val,
        currency=(data.get("currency") or "INR").strip() or "INR",
        notes=(data.get("notes") or "").strip(),
        confidence=confidence,
        needs_confirmation=needs,
        summary=(data.get("summary") or "").strip()
        or f"{data.get('merchant')} ₹{amount}",
        raw=data,
    )
