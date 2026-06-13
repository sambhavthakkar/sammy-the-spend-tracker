from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from .models import User, Pocket, Transaction, Commitment, CommitmentType, Frequency, BudgetSnapshot, TransactionMode, TransactionSource
from .expense_parser import expense_parser

class BudgetManager:
    """
    Manages budget pockets, transactions, and financial intelligence.
    Core logic for envelope budgeting system.
    """

    def __init__(self):
        self.users: Dict[str, User] = {}  # user_id -> User

    def create_user(self, phone: str, name: str, language: str = "en",
                   mode: str = "personal") -> User:
        """Create a new user"""
        user = User(
            phone=phone,
            name=name,
            language=language,
            mode=TransactionMode.PERSONAL if mode == "personal" else TransactionMode.BUSINESS
        )
        self.users[user.id] = user
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        return self.users.get(user_id)

    def get_user_by_phone(self, phone: str) -> Optional[User]:
        """Get user by phone number"""
        for user in self.users.values():
            if user.phone == phone:
                return user
        return None

    def add_pocket(self, user_id: str, name: str, monthly_limit: float,
                  is_shared: bool = False) -> Pocket:
        """Add a new budget pocket for user"""
        user = self.get_user(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        pocket = Pocket(
            user_id=user_id,
            name=name,
            monthly_limit=monthly_limit,
            spent_mtd=0.0,
            rollover_balance=0.0,
            is_shared=is_shared
        )
        user.pockets[pocket.id] = pocket
        return pocket

    def get_pocket(self, user_id: str, pocket_id: str) -> Optional[Pocket]:
        """Get pocket by ID"""
        user = self.get_user(user_id)
        if not user:
            return None
        return user.pockets.get(pocket_id)

    def log_transaction(self, user_id: str, amount: float, category: str,
                       merchant: str = "", source: str = "text",
                       notes: str = "", mode: str = "personal") -> Transaction:
        """
        Log a new transaction and update pocket spending
        """
        user = self.get_user(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Create transaction
        transaction = Transaction(
            user_id=user_id,
            amount=amount,
            currency="INR",
            category=category,
            merchant=merchant,
            source=TransactionSource.TEXT if source == "text" else
                   TransactionSource.VOICE if source == "voice" else
                   TransactionSource.BILL if source == "bill" else TransactionSource.PDF,
            mode=TransactionMode.PERSONAL if mode == "personal" else TransactionMode.BUSINESS,
            notes=notes
        )

        user.transactions.append(transaction)

        # Update pocket spending if category matches a pocket
        self._update_pocket_spending(user_id, category, amount)

        return transaction

    def _update_pocket_spending(self, user_id: str, category: str, amount: float):
        """Update spending in relevant pockets based on category"""
        user = self.get_user(user_id)
        if not user:
            return

        # Simple category-to-pocket mapping (in reality would be more sophisticated)
        category_pocket_map = {
            'food': ['Food', 'Groceries', 'Dining'],
            'transport': ['Transport', 'Fuel', 'Commute'],
            'shopping': ['Shopping', 'Lifestyle'],
            'entertainment': ['Entertainment', 'Fun'],
            'utilities': ['Utilities', 'Bills'],
            'health': ['Health', 'Medical'],
            'education': ['Education', 'Learning']
        }

        # Find matching pockets
        for pocket in user.pockets.values():
            pocket_keywords = category_pocket_map.get(pocket.name.lower(), [pocket.name.lower()])
            if any(keyword in category.lower() for keyword in pocket_keywords):
                pocket.spent_mtd += amount
                break
        else:
            # If no specific pocket matches, look for "Other" or similar pocket
            for pocket in user.pockets.values():
                if 'other' in pocket.name.lower() or 'misc' in pocket.name.lower():
                    pocket.spent_mtd += amount
                    break

    def log_expense_from_text(self, user_id: str, text: str,
                             mode: str = "personal") -> Transaction:
        """
        Convenience method: parse text and log transaction
        """
        parsed = expense_parser.parse_expense_text(text, user_id,
                                                  TransactionMode.PERSONAL if mode == "personal" else TransactionMode.BUSINESS)
        return self.log_transaction(
            user_id=user_id,
            amount=parsed.amount,
            category=parsed.category,
            merchant=parsed.merchant,
            source="text",
            notes=parsed.notes,
            mode=mode
        )

    def add_commitment(self, user_id: str, name: str, amount: float,
                      commitment_type: str, frequency: str = "monthly",
                      day_of_month: int = 1) -> Commitment:
        """
        Add a recurring commitment (SIP, EMI, subscription, etc.)
        """
        user = self.get_user(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Calculate next date
        next_date = self._calculate_next_date(day_of_month, frequency)

        commitment = Commitment(
            user_id=user_id,
            name=name,
            amount=amount,
            type=CommitmentType(commitment_type),
            frequency=Frequency(frequency),
            day_of_month=day_of_month,
            next_date=next_date
        )
        user.commitments[commitment.id] = commitment
        return commitment

    def _calculate_next_date(self, day_of_month: int, frequency: str) -> datetime:
        """Calculate next occurrence date"""
        today = datetime.now()

        if frequency == "monthly":
            # Try to set to this month's day
            try:
                next_date = today.replace(day=day_of_month)
                if next_date < today:  # If date has passed, go to next month
                    if today.month == 12:
                        next_date = next_date.replace(year=today.year + 1, month=1)
                    else:
                        next_date = next_date.replace(month=today.month + 1)
            except ValueError:  # Handle invalid day (e.g., Feb 30)
                # Go to last day of month
                if today.month == 12:
                    next_date = datetime(today.year + 1, 1, 1) - timedelta(days=1)
                else:
                    next_date = datetime(today.year, today.month + 1, 1) - timedelta(days=1)

        elif frequency == "quarterly":
            # Similar logic for quarterly
            months_to_add = 3
            try:
                next_date = today.replace(month=today.month + months_to_add, day=day_of_month)
                if next_date < today:
                    # Add another quarter
                    next_date = next_date.replace(month=next_date.month + months_to_add)
            except ValueError:
                # Handle end of month
                pass

        elif frequency == "yearly":
            try:
                next_date = today.replace(year=today.year + 1, day=day_of_month)
            except ValueError:
                # Handle Feb 29 etc.
                next_date = datetime(today.year + 1, 3, 1)  # March 1 as fallback
        else:
            next_date = today + timedelta(days=30)  # Default to monthly

        return next_date

    def get_committed_spending(self, user_id: str) -> Tuple[float, List[Commitment]]:
        """
        Calculate total committed spending and list of active commitments
        """
        user = self.get_user(user_id)
        if not user:
            return 0.0, []

        total = 0.0
        active_commitments = []

        for commitment in user.commitments.values():
            if commitment.status == "active":
                # For monthly commitments, add full amount
                if commitment.frequency == Frequency.MONTHLY:
                    total += commitment.amount
                    active_commitments.append(commitment)
                # For quarterly, add one-third of amount per month
                elif commitment.frequency == Frequency.QUARTERLY:
                    total += commitment.amount / 3
                    active_commitments.append(commitment)
                # For yearly, add one-twelfth of amount per month
                elif commitment.frequency == Frequency.YEARLY:
                    total += commitment.amount / 12
                    active_commitments.append(commitment)

        return total, active_commitments

    def get_budget_snapshot(self, user_id: str) -> BudgetSnapshot:
        """
        Get current budget status including income, committed, and available funds
        """
        user = self.get_user(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Calculate total spent this month
        total_spent = sum(t.amount for t in user.transactions
                         if t.timestamp.month == datetime.now().month
                         and t.timestamp.year == datetime.now().year)

        # Calculate committed spending
        total_committed, active_commitments = self.get_committed_spending(user_id)

        # Calculate pocket details
        pocket_details = {}
        for pocket in user.pockets.values():
            pocket_details[pocket.name] = {
                "budget": pocket.monthly_limit,
                "spent": pocket.spent_mtd,
                "remaining": pocket.monthly_limit - pocket.spent_mtd + pocket.rollover_balance,
                "rollover": pocket.rollover_balance
            }

        # Available to spend = income - committed - spent (simplified)
        available_to_spend = max(0, user.income - total_committed - total_spent)

        return BudgetSnapshot(
            user_id=user_id,
            period_start=datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            period_end=(datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0) +
                       timedelta(days=32)).replace(day=1) - timedelta(seconds=1),
            total_income=user.income,
            total_committed=total_committed,
            available_to_spend=available_to_spend,
            total_spent=total_spent,
            pocket_details=pocket_details
        )

    def check_budget_alerts(self, user_id: str) -> List[Dict]:
        """
        Check if any budget thresholds have been exceeded
        Returns list of alerts to send
        """
        alerts = []
        user = self.get_user(user_id)
        if not user:
            return alerts

        snapshot = self.get_budget_snapshot(user_id)

        for pocket_name, details in snapshot.pocket_details.items():
            budget = details["budget"]
            spent = details["spent"]

            if budget > 0:
                percentage_used = (spent / budget) * 100

                # Check thresholds: 70%, 90%, 100%
                if percentage_used >= 100:
                    alerts.append({
                        "type": "budget_exceeded",
                        "pocket": pocket_name,
                        "message": f"You've exceeded your {pocket_name} budget! Spent: ₹{spent:.0f}/{budget:.0f}",
                        "severity": "high"
                    })
                elif percentage_used >= 90:
                    alerts.append({
                        "type": "budget_warning",
                        "pocket": pocket_name,
                        "message": f"You've used 90% of your {pocket_name} budget. Spent: ₹{spent:.0f}/{budget:.0f}",
                        "severity": "medium"
                    })
                elif percentage_used >= 70:
                    alerts.append({
                        "type": "budget_notice",
                        "pocket": pocket_name,
                        "message": f"You've used 70% of your {pocket_name} budget. Spent: ₹{spent:.0f}/{budget:.0f}",
                        "severity": "low"
                    })

        return alerts

    def get_upcoming_deductions(self, days_ahead: int = 3) -> List[Dict]:
        """
        Get commitments that will deduct in the next N days
        For pre-deduction alerts
        """
        upcoming = []
        cutoff_date = datetime.now() + timedelta(days=days_ahead)

        for user in self.users.values():
            for commitment in user.commitments.values():
                if commitment.status == "active" and commitment.next_date <= cutoff_date:
                    days_until = (commitment.next_date - datetime.now()).days
                    upcoming.append({
                        "user_id": user.id,
                        "user_name": user.name,
                        "commitment_name": commitment.name,
                        "amount": commitment.amount,
                        "date": commitment.next_date.strftime("%d %b"),
                        "days_until": max(0, days_until),
                        "type": commitment.type.value
                    })

        return sorted(upcoming, key=lambda x: x["days_until"])

# Global budget manager instance
budget_manager = BudgetManager()