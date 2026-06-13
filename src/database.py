"""
Database abstraction layer for BudgetBot
Provides SQLAlchemy models and database session management
"""
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    ForeignKey, Text, Enum, Date, UniqueConstraint, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy import create_engine
from src.config import Config

Base = declarative_base()

# Enums matching our dataclasses
class TransactionSource(PyEnum):
    TEXT = "text"
    VOICE = "voice"
    BILL = "bill"
    PDF = "pdf"

class TransactionMode(PyEnum):
    PERSONAL = "personal"
    BUSINESS = "business"

class CommitmentType(PyEnum):
    SIP = "sip"
    EMI = "emi"
    SUBSCRIPTION = "subscription"
    INSURANCE = "insurance"

class Frequency(PyEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

# Database Models
class User(Base):
    __tablename__ = 'users'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    phone = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    language = Column(String(10), default='en')
    mode = Column(Enum(TransactionMode), default=TransactionMode.PERSONAL)
    income = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    pockets = relationship("Pocket", back_populates="user", cascade="all, delete-orphan")
    commitments = relationship("Commitment", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_users_phone', 'phone'),
    )

class Pocket(Base):
    __tablename__ = 'pockets'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    name = Column(String(100), nullable=False)
    monthly_limit = Column(Float, nullable=False, default=0.0)
    spent_mtd = Column(Float, default=0.0)
    rollover_balance = Column(Float, default=0.0)
    alert_pct = Column(Float, default=0.7)
    is_shared = Column(Boolean, default=False)
    shared_with = Column(Text)  # JSON string of user IDs
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="pockets")

    __table_args__ = (
        Index('ix_pockets_user_id', 'user_id'),
        Index('ix_pockets_name', 'name'),
    )

class Transaction(Base):
    __tablename__ = 'transactions'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default='INR')
    category = Column(String(100), nullable=False)
    merchant = Column(String(200))
    source = Column(Enum(TransactionSource), default=TransactionSource.TEXT)
    mode = Column(Enum(TransactionMode), default=TransactionMode.PERSONAL)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    receipt_url = Column(String(500))
    reimbursable = Column(Boolean, default=False)
    gst_eligible = Column(Boolean, default=False)
    gst_rate = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="transactions")

    __table_args__ = (
        Index('ix_transactions_user_id', 'user_id'),
        Index('ix_transactions_timestamp', 'timestamp'),
        Index('ix_transactions_category', 'category'),
    )

class Commitment(Base):
    __tablename__ = 'commitments'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    name = Column(String(200), nullable=False)
    type = Column(Enum(CommitmentType), default=CommitmentType.SIP)
    amount = Column(Float, nullable=False)
    frequency = Column(Enum(Frequency), default=Frequency.MONTHLY)
    day_of_month = Column(Integer, default=1)
    next_date = Column(DateTime, nullable=False, index=True)
    status = Column(String(20), default='active')  # active, paused, cancelled
    pocket_id = Column(String(36), ForeignKey('pockets.id'))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="commitments")
    pocket = relationship("Pocket")

    __table_args__ = (
        Index('ix_commitments_user_id', 'user_id'),
        Index('ix_commitments_next_date', 'next_date'),
        Index('ix_commitments_status', 'status'),
    )

class BudgetSnapshot(Base):
    __tablename__ = 'budget_snapshots'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    total_income = Column(Float, default=0.0)
    total_committed = Column(Float, default=0.0)
    available_to_spend = Column(Float, default=0.0)
    total_spent = Column(Float, default=0.0)
    # pocket_details stored as JSON
    pocket_details = Column(Text)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('ix_budget_snapshots_user_id', 'user_id'),
        Index('ix_budget_snapshots_period', 'period_start', 'period_end'),
    )


# New models for enhanced features

class SavingsGoal(Base):
    """Savings goals linked to pockets"""
    __tablename__ = 'savings_goals'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    pocket_id = Column(String(36), ForeignKey('pockets.id'), nullable=False)
    name = Column(String(100), nullable=False)  # e.g., "Emergency Fund", "Vacation"
    target_amount = Column(Float, nullable=False)
    current_amount = Column(Float, default=0.0)
    target_date = Column(DateTime)  # Optional target date
    monthly_contribution = Column(Float)  # Suggested monthly contribution
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    pocket = relationship("Pocket")

    __table_args__ = (
        Index('ix_savings_goals_pocket_id', 'pocket_id'),
        Index('ix_savings_goals_target_date', 'target_date'),
    )


