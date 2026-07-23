"""
Service layer for BudgetBot
Contains business logic separated from data access and presentation layers
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import statistics
import math
from src.database import get_db, User, Pocket, Transaction, Commitment, BudgetSnapshot, \
    SavingsGoal, Asset, Liability, GroupSplit, SplitTransaction, SpendingPattern, \
    BudgetSuggestion, AnomalyAlert, UserStreak, UserCategoryPreference, \
    ConversationTurn, ProcessedMessage, PendingAction, TransactionSource, TransactionMode
from src.expense_parser import expense_parser
from src.logging_config import get_logger
from src.config import Config
from src.timeutils.dates import inclusive_datetime_range
import json
import logging
import uuid

logger = get_logger(__name__)

class UserService:
    """Service for user-related operations"""

    @staticmethod
    def create_user(phone: str, name: str, language: str = "en",
                   mode: str = "personal") -> Dict[str, Any]:
        """Create a new user"""
        db = get_db()
        try:
            # Check if user already exists
            existing_user = db.query(User).filter(User.phone == phone).first()
            if existing_user:
                return {
                    "success": False,
                    "message": "User with this phone number already exists",
                    "user_id": existing_user.id
                }

            # Create new user
            try:
                mode_enum = TransactionMode(mode.lower()) if isinstance(mode, str) else mode
            except Exception:
                mode_enum = TransactionMode.PERSONAL
            user = User(
                phone=phone,
                name=name,
                language=language,
                mode=mode_enum,
                income=0.0
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            logger.info(f"Created new user: {user.id} ({user.name})")
            return {
                "success": True,
                "message": "User created successfully",
                "user_id": user.id,
                "user": {
                    "id": user.id,
                    "phone": user.phone,
                    "name": user.name,
                    "language": user.language,
                    "mode": user.mode.value,
                    "income": user.income
                }
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating user: {str(e)}")
            return {
                "success": False,
                "message": f"Error creating user: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def get_user(user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        db = get_db()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                return UserService._user_to_dict(user)
            return None
        finally:
            db.close()

    @staticmethod
    def get_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
        """Get user by phone number"""
        db = get_db()
        try:
            user = db.query(User).filter(User.phone == phone).first()
            if user:
                return UserService._user_to_dict(user)
            return None
        finally:
            db.close()

    @staticmethod
    def _user_to_dict(user: User) -> Dict[str, Any]:
        return {
            "id": user.id,
            "phone": user.phone,
            "name": user.name,
            "language": user.language,
            "mode": user.mode.value if user.mode else "personal",
            "income": user.income or 0.0,
            "telegram_id": getattr(user, "telegram_id", None),
            "timezone": getattr(user, "timezone", None) or Config.AGENT_TIMEZONE_DEFAULT,
            "currency": getattr(user, "currency", None) or Config.AGENT_CURRENCY_DEFAULT,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    @staticmethod
    def get_or_create_by_telegram(
        telegram_id: str,
        name: Optional[str] = None,
        language: str = "en",
    ) -> Dict[str, Any]:
        """Get or create a user linked to a Telegram id."""
        db = get_db()
        try:
            telegram_id = str(telegram_id)
            user = db.query(User).filter(User.telegram_id == telegram_id).first()
            if not user:
                # Also try synthetic phone from earlier design
                user = db.query(User).filter(User.phone == f"tg:{telegram_id}").first()
            if user:
                if name and user.name in (None, "", "Friend", f"User {telegram_id}"):
                    user.name = name
                    db.commit()
                    db.refresh(user)
                return {"success": True, "created": False, "user": UserService._user_to_dict(user)}

            display_name = (name or f"User {telegram_id}").strip() or f"User {telegram_id}"
            user = User(
                phone=f"tg:{telegram_id}",
                name=display_name,
                language=language,
                mode=TransactionMode.PERSONAL,
                income=0.0,
                telegram_id=telegram_id,
                timezone=Config.AGENT_TIMEZONE_DEFAULT,
                currency=Config.AGENT_CURRENCY_DEFAULT,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"Created Telegram user {user.id} telegram_id={telegram_id}")
            return {"success": True, "created": True, "user": UserService._user_to_dict(user)}
        except Exception as e:
            db.rollback()
            logger.error(f"Error get_or_create_by_telegram: {e}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    @staticmethod
    def update_profile(user_id: str, **fields) -> Dict[str, Any]:
        """Update profile fields: name, language, timezone, currency, income."""
        db = get_db()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {"success": False, "message": "User not found"}
            allowed = {"name", "language", "timezone", "currency", "income"}
            for key, value in fields.items():
                if key in allowed and value is not None:
                    setattr(user, key, value)
            user.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(user)
            return {"success": True, "user": UserService._user_to_dict(user)}
        except Exception as e:
            db.rollback()
            logger.error(f"Error update_profile: {e}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    @staticmethod
    def update_income(user_id: str, income: float) -> Dict[str, Any]:
        """Update user's monthly income"""
        db = get_db()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            user.income = income
            user.updated_at = datetime.utcnow()
            db.commit()

            logger.info(f"Updated income for user {user_id}: {income}")
            return {
                "success": True,
                "message": "Income updated successfully",
                "income": income
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating income: {str(e)}")
            return {
                "success": False,
                "message": f"Error updating income: {str(e)}"
            }
        finally:
            db.close()

class PocketService:
    """Service for pocket-related operations"""

    @staticmethod
    def create_pocket(user_id: str, name: str, monthly_limit: float,
                     is_shared: bool = False) -> Dict[str, Any]:
        """Create a new budget pocket"""
        db = get_db()
        try:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            # Create pocket
            pocket = Pocket(
                user_id=user_id,
                name=name,
                monthly_limit=monthly_limit,
                spent_mtd=0.0,
                rollover_balance=0.0,
                is_shared=is_shared
            )
            db.add(pocket)
            db.commit()
            db.refresh(pocket)

            logger.info(f"Created pocket {pocket.id} for user {user_id}: {name}")
            return {
                "success": True,
                "message": "Pocket created successfully",
                "pocket_id": pocket.id,
                "pocket": {
                    "id": pocket.id,
                    "name": pocket.name,
                    "monthly_limit": pocket.monthly_limit,
                    "spent_mtd": pocket.spent_mtd,
                    "remaining": pocket.monthly_limit - pocket.spent_mtd,
                    "is_shared": pocket.is_shared
                }
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating pocket: {str(e)}")
            return {
                "success": False,
                "message": f"Error creating pocket: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def get_user_pockets(user_id: str) -> List[Dict[str, Any]]:
        """Get all pockets for a user"""
        db = get_db()
        try:
            pockets = db.query(Pocket).filter(Pocket.user_id == user_id).all()
            return [
                {
                    "id": pocket.id,
                    "name": pocket.name,
                    "monthly_limit": pocket.monthly_limit,
                    "spent_mtd": pocket.spent_mtd,
                    "remaining": pocket.monthly_limit - pocket.spent_mtd + pocket.rollover_balance,
                    "rollover_balance": pocket.rollover_balance,
                    "alert_pct": pocket.alert_pct,
                    "is_shared": pocket.is_shared,
                    "rollover_enabled": pocket.rollover_enabled,
                    "rollover_percentage": pocket.rollover_percentage,
                    "created_at": pocket.created_at.isoformat() if pocket.created_at else None
                }
                for pocket in pockets
            ]
        finally:
            db.close()

    @staticmethod
    def update_pocket_spending(pocket_id: str, amount: float) -> Dict[str, Any]:
        """Update pocket spending"""
        db = get_db()
        try:
            pocket = db.query(Pocket).filter(Pocket.id == pocket_id).first()
            if not pocket:
                return {
                    "success": False,
                    "message": "Pocket not found"
                }

            pocket.spent_mtd += amount
            pocket.updated_at = datetime.utcnow()
            db.commit()

            logger.info(f"Updated spending for pocket {pocket_id}: +{amount}")
            return {
                "success": True,
                "message": "Pocket spending updated",
                "spent_mtd": pocket.spent_mtd,
                "remaining": pocket.monthly_limit - pocket.spent_mtd
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating pocket spending: {str(e)}")
            return {
                "success": False,
                "message": f"Error updating pocket spending: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def configure_pocket_rollover(pocket_id: str, enabled: bool = None, percentage: float = None) -> Dict[str, Any]:
        """Configure rollover settings for a pocket"""
        db = get_db()
        try:
            pocket = db.query(Pocket).filter(Pocket.id == pocket_id).first()
            if not pocket:
                return {
                    "success": False,
                    "message": "Pocket not found"
                }

            # Update rollover settings if provided
            if enabled is not None:
                if not isinstance(enabled, bool):
                    return {
                        "success": False,
                        "message": "Enabled must be a boolean value"
                    }
                pocket.rollover_enabled = enabled

            if percentage is not None:
                if not isinstance(percentage, (int, float)) or percentage < 0 or percentage > 100:
                    return {
                        "success": False,
                        "message": "Percentage must be a number between 0 and 100"
                    }
                pocket.rollover_percentage = float(percentage)

            pocket.updated_at = datetime.utcnow()
            db.commit()

            logger.info(f"Updated rollover settings for pocket {pocket_id}")
            return {
                "success": True,
                "message": "Pocket rollover settings updated successfully",
                "pocket_id": pocket_id,
                "rollover_enabled": pocket.rollover_enabled,
                "rollover_percentage": pocket.rollover_percentage
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error configuring pocket rollover: {str(e)}")
            return {
                "success": False,
                "message": f"Error configuring pocket rollover: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def apply_monthly_rollover() -> Dict[str, Any]:
        """Apply rollover for all pockets at month boundary (called periodically)"""
        db = get_db()
        try:
            # Get all pockets with rollover enabled
            pockets = db.query(Pocket).filter(Pocket.rollover_enabled == True).all()

            rolled_over_count = 0
            total_rolled_over_amount = 0.0

            for pocket in pockets:
                # Calculate unspent amount for the month
                unspent_amount = pocket.monthly_limit - pocket.spent_mtd
                if unspent_amount > 0:
                    # Calculate amount to rollover based on percentage
                    rollover_amount = unspent_amount * (pocket.rollover_percentage / 100.0)
                    if rollover_amount > 0:
                        # Add to rollover balance
                        pocket.rollover_balance += rollover_amount
                        # Reset monthly spending (but keep track of what was actually spent)
                        pocket.spent_mtd = pocket.monthly_limit - (unspent_amount - rollover_amount)
                        rolled_over_count += 1
                        total_rolled_over_amount += rollover_amount

            db.commit()

            logger.info(f"Applied monthly rollover to {rolled_over_count} pockets, total amount: {total_rolled_over_amount}")
            return {
                "success": True,
                "message": f"Monthly rollover applied to {rolled_over_count} pockets",
                "rolled_over_count": rolled_over_count,
                "total_rolled_over_amount": total_rolled_over_amount
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error applying monthly rollover: {str(e)}")
            return {
                "success": False,
                "message": f"Error applying monthly rollover: {str(e)}"
            }
        finally:
            db.close()

class TransactionService:
    """Service for transaction-related operations"""

    @staticmethod
    def _txn_to_dict(t: Transaction) -> Dict[str, Any]:
        return {
            "id": t.id,
            "amount": t.amount,
            "currency": t.currency,
            "category": t.category,
            "merchant": t.merchant,
            "source": t.source.value if t.source else "text",
            "mode": t.mode.value if t.mode else "personal",
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            "receipt_url": t.receipt_url,
            "notes": t.notes,
        }

    @staticmethod
    def log_expense_text(user_id: str, text: str, mode: str = "personal") -> Dict[str, Any]:
        """Log expense from text input"""
        db = get_db()
        try:
            # Parse the expense text
            parsed = expense_parser.parse_expense_text(
                text, user_id,
                mode="personal" if mode == "personal" else "business"
            )

            # Create transaction
            transaction = Transaction(
                user_id=user_id,
                amount=parsed.amount,
                currency=parsed.currency,
                category=parsed.category,
                merchant=parsed.merchant,
                source=parsed.source if hasattr(parsed, "source") else TransactionSource.TEXT,
                mode=parsed.mode if hasattr(parsed, "mode") else TransactionMode.PERSONAL,
                notes=parsed.notes
            )
            db.add(transaction)
            db.flush()

            # Update pocket spending if applicable
            pocket_update_result = TransactionService.update_pocket_spending_by_category(
                user_id, parsed.category, parsed.amount
            )

            db.commit()
            db.refresh(transaction)

            logger.info(f"Logged expense transaction {transaction.id} for user {user_id}")
            return {
                "success": True,
                "message": "Expense logged successfully",
                "transaction_id": transaction.id,
                "transaction": TransactionService._txn_to_dict(transaction),
                "pocket_update": pocket_update_result
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error logging expense: {str(e)}")
            return {
                "success": False,
                "message": f"Error logging expense: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def log_expense_structured(
        user_id: str,
        amount: float,
        category: Optional[str] = None,
        merchant: str = "",
        notes: str = "",
        mode: str = "personal",
        source: str = "text",
        timestamp: Optional[datetime] = None,
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log expense from structured agent/tool fields (DB is source of truth)."""
        db = get_db()
        try:
            if amount is None or float(amount) <= 0:
                return {"success": False, "message": "Amount must be a positive number"}

            amount = float(amount)
            merchant = (merchant or "").strip() or "Unknown"
            notes = (notes or "").strip()
            text_for_category = notes or merchant

            if not category:
                # Reuse rule parser category logic without inventing amount
                category = expense_parser._determine_category_with_user_preference(
                    user_id, merchant, text_for_category
                )
            category = (category or "other").strip().lower()

            try:
                source_enum = TransactionSource(source.lower())
            except Exception:
                source_enum = TransactionSource.TEXT
            try:
                mode_enum = TransactionMode(mode.lower())
            except Exception:
                mode_enum = TransactionMode.PERSONAL

            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {"success": False, "message": "User not found"}

            cur = currency or getattr(user, "currency", None) or Config.AGENT_CURRENCY_DEFAULT
            txn_ts = timestamp or datetime.utcnow()

            transaction = Transaction(
                user_id=user_id,
                amount=amount,
                currency=cur,
                category=category,
                merchant=merchant,
                source=source_enum,
                mode=mode_enum,
                notes=notes or f"{merchant} {amount}".strip(),
                timestamp=txn_ts,
            )
            db.add(transaction)
            db.flush()

            pocket_update_result = TransactionService.update_pocket_spending_by_category(
                user_id, category, amount
            )

            db.commit()
            db.refresh(transaction)
            logger.info(f"Structured expense {transaction.id} user={user_id} amount={amount}")
            return {
                "success": True,
                "message": "Expense logged successfully",
                "transaction_id": transaction.id,
                "transaction": TransactionService._txn_to_dict(transaction),
                "pocket_update": pocket_update_result,
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error log_expense_structured: {e}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    @staticmethod
    def get_user_transactions(
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        category: Optional[str] = None,
        merchant: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get transactions for a user with optional date/category filters."""
        db = get_db()
        try:
            q = db.query(Transaction).filter(Transaction.user_id == user_id)

            if from_date or to_date:
                tz = timezone or Config.AGENT_TIMEZONE_DEFAULT
                start_s = from_date or "1970-01-01"
                end_s = to_date or "2999-12-31"
                start, end = inclusive_datetime_range(start_s, end_s, tz)
                q = q.filter(Transaction.timestamp >= start, Transaction.timestamp <= end)

            if category:
                q = q.filter(Transaction.category == category.lower().strip())
            if merchant:
                q = q.filter(Transaction.merchant.ilike(f"%{merchant.strip()}%"))

            transactions = (
                q.order_by(Transaction.timestamp.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [TransactionService._txn_to_dict(t) for t in transactions]
        finally:
            db.close()

    @staticmethod
    def sum_spending(
        user_id: str,
        from_date: str,
        to_date: str,
        category: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sum spending for an inclusive date range."""
        from sqlalchemy import func

        db = get_db()
        try:
            tz = timezone or Config.AGENT_TIMEZONE_DEFAULT
            start, end = inclusive_datetime_range(from_date, to_date, tz)
            q = db.query(
                func.coalesce(func.sum(Transaction.amount), 0.0),
                func.count(Transaction.id),
            ).filter(
                Transaction.user_id == user_id,
                Transaction.timestamp >= start,
                Transaction.timestamp <= end,
            )
            if category:
                q = q.filter(Transaction.category == category.lower().strip())
            total, count = q.one()
            return {
                "success": True,
                "from_date": from_date,
                "to_date": to_date,
                "category": category,
                "total": float(total or 0.0),
                "count": int(count or 0),
            }
        except Exception as e:
            logger.error(f"sum_spending error: {e}")
            return {"success": False, "message": str(e), "total": 0.0, "count": 0}
        finally:
            db.close()

    @staticmethod
    def spending_breakdown(
        user_id: str,
        from_date: str,
        to_date: str,
        group_by: str = "category",
        category: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Group spending by category, day, or merchant."""
        from sqlalchemy import func, cast, Date

        db = get_db()
        try:
            tz = timezone or Config.AGENT_TIMEZONE_DEFAULT
            start, end = inclusive_datetime_range(from_date, to_date, tz)
            group_by = (group_by or "category").lower()

            if group_by == "day":
                key_col = cast(Transaction.timestamp, Date).label("key")
            elif group_by == "merchant":
                key_col = Transaction.merchant.label("key")
            else:
                key_col = Transaction.category.label("key")
                group_by = "category"

            q = db.query(
                key_col,
                func.coalesce(func.sum(Transaction.amount), 0.0),
                func.count(Transaction.id),
            ).filter(
                Transaction.user_id == user_id,
                Transaction.timestamp >= start,
                Transaction.timestamp <= end,
            )
            if category:
                q = q.filter(Transaction.category == category.lower().strip())

            rows = q.group_by(key_col).order_by(func.sum(Transaction.amount).desc()).all()
            groups = [
                {
                    "key": str(r[0]) if r[0] is not None else "unknown",
                    "total": float(r[1] or 0.0),
                    "count": int(r[2] or 0),
                }
                for r in rows
            ]
            total = sum(g["total"] for g in groups)
            return {
                "success": True,
                "from_date": from_date,
                "to_date": to_date,
                "group_by": group_by,
                "total": total,
                "groups": groups,
                "count": sum(g["count"] for g in groups),
            }
        except Exception as e:
            logger.error(f"spending_breakdown error: {e}")
            return {"success": False, "message": str(e), "total": 0.0, "groups": []}
        finally:
            db.close()

    @staticmethod
    def top_expenses(
        user_id: str,
        from_date: str,
        to_date: str,
        limit: int = 5,
        timezone: Optional[str] = None,
    ) -> Dict[str, Any]:
        db = get_db()
        try:
            tz = timezone or Config.AGENT_TIMEZONE_DEFAULT
            start, end = inclusive_datetime_range(from_date, to_date, tz)
            rows = (
                db.query(Transaction)
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.timestamp >= start,
                    Transaction.timestamp <= end,
                )
                .order_by(Transaction.amount.desc())
                .limit(limit)
                .all()
            )
            return {
                "success": True,
                "from_date": from_date,
                "to_date": to_date,
                "transactions": [TransactionService._txn_to_dict(t) for t in rows],
            }
        except Exception as e:
            return {"success": False, "message": str(e), "transactions": []}
        finally:
            db.close()

    @staticmethod
    def update_transaction(transaction_id: str, **kwargs) -> Dict[str, Any]:
        """Update an existing transaction"""
        db = get_db()
        try:
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                return {
                    "success": False,
                    "message": "Transaction not found"
                }

            # Update allowed fields
            allowed_fields = ['amount', 'category', 'merchant', 'notes', 'timestamp']
            for field, value in kwargs.items():
                if field in allowed_fields and value is not None and hasattr(transaction, field):
                    if field == 'category' and isinstance(value, str):
                        value = value.lower().strip()
                    if field == 'amount':
                        value = float(value)
                    setattr(transaction, field, value)

            transaction.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(transaction)

            logger.info(f"Updated transaction {transaction_id}")
            return {
                "success": True,
                "message": "Transaction updated successfully",
                "transaction": {
                    "id": transaction.id,
                    "amount": transaction.amount,
                    "category": transaction.category,
                    "merchant": transaction.merchant,
                    "timestamp": transaction.timestamp.isoformat()
                }
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating transaction: {str(e)}")
            return {
                "success": False,
                "message": f"Error updating transaction: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def delete_transaction(transaction_id: str) -> Dict[str, Any]:
        """Delete a transaction"""
        db = get_db()
        try:
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                return {
                    "success": False,
                    "message": "Transaction not found"
                }

            db.delete(transaction)
            db.commit()

            logger.info(f"Deleted transaction {transaction_id}")
            return {
                "success": True,
                "message": "Transaction deleted successfully"
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting transaction: {str(e)}")
            return {
                "success": False,
                "message": f"Error deleting transaction: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def update_pocket_spending_by_category(user_id: str, category: str, amount: float) -> Dict[str, Any]:
        """Update pocket spending based on category (internal method)"""
        db = get_db()
        try:
            # Map categories to pocket names (simplified)
            category_pocket_map = {
                'food': ['Food', 'Groceries', 'Dining'],
                'transport': ['Transport', 'Fuel', 'Commute'],
                'shopping': ['Shopping', 'Lifestyle'],
                'entertainment': ['Entertainment', 'Fun'],
                'utilities': ['Utilities', 'Bills'],
                'health': ['Health', 'Medical'],
                'education': ['Education', 'Learning']
            }

            # Find matching pocket
            target_pocket = None
            pockets = db.query(Pocket).filter(Pocket.user_id == user_id).all()

            for pocket in pockets:
                pocket_keywords = category_pocket_map.get(pocket.name.lower(), [pocket.name.lower()])
                if any(keyword in category.lower() for keyword in pocket_keywords):
                    target_pocket = pocket
                    break

            # If no specific match, look for 'Other' or similar
            if not target_pocket:
                for pocket in pockets:
                    if 'other' in pocket.name.lower() or 'misc' in pocket.name.lower():
                        target_pocket = pocket
                        break

            # If still no match, use first pocket
            if not target_pocket and pockets:
                target_pocket = pockets[0]

            if target_pocket:
                target_pocket.spent_mtd += amount
                target_pocket.updated_at = datetime.utcnow()
                db.commit()

                return {
                    "success": True,
                    "pocket_id": target_pocket.id,
                    "pocket_name": target_pocket.name,
                    "amount_added": amount,
                    "new_spent": target_pocket.spent_mtd,
                    "remaining": target_pocket.monthly_limit - target_pocket.spent_mtd
                }
            else:
                return {
                    "success": False,
                    "message": "No matching pocket found for category"
                }
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating pocket spending by category: {str(e)}")
            return {
                "success": False,
                "message": f"Error updating pocket spending: {str(e)}"
            }
        finally:
            db.close()

class CommitmentService:
    """Service for commitment-related operations"""

    @staticmethod
    def add_commitment(user_id: str, name: str, amount: float,
                      commitment_type: str, frequency: str = "monthly",
                      day_of_month: int = 1) -> Dict[str, Any]:
        """Add a recurring commitment"""
        db = get_db()
        try:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            # Calculate next date
            next_date = CommitmentService._calculate_next_date(day_of_month, frequency)

            # Create commitment
            commitment = Commitment(
                user_id=user_id,
                name=name,
                amount=amount,
                type=commitment_type,
                frequency=frequency,
                day_of_month=day_of_month,
                next_date=next_date
            )
            db.add(commitment)
            db.commit()
            db.refresh(commitment)

            logger.info(f"Added commitment {commitment.id} for user {user_id}: {name}")
            return {
                "success": True,
                "message": "Commitment added successfully",
                "commitment_id": commitment.id,
                "commitment": {
                    "id": commitment.id,
                    "name": commitment.name,
                    "amount": commitment.amount,
                    "type": commitment.type.value,
                    "frequency": commitment.frequency.value,
                    "day_of_month": commitment.day_of_month,
                    "next_date": commitment.next_date.isoformat(),
                    "status": commitment.status
                }
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error adding commitment: {str(e)}")
            return {
                "success": False,
                "message": f"Error adding commitment: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def _calculate_next_date(day_of_month: int, frequency: str) -> datetime:
        """Calculate next occurrence date"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if frequency == "monthly":
            try:
                next_date = today.replace(day=day_of_month)
                if next_date < today:
                    if today.month == 12:
                        next_date = next_date.replace(year=today.year + 1, month=1)
                    else:
                        next_date = next_date.replace(month=today.month + 1)
            except ValueError:
                # Handle invalid day (e.g., Feb 30)
                if today.month == 12:
                    next_date = datetime(today.year + 1, 1, 1) - timedelta(days=1)
                else:
                    next_date = datetime(today.year, today.month + 1, 1) - timedelta(days=1)

        elif frequency == "quarterly":
            months_to_add = 3
            try:
                next_date = today.replace(month=today.month + months_to_add, day=day_of_month)
                if next_date < today:
                    next_date = next_date.replace(month=next_date.month + months_to_add)
            except ValueError:
                # Handle end of month
                if today.month + months_to_add > 12:
                    next_date = datetime(today.year + 1, (today.month + months_to_add) - 12, 1) - timedelta(days=1)
                else:
                    next_date = datetime(today.year, today.month + months_to_add, 1) - timedelta(days=1)

        elif frequency == "yearly":
            try:
                next_date = today.replace(year=today.year + 1, day=day_of_month)
            except ValueError:
                # Handle Feb 29 etc.
                next_date = datetime(today.year + 1, 3, 1)  # March 1 as fallback
        else:
            next_date = today + timedelta(days=30)  # Default to monthly

        return next_date

    @staticmethod
    def get_user_commitments(user_id: str) -> List[Dict[str, Any]]:
        """Get all commitments for a user"""
        db = get_db()
        try:
            commitments = db.query(Commitment).filter(Commitment.user_id == user_id).all()
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "amount": c.amount,
                    "type": c.type.value,
                    "frequency": c.frequency.value,
                    "day_of_month": c.day_of_month,
                    "next_date": c.next_date.isoformat() if c.next_date else None,
                    "status": c.status,
                    "created_at": c.created_at.isoformat() if c.created_at else None
                }
                for c in commitments
            ]
        finally:
            db.close()

    @staticmethod
    def get_committed_spending(user_id: str) -> Dict[str, Any]:
        """Calculate total committed spending"""
        db = get_db()
        try:
            commitments = db.query(Commitment).filter(
                Commitment.user_id == user_id,
                Commitment.status == "active"
            ).all()

            total_monthly = 0.0
            commitment_details = []

            for commitment in commitments:
                monthly_amount = 0.0
                if commitment.frequency == "monthly":
                    monthly_amount = commitment.amount
                elif commitment.frequency == "quarterly":
                    monthly_amount = commitment.amount / 3
                elif commitment.frequency == "yearly":
                    monthly_amount = commitment.amount / 12

                total_monthly += monthly_amount
                commitment_details.append({
                    "id": commitment.id,
                    "name": commitment.name,
                    "amount": commitment.amount,
                    "frequency": commitment.frequency.value,
                    "monthly_equivalent": monthly_amount
                })

            return {
                "total_monthly": total_monthly,
                "commitments": commitment_details
            }
        finally:
            db.close()

class BudgetService:
    """Service for budget-related operations"""

    @staticmethod
    def get_budget_snapshot(user_id: str) -> Dict[str, Any]:
        """Get current budget snapshot for user"""
        db = get_db()
        try:
            # Get user
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            # Calculate period (current month)
            now = datetime.now()
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now.month == 12:
                period_end = datetime(now.year + 1, 1, 1) - timedelta(seconds=1)
            else:
                period_end = datetime(now.year, now.month + 1, 1) - timedelta(seconds=1)

            # Get transactions for current month
            transactions = db.query(Transaction)\
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.timestamp >= period_start,
                    Transaction.timestamp <= period_end
                )\
                .all()

            total_spent = sum(t.amount for t in transactions)

            # Get committed spending
            committed_result = CommitmentService.get_committed_spending(user_id)
            total_committed = committed_result["total_monthly"]

            # Calculate available to spend
            available_to_spend = max(0, user.income - total_committed - total_spent)

            # Get pocket details
            pockets = db.query(Pocket).filter(Pocket.user_id == user_id).all()
            pocket_details = {}
            for pocket in pockets:
                pocket_details[pocket.name] = {
                    "budget": pocket.monthly_limit,
                    "spent": pocket.spent_mtd,
                    "remaining": pocket.monthly_limit - pocket.spent_mtd + pocket.rollover_balance,
                    "rollover": pocket.rollover_balance
                }

            snapshot = {
                "user_id": user_id,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "total_income": user.income,
                "total_committed": total_committed,
                "available_to_spend": available_to_spend,
                "total_spent": total_spent,
                "pocket_details": pocket_details
            }

            logger.debug(f"Generated budget snapshot for user {user_id}")
            return {
                "success": True,
                "snapshot": snapshot
            }
        except Exception as e:
            logger.error(f"Error generating budget snapshot: {str(e)}")
            return {
                "success": False,
                "message": f"Error generating budget snapshot: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def check_budget_alerts(user_id: str) -> List[Dict[str, Any]]:
        """Check for budget threshold alerts"""
        db = get_db()
        try:
            snapshot_result = BudgetService.get_budget_snapshot(user_id)
            if not snapshot_result["success"]:
                return []

            snapshot = snapshot_result["snapshot"]
            alerts = []

            for pocket_name, details in snapshot["pocket_details"].items():
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
                            "severity": "high",
                            "percentage": percentage_used
                        })
                    elif percentage_used >= 90:
                        alerts.append({
                            "type": "budget_warning",
                            "pocket": pocket_name,
                            "message": f"You've used 90% of your {pocket_name} budget. Spent: ₹{spent:.0f}/{budget:.0f}",
                            "severity": "medium",
                            "percentage": percentage_used
                        })
                    elif percentage_used >= 70:
                        alerts.append({
                            "type": "budget_notice",
                            "pocket": pocket_name,
                            "message": f"You've used 70% of your {pocket_name} budget. Spent: ₹{spent:.0f}/{budget:.0f}",
                            "severity": "low",
                            "percentage": percentage_used
                        })

            return alerts
        finally:
            db.close()

    @staticmethod
    def get_upcoming_deductions(user_id: str, days_ahead: int = 3) -> List[Dict[str, Any]]:
        """Get upcoming commitments for pre-deduction alerts"""
        db = get_db()
        try:
            cutoff_date = datetime.now() + timedelta(days=days_ahead)

            commitments = db.query(Commitment)\
                .filter(
                    Commitment.user_id == user_id,
                    Commitment.status == "active",
                    Commitment.next_date <= cutoff_date
                )\
                .order_by(Commitment.next_date.asc())\
                .all()

            upcoming = []
            for commitment in commitments:
                days_until = (commitment.next_date - datetime.now()).days
                upcoming.append({
                    "commitment_id": commitment.id,
                    "commitment_name": commitment.name,
                    "amount": commitment.amount,
                    "type": commitment.type.value,
                    "frequency": commitment.frequency.value,
                    "next_date": commitment.next_date.isoformat(),
                    "days_until": max(0, days_until),
                    "urgency": "high" if days_until <= 3 else "medium" if days_until <= 5 else "low"
                })

            return upcoming
        finally:
            db.close()


class SavingsGoalService:
    """Service for savings goal-related operations"""

    @staticmethod
    def create_savings_goal(user_id: str, pocket_id: str, name: str,
                           target_amount: float, target_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Create a new savings goal linked to a pocket"""
        db = get_db()
        try:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            # Verify pocket exists and belongs to user
            pocket = db.query(Pocket).filter(
                Pocket.id == pocket_id,
                Pocket.user_id == user_id
            ).first()
            if not pocket:
                return {
                    "success": False,
                    "message": "Pocket not found or does not belong to user"
                }

            # Validate target amount
            if target_amount <= 0:
                return {
                    "success": False,
                    "message": "Target amount must be positive"
                }

            # Calculate monthly contribution if target date is provided
            monthly_contribution = None
            if target_date:
                months_remaining = max(1, (target_date.year - datetime.now().year) * 12 + target_date.month - datetime.now().month)
                if months_remaining > 0:
                    monthly_contribution = (target_amount - pocket.spent_mtd) / months_remaining
                    monthly_contribution = max(0, monthly_contribution)  # Don't suggest negative contributions

            # Create savings goal
            goal = SavingsGoal(
                pocket_id=pocket_id,
                name=name,
                target_amount=target_amount,
                current_amount=pocket.spent_mtd,  # Start with current pocket spending
                target_date=target_date,
                monthly_contribution=monthly_contribution,
                is_active=True
            )
            db.add(goal)
            db.commit()
            db.refresh(goal)

            logger.info(f"Created savings goal {goal.id} for user {user_id}: {name}")
            return {
                "success": True,
                "message": "Savings goal created successfully",
                "goal_id": goal.id,
                "goal": {
                    "id": goal.id,
                    "name": goal.name,
                    "target_amount": goal.target_amount,
                    "current_amount": goal.current_amount,
                    "target_date": goal.target_date.isoformat() if goal.target_date else None,
                    "monthly_contribution": goal.monthly_contribution,
                    "progress_percentage": (goal.current_amount / goal.target_amount * 100) if goal.target_amount > 0 else 0
                }
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating savings goal: {str(e)}")
            return {
                "success": False,
                "message": f"Error creating savings goal: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def get_user_savings_goals(user_id: str) -> List[Dict[str, Any]]:
        """Get all savings goals for a user"""
        db = get_db()
        try:
            # Join with pockets to ensure goals belong to user's pockets
            goals = db.query(SavingsGoal)\
                .join(Pocket, SavingsGoal.pocket_id == Pocket.id)\
                .filter(Pocket.user_id == user_id)\
                .all()

            return [
                {
                    "id": goal.id,
                    "pocket_id": goal.pocket_id,
                    "name": goal.name,
                    "target_amount": goal.target_amount,
                    "current_amount": goal.current_amount,
                    "target_date": goal.target_date.isoformat() if goal.target_date else None,
                    "monthly_contribution": goal.monthly_contribution,
                    "progress_percentage": (goal.current_amount / goal.target_amount * 100) if goal.target_amount > 0 else 0,
                    "is_active": goal.is_active,
                    "created_at": goal.created_at.isoformat() if goal.created_at else None
                }
                for goal in goals
            ]
        finally:
            db.close()

    @staticmethod
    def update_savings_goal_progress(goal_id: str) -> Dict[str, Any]:
        """Update the current amount of a savings goal based on pocket spending"""
        db = get_db()
        try:
            goal = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id).first()
            if not goal:
                return {
                    "success": False,
                    "message": "Savings goal not found"
                }

            # Update current amount to match pocket spending
            goal.current_amount = goal.pocket.spent_mtd
            goal.updated_at = datetime.utcnow()
            db.commit()

            logger.info(f"Updated savings goal {goal_id} progress to {goal.current_amount}")
            return {
                "success": True,
                "message": "Savings goal progress updated",
                "current_amount": goal.current_amount,
                "progress_percentage": (goal.current_amount / goal.target_amount * 100) if goal.target_amount > 0 else 0
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating savings goal progress: {str(e)}")
            return {
                "success": False,
                "message": f"Error updating savings goal progress: {str(e)}"
            }
        finally:
            db.close()


class BudgetIntelligenceService:
    """Service for AI-powered budget intelligence and suggestions"""

    @staticmethod
    def analyze_spending_patterns(user_id: str, months_back: int = 3) -> List[Dict[str, Any]]:
        """Analyze historical spending to detect patterns"""
        db = get_db()
        try:
            # Get user
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return []

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30 * months_back)

            # Get transactions for the period
            transactions = db.query(Transaction)\
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                )\
                .all()

            if len(transactions) < 2:  # Need at least 2 transactions to analyze
                return []

            # Group by category and month
            category_monthly = {}
            for transaction in transactions:
                # Get year-month key
                year_month = transaction.timestamp.strftime("%Y-%m")
                category = transaction.category

                if category not in category_monthly:
                    category_monthly[category] = {}
                if year_month not in category_monthly[category]:
                    category_monthly[category][year_month] = 0

                category_monthly[category][year_month] += transaction.amount

            # Calculate statistics for each category
            patterns = []
            for category, monthly_data in category_monthly.items():
                amounts = list(monthly_data.values())
                if len(amounts) >= 2:  # Need at least 2 months of data
                    try:
                        mean = statistics.mean(amounts)
                        median = statistics.median(amounts)
                        stdev = statistics.stdev(amounts) if len(amounts) >= 2 else 0.0

                        # Determine trend
                        if len(amounts) >= 3:
                            # Simple trend detection: compare first half to second half
                            mid = len(amounts) // 2
                            first_half_avg = statistics.mean(amounts[:mid])
                            second_half_avg = statistics.mean(amounts[mid:])
                            if second_half_avg > first_half_avg * 1.1:
                                trend = "increasing"
                            elif second_half_avg < first_half_avg * 0.9:
                                trend = "decreasing"
                            else:
                                trend = "stable"
                        else:
                            trend = "insufficient_data"

                        # Calculate confidence based on consistency
                        if mean > 0:
                            cv = stdev / mean  # Coefficient of variation
                            confidence = max(0, min(1, 1 - cv))  # Higher confidence when CV is low
                        else:
                            confidence = 0.0

                        pattern = {
                            "category": category,
                            "average_monthly": mean,
                            "median_monthly": median,
                            "std_deviation": stdev,
                            "sample_size": len(amounts),
                            "trend": trend,
                            "confidence": confidence
                        }
                        patterns.append(pattern)

                        # Save or update spending pattern in database
                        existing_pattern = db.query(SpendingPattern)\
                            .filter(
                                SpendingPattern.user_id == user_id,
                                SpendingPattern.category == category
                            )\
                            .first()

                        if existing_pattern:
                            # Update existing
                            existing_pattern.average_monthly = mean
                            existing_pattern.median_monthly = median
                            existing_pattern.std_deviation = stdev
                            existing_pattern.sample_size = len(amounts)
                            existing_pattern.trend = trend
                            existing_pattern.confidence = confidence
                            existing_pattern.detected_at = datetime.utcnow()
                            existing_pattern.valid_until = datetime.utcnow() + timedelta(days=30)
                        else:
                            # Create new
                            new_pattern = SpendingPattern(
                                user_id=user_id,
                                category=category,
                                average_monthly=mean,
                                median_monthly=median,
                                std_deviation=stdev,
                                sample_size=len(amounts),
                                trend=trend,
                                confidence=confidence,
                                detected_at=datetime.utcnow(),
                                valid_until=datetime.utcnow() + timedelta(days=30)
                            )
                            db.add(new_pattern)

                    except Exception as e:
                        logger.warning(f"Could not calculate statistics for category {category}: {str(e)}")
                        continue

            db.commit()

            logger.info(f"Analyzed spending patterns for user {user_id}, found {len(patterns)} patterns")
            return patterns
        except Exception as e:
            db.rollback()
            logger.error(f"Error analyzing spending patterns: {str(e)}")
            return []
        finally:
            db.close()

    @staticmethod
    def generate_budget_suggestions(user_id: str) -> List[Dict[str, Any]]:
        """Generate AI-powered budget suggestions based on spending patterns"""
        db = get_db()
        try:
            # Get user
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return []

            # Get current pockets
            pockets = db.query(Pocket).filter(Pocket.user_id == user_id).all()
            pocket_names = [pocket.name for pocket in pockets]

            # Analyze spending patterns
            patterns = BudgetIntelligenceService.analyze_spending_patterns(user_id)
            suggestions = []

            for pattern in patterns:
                category = pattern["category"]
                suggested_amount = pattern["average_monthly"]

                # Find matching pocket or suggest creating one
                pocket_match = None
                for pocket in pockets:
                    # Simple matching - in reality would be more sophisticated
                    if (category.lower() in pocket.name.lower() or
                        pocket.name.lower() in category.lower()):
                        pocket_match = pocket
                        break

                suggestion_text = f"Based on your spending, you typically spend ₹{suggested_amount:.0f}/month on {category}."
                if pattern["trend"] == "increasing":
                    suggestion_text += " This category has been increasing lately."
                elif pattern["trend"] == "decreasing":
                    suggestion_text += " This category has been decreasing lately."

                if pocket_match:
                    suggestion_text += f" Consider setting your {pocket_match.name} budget to ₹{suggested_amount:.0f}."
                else:
                    suggestion_text += f" You might want to create a '{category.title()}' pocket with a budget of ₹{suggested_amount:.0f}."

                # Create suggestion in database
                suggestion = BudgetSuggestion(
                    user_id=user_id,
                    pocket_name=pocket_match.name if pocket_match else category.title(),
                    suggested_amount=suggested_amount,
                    reasoning=suggestion_text,
                    confidence=pattern["confidence"],
                    is_accepted=False,
                    is_dismissed=False,
                    valid_until=datetime.utcnow() + timedelta(days=7)  # Suggestions expire in a week
                )
                db.add(suggestion)

                suggestions.append({
                    "category": category,
                    "suggested_amount": suggested_amount,
                    "reasoning": suggestion_text,
                    "confidence": pattern["confidence"],
                    "trend": pattern["trend"],
                    "matches_existing_pocket": pocket_match is not None,
                    "pocket_name": pocket_match.name if pocket_match else None
                })

            db.commit()

            logger.info(f"Generated {len(suggestions)} budget suggestions for user {user_id}")
            return suggestions
        except Exception as e:
            db.rollback()
            logger.error(f"Error generating budget suggestions: {str(e)}")
            return []
        finally:
            db.close()

    @staticmethod
    def get_budget_suggestions(user_id: str) -> List[Dict[str, Any]]:
        """Get existing budget suggestions for a user"""
        db = get_db()
        try:
            suggestions = db.query(BudgetSuggestion)\
                .filter(
                    BudgetSuggestion.user_id == user_id,
                    BudgetSuggestion.is_accepted == False,
                    BudgetSuggestion.is_dismissed == False,
                    BudgetSuggestion.valid_until >= datetime.utcnow()
                )\
                .order_by(BudgetSuggestion.confidence.desc())\
                .all()

            return [
                {
                    "id": suggestion.id,
                    "pocket_name": suggestion.pocket_name,
                    "suggested_amount": suggestion.suggested_amount,
                    "reasoning": suggestion.reasoning,
                    "confidence": suggestion.confidence,
                    "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
                    "valid_until": suggestion.valid_until.isoformat() if suggestion.valid_until else None
                }
                for suggestion in suggestions
            ]
        finally:
            db.close()

    @staticmethod
    def respond_to_suggestion(suggestion_id: str, accept: bool) -> Dict[str, Any]:
        """Respond to a budget suggestion (accept or dismiss)"""
        db = get_db()
        try:
            suggestion = db.query(BudgetSuggestion).filter(BudgetSuggestion.id == suggestion_id).first()
            if not suggestion:
                return {
                    "success": False,
                    "message": "Suggestion not found"
                }

            if accept:
                suggestion.is_accepted = True
                message = "Budget suggestion accepted!"
                # Optionally auto-create/update pocket here
            else:
                suggestion.is_dismissed = True
                message = "Budget suggestion dismissed."

            suggestion.updated_at = datetime.utcnow()
            db.commit()

            return {
                "success": True,
                "message": message,
                "suggestion_id": suggestion_id,
                "accepted": accept
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error responding to suggestion: {str(e)}")
            return {
                "success": False,
                "message": f"Error responding to suggestion: {str(e)}"
            }
        finally:
            db.close()


class SplitService:
    """Service for bill splitting and group expense management"""

    @staticmethod
    def create_group_split(user_id: str, group_name: str, description: str,
                          total_amount: float, split_method: str = "equal",
                          splits: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Create a new group split for tracking shared expenses"""
        db = get_db()
        try:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            # Validate total amount
            if total_amount <= 0:
                return {
                    "success": False,
                    "message": "Total amount must be positive"
                }

            # Validate split method
            valid_methods = ["equal", "percentage", "exact", "shares"]
            if split_method not in valid_methods:
                return {
                    "success": False,
                    "message": f"Split method must be one of: {', '.join(valid_methods)}"
                }

            # Create group split
            group_split = GroupSplit(
                user_id=user_id,
                group_name=group_name,
                description=description,
                total_amount=total_amount,
                split_method=split_method,
                is_settled=False
            )
            db.add(group_split)
            db.flush()  # Get the ID without committing

            # Process splits if provided
            split_transactions = []
            if splits:
                if split_method == "equal":
                    # Equal split: divide total by number of splits
                    amount_per_person = total_amount / len(splits)
                    for i, split_data in enumerate(splits):
                        owed_by_user_id = split_data.get("user_id")
                        if not owed_by_user_id:
                            continue

                        split_transaction = SplitTransaction(
                            group_split_id=group_split.id,
                            user_id=user_id,  # Expense incurred by current user
                            amount=total_amount,
                            description=split_data.get("description", f"Split {i+1}"),
                            owed_by_user_id=owed_by_user_id,
                            owed_amount=amount_per_person,
                            paid_amount=0.0
                        )
                        db.add(split_transaction)
                        split_transactions.append(split_transaction)

                elif split_method == "percentage":
                    # Percentage split: allocate based on percentages
                    total_percentage = sum(split_data.get("percentage", 0) for split_data in splits)
                    if abs(total_percentage - 100) > 0.01:  # Allow small floating point differences
                        return {
                            "success": False,
                            "message": "Percentages must sum to 100%"
                        }

                    for split_data in splits:
                        owed_by_user_id = split_data.get("user_id")
                        percentage = split_data.get("percentage", 0)
                        if not owed_by_user_id or percentage <= 0:
                            continue

                        owed_amount = total_amount * (percentage / 100)
                        split_transaction = SplitTransaction(
                            group_split_id=group_split.id,
                            user_id=user_id,
                            amount=total_amount,
                            description=split_data.get("description", f"Split"),
                            owed_by_user_id=owed_by_user_id,
                            owed_amount=owed_amount,
                            paid_amount=0.0
                        )
                        db.add(split_transaction)
                        split_transactions.append(split_transaction)

                elif split_method == "exact":
                    # Exact split: specify exact amounts
                    total_exact = sum(split_data.get("amount", 0) for split_data in splits)
                    if abs(total_exact - total_amount) > 0.01:
                        return {
                            "success": False,
                            "message": "Exact amounts must sum to total amount"
                        }

                    for split_data in splits:
                        owed_by_user_id = split_data.get("user_id")
                        amount = split_data.get("amount", 0)
                        if not owed_by_user_id or amount <= 0:
                            continue

                        split_transaction = SplitTransaction(
                            group_split_id=group_split.id,
                            user_id=user_id,
                            amount=total_amount,
                            description=split_data.get("description", f"Split"),
                            owed_by_user_id=owed_by_user_id,
                            owed_amount=amount,
                            paid_amount=0.0
                        )
                        db.add(split_transaction)
                        split_transactions.append(split_transaction)

                # For 'shares' method, we'd implement similar logic based on share values

            db.commit()

            logger.info(f"Created group split {group_split.id} for user {user_id}: {group_name}")
            return {
                "success": True,
                "message": "Group split created successfully",
                "group_split_id": group_split.id,
                "group_split": {
                    "id": group_split.id,
                    "group_name": group_split.group_name,
                    "description": group_split.description,
                    "total_amount": group_split.total_amount,
                    "split_method": group_split.split_method,
                    "is_settled": group_split.is_settled
                },
                "split_transactions": [
                    {
                        "id": st.id,
                        "owed_by_user_id": st.owed_by_user_id,
                        "owed_amount": st.owed_amount,
                        "paid_amount": st.paid_amount,
                        "is_settled": st.is_settled
                    }
                    for st in split_transactions
                ]
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating group split: {str(e)}")
            return {
                "success": False,
                "message": f"Error creating group split: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def get_user_group_splits(user_id: str, include_settled: bool = False) -> List[Dict[str, Any]]:
        """Get group splits for a user"""
        db = get_db()
        try:
            query = db.query(GroupSplit).filter(GroupSplit.user_id == user_id)
            if not include_settled:
                query = query.filter(GroupSplit.is_settled == False)

            group_splits = query.order_by(GroupSplit.created_at.desc()).all()

            return [
                {
                    "id": gs.id,
                    "group_name": gs.group_name,
                    "description": gs.description,
                    "total_amount": gs.total_amount,
                    "split_method": gs.split_method,
                    "is_settled": gs.is_settled,
                    "settled_date": gs.settled_date.isoformat() if gs.settled_date else None,
                    "created_at": gs.created_at.isoformat() if gs.created_at else None,
                    "split_count": len(gs.transactions)
                }
                for gs in group_splits
            ]
        finally:
            db.close()

    @staticmethod
    def record_split_payment(split_transaction_id: str, amount_paid: float) -> Dict[str, Any]:
        """Record a payment towards a split transaction"""
        db = get_db()
        try:
            split_transaction = db.query(SplitTransaction).filter(SplitTransaction.id == split_transaction_id).first()
            if not split_transaction:
                return {
                    "success": False,
                    "message": "Split transaction not found"
                }

            if amount_paid < 0:
                return {
                    "success": False,
                    "message": "Payment amount cannot be negative"
                }

            # Update paid amount
            split_transaction.paid_amount += amount_paid
            split_transaction.updated_at = datetime.utcnow()

            # Check if fully paid
            if split_transaction.paid_amount >= split_transaction.owed_amount:
                split_transaction.paid_amount = split_transaction.owed_amount
                split_transaction.is_settled = True

            db.commit()

            logger.info(f"Recorded payment of {amount_paid} for split transaction {split_transaction_id}")
            return {
                "success": True,
                "message": "Payment recorded successfully",
                "split_transaction_id": split_transaction_id,
                "total_paid": split_transaction.paid_amount,
                "total_owed": split_transaction.owed_amount,
                "remaining": split_transaction.owed_amount - split_transaction.paid_amount,
                "is_settled": split_transaction.is_settled
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error recording split payment: {str(e)}")
            return {
                "success": False,
                "message": f"Error recording split payment: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def get_owe_summary(user_id: str) -> Dict[str, Any]:
        """Get summary of what user owes and is owed"""
        db = get_db()
        try:
            # What user owes (they are the 'owed_by' in split transactions)
            owes = db.query(SplitTransaction)\
                .filter(SplitTransaction.owed_by_user_id == user_id)\
                .all()

            total_owed = sum(st.owed_amount - st.paid_amount for st in owes if not st.is_settled)

            # What is owed to user (they are the 'user_id' who incurred expense)
            owed_to = db.query(SplitTransaction)\
                .filter(SplitTransaction.user_id == user_id)\
                .all()

            total_owed_to_user = sum(st.owed_amount - st.paid_amount for st in owed_to if not st.is_settled)

            owes_details = []
            for st in owes:
                if not st.is_settled and st.owed_amount > st.paid_amount:
                    owes_details.append({
                        "group_split_id": st.group_split_id,
                        "group_name": st.group_split.group_name if st.group_split else "Unknown",
                        "description": st.description,
                        "owed_amount": st.owed_amount,
                        "paid_amount": st.paid_amount,
                        "remaining": st.owed_amount - st.paid_amount
                    })

            owed_to_details = []
            for st in owed_to:
                if not st.is_settled and st.owed_amount > st.paid_amount:
                    owed_to_details.append({
                        "group_split_id": st.group_split_id,
                        "group_name": st.group_split.group_name if st.group_split else "Unknown",
                        "description": st.description,
                        "owed_amount": st.owed_amount,
                        "paid_amount": st.paid_amount,
                        "remaining": st.owed_amount - st.paid_amount
                    })

            return {
                "total_owed": total_owed,
                "total_owed_to_user": total_owed_to_user,
                "net_position": total_owed_to_user - total_owed,  # Positive means others owe you
                "owes_details": owes_details,
                "owed_to_details": owed_to_details
            }
        finally:
            db.close()


class AnomalyDetectionService:
    """Service for detecting unusual spending patterns"""

    @staticmethod
    def detect_anomalies(user_id: str, lookback_days: int = 30) -> List[Dict[str, Any]]:
        """Detect anomalous transactions based on historical spending"""
        db = get_db()
        try:
            # Get user
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return []

            # Calculate date ranges
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days)

            # Get transactions for the period
            transactions = db.query(Transaction)\
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                )\
                .order_by(Transaction.timestamp.desc())\
                .all()

            if len(transactions) < 5:  # Need sufficient data for anomaly detection
                return []

            anomalies = []

            # Group by category for category-based anomaly detection
            category_transactions = {}
            for transaction in transactions:
                category = transaction.category
                if category not in category_transactions:
                    category_transactions[category] = []
                category_transactions[category].append(transaction)

            # Check each category for anomalies
            for category, cat_transactions in category_transactions.items():
                if len(cat_transactions) >= 3:  # Need at least 3 transactions for meaningful stats
                    amounts = [t.amount for t in cat_transactions]
                    try:
                        mean = statistics.mean(amounts)
                        stdev = statistics.stdev(amounts) if len(amounts) >= 2 else 0

                        # Avoid division by zero
                        if stdev == 0:
                            continue

                        # Check each transaction for being an outlier
                        for transaction in cat_transactions:
                            if transaction.amount > 0:  # Only check positive amounts (expenses)
                                z_score = abs(transaction.amount - mean) / stdev

                                # Consider it an anomaly if > 2 standard deviations from mean
                                if z_score > 2.0:
                                    # Check if we've already alerted for this transaction
                                    existing_alert = db.query(AnomalyAlert)\
                                        .filter(AnomalyAlert.transaction_id == transaction.id)\
                                        .first()

                                    if not existing_alert:
                                        # Determine severity based on z-score
                                        if z_score > 3.0:
                                            severity = "high"
                                        elif z_score > 2.5:
                                            severity = "medium"
                                        else:
                                            severity = "low"

                                        alert = AnomalyAlert(
                                            user_id=user_id,
                                            transaction_id=transaction.id,
                                            anomaly_type="amount",
                                            severity=severity,
                                            description=f"Unusual spending detected: ₹{transaction.amount:.0f} in {category} (expected: ₹{mean:.0f} ± {stdev:.0f})",
                                            expected_value=mean,
                                            actual_value=transaction.amount,
                                            z_score=z_score
                                        )
                                        db.add(alert)
                                        anomalies.append({
                                            "id": alert.id,
                                            "transaction_id": transaction.id,
                                            "amount": transaction.amount,
                                            "category": category,
                                            "expected": mean,
                                            "actual": transaction.amount,
                                            "z_score": z_score,
                                            "severity": severity,
                                            "description": alert.description
                                        })

                    except Exception as e:
                        logger.warning(f"Could not analyze category {category} for anomalies: {str(e)}")
                        continue

            # Also check for temporal anomalies (unusual timing)
            # For simplicity, we'll look for transactions at unusual hours
            for transaction in transactions:
                hour = transaction.timestamp.hour
                # Consider transactions between 2am-5am as potentially unusual
                if 2 <= hour <= 5:
                    existing_alert = db.query(AnomalyAlert)\
                        .filter(AnomalyAlert.transaction_id == transaction.id)\
                        .first()

                    if not existing_alert:
                        alert = AnomalyAlert(
                            user_id=user_id,
                            transaction_id=transaction.id,
                            anomaly_type="time",
                            severity="low",
                            description=f"Transaction at unusual time: {transaction.timestamp.strftime('%H:%M')}",
                            expected_value=12.0,  # Noon as reference
                            actual_value=float(hour),
                            z_score=abs(hour - 12) / 6.0  # Rough normalization
                        )
                        db.add(alert)
                        anomalies.append({
                            "id": alert.id,
                            "transaction_id": transaction.id,
                            "amount": transaction.amount,
                            "category": transaction.category,
                            "anomaly_type": "time",
                            "severity": "low",
                            "description": alert.description
                        })

            db.commit()

            logger.info(f"Detected {len(anomalies)} anomalies for user {user_id}")
            return anomalies
        except Exception as e:
            db.rollback()
            logger.error(f"Error detecting anomalies: {str(e)}")
            return []
        finally:
            db.close()

    @staticmethod
    def get_user_anomalies(user_id: str, include_resolved: bool = False) -> List[Dict[str, Any]]:
        """Get anomaly alerts for a user"""
        db = get_db()
        try:
            query = db.query(AnomalyAlert).filter(AnomalyAlert.user_id == user_id)
            if not include_resolved:
                query = query.filter(AnomalyAlert.is_resolved == False)

            alerts = query.order_by(AnomalyAlert.created_at.desc()).all()

            return [
                {
                    "id": alert.id,
                    "transaction_id": alert.transaction_id,
                    "anomaly_type": alert.anomaly_type,
                    "severity": alert.severity,
                    "description": alert.description,
                    "expected_value": alert.expected_value,
                    "actual_value": alert.actual_value,
                    "z_score": alert.z_score,
                    "is_resolved": alert.is_resolved,
                    "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                    "created_at": alert.created_at.isoformat() if alert.created_at else None
                }
                for alert in alerts
            ]
        finally:
            db.close()

    @staticmethod
    def resolve_anomaly(alert_id: str, resolution_note: Optional[str] = None) -> Dict[str, Any]:
        """Mark an anomaly as resolved"""
        db = get_db()
        try:
            alert = db.query(AnomalyAlert).filter(AnomalyAlert.id == alert_id).first()
            if not alert:
                return {
                    "success": False,
                    "message": "Anomaly alert not found"
                }

            alert.is_resolved = True
            alert.resolved_at = datetime.utcnow()
            if resolution_note:
                # In a real implementation, we might store this in a separate field or notes
                pass
            alert.updated_at = datetime.utcnow()

            db.commit()

            logger.info(f"Resolved anomaly alert {alert_id}")
            return {
                "success": True,
                "message": "Anomaly alert resolved",
                "alert_id": alert_id,
                "resolved_at": alert.resolved_at.isoformat()
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error resolving anomaly: {str(e)}")
            return {
                "success": False,
                "message": f"Error resolving anomaly: {str(e)}"
            }
        finally:
            db.close()


class NetWorthService:
    """Service for net worth tracking (assets and liabilities)"""

    @staticmethod
    def add_asset(user_id: str, name: str, asset_type: str, value: float,
                 description: Optional[str] = None) -> Dict[str, Any]:
        """Add an asset for net worth tracking"""
        db = get_db()
        try:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            # Validate value
            if value < 0:
                return {
                    "success": False,
                    "message": "Asset value cannot be negative"
                }

            # Create asset
            asset = Asset(
                user_id=user_id,
                name=name,
                asset_type=asset_type,
                value=value,
                description=description,
                is_active=True
            )
            db.add(asset)
            db.commit()
            db.refresh(asset)

            logger.info(f"Added asset {asset.id} for user {user_id}: {name}")
            return {
                "success": True,
                "message": "Asset added successfully",
                "asset_id": asset.id,
                "asset": {
                    "id": asset.id,
                    "name": asset.name,
                    "asset_type": asset.asset_type,
                    "value": asset.value,
                    "description": asset.description
                }
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error adding asset: {str(e)}")
            return {
                "success": False,
                "message": f"Error adding asset: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def add_liability(user_id: str, name: str, liability_type: str, amount_owed: float,
                     interest_rate: Optional[float] = None, minimum_payment: Optional[float] = None,
                     due_date: Optional[datetime] = None, description: Optional[str] = None) -> Dict[str, Any]:
        """Add a liability for net worth tracking"""
        db = get_db()
        try:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            # Validate amount
            if amount_owed <= 0:
                return {
                    "success": False,
                    "message": "Liability amount must be positive"
                }

            # Create liability
            liability = Liability(
                user_id=user_id,
                name=name,
                liability_type=liability_type,
                amount_owed=amount_owed,
                interest_rate=interest_rate,
                minimum_payment=minimum_payment,
                due_date=due_date,
                description=description,
                is_active=True
            )
            db.add(liability)
            db.commit()
            db.refresh(liability)

            logger.info(f"Added liability {liability.id} for user {user_id}: {name}")
            return {
                "success": True,
                "message": "Liability added successfully",
                "liability_id": liability.id,
                "liability": {
                    "id": liability.id,
                    "name": liability.name,
                    "liability_type": liability.liability_type,
                    "amount_owed": liability.amount_owed,
                    "interest_rate": liability.interest_rate,
                    "minimum_payment": liability.minimum_payment,
                    "due_date": liability.due_date.isoformat() if liability.due_date else None,
                    "description": liability.description
                }
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error adding liability: {str(e)}")
            return {
                "success": False,
                "message": f"Error adding liability: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def get_net_worth(user_id: str) -> Dict[str, Any]:
        """Calculate and return net worth for a user"""
        db = get_db()
        try:
            # Get user
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            # Get assets
            assets = db.query(Asset).filter(
                Asset.user_id == user_id,
                Asset.is_active == True
            ).all()

            # Get liabilities
            liabilities = db.query(Liability).filter(
                Liability.user_id == user_id,
                Liability.is_active == True
            ).all()

            # Calculate totals
            total_assets = sum(asset.value for asset in assets)
            total_liabilities = sum(liability.amount_owed for liability in liabilities)
            net_worth = total_assets - total_liabilities

            # Group by type
            assets_by_type = {}
            for asset in assets:
                asset_type = asset.asset_type or "other"
                if asset_type not in assets_by_type:
                    assets_by_type[asset_type] = []
                assets_by_type[asset_type].append({
                    "id": asset.id,
                    "name": asset.name,
                    "value": asset.value,
                    "description": asset.description
                })

            liabilities_by_type = {}
            for liability in liabilities:
                liability_type = liability.liability_type or "other"
                if liability_type not in liabilities_by_type:
                    liabilities_by_type[liability_type] = []
                liabilities_by_type[liability_type].append({
                    "id": liability.id,
                    "name": liability.name,
                    "amount_owed": liability.amount_owed,
                    "interest_rate": liability.interest_rate,
                    "minimum_payment": liability.minimum_payment,
                    "due_date": liability.due_date.isoformat() if liability.due_date else None,
                    "description": liability.description
                })

            return {
                "success": True,
                "user_id": user_id,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "net_worth": net_worth,
                "assets_by_type": assets_by_type,
                "liabilities_by_type": liabilities_by_type,
                "asset_count": len(assets),
                "liability_count": len(liabilities),
                "calculated_at": datetime.utcnow().isoformat()
            }
        finally:
            db.close()

    @staticmethod
    def get_user_assets(user_id: str) -> List[Dict[str, Any]]:
        """Get all assets for a user"""
        db = get_db()
        try:
            assets = db.query(Asset)\
                .filter(
                    Asset.user_id == user_id,
                    Asset.is_active == True
                )\
                .order_by(Asset.created_at.desc())\
                .all()

            return [
                {
                    "id": asset.id,
                    "name": asset.name,
                    "asset_type": asset.asset_type,
                    "value": asset.value,
                    "description": asset.description,
                    "created_at": asset.created_at.isoformat() if asset.created_at else None
                }
                for asset in assets
            ]
        finally:
            db.close()

    @staticmethod
    def get_user_liabilities(user_id: str) -> List[Dict[str, Any]]:
        """Get all liabilities for a user"""
        db = get_db()
        try:
            liabilities = db.query(Liability)\
                .filter(
                    Liability.user_id == user_id,
                    Liability.is_active == True
                )\
                .order_by(Liability.created_at.desc())\
                .all()

            return [
                {
                    "id": liability.id,
                    "name": liability.name,
                    "liability_type": liability.liability_type,
                    "amount_owed": liability.amount_owed,
                    "interest_rate": liability.interest_rate,
                    "minimum_payment": liability.minimum_payment,
                    "due_date": liability.due_date.isoformat() if liability.due_date else None,
                    "description": liability.description,
                    "created_at": liability.created_at.isoformat() if liability.created_at else None
                }
                for liability in liabilities
            ]
        finally:
            db.close()


class GamificationService:
    """Service for gamification features like streaks and achievements"""

    @staticmethod
    def update_streak(user_id: str, streak_type: str) -> Dict[str, Any]:
        """Update a user's streak for a given type"""
        db = get_db()
        try:
            # Get or create streak record
            streak = db.query(UserStreak)\
                .filter(
                    UserStreak.user_id == user_id,
                    UserStreak.streak_type == streak_type
                )\
                .first()

            today = datetime.now().date()

            if streak:
                # Check if we need to update the streak
                last_updated_date = streak.last_updated.date() if streak.last_updated else None

                if last_updated_date == today:
                    # Already updated today, no change
                    return {
                        "success": True,
                        "message": "Streak already updated today",
                        "current_streak": streak.current_streak,
                        "longest_streak": streak.longest_streak
                    }
                elif last_updated_date == today - timedelta(days=1):
                    # Yesterday was last update, increment streak
                    streak.current_streak += 1
                else:
                    # More than a day gap, reset streak
                    streak.current_streak = 1

                # Update longest streak if needed
                if streak.current_streak > streak.longest_streak:
                    streak.longest_streak = streak.current_streak

                # Update streak start date if this is a new streak
                if streak.current_streak == 1:
                    streak.streak_start_date = datetime.utcnow()

                streak.last_updated = datetime.utcnow()
            else:
                # Create new streak record
                streak = UserStreak(
                    user_id=user_id,
                    streak_type=streak_type,
                    current_streak=1,
                    longest_streak=1,
                    last_updated=datetime.utcnow(),
                    streak_start_date=datetime.utcnow()
                )
                db.add(streak)

            db.commit()

            logger.info(f"Updated {streak_type} streak for user {user_id}: {streak.current_streak} days")
            return {
                "success": True,
                "message": f"{streak_type.replace('_', ' ').title()} streak updated",
                "current_streak": streak.current_streak,
                "longest_streak": streak.longest_streak,
                "streak_start_date": streak.streak_start_date.isoformat() if streak.streak_start_date else None
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating streak: {str(e)}")
            return {
                "success": False,
                "message": f"Error updating streak: {str(e)}"
            }
        finally:
            db.close()


class CategoryPreferenceService:
    """Service for managing user category preferences for transaction categorization"""

    @staticmethod
    def add_or_update_preference(user_id: str, transaction_description: str, preferred_category: str, confidence: float = 1.0) -> Dict[str, Any]:
        """Add or update a user's category preference for a transaction description"""
        db = get_db()
        try:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found"
                }

            # Validate inputs
            if not transaction_description or not transaction_description.strip():
                return {
                    "success": False,
                    "message": "Transaction description cannot be empty"
                }

            if not preferred_category or not preferred_category.strip():
                return {
                    "success": False,
                    "message": "Preferred category cannot be empty"
                }

            if confidence < 0.0 or confidence > 1.0:
                return {
                    "success": False,
                    "message": "Confidence must be between 0.0 and 1.0"
                }

            # Check if preference already exists
            existing_preference = db.query(UserCategoryPreference)\
                .filter(
                    UserCategoryPreference.user_id == user_id,
                    UserCategoryPreference.transaction_description == transaction_description.strip()
                )\
                .first()

            if existing_preference:
                # Update existing preference
                existing_preference.preferred_category = preferred_category.strip()
                existing_preference.confidence = confidence
                existing_preference.updated_at = datetime.utcnow()
                db.commit()

                logger.info(f"Updated category preference for user {user_id}: '{transaction_description}' -> '{preferred_category}'")
                return {
                    "success": True,
                    "message": "Category preference updated successfully",
                    "preference_id": existing_preference.id
                }
            else:
                # Create new preference
                preference = UserCategoryPreference(
                    user_id=user_id,
                    transaction_description=transaction_description.strip(),
                    preferred_category=preferred_category.strip(),
                    confidence=confidence
                )
                db.add(preference)
                db.commit()
                db.refresh(preference)

                logger.info(f"Added category preference for user {user_id}: '{transaction_description}' -> '{preferred_category}'")
                return {
                    "success": True,
                    "message": "Category preference added successfully",
                    "preference_id": preference.id
                }
        except Exception as e:
            db.rollback()
            logger.error(f"Error managing category preference: {str(e)}")
            return {
                "success": False,
                "message": f"Error managing category preference: {str(e)}"
            }
        finally:
            db.close()

    @staticmethod
    def get_user_preferences(user_id: str) -> List[Dict[str, Any]]:
        """Get all category preferences for a user"""
        db = get_db()
        try:
            preferences = db.query(UserCategoryPreference)\
                .filter(UserCategoryPreference.user_id == user_id)\
                .order_by(UserCategoryPreference.created_at.desc())\
                .all()

            return [
                {
                    "id": pref.id,
                    "transaction_description": pref.transaction_description,
                    "preferred_category": pref.preferred_category,
                    "confidence": pref.confidence,
                    "created_at": pref.created_at.isoformat() if pref.created_at else None,
                    "updated_at": pref.updated_at.isoformat() if pref.updated_at else None
                }
                for pref in preferences
            ]
        finally:
            db.close()

    @staticmethod
    def get_preferred_category(user_id: str, transaction_description: str) -> Optional[Dict[str, Any]]:
        """Get the preferred category for a transaction description, if any"""
        db = get_db()
        try:
            preference = db.query(UserCategoryPreference)\
                .filter(
                    UserCategoryPreference.user_id == user_id,
                    UserCategoryPreference.transaction_description == transaction_description.strip()
                )\
                .first()

            if preference:
                return {
                    "id": preference.id,
                    "transaction_description": preference.transaction_description,
                    "preferred_category": preference.preferred_category,
                    "confidence": preference.confidence
                }
            return None
        finally:
            db.close()

    @staticmethod
    def get_user_streaks(user_id: str) -> List[Dict[str, Any]]:
        """Get all streaks for a user"""
        db = get_db()
        try:
            streaks = db.query(UserStreak)\
                .filter(UserStreak.user_id == user_id)\
                .order_by(UserStreak.streak_type)\
                .all()

            return [
                {
                    "id": streak.id,
                    "streak_type": streak.streak_type,
                    "current_streak": streak.current_streak,
                    "longest_streak": streak.longest_streak,
                    "last_updated": streak.last_updated.isoformat() if streak.last_updated else None,
                    "streak_start_date": streak.streak_start_date.isoformat() if streak.streak_start_date else None,
                    "total_days_achieved": streak.total_days_achieved
                }
                for streak in streaks
            ]
        finally:
            db.close()

    @staticmethod
    def check_and_award_achievements(user_id: str) -> List[Dict[str, Any]]:
        """Check for and award achievements based on user progress"""
        db = get_db()
        try:
            # Get user
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return []

            # Get current streaks
            streaks = GamificationService.get_user_streaks(user_id)

            # Get net worth info
            net_worth_result = NetWorthService.get_net_worth(user_id)
            if not net_worth_result["success"]:
                net_worth_data = {"net_worth": 0}
            else:
                net_worth_data = net_worth_result

            # Get savings goals progress
            savings_goals = SavingsGoalService.get_user_savings_goals(user_id)

            achievements = []

            # Define achievement criteria
            achievement_definitions = [
                {
                    "id": "first_expense",
                    "name": "First Expense Logged",
                    "description": "Logged your first expense",
                    "criteria_type": "expense_count",
                    "threshold": 1,
                    "icon": "💰"
                },
                {
                    "id": "expense_week",
                    "name": "Weekly Tracker",
                    "description": "Logged expenses for 7 consecutive days",
                    "criteria_type": "streak_expense_logging",
                    "threshold": 7,
                    "icon": "📅"
                },
                {
                    "id": "expense_month",
                    "name": "Monthly Tracker",
                    "description": "Logged expenses for 30 consecutive days",
                    "criteria_type": "streak_expense_logging",
                    "threshold": 30,
                    "icon": "🗓️"
                },
                {
                    "id": "saver_beginner",
                    "name": "Beginner Saver",
                    "description": "Reached 25% of your first savings goal",
                    "criteria_type": "savings_progress",
                    "threshold": 25,
                    "icon": "🥉"
                },
                {
                    "id": "saver_intermediate",
                    "name": "Intermediate Saver",
                    "description": "Reached 50% of your savings goals",
                    "criteria_type": "savings_progress",
                    "threshold": 50,
                    "icon": "🥈"
                },
                {
                    "id": "saver_expert",
                    "name": "Expert Saver",
                    "description": "Reached 75% of your savings goals",
                    "criteria_type": "savings_progress",
                    "threshold": 75,
                    "icon": "🥇"
                },
                {
                    "id": "net_worth_positive",
                    "name": "Positive Net Worth",
                    "description": "Achieved positive net worth",
                    "criteria_type": "net_worth_positive",
                    "threshold": 0,
                    "icon": "💎"
                },
                {
                    "id": "budget_disciplined",
                    "name": "Budget Disciplined",
                    "description": "Stayed within budget for 3 consecutive months",
                    "criteria_type": "budget_adherence",
                    "threshold": 3,
                    "icon": "🛡️"
                }
            ]

            # Check each achievement
            for achievement in achievement_definitions:
                # Check if user already has this achievement
                # In a real implementation, we'd have a user_achievements table
                # For now, we'll simulate by checking if criteria are met

                earned = False
                progress = 0

                if achievement["criteria_type"] == "streak_expense_logging":
                    # Find expense logging streak
                    expense_streak = next((s for s in streaks if s["streak_type"] == "expense_logging"), None)
                    if expense_streak:
                        progress = expense_streak["current_streak"]
                        earned = progress >= achievement["threshold"]

                elif achievement["criteria_type"] == "savings_progress":
                    # Calculate average savings progress
                    if savings_goals:
                        total_progress = sum(
                            (goal["current_amount"] / goal["target_amount"] * 100)
                            for goal in savings_goals
                            if goal["target_amount"] > 0
                        )
                        avg_progress = total_progress / len(savings_goals) if savings_goals else 0
                        progress = avg_progress
                        earned = progress >= achievement["threshold"]

                elif achievement["criteria_type"] == "net_worth_positive":
                    progress = net_worth_data.get("net_worth", 0)
                    earned = progress >= achievement["threshold"]

                # For simplicity, we're not persisting achievements in this MVP
                # In a full implementation, we'd store which achievements a user has earned

                if earned:
                    achievements.append({
                        "id": achievement["id"],
                        "name": achievement["name"],
                        "description": achievement["description"],
                        "icon": achievement["icon"],
                        "earned": True,
                        "progress": progress,
                        "threshold": achievement["threshold"]
                    })

            logger.info(f"Checked achievements for user {user_id}, found {len(achievements)} earned")
            return achievements
        except Exception as e:
            logger.error(f"Error checking achievements: {str(e)}")
            return []
        finally:
            db.close()