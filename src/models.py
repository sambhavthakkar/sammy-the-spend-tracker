from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional
import uuid

class TransactionSource(Enum):
    TEXT = "text"
    VOICE = "voice"
    BILL = "bill"
    PDF = "pdf"

class TransactionMode(Enum):
    PERSONAL = "personal"
    BUSINESS = "business"

class CommitmentType(Enum):
    SIP = "sip"
    EMI = "emi"
    SUBSCRIPTION = "subscription"
    INSURANCE = "insurance"

class Frequency(Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

@dataclass
class Transaction:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    amount: float = 0.0
    currency: str = "INR"
    category: str = ""
    merchant: str = ""
    source: TransactionSource = TransactionSource.TEXT
    mode: TransactionMode = TransactionMode.PERSONAL
    timestamp: datetime = field(default_factory=datetime.now)
    receipt_url: Optional[str] = None
    reimbursable: bool = False
    gst_eligible: bool = False
    gst_rate: Optional[float] = None
    notes: str = ""

@dataclass
class Pocket:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    name: str = ""
    monthly_limit: float = 0.0
    spent_mtd: float = 0.0
    rollover_balance: float = 0.0
    alert_pct: float = 0.7  # Default 70% alert
    is_shared: bool = False
    shared_with: List[str] = field(default_factory=list)

@dataclass
class Commitment:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    name: str = ""
    type: CommitmentType = CommitmentType.SIP
    amount: float = 0.0
    frequency: Frequency = Frequency.MONTHLY
    day_of_month: int = 1
    next_date: datetime = field(default_factory=datetime.now)
    status: str = "active"  # active, paused, cancelled
    pocket_id: Optional[str] = None  # Linked to a pocket for budget tracking

@dataclass
class User:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    phone: str = ""
    name: str = ""
    language: str = "en"  # en, hi, etc.
    mode: TransactionMode = TransactionMode.PERSONAL
    income: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    pockets: Dict[str, Pocket] = field(default_factory=dict)
    commitments: Dict[str, Commitment] = field(default_factory=dict)
    transactions: List[Transaction] = field(default_factory=list)

@dataclass
class BudgetSnapshot:
    user_id: str
    period_start: datetime
    period_end: datetime
    total_income: float
    total_committed: float
    available_to_spend: float
    total_spent: float
    pocket_details: Dict[str, Dict[str, float]]  # pocket_name -> {budget, spent, remaining}