class Asset(Base):
    """User assets for net worth tracking"""
    __tablename__ = 'assets'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    name = Column(String(100), nullable=False)  # e.g., "Savings Account", "Mutual Funds"
    asset_type = Column(String(50))  # e.g., "cash", "investment", "property", "vehicle"
    value = Column(Float, nullable=False)
    currency = Column(String(3), default='INR')
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User")

    __table_args__ = (
        Index('ix_assets_user_id', 'user_id'),
        Index('ix_assets_asset_type', 'asset_type'),
    )


class Liability(Base):
    """User liabilities for net worth tracking"""
    __tablename__ = 'liabilities'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    name = Column(String(100), nullable=False)  # e.g., "Home Loan", "Credit Card"
    liability_type = Column(String(50))  # e.g., "loan", "credit_card", "mortgage"
    amount_owed = Column(Float, nullable=False)
    currency = Column(String(3), default='INR')
    interest_rate = Column(Float)  # Annual interest rate as percentage
    minimum_payment = Column(Float)  # Minimum monthly payment
    due_date = Column(DateTime)  # When the liability is due/paid off
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User")

    __table_args__ = (
        Index('ix_liabilities_user_id', 'user_id'),
        Index('ix_liabilities_liability_type', 'liability_type'),
    )


class GroupSplit(Base):
    """Group expense splitting tracking"""
    __tablename__ = 'group_splits'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    group_name = Column(String(100))  # e.g., "Roommates", "Family Dinner"
    description = Column(Text)
    total_amount = Column(Float, nullable=False)
    currency = Column(String(3), default='INR')
    split_method = Column(String(20))  # 'equal', 'percentage', 'exact', 'shares'
    is_settled = Column(Boolean, default=False)
    settled_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User")
    transactions = relationship("SplitTransaction", back_populates="group_split", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_group_splits_user_id', 'user_id'),
        Index('ix_group_splits_created_at', 'created_at'),
        Index('ix_group_splits_is_settled', 'is_settled'),
    )


class SplitTransaction(Base):
    """Individual transactions within a group split"""
    __tablename__ = 'split_transactions'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    group_split_id = Column(String(36), ForeignKey('group_splits.id'), nullable=False)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # Who incurred the expense
    amount = Column(Float, nullable=False)  # Total expense amount
    currency = Column(String(3), default='INR')
    description = Column(String(200))  # What the expense was for
    owed_by_user_id = Column(String(36), ForeignKey('users.id'))  # Who owes money (for reimbursement)
    owed_amount = Column(Float, default=0.0)  # How much they owe
    paid_amount = Column(Float, default=0.0)  # How much they've paid
    is_settled = Column(Boolean, default=False)  # Whether this split is settled
    transaction_id = Column(String(36), ForeignKey('transactions.id'))  # Link to original transaction
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    group_split = relationship("GroupSplit", back_populates="transactions")
    user = relationship("User", foreign_keys=[user_id])
    owed_by = relationship("User", foreign_keys=[owed_by_user_id])
    transaction = relationship("Transaction")

    __table_args__ = (
        Index('ix_split_transactions_group_split_id', 'group_split_id'),
        Index('ix_split_transactions_user_id', 'user_id'),
        Index('ix_split_transactions_owed_by_user_id', 'owed_by_user_id'),
        Index('ix_split_transactions_is_settled', 'is_settled'),
    )


class SpendingPattern(Base):
    """Detected spending patterns for auto-budget suggestions"""
    __tablename__ = 'spending_patterns'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    category = Column(String(100), nullable=False)  # e.g., 'food', 'transport'
    average_monthly = Column(Float, nullable=False)  # Average spending per month
    median_monthly = Column(Float)  # Median spending per month
    std_deviation = Column(Float)  # Standard deviation
    sample_size = Column(Integer)  # Number of months analyzed
    trend = Column(String(20))  # 'increasing', 'decreasing', 'stable'
    confidence = Column(Float)  # 0.0 to 1.0 confidence in the pattern
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    valid_until = Column(DateTime)  # When this pattern should be re-evaluated

    # Relationships
    user = relationship("User")

    __table_args__ = (
        Index('ix_spending_patterns_user_id', 'user_id'),
        Index('ix_spending_patterns_category', 'category'),
        Index('ix_spending_patterns_detected_at', 'detected_at'),
    )


