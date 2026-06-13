"""
Basic tests for BudgetBot models and services
"""
import unittest
import tempfile
import os
from datetime import datetime

# Set up test environment
os.environ['FLASK_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from src.models import User, Pocket, Transaction, Commitment, BudgetSnapshot
from src.database import Base, engine, SessionLocal, init_db, get_db, close_db
from src.services import UserService, PocketService, TransactionService, CommitmentService, BudgetService

class TestBudgetBotModels(unittest.TestCase):
    """Test cases for BudgetBot models and services"""

    def setUp(self):
        """Set up test database"""
        self.db = SessionLocal()
        # Create tables
        Base.metadata.create_all(bind=self.db.engine)

    def tearDown(self):
        """Clean up after tests"""
        self.db.close()
        Base.metadata.drop_all(bind=self.db.engine)

    def test_user_creation(self):
        """Test user creation"""
        result = UserService.create_user(
            phone="9876543210",
            name="Test User",
            language="en",
            mode="personal"
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["user"]["name"], "Test User")
        self.assertEqual(result["user"]["phone"], "9876543210")

    def test_pocket_creation(self):
        """Test pocket creation"""
        # First create a user
        user_result = UserService.create_user(
            phone="9876543211",
            name="Test User 2",
            language="en",
            mode="personal"
        )
        user_id = user_result["user_id"]

        # Then create a pocket
        pocket_result = PocketService.create_pocket(
            user_id=user_id,
            name="Food",
            monthly_limit=5000.0
        )

        self.assertTrue(pocket_result["success"])
        self.assertEqual(pocket_result["pocket"]["name"], "Food")
        self.assertEqual(pocket_result["pocket"]["monthly_limit"], 5000.0)

    def test_expense_logging(self):
        """Test expense logging"""
        # Create user
        user_result = UserService.create_user(
            phone="9876543212",
            name="Test User 3",
            language="en",
            mode="personal"
        )
        user_id = user_result["user_id"]

        # Create pocket
        pocket_result = PocketService.create_pocket(
            user_id=user_id,
            name="Food",
            monthly_limit=5000.0
        )
        pocket_id = pocket_result["pocket_id"]

        # Log expense
        expense_result = TransactionService.log_expense_text(
            user_id=user_id,
            text="lunch 250",
            mode="personal"
        )

        self.assertTrue(expense_result["success"])
        self.assertEqual(expense_result["transaction"]["amount"], 250.0)
        self.assertEqual(expense_result["transaction"]["category"], "food")

    def test_budget_snapshot(self):
        """Test budget snapshot generation"""
        # Create user with income
        user_result = UserService.create_user(
            phone="9876543213",
            name="Test User 4",
            language="en",
            mode="personal"
        )
        user_id = user_result["user_id"]

        # Update income
        UserService.update_income(user_id, 50000.0)

        # Create pocket
        PocketService.create_pocket(
            user_id=user_id,
            name="Food",
            monthly_limit=5000.0
        )

        # Add a commitment
        CommitmentService.add_commitment(
            user_id=user_id,
            name="SIP HDFC Flexi Cap",
            amount=3000.0,
            commitment_type="sip",
            frequency="monthly",
            day_of_month=5
        )

        # Log some expenses
        TransactionService.log_expense_text(user_id, "lunch 300", "personal")
        TransactionService.log_expense_text(user_id, "groceries 800", "personal")

        # Get budget snapshot
        snapshot_result = BudgetService.get_budget_snapshot(user_id)

        self.assertTrue(snapshot_result["success"])
        snapshot = snapshot_result["snapshot"]

        # Check values
        self.assertEqual(snapshot["total_income"], 50000.0)
        self.assertEqual(snapshot["total_committed"], 3000.0)  # SIP
        self.assertEqual(snapshot["total_spent"], 1100.0)      # lunch + groceries
        self.assertEqual(snapshot["available_to_spend"], 50000.0 - 3000.0 - 1100.0)

        # Check pocket details
        self.assertIn("Food", snapshot["pocket_details"])
        food_pocket = snapshot["pocket_details"]["Food"]
        self.assertEqual(food_pocket["budget"], 5000.0)
        self.assertEqual(food_pocket["spent"], 1100.0)

if __name__ == '__main__':
    unittest.main()