"""
Command-line interface to simulate WhatsApp interactions for BudgetBot MVP.
This allows testing the core functionality without actual WhatsApp API integration.
"""

from datetime import datetime
from typing import Optional
from .models import User, TransactionMode
from .budget_manager import budget_manager
from .expense_parser import expense_parser

class BudgetBotCLI:
    """Simulates BudgetBot interactions via command line"""

    def __init__(self):
        self.current_user: Optional[User] = None
        print("🤖 BudgetBot CLI - WhatsApp Native Financial OS")
        print("=" * 50)

    def start(self):
        """Main interaction loop"""
        while True:
            if not self.current_user:
                self._show_welcome()
                user_input = input("\nYou: ").strip()
                self._handle_onboarding(user_input)
            else:
                self._show_prompt()
                user_input = input("\nYou: ").strip()
                if user_input.lower() in ['exit', 'quit', 'bye']:
                    print("\n👋 Thanks for using BudgetBot! Have a financially wise day!")
                    break
                self._process_message(user_input)

    def _show_welcome(self):
        """Show welcome message for new users"""
        print("\n👋 Hi! I'm BudgetBot, your WhatsApp-native financial assistant.")
        print("I'll help you track expenses, manage budgets, and stay on top of your money.")
        print("\nTo get started, tell me your name and phone number:")
        print("Example: 'My name is Priya and my number is 9876543210'")

    def _handle_onboarding(self, user_input: str):
        """Handle user onboarding flow"""
        # Simple name/phone extraction
        name_match = re.search(r'(?:name is|i\'m|i am|call me)\s+([a-zA-Z\s]+)', user_input, re.IGNORECASE)
        phone_match = re.search(r'(\d{10})', user_input)

        name = name_match.group(1).strip() if name_match else "User"
        phone = phone_match.group(1) if phone_match else "0000000000"

        # Create user
        self.current_user = budget_manager.create_user(phone=phone, name=name)
        print(f"\n✅ Great to meet you, {name}! I've created your account.")
        print(f"📱 Your phone: {phone}")
        print(f"🆔 Your user ID: {self.current_user.id[:8]}...")

        # Ask for income
        print("\n💰 To give you personalized budget insights, what's your monthly income?")
        print("(You can skip this for now by typing 'skip')")

    def _show_prompt(self):
        """Show command prompt with user context"""
        if self.current_user:
            print(f"\n💬 {self.current_user.name}:", end="")

    def _process_message(self, user_input: str):
        """Process incoming message and generate response"""
        user_input = user_input.strip()
        if not user_input:
            return

        # Handle special commands
        if user_input.lower() == 'help':
            self._show_help()
            return
        elif user_input.lower() == 'balance':
            self._show_balance()
            return
        elif user_input.lower() == 'commitments':
            self._show_commitments()
            return
        elif user_input.lower() == 'goals':
            self._show_savings_goals()
            return
        elif user_input.lower() == 'suggest budget':
            self._suggest_budget()
            return
        elif user_input.lower() == 'net worth':
            self._show_net_worth()
            return
        elif user_input.lower() == 'anomalies':
            self._show_anomalies()
            return
        elif user_input.lower() == 'streak':
            self._update_streak()
            return
        elif user_input.lower() == 'achievements':
            self._show_achievements()
            return
        elif user_input.lower().startswith('add pocket'):
            self._handle_add_pocket(user_input)
            return
        elif user_input.lower().startswith('add goal'):
            self._handle_add_goal(user_input)
            return
        elif user_input.lower().startswith('split'):
            self._handle_split_command(user_input)
            return
        elif user_input.lower().startswith('add sip') or user_input.lower().startswith('add emi') or user_input.lower().startswith('add subscription'):
            self._handle_add_commitment(user_input)
            return
        elif user_input.lower() == 'alerts':
            self._show_alerts()
            return
        elif user_input.lower() == 'upcoming':
            self._show_upcoming_deductions()
            return

        # Try to parse as expense
        try:
            transaction = budget_manager.log_expense_from_text(
                user_id=self.current_user.id,
                text=user_input,
                mode="personal"
            )
            self._respond_to_expense(transaction)
        except Exception as e:
            print(f"\n🤖 Sorry, I didn't understand that. Try saying something like:")
            print("   'lunch 250' or 'uber 450' or 'add pocket Food 5000'")
            print(f"   Error: {str(e)}")

    def _respond_to_expense(self, transaction: Transaction):
        """Generate response after logging an expense"""
        # Get updated budget snapshot
        snapshot = budget_manager.get_budget_snapshot(self.current_user.id)

        # Find which pocket was updated (simplified)
        category_pocket_map = {
            'food': ['Food', 'Groceries', 'Dining'],
            'transport': ['Transport', 'Fuel', 'Commute'],
            'shopping': ['Shopping', 'Lifestyle'],
            'entertainment': ['Entertainment', 'Fun'],
            'utilities': ['Utilities', 'Bills'],
            'health': ['Health', 'Medical'],
            'education': ['Education', 'Learning']
        }

        updated_pocket_name = "Unknown"
        for pocket_name, keywords in category_pocket_map.items():
            if any(keyword in transaction.category.lower() for keyword in keywords):
                # Find matching pocket
                for pocket in self.current_user.pockets.values():
                    if pocket.name in keywords or any(kw in pocket.name.lower() for kw in keywords):
                        updated_pocket_name = pocket.name
                        break
                break

        if updated_pocket_name == "Unknown":
            # Look for any pocket
            if self.current_user.pockets:
                updated_pocket_name = list(self.current_user.pockets.values())[0].name
            else:
                updated_pocket_name = "General"

        pocket = None
        for p in self.current_user.pockets.values():
            if p.name == updated_pocket_name:
                pocket = p
                break

        # Format response
        response = f"✅ ₹{transaction.amount:.0f} → {transaction.category}"
        if transaction.merchant and transaction.merchant != "Unknown":
            response += f" ({transaction.merchant})"

        if pocket:
            remaining = pocket.monthly_limit - pocket.spent_mtd
            response += f"\n📊 {updated_pocket_name} pocket: ₹{remaining:.0f} left this month"

            # Add alert if threshold crossed
            percentage_used = (pocket.spent_mtd / pocket.monthly_limit) * 100 if pocket.monthly_limit > 0 else 0
            if percentage_used >= 100:
                response += f"\n⚠️  You've exceeded your {updated_pocket_name} budget!"
            elif percentage_used >= 90:
                response += f"\n🔔 You've used 90% of your {updated_pocket_name} budget."

        print(f"\n🤖 {response}")

        # Show any budget alerts
        alerts = budget_manager.check_budget_alerts(self.current_user.id)
        for alert in alerts:
            if alert["severity"] in ["high", "medium"]:
                print(f"\n{alert['message']}")

    def _show_help(self):
        """Show available commands"""
        help_text = """
📋 BudgetBot Commands:
=====================
Expense Logging:
  • 'lunch 250' - Log an expense
  • 'uber 450' - Log transport expense
  • 'sabzi 340' - Log groceries

Budget Management:
  • 'add pocket Food 5000' - Create a budget pocket
  • 'add pocket Transport 3000'

Commitments:
  • 'add sip HDFC Flexi Cap 5000 on 10' - Add monthly SIP
  • 'add emi home loan 25000 on 15' - Add monthly EMI
  • 'add subscription netflix 649 monthly' - Add subscription

Savings Goals:
  • 'add goal PocketName GoalName 100000' - Create savings goal (e.g., 'add goal Emergency Fund 50000')
  • 'goals' - Show your savings goals

Bill Splitting:
  • 'split GroupName Description Amount Method' - Create group split
    Methods: equal, percentage, exact
    Example: 'split Roommates Groceries 3000 equal'

Savings & Goals:
  • 'suggest budget' - Get AI-powered budget suggestions
  • 'net worth' - Show your net worth
  • 'anomalies' - Check for unusual spending
  • 'streak' - Update your logging streak
  • 'achievements' - Check your achievements

Information:
  • 'balance' - Show current budget status
  • 'commitments' - Show your recurring commitments
  • 'alerts' - Show budget threshold alerts
  • 'upcoming' - Show upcoming deductions
  • 'help' - Show this help message
  • 'exit' - Quit BudgetBot

Examples:
  • 'My name is Priya and my number is 9876543210'
  • 'lunch 250'
  • 'add pocket Food 5000'
  • 'add sip HDFC Index Fund 3000 on 5'
  • 'add goal Emergency Fund 50000'
  • 'suggest budget'
  • 'split Roommates Groceries 3000 equal'
  • 'net worth'
  • 'balance'
        """
        print(help_text)

    def _show_balance(self):
        """Show current budget snapshot"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        snapshot = budget_manager.get_budget_snapshot(self.current_user.id)

        print(f"\n📊 Budget Snapshot for {self.current_user.name}")
        print("=" * 40)
        print(f"💰 Monthly Income: ₹{snapshot.total_income:,.0f}")
        print(f"🔒 Committed Outflows: ₹{snapshot.total_committed:,.0f}")
        print(f"💵 Available to Spend: ₹{snapshot.available_to_spend:,.0f}")
        print(f"💸 Actually Spent: ₹{snapshot.total_spent:,.0f}")

        if snapshot.pocket_details:
            print("\n📦 Budget Pockets:")
            for pocket_name, details in snapshot.pocket_details.items():
                budget = details["budget"]
                spent = details["spent"]
                remaining = details["remaining"]
                percent = (spent / budget * 100) if budget > 0 else 0
                status = "✅" if percent < 70 else "⚠️" if percent < 90 else "🔴"
                print(f"  {status} {pocket_name}: ₹{spent:.0f}/{budget:.0f} ({percent:.0f}%) - ₹{remaining:.0f} left")

    def _show_commitments(self):
        """Show user's recurring commitments"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        total, commitments = budget_manager.get_committed_spending(self.current_user.id)

        print(f"\n🔒 Your Commitments for {self.current_user.name}")
        print("=" * 40)
        print(f"💰 Total Monthly Commitment: ₹{total:.0f}")

        if commitments:
            print("\n📋 Active Commitments:")
            for commitment in commitments:
                freq_text = {
                    Frequency.MONTHLY: "monthly",
                    Frequency.QUARTERLY: "quarterly",
                    Frequency.YEARLY: "yearly"
                }.get(commitment.frequency, "unknown")
                print(f"  • {commitment.name}: ₹{commitment.amount:.0f} {freq_text} (next: {commitment.next_date.strftime('%d %b')})")
        else:
            print("\n📝 No commitments added yet.")

    def _handle_add_pocket(self, user_input: str):
        """Handle add pocket command"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        # Parse: "add pocket Food 5000"
        parts = user_input.split()
        if len(parts) >= 4:
            pocket_name = parts[2]
            try:
                amount = float(parts[3])
                pocket = budget_manager.add_pocket(
                    user_id=self.current_user.id,
                    name=pocket_name,
                    monthly_limit=amount
                )
                print(f"\n✅ Created pocket '{pocket_name}' with budget ₹{amount:.0f}/month")
            except ValueError:
                print("\n🤖 Please specify a valid amount. Example: 'add pocket Food 5000'")
        else:
            print("\n🤖 Please specify pocket name and amount. Example: 'add pocket Food 5000'")

    def _handle_add_commitment(self, user_input: str):
        """Handle add commitment command"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        # Parse commitment type
        user_input_lower = user_input.lower()
        if user_input_lower.startswith('add sip'):
            commitment_type = 'sip'
            # Extract amount and fund name
            match = re.search(r'add sip\s+(?:([\w\s]+?)\s+)?(\d+(?:\.\d+)?)\s*(?:on\s+(\d+))?', user_input, re.IGNORECASE)
            if match:
                fund_name = match.group(1) or "SIP Investment"
                amount = float(match.group(2))
                day = int(match.group(3)) if match.group(3) else 5  # Default to 5th
                name = f"{fund_name} SIP"
            else:
                print("\n🤖 Please specify amount. Example: 'add sip HDFC Flexi Cap 3000 on 10'")
                return
        elif user_input_lower.startswith('add emi'):
            commitment_type = 'emi'
            match = re.search(r'add emi\s+(?:([\w\s]+?)\s+)?(\d+(?:\.\d+)?)\s*(?:on\s+(\d+))?', user_input, re.IGNORECASE)
            if match:
                loan_name = match.group(1) or "Loan"
                amount = float(match.group(2))
                day = int(match.group(3)) if match.group(3) else 15  # Default to 15th
                name = f"{loan_name} EMI"
            else:
                print("\n🤖 Please specify amount. Example: 'add emi home loan 25000 on 15'")
                return
        elif user_input_lower.startswith('add subscription'):
            commitment_type = 'subscription'
            match = re.search(r'add subscription\s+(?:([\w\s]+?)\s+)?(\d+(?:\.\d+)?)\s*(monthly|quarterly|yearly)?', user_input, re.IGNORECASE)
            if match:
                service_name = match.group(1) or "Subscription"
                amount = float(match.group(2))
                freq_str = match.group(3) or "monthly"
                name = f"{service_name} Subscription"
                frequency = freq_str
            else:
                print("\n🤖 Please specify amount. Example: 'add subscription netflix 649 monthly'")
                return
        else:
            print("\n🤖 Unknown commitment type. Use: add sip, add emi, or add subscription")
            return

        # Add the commitment
        try:
            if 'frequency' in locals():
                commitment = budget_manager.add_commitment(
                    user_id=self.current_user.id,
                    name=name,
                    amount=amount,
                    commitment_type=commitment_type,
                    frequency=frequency,
                    day_of_month=int(day) if 'day' in locals() else 1
                )
            else:
                commitment = budget_manager.add_commitment(
                    user_id=self.current_user.id,
                    name=name,
                    amount=amount,
                    commitment_type=commitment_type
                )
            print(f"\n✅ Added {commitment.name}: ₹{commitment.amount:.0f} {commitment.frequency.value}")
            if commitment.next_date:
                print(f"   Next deduction: {commitment.next_date.strftime('%d %b %Y')}")
        except Exception as e:
            print(f"\n🤖 Error adding commitment: {str(e)}")

    def _show_alerts(self):
        """Show budget threshold alerts"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        alerts = budget_manager.check_budget_alerts(self.current_user.id)
        if alerts:
            print(f"\n🚨 Budget Alerts for {self.current_user.name}")
            print("=" * 40)
            for alert in alerts:
                icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(alert["severity"], "⚪")
                print(f"{icon} {alert['message']}")
        else:
            print(f"\n✅ No budget alerts for {self.current_user.name}. You're on track!")

    def _show_upcoming_deductions(self):
        """Show upcoming deductions"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        upcoming = budget_manager.get_upcoming_deductions(days_ahead=7)
        user_upcomings = [u for u in upcoming if u["user_id"] == self.current_user.id]

        if user_upcomings:
            print(f"\n📅 Upcoming Deductions for {self.current_user.name} (next 7 days)")
            print("=" * 50)
            for item in user_upcomings:
                urgency = "🔴" if item["days_until"] <= 3 else "🟠" if item["days_until"] <= 5 else "🟡"
                print(f"{urgency} {item['commitment_name']}: ₹{item['amount']:.0f} on {item['date']} ({item['days_until']} days)")
        else:
            print(f"\n✅ No upcoming deductions in the next 7 days for {self.current_user.name}")

    def _show_savings_goals(self):
        """Show user's savings goals"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        # This would normally call the API service, but for CLI we'll simulate
        # by accessing the database directly through services
        from src.services import SavingsGoalService
        result = SavingsGoalService.get_user_savings_goals(self.current_user.id)

        if not result:
            print(f"\n🎯 No savings goals set for {self.current_user.name}")
            print("💡 Use 'add goal PocketName GoalName Amount' to create one")
            return

        print(f"\n🎯 Savings Goals for {self.current_user.name}")
        print("=" * 40)
        for goal in result:
            progress = (goal["current_amount"] / goal["target_amount"] * 100) if goal["target_amount"] > 0 else 0
            status = "🟢" if progress >= 100 else "🟡" if progress >= 50 else "🔴"
            target_date = goal["target_date"][:10] if goal["target_date"] else "No target date"
            print(f"{status} {goal['name']}: ₹{goal['current_amount']:.0f}/₹{goal['target_amount']:.0f} ({progress:.0f}%)")
            print(f"   Target date: {target_date}")
            if goal["monthly_contribution"]:
                print(f"   Suggested monthly: ₹{goal['monthly_contribution']:.0f}")
            print()

    def _handle_add_goal(self, user_input: str):
        """Handle add goal command"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        # Parse: "add goal Emergency Fund 50000"
        parts = user_input.split()
        if len(parts) >= 4:
            # Find the pocket (first part after 'add goal')
            # Assume pocket name might have spaces, so we need to be smart
            # For simplicity, we'll look for a pocket that matches the beginning
            pocket_name_parts = []
            amount_index = -1

            # Find where the number starts
            for i, part in enumerate(parts[2:], 2):  # Skip 'add goal'
                try:
                    float(part)
                    amount_index = i
                    break
                except ValueError:
                    pocket_name_parts.append(part)

            if amount_index == -1:
                print("\n🤖 Please specify an amount. Example: 'add goal Emergency Fund 50000'")
                return

            pocket_name = " ".join(pocket_name_parts)
            try:
                target_amount = float(parts[amount_index])

                # Optional target date (next part if it's a date)
                target_date = None
                if amount_index + 1 < len(parts):
                    try:
                        target_date = datetime.fromisoformat(parts[amount_index + 1])
                    except ValueError:
                        pass  # Not a date, ignore

                # Find the pocket ID
                from src.services import PocketService
                pockets = PocketService.get_user_pockets(self.current_user.id)
                pocket_id = None
                for pocket in pockets:
                    if pocket["name"].lower() == pocket_name.lower():
                        pocket_id = pocket["id"]
                        break

                if not pocket_id:
                    print(f"\n🤖 Pocket '{pocket_name}' not found. Please create it first with 'add pocket {pocket_name} [amount]'")
                    return

                # Create the goal
                from src.services import SavingsGoalService
                result = SavingsGoalService.create_savings_goal(
                    self.current_user.id, pocket_id, pocket_name, target_amount, target_date
                )

                if result["success"]:
                    print(f"\n✅ Created savings goal '{result['goal']['name']}' with target ₹{result['goal']['target_amount']:.0f}")
                    if result["goal"]["monthly_contribution"]:
                        print(f"💡 Suggested monthly contribution: ₹{result['goal']['monthly_contribution']:.0f}")
                else:
                    print(f"\n🤖 {result['message']}")

            except ValueError:
                print("\n🤖 Please specify a valid amount. Example: 'add goal Emergency Fund 50000'")
        else:
            print("\n🤖 Please specify pocket name, goal name, and amount. Example: 'add goal Emergency Fund 50000'")

    def _suggest_budget(self):
        """Get AI-powered budget suggestions"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        from src.services import BudgetIntelligenceService
        # Generate new suggestions
        BudgetIntelligenceService.generate_budget_suggestions(self.current_user.id)
        # Then get them
        result = BudgetIntelligenceService.get_budget_suggestions(self.current_user.id)

        if not result:
            print(f"\n💡 No budget suggestions available for {self.current_user.name}")
            print("💡 Keep logging expenses for a few days to get personalized suggestions")
            return

        print(f"\n💡 Budget Suggestions for {self.current_user.name}")
        print("=" * 50)
        for suggestion in result:
            confidence_pct = suggestion["confidence"] * 100
            confidence_icon = "🟢" if confidence_pct >= 70 else "🟡" if confidence_pct >= 40 else "🔴"
            print(f"{confidence_icon} For {suggestion['pocket_name']}:")
            print(f"   💰 Suggested budget: ₹{suggestion['suggested_amount']:.0f}/month")
            print(f"   📝 {suggestion['reasoning']}")
            print(f"   🎯 Confidence: {confidence_pct:.0f}%")
            if suggestion.get("matches_existing_pocket"):
                print(f"   ✅ Matches your existing '{suggestion['pocket_name']}' pocket")
            else:
                print(f"   ➕ Consider creating a '{suggestion['pocket_name']}' pocket")
            print()

    def _show_net_worth(self):
        """Show user's net worth"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        from src.services import NetWorthService
        result = NetWorthService.get_net_worth(self.current_user.id)

        if not result["success"]:
            print(f"\n🤖 {result['message']}")
            return

        print(f"\n💰 Net Worth for {self.current_user.name}")
        print("=" * 40)
        print(f"🏦 Total Assets: ₹{result['total_assets']:,.0f}")
        print(f"💳 Total Liabilities: ₹{result['total_liabilities']:,.0f}")

        if result["net_worth"] >= 0:
            print(f"💰 Net Worth: 🟢 ₹{result['net_worth']:,.0f}")
        else:
            print(f"💰 Net Worth: 🔴 ₹{result['net_worth']:,.0f}")

        print(f"\n📊 Asset Breakdown:")
        for asset_type, assets in result["assets_by_type"].items():
            total = sum(asset["value"] for asset in assets)
            print(f"   {asset_type.title()}: ₹{total:,.0f} ({len(assets)} items)")

        print(f"\n📊 Liability Breakdown:")
        for liability_type, liabilities in result["liabilities_by_type"].items():
            total = sum(liability["amount_owed"] for liability in liabilities)
            print(f"   {liability_type.title()}: ₹{total:,.0f} ({len(liabilities)} items)")

    def _show_anomalies(self):
        """Show unusual spending anomalies"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        from src.services import AnomalyDetectionService
        # Detect new anomalies
        AnomalyDetectionService.detect_anomalies(self.current_user.id)
        # Get current ones
        result = AnomalyDetectionService.get_user_anomalies(self.current_user.id)

        if not result:
            print(f"\n✅ No unusual spending detected for {self.current_user.name}")
            print("💡 Your spending patterns look normal!")
            return

        print(f"\n🚨 Unusual Spending Alerts for {self.current_user.name}")
        print("=" * 50)
        for alert in result:
            severity_icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(alert["severity"], "⚪")
            print(f"{severity_icon} {alert['description']}")
            if alert["z_score"]:
                print(f"   📊 Z-score: {alert['z_score']:.1f} standard deviations")
            if alert["amount"]:
                print(f"   💰 Amount: ₹{alert['amount']:.0f}")
            print(f"   🏷️  Category: {alert['category']}")
            print()

    def _handle_split_command(self, user_input: str):
        """Handle split command for bill splitting"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        # Parse: "split Roommates Groceries 3000 equal"
        parts = user_input.split()
        if len(parts) < 5:
            print("\n🤖 Please specify: split GroupName Description Amount Method [details]")
            print("   Methods: equal, percentage, exact")
            print("   Example: 'split Roommates Groceries 3000 equal'")
            return

        group_name = parts[1]
        # Find where the amount starts
        amount_index = -1
        for i, part in enumerate(parts[2:], 2):  # Start from index 2
            try:
                float(part)
                amount_index = i
                break
            except ValueError:
                continue

        if amount_index == -1:
            print("\n🤖 Please specify an amount. Example: 'split Roommates Groceries 3000 equal'")
            return

        # Description is everything between group name and amount
        description_parts = parts[2:amount_index]
        description = " ".join(description_parts) if description_parts else "Group expense"

        try:
            total_amount = float(parts[amount_index])
            if total_amount <= 0:
                print("\n🤖 Amount must be positive")
                return
        except ValueError:
            print("\n🤖 Please specify a valid amount")
            return

        # Method is after amount
        if amount_index + 1 >= len(parts):
            print("\n🤖 Please specify split method (equal, percentage, exact)")
            return

        split_method = parts[amount_index + 1].lower()
        valid_methods = ["equal", "percentage", "exact"]
        if split_method not in valid_methods:
            print(f"\n🤖 Invalid method. Use one of: {', '.join(valid_methods)}")
            return

        # For now, we'll handle simple equal split
        # In a full implementation, we'd parse additional parameters for percentage/exact
        if split_method == "equal":
            # Ask for number of people or assume 2 for simplicity
            # For MVP, we'll just create a basic split
            from src.services import SplitService
            result = SplitService.create_group_split(
                self.current_user.id,
                group_name,
                description,
                total_amount,
                split_method
            )

            if result["success"]:
                print(f"\n✅ Created group split '{result['group_split']['group_name']}' for ₹{result['group_split']['total_amount']:.0f}")
                print(f"👥 Split method: {result['group_split']['split_method']}")
                print(f"💡 Use 'owe' command to see what you owe/are owed")
            else:
                print(f"\n🤖 {result['message']}")
        else:
            print(f"\n🤖 {split_method.title()} splits coming soon! For now, use 'equal' method.")

    def _update_streak(self):
        """Update user's expense logging streak"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        from src.services import GamificationService
        result = GamificationService.update_streak(self.current_user.id, "expense_logging")

        if result["success"]:
            streak_msg = f"🔥 {result['current_streak']} day streak!"
            if result['current_streak'] >= result['longest_streak']:
                streak_msg += " New personal best!"
            print(f"\n{streak_msg}")
            if result['current_streak'] in [7, 30, 100]:
                milestone_msgs = {7: "Week milestone!", 30: "Month milestone!", 100: "Century milestone!"}
                print(f"🎉 {milestone_msgs[result['current_streak']]}")
        else:
            print(f"\n🤖 {result['message']}")

    def _show_achievements(self):
        """Show user's achievements"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        from src.services import GamificationService
        result = GamificationService.check_and_award_achievements(self.current_user.id)

        if not result:
            print(f"\n🏆 No achievements earned yet for {self.current_user.name}")
            print("💡 Keep using BudgetBot to unlock achievements!")
            return

        print(f"\n🏆 Achievements for {self.current_user.name}")
        print("=" * 40)
        for achievement in result:
            print(f"{achievement['icon']} {achievement['name']}")
            print(f"   {achievement['description']}")
            if achievement.get('progress') is not None and achievement.get('threshold') is not None:
                print(f"   Progress: {achievement['progress']:.0f}/{achievement['threshold']}")
            print()

# Import regex here to avoid issues
import re
from datetime import datetime

if __name__ == "__main__":
    cli = BudgetBotCLI()
    cli.start()