class BudgetSuggestion(Base):
    """AI-generated budget suggestions"""
    __tablename__ = 'budget_suggestions'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    pocket_name = Column(String(100), nullable=False)  # Which pocket this suggestion is for
    suggested_amount = Column(Float, nullable=False)
    reasoning = Column(Text)  # Explanation for the suggestion
    confidence = Column(Float)  # 0.0 to 1.0 confidence in suggestion
    is_accepted = Column(Boolean, default=False)  # Whether user accepted the suggestion
    is_dismissed = Column(Boolean, default=False)  # Whether user dismissed the suggestion
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    valid_until = Column(DateTime)  # When suggestion expires

    # Relationships
    user = relationship("User")

    __table_args__ = (
        Index('ix_budget_suggestions_user_id', 'user_id'),
        Index('ix_budget_suggestions_pocket_name', 'pocket_name'),
        Index('ix_budget_suggestions_created_at', 'created_at'),
        Index('ix_budget_suggestions_is_accepted', 'is_accepted'),
    )


class AnomalyAlert(Base):
    """Alerts for unusual spending detected"""
    __tablename__ = 'anomaly_alerts'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    transaction_id = Column(String(36), ForeignKey('transactions.id'))
    anomaly_type = Column(String(50))  # 'amount', 'frequency', 'category', 'time'
    severity = Column(String(20))  # 'low', 'medium', 'high'
    description = Column(Text)
    expected_value = Column(Float)  # What was expected
    actual_value = Column(Float)  # What actually occurred
    z_score = Column(Float)  # How many standard deviations from mean
    is_resolved = Column(Boolean, default=False)  # Whether user has addressed it
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User")
    transaction = relationship("Transaction")

    __table_args__ = (
        Index('ix_anomaly_alerts_user_id', 'user_id'),
        Index('ix_anomaly_alerts_transaction_id', 'transaction_id'),
        Index('ix_anomaly_alerts_severity', 'severity'),
        Index('ix_anomaly_alerts_is_resolved', 'is_resolved'),
        Index('ix_anomaly_alerts_created_at', 'created_at'),
    )


class UserStreak(Base):
    """Tracking user streaks for gamification"""
    __tablename__ = 'user_streaks'

    id = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    streak_type = Column(String(50), nullable=False)  # 'budget_adherence', 'expense_logging', 'savings'
    current_streak = Column(Integer, default=0)  # Current consecutive days
    longest_streak = Column(Integer, default=0)  # Longest streak ever achieved
    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)  # Last day the streak was updated
    streak_start_date = Column(DateTime)  # When the current streak started
    total_days_achieved = Column(Integer, default=0)  # Total days across all streaks
    achievements_unlocked = Column(Text)  # JSON string of achievement IDs

    # Relationships
    user = relationship("User")

    __table_args__ = (
        Index('ix_user_streaks_user_id', 'user_id'),
        Index('ix_user_streaks_streak_type', 'streak_type'),
        Index('ix_user_streaks_current_streak', 'current_streak'),
    )


# Database setup remains unchanged

# Database setup
def get_database_url() -> str:
    """Get database URL from config"""
    return Config.DATABASE_URL

def create_database_engine():
    """Create SQLAlchemy engine"""
    engine = create_engine(
        get_database_url(),
        echo=Config.SQLALCHEMY_ECHO,
        pool_pre_ping=True
    )
    return engine

def create_tables(engine):
    """Create all database tables"""
    Base.metadata.create_all(bind=engine)

def get_session_local(engine):
    """Get session factory"""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Global instances (to be initialized in app)
engine = None
SessionLocal = None

def init_db():
    """Initialize database connection"""
    global engine, SessionLocal
    engine = create_database_engine()
    SessionLocal = get_session_local(engine)
    create_tables(engine)

def get_db():
    """Get database session"""
    if SessionLocal is None:
        init_db()
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise

def close_db(db):
    """Close database session"""
    if db:
        db.close()