"""Bill vision parsing tests (mocked HTTP)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from src.media.bill_vision import (  # noqa: E402
    _parse_json_content,
    _to_extraction,
    extract_bill_from_image,
)


class TestBillVisionParse(unittest.TestCase):
    def test_parse_fenced_json(self):
        raw = '```json\n{"is_bill": true, "amount": 250, "merchant": "Cafe", "category": "food", "confidence": 0.9, "needs_confirmation": false, "summary": "ok"}\n```'
        data = _parse_json_content(raw)
        self.assertTrue(data.get("is_bill"))
        self.assertEqual(data.get("amount"), 250)

    def test_to_extraction_low_confidence_needs_confirm(self):
        ext = _to_extraction(
            {
                "is_bill": True,
                "amount": 100,
                "merchant": "Shop",
                "category": "shopping",
                "confidence": 0.4,
                "needs_confirmation": False,
                "summary": "maybe",
            },
            "",
        )
        self.assertTrue(ext.needs_confirmation)
        self.assertEqual(ext.category, "shopping")

    def test_extract_mocked_http(self):
        path = Path(tempfile.mkstemp(suffix=".jpg")[1])
        try:
            path.write_bytes(b"\xff\xd8\xfffakejpeg")
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "is_bill": True,
                                    "amount": 450,
                                    "merchant": "Swiggy",
                                    "category": "food",
                                    "date": None,
                                    "currency": "INR",
                                    "notes": "order",
                                    "confidence": 0.92,
                                    "needs_confirmation": False,
                                    "summary": "Swiggy ₹450",
                                }
                            )
                        }
                    }
                ]
            }
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = body

            client = MagicMock()
            client.post.return_value = mock_resp
            with patch("src.media.bill_vision._http_client", return_value=client):
                ext = extract_bill_from_image(path, mime="image/jpeg")
                self.assertTrue(ext.is_bill)
                self.assertEqual(ext.amount, 450)
                self.assertEqual(ext.merchant, "Swiggy")
                self.assertFalse(ext.needs_confirmation)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
