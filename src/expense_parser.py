import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from .models import Transaction, TransactionSource, TransactionMode

class ExpenseParser:
    """
    Parses natural language expense descriptions into structured transaction data.
    Simulates Claude API NLU capabilities for the MVP.
    """

    def __init__(self):
        # Common category mappings
        self.category_keywords = {
            'food': ['food', 'lunch', 'dinner', 'breakfast', 'meal', 'groceries', 'sabzi', 'dal', 'roti', 'chawal', 'rice', 'atta'],
            'transport': ['transport', 'petrol', 'diesel', 'fuel', 'uber', 'ola', 'metro', 'bus', 'train', 'taxi', 'auto'],
            'shopping': ['shopping', 'clothes', 'dress', 'shirt', 'pant', 'shoe', 'flipkart', 'amazon', 'myntra'],
            'entertainment': ['movie', 'netflix', 'prime', 'hotstar', 'game', 'play', 'fun', 'entertainment'],
            'utilities': ['electricity', 'bijli', 'water', 'gas', 'internet', 'wifi', 'mobile', 'recharge', 'bill'],
            'health': ['medicine', 'doctor', 'hospital', 'pharmacy', 'health', 'dawa', 'clinic'],
            'education': ['book', 'stationery', 'course', 'fee', 'school', 'college', 'education'],
            'emi': ['emi', 'loan', 'mortgage'],
            'sip': ['sip', 'mutual fund', 'investment'],
            'subscription': ['subscription', 'netflix', 'spotify', 'prime', 'hotstar', 'zed', 'sony liv']
        }

        # Common merchant patterns
        self.merchant_patterns = {
            'swiggy': ['swiggy', 'swgy', 'swiggy food'],
            'zomato': ['zomato', 'zomato food'],
            'uber': ['uber', 'uber ride'],
            'ola': ['ola', 'ola cab'],
            'amazon': ['amazon', 'amazon.in'],
            'flipkart': ['flipkart', 'flipkart.com'],
            'netflix': ['netflix', 'netflixx'],
            'spotify': ['spotify'],
        }

    def parse_expense_text(self, text: str, user_id: str, mode: TransactionMode = TransactionMode.PERSONAL) -> Transaction:
        """
        Parse freeform text to extract expense details.
        Example inputs: 'lunch 250', 'sabzi 340', 'paid Mohit 15000', 'uber 450'
        """
        text = text.lower().strip()

        # Extract amount - look for numbers
        amount_match = re.search(r'(\d+(?:\.\d+)?)', text)
        amount = float(amount_match.group(1)) if amount_match else 0.0

        # Extract merchant/entity (everything before the amount)
        merchant_text = re.sub(r'\d+(?:\.\d+)?', '', text).strip()
        merchant_text = re.sub(r'[^\w\s]', ' ', merchant_text).strip()

        # Clean up merchant text
        merchant = self._extract_merchant(merchant_text) or merchant_text or "Unknown"

        # Determine category - first check user preferences, then fallback to default logic
        category = self._determine_category_with_user_preference(user_id, merchant_text, text)

        # Create transaction
        transaction = Transaction(
            user_id=user_id,
            amount=amount,
            currency="INR",
            category=category,
            merchant=merchant,
            source=TransactionSource.TEXT,
            mode=mode,
            notes=text
        )

        return transaction

    def _extract_merchant(self, text: str) -> Optional[str]:
        """Extract known merchant from text"""
        text_lower = text.lower()
        for merchant, patterns in self.merchant_patterns.items():
            for pattern in patterns:
                if pattern in text_lower:
                    return merchant.title()
        return None

    def _determine_category_with_user_preference(self, user_id: str, merchant_text: str, full_text: str) -> str:
        """Determine expense category, first checking user preferences, then using default logic"""
        # Check if user has a preference for this transaction description
        from src.services import CategoryPreferenceService
        preference_result = CategoryPreferenceService.get_preferred_category(user_id, full_text)
        if preference_result:
            return preference_result["preferred_category"]

        # Fallback to default category determination logic
        return self._determine_category(merchant_text, full_text)

    def _determine_category(self, merchant_text: str, full_text: str) -> str:
        """Determine expense category based on keywords"""
        combined_text = (merchant_text + " " + full_text).lower()

        for category, keywords in self.category_keywords.items():
            for keyword in keywords:
                if keyword in combined_text:
                    return category

        return "other"

    def _determine_category_with_user_preference(self, user_id: str, merchant_text: str, full_text: str) -> str:
        """Determine expense category, first checking user preferences, then using default logic"""
        # Check if user has a preference for this transaction description
        from src.services import CategoryPreferenceService
        preference_result = CategoryPreferenceService.get_preferred_category(user_id, full_text)
        if preference_result:
            return preference_result["preferred_category"]

        # Fallback to default category determination logic
        return self._determine_category(merchant_text, full_text)

    def parse_voice_note(self, transcript: str, user_id: str, mode: TransactionMode = TransactionMode.PERSONAL) -> Transaction:
        """
        Parse voice note transcript (simulates Whisper/Sarvam AI output)
        """
        # In reality, this would go through speech-to-text first
        # For MVP, we treat it the same as text but could add voice-specific handling
        return self.parse_expense_text(transcript, user_id, mode)

    def parse_bill_image(self, ocr_text: str, user_id: str, mode: TransactionMode = TransactionMode.PERSONAL) -> List[Transaction]:
        """
        Parse OCR text from bill/receipt image.
        Simulates Google Vision OCR output and splits multi-item bills.
        """
        # Simple implementation - in reality would be more sophisticated
        lines = ocr_text.strip().split('\n')
        transactions = []

        total_amount = 0.0
        merchant = "Unknown"

        for line in lines:
            line = line.lower().strip()
            # Look for amount patterns
            amount_matches = re.findall(r'(\d+(?:\.\d+)?)', line)
            if amount_matches:
                # Assume last number is the amount for that line
                try:
                    amount = float(amount_matches[-1])
                    if amount > total_amount:  # Likely the total
                        total_amount = amount

                    # Extract item description (text before amount)
                    item_text = re.sub(r'\d+(?:\.\d+)?', '', line).strip()
                    item_text = re.sub(r'[^\w\s]', ' ', item_text).strip()

                    if item_text and amount > 0:
                        # Don't create transaction for total line
                        if amount != total_amount or len([t for t in transactions if t.merchant == merchant]) == 0:
                            category = self._determine_category(item_text, line)
                            transactions.append(Transaction(
                                user_id=user_id,
                                amount=amount,
                                currency="INR",
                                category=category,
                                merchant=merchant or "From Bill",
                                source=TransactionSource.BILL,
                                mode=mode,
                                notes=f"Bill item: {item_text}"
                            ))
                except ValueError:
                    continue

            # Try to extract merchant name
            if merchant == "Unknown":
                # Look for common merchant indicators
                merchant_indicators = ['restaurant', 'hotel', 'store', 'mart', 'shop']
                if any(indicator in line for indicator in merchant_indicators):
                    # Extract potential merchant name
                    words = line.split()
                    if words:
                        merchant = words[0].title()

        # If we found a total but no line items, create one transaction for the total
        if not transactions and total_amount > 0:
            transactions.append(Transaction(
                user_id=user_id,
                amount=total_amount,
                currency="INR",
                category="other",
                merchant=merchant,
                source=TransactionSource.BILL,
                mode=mode,
                notes="Total from bill"
            ))

        return transactions

# Global parser instance
expense_parser = ExpenseParser()