"""
Command-line interface to simulate WhatsApp interactions for BudgetBot MVP.
This allows testing the core functionality without actual WhatsApp API integration.
"""

import re
from datetime import datetime
from typing import Optional
from .models import User, TransactionMode
from .budget_manager import budget_manager
from .expense_parser import expense_parser

class BudgetBotCLI:
    """Simulates BudgetBot interactions via command line"""

    def __init__(self):
        self.current_user: Optional[User] = None
        self._onboarding_stage: Optional[str] = None  # Tracks onboarding progress: None, 'name', 'phone', 'income'
        self._onboarding_data: dict = {}  # Temporarily stores collected data during onboarding
        self._conversation_history: list = []  # Lightweight conversation context
        self._session_start = datetime.now()
        self._expenses_logged_session = 0  # Track expenses logged in this session
        print("👋 Hey there! I'm BudgetBot, your friendly financial helper.")
        print("I'm here to make managing your money simple and stress-free. 😊")
        print("\nTo get started, what should I call you?")

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
        print("\n👋 Hey there! I'm BudgetBot, your friendly financial helper.")
        print("I'm here to make managing your money simple and stress-free.")
        print("\nTo get started, what should I call you?")

    def _handle_onboarding(self, user_input: str):
        """Handle user onboarding flow"""
        # If we don't have a name yet, try to extract it
        if not hasattr(self, '_onboarding_name'):
            name_match = re.search(r'(?:name is|i\'m|i am|call me)\s+([a-zA-Z\s]+)', user_input, re.IGNORECASE)
            if name_match:
                self._onboarding_name = name_match.group(1).strip()
                print(f"\n👋 Nice to meet you, {self._onboarding_name}! 😊")
                print("What's your best contact number? (WhatsApp works best)")
                return
            else:
                # If no name pattern matched, use the input as name or ask again
                self._onboarding_name = user_input.strip() or "Friend"
                print(f"\n👋 Great to meet you, {self._onboarding_name}!")
                print("What's your best contact number? (WhatsApp works best)")
                return

        # If we have name but not phone yet, extract phone
        if not hasattr(self, '_onboarding_phone'):
            phone_match = re.search(r'(\d{10})', user_input)
            if phone_match:
                self._onboarding_phone = phone_match.group(1)
                print(f"\n📱 Got it! Your number ending in {self._onboarding_phone[-4:]} is saved.")
                print("Almost there! To give you personalized advice, what's your monthly income?")
                print("(You can type 'skip' if you'd rather not share this yet)")
                return
            else:
                # Try to extract any number sequence that looks like a phone
                numbers = re.findall(r'\d+', user_input)
                if numbers:
                    # Take the longest number sequence that could be a phone
                    potential_phones = [n for n in numbers if len(n) >= 10 and len(n) <= 15]
                    if potential_phones:
                        self._onboarding_phone = max(potential_phones, key=len)
                        print(f"\n📱 Got it! Your number ending in {self._onboarding_phone[-4:]} is saved.")
                        print("Almost there! To give you personalized advice, what's your monthly income?")
                        print("(You can type 'skip' if you'd rather not share this yet)")
                        return

                print("Hmm, I don't see a valid phone number there. Could you share your 10-digit phone number?")
                return

        # We have both name and phone, now handle income
        if user_input.lower().strip() == 'skip':
            income = 0.0
            print("\n👍 No worries! We'll skip income for now. You can always add it later.")
        else:
            # Try to extract income amount
            income_match = re.search(r'[\d,]+(?:\.\d{1,2})?', user_input.replace(',', ''))
            if income_match:
                try:
                    income = float(income_match.group())
                    if income < 0:
                        income = 0.0
                        print("\n🤔 Income can't be negative, so I'll set it to zero for now. You can update it later!")
                    elif income > 10000000:  # 1 crore - reasonable upper bound
                        print("\n🤔 That seems quite high! Did you mean to enter a different amount?")
                        print("Please share your monthly income (or type 'skip' to skip):")
                        return
                    else:
                        print(f"\n💰 Got it! I'll use ₹{income:,.0f} as your monthly income for personalized insights.")
                except ValueError:
                    income = 0.0
                    print("\n🤔 I didn't catch that amount. No worries - we'll skip income for now. You can add it later!")
            else:
                income = 0.0
                print("\n🤔 I didn't catch that amount. No worries - we'll skip income for now. You can add it later!")

        # Create user with collected information
        self.current_user = budget_manager.create_user(phone=self._onboarding_phone, name=self._onboarding_name)

        # Clean up onboarding attributes
        if hasattr(self, '_onboarding_name'):
            delattr(self, '_onboarding_name')
        if hasattr(self, '_onboarding_phone'):
            delattr(self, '_onboarding_phone')

        # Warm welcome completion with contextual touch
        print(f"\n🎉 Welcome aboard, {self.current_user.name}! 🎉")
        print("You're all set up and ready to take control of your money.")
        print("💡 To get started, try telling me about your first expense:")
        print("   Something like 'lunch 250' or 'coffee 120' or 'uber 150'")
        print("   Just tell me what you spent and on what - I'll handle the rest!")
        print("\n😊 Remember, I'm here to help, not judge. Every step counts!")

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
            self._add_to_conversation_history(user_input, 'help')
            return
        elif user_input.lower() == 'balance':
            self._show_balance()
            self._add_to_conversation_history(user_input, 'balance')
            return
        elif user_input.lower() == 'commitments':
            self._show_commitments()
            self._add_to_conversation_history(user_input, 'commitments')
            return
        elif user_input.lower() == 'goals':
            self._show_savings_goals()
            self._add_to_conversation_history(user_input, 'goals')
            return
        elif user_input.lower() == 'suggest budget':
            self._suggest_budget()
            self._add_to_conversation_history(user_input, 'suggest_budget')
            return
        elif user_input.lower() == 'net worth':
            self._show_net_worth()
            self._add_to_conversation_history(user_input, 'net_worth')
            return
        elif user_input.lower() == 'anomalies':
            self._show_anomalies()
            self._add_to_conversation_history(user_input, 'anomalies')
            return
        elif user_input.lower() == 'streak':
            self._update_streak()
            self._add_to_conversation_history(user_input, 'streak')
            return
        elif user_input.lower() == 'achievements':
            self._show_achievements()
            self._add_to_conversation_history(user_input, 'achievements')
            return
        elif user_input.lower() == 'apply rollover':
            self._handle_apply_rollover(user_input)
            self._add_to_conversation_history(user_input, 'apply_rollover')
            return
        elif user_input.lower().startswith('add pocket'):
            self._handle_add_pocket(user_input)
            self._add_to_conversation_history(user_input, 'add_pocket')
            return
        elif user_input.lower().startswith('add goal'):
            self._handle_add_goal(user_input)
            self._add_to_conversation_history(user_input, 'add_goal')
            return
        elif user_input.lower().startswith('split'):
            self._handle_split_command(user_input)
            self._add_to_conversation_history(user_input, 'split')
            return
        elif user_input.lower().startswith('fix '):
            self._handle_fix_transaction(user_input)
            self._add_to_conversation_history(user_input, 'fix_transaction')
            return
        elif user_input.lower().startswith('remove '):
            self._handle_remove_transaction(user_input)
            self._add_to_conversation_history(user_input, 'remove_transaction')
            return
        elif user_input.lower().startswith('rollover '):
            self._handle_rollover_command(user_input)
            self._add_to_conversation_history(user_input, 'rollover_command')
            return
        elif user_input.lower().startswith('add sip') or user_input.lower().startswith('add emi') or user_input.lower().startswith('add subscription'):
            self._handle_add_commitment(user_input)
            self._add_to_conversation_history(user_input, 'add_commitment')
            return
        elif user_input.lower() == 'alerts':
            self._show_alerts()
            self._add_to_conversation_history(user_input, 'alerts')
            return
        elif user_input.lower() == 'upcoming':
            self._show_upcoming_deductions()
            self._add_to_conversation_history(user_input, 'upcoming_deductions')
            return

        # Try to parse as expense
        try:
            transaction = budget_manager.log_expense_from_text(
                user_id=self.current_user.id,
                text=user_input,
                mode="personal"
            )
            self._respond_to_expense(transaction)
            self._add_to_conversation_history(user_input, 'expense_logged')
        except Exception as e:
            # More helpful, intent-aware error response
            user_lower = user_input.lower().strip()

            # Try to guess what the user might have wanted to do
            suggested_actions = []

            # Check for expense-like patterns
            if any(word in user_lower for word in ['spent', 'paid', 'bought', 'cost', 'expense']):
                suggested_actions.append("It looks like you might want to log an expense. Try something like 'lunch 250' or 'uber 450'")

            # Check for budget/pocket patterns
            if any(word in user_lower for word in ['budget', 'pocket', 'limit']):
                suggested_actions.append("It seems like you want to manage your budget. Try 'add pocket Food 5000' or 'balance'")

            # Check for goal patterns
            if any(word in user_lower for word in ['goal', 'save', 'saving']):
                suggested_actions.append("Looks like you want to set a savings goal. Try 'add goal Emergency Fund 100000'")

            # Check for split patterns
            if any(word in user_lower for word in ['split', 'share', 'owe']):
                suggested_actions.append("Are you trying to split a bill? Try 'split Roommates Groceries 3000 equal'")

            # Check for suggestion patterns
            if any(word in user_lower for word in ['suggest', 'advice', 'recommend']):
                suggested_actions.append("Want budget suggestions? Try 'suggest budget'")

            # Check for net worth patterns
            if any(word in user_lower for word in ['worth', 'asset', 'liability', 'net']):
                suggested_actions.append("Checking your net worth? Try 'net worth'")

            # Check for anomaly patterns
            if any(word in user_lower for word in ['unusual', 'strange', 'odd', 'anomaly']):
                suggested_actions.append("Looking for unusual spending? Try 'anomalies'")

            # Check for streak/achievement patterns
            if any(word in user_lower for word in ['streak', 'achievement', 'milestone']):
                suggested_actions.append("Want to check your progress? Try 'streak' or 'achievements'")

            # If we have suggestions, show them
            if suggested_actions:
                print(f"\n🤖 Hmm, I'm not sure I understood that. ")
                print("Here's what I think you might have meant:")
                for i, suggestion in enumerate(suggested_actions[:2], 1):  # Show max 2 suggestions
                    print(f"   {i}. {suggestion}")
                print("\n💡 Or just tell me what you'd like to do in your own words!")
            else:
                # Generic helpful response
                print(f"\n🤖 I'm not quite sure I got that. No worries!\n"
                      f"Let me help you out:\n"
                      f"   💰 To log an expense: 'lunch 250' or 'uber 450'\n"
                      f"   🏦 To manage budgets: 'add pocket Food 5000' or 'balance'\n"
                      f"   🎯 To set goals: 'add goal Emergency Fund 100000'\n"
                      f"   🔪 To split bills: 'split Roommates Groceries 3000 equal'\n"
                      f"   💡 For advice: 'suggest budget'\n"
                      f"   📊 To check status: 'net worth' or 'anomalies'\n"
                      f"Just try one of these, or tell me what you had in mind!")

            self._add_to_conversation_history(user_input, 'unrecognized')

    def _respond_to_expense(self, transaction: Transaction):
        """Generate response after logging an expense - more human/comfortable version"""
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

        # More natural, varied responses
        import random

        # Base transaction description
        if transaction.merchant and transaction.merchant != "Unknown":
            base_desc = f"Logged ₹{transaction.amount:.0f} for {transaction.category} at {transaction.merchant}"
        else:
            base_desc = f"Logged ₹{transaction.amount:.0f} for {transaction.category}"

        # Varied response starters
        starters = [
            "Got it!",
            "Nice!",
            "Perfect!",
            "Alright!",
            "Cool!",
            "Thanks!",
            "Awesome!",
            "Great!",
            "Thanks for sharing!",
            "Noted!"
        ]

        starter = random.choice(starters)

        # Build the response
        response_parts = [f"{starter} {base_desc}."]

        if pocket:
            remaining = pocket.monthly_limit - pocket.spent_mtd
            percentage_used = (pocket.spent_mtd / pocket.monthly_limit) * 100 if pocket.monthly_limit > 0 else 0

            # Add pocket status in a more natural way
            if percentage_used < 50:
                response_parts.append(f"You've got ₹{remaining:.0f} left in your {updated_pocket_name} pocket this month.")
            elif percentage_used < 70:
                response_parts.append(f"You've used about {int(percentage_used)}% of your {updated_pocket_name} pocket - you're doing well!")
            elif percentage_used < 90:
                response_parts.append(f"You've used {int(percentage_used)}% of your {updated_pocket_name} pocket. You've got ₹{remaining:.0f} left.")
            else:
                # High usage but not yet alert threshold
                response_parts.append(f"Heads up: you've used {int(percentage_used)}% of your {updated_pocket_name} pocket. Only ₹{remaining:.0f} left for the month.")

            # Add occasional insights based on spending (lightweight, not computational heavy)
            # Just simple observational comments to feel more human
            if transaction.category.lower() in ['food', 'dining', 'groceries']:
                food_insights = [
                    "Hope you enjoyed your meal!",
                    "Food is such an important part of wellbeing - hope it was satisfying!",
                    "Nice to see you investing in good food!",
                    "Food expenses are important - tracking them helps you stay mindful!",
                    "Remember to enjoy your meals mindfully!"
                ]
                # Occasionally add a food-related insight (20% chance)
                if random.random() < 0.2:
                    response_parts.append(random.choice(food_insights))
            elif transaction.category.lower() in ['transport', 'fuel', 'commute']:
                transport_insights = [
                    "Hope your commute was smooth!",
                    "Getting around efficiently saves both time and money!",
                    "Transport costs can really add up - good you're tracking them!",
                    "Consider combining trips when possible to save on fuel!",
                    "Every kilometer tracked helps you understand your mobility patterns!"
                ]
                if random.random() < 0.2:
                    response_parts.append(random.choice(transport_insights))
        else:
            # No specific pocket found
            response_parts.append(f"This expense has been recorded. You can create a specific pocket for {transaction.category} if you'd like to track it separately.")

        # Add occasional general helpful tips (10% chance)
        if random.random() < 0.1:
            tips = [
                "💡 Tip: Try reviewing your expenses weekly to spot patterns!",
                "💡 Tip: Small consistent savings add up over time!",
                "💡 Tip: Tracking helps you make intentional choices about your money!",
                "💡 Tip: Financial awareness is the first step to financial freedom!",
                "💡 Tip: You're building great money habits - keep it up!"
            ]
            response_parts.append(random.choice(tips))

        # Add subtle contextual touch based on session
        self._expenses_logged_session += 1
        if self._expenses_logged_session == 1:
            # First expense of the session
            response_parts.append("🎉 Great start! Tracking your first expense is the first step to financial awareness.")
        elif self._expenses_logged_session == 5:
            # Fifth expense - acknowledge consistency
            response_parts.append("👍 Nice consistency! You're building a great habit of tracking your spending.")
        elif self._expenses_logged_session == 10:
            # Tenth expense - celebrate the milestone
            response_parts.append("🏆 Awesome! You've logged 10 expenses this session - you're really getting the hang of this!")

        # Format the main response
        response = " ".join(response_parts)

        print(f"\n🤖 {response}")

        # Show any budget alerts (these remain important and should be prominent)
        alerts = budget_manager.check_budget_alerts(self.current_user.id)
        high_medium_alerts = [alert for alert in alerts if alert["severity"] in ["high", "medium"]]
        if high_medium_alerts:
            print()  # Add spacing
            for alert in high_medium_alerts:
                icon = {"high": "🔴", "medium": "🟠"}.get(alert["severity"], "⚪")
                print(f"{icon} {alert['message']}")

    def _show_help(self):
        """Show available commands - more welcoming and less overwhelming"""
        print("\n👋 Hey there! I'm here to help you with your money.")
        print("Think of me as your friendly financial helper - no judgment, just helpful insights!")
        print("\nHere's what you can do with me:")

        print("\n💰 **Everyday Money Tracking**")
        print("   • 'lunch 250' - Log an expense (try: 'coffee 80', 'movie 300', etc.)")
        print("   • 'uber 450' - Log transport or any other expense")
        print("   • Just tell me what you spent and on what - I'll figure it out!")
        print("   • 'fix <transaction_id> <field>=<value>' - Correct a transaction (e.g., 'fix abc123 category=Food')")
        print("   • 'remove <transaction_id>' - Delete a transaction")
        print("   • 'apply rollover' - Apply monthly rollover to all pockets")

        print("\n🎯 **Budget & Goals**")
        print("   • 'add pocket Food 5000' - Set up a budget for groceries, eating out, etc.")
        print("   • 'add goal Emergency Fund 100000' - Save for something special")
        print("   • 'balance' - See how you're doing this month")
        print("   • 'suggest budget' - Get personalized advice based on your spending")
        print("   • 'rollover <pocket_name> <on/off> [percentage]' - Configure pocket rollover (e.g., 'rollover Food on 80')")

        print("\n👥 **Sharing & Splitting**")
        print("   • 'split Roommates Groceries 3000 equal' - Split bills with friends/family")
        print("   • 'owe' - See what you owe/are owed")
        print("   • Great for shared expenses, trips, or group activities")

        print("\n📊 **Insights & Tracking**")
        print("   • 'net worth' - See your complete financial picture")
        print("   • 'anomalies' - Check for unusual spending patterns")
        print("   • 'streak' - See how many days you've logged expenses")
        print("   • 'achievements' - Check your financial milestones")

        print("\n𔒀 **Regular Money Things**")
        print("   • 'add sip HDFC Flexi Cap 3000 on 10' - Track your investments")
        print("   • 'add emi home loan 25000 on 15' - Track loan payments")
        print("   • 'add subscription netflix 649 monthly' - Track recurring bills")

        print("\n❓ **Need Help?**")
        print("   • 'help' - Show this message again")
        print("   • Just talk to me naturally - I'll do my best to understand!")
        print("   • Examples: 'My name is Alex and my number is 9876543210'")

        print("\n🚀 **Ready to get started?**")
        print("   Try telling me about your last expense - like 'lunch 250' or 'coffee 120'")
        print("   Or if you're setting up, tell me your name to begin! 😊")

    def _show_balance(self):
        """Show current budget snapshot - with more encouraging feedback"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        snapshot = budget_manager.get_budget_snapshot(self.current_user.id)

        print(f"\n📊 Here's how you're doing this month, {self.current_user.name}:")
        print("=" * 50)
        print(f"💰 Money coming in: ₹{snapshot.total_income:,.0f}")
        print(f"🔒 Regular bills/commitments: ₹{snapshot.total_committed:,.0f}")
        print(f"💵 Money you can freely use: ₹{snapshot.available_to_spend:,.0f}")
        print(f"💸 Actually spent so far: ₹{snapshot.total_spent:,.0f}")

        # Add some encouraging context
        if snapshot.total_income > 0:
            savings_rate = ((snapshot.total_income - snapshot.total_spent - snapshot.total_committed) / snapshot.total_income) * 100
            if savings_rate >= 20:
                print(f"💚 You're saving about {savings_rate:.0f}% of your income - excellent!")
            elif savings_rate >= 0:
                print(f"👍 You're saving {savings_rate:.0f}% of your income - a great start!")
            else:
                print(f"📊 You're spending {abs(savings_rate):.0f}% more than your income - let's find ways to optimize!")

        if snapshot.pocket_details:
            print("\n📦 Your budget buckets:")
            any_concerns = False
            any_good_news = False

            for pocket_name, details in snapshot.pocket_details.items():
                budget = details["budget"]
                spent = details["spent"]
                remaining = details["remaining"]
                percent = (spent / budget * 100) if budget > 0 else 0

                if percent >= 90:
                    status = "🔴"
                    concern_msg = f"You've used {percent:.0f}% of this budget"
                    any_concerns = True
                elif percent >= 70:
                    status = "🟠"
                    status_msg = f"You've used {percent:.0f}% of this budget"
                else:
                    status = "🟢"
                    status_msg = f"You've used {percent:.0f}% of this budget - plenty of room!"
                    any_good_news = True

                print(f"  {status} {pocket_name}: ₹{spent:.0f}/{budget:.0f} ({percent:.0f}%)")
                if percent >= 90:
                    print(f"      → {concern_msg}")
                elif percent >= 70:
                    print(f"      → {status_msg}")
                else:
                    print(f"      → {status_msg}")

            # Add overall encouragement
            if any_concerns and any_good_news:
                print("\n💡 You've got some areas doing great and some to watch - that's totally normal!")
            elif any_good_news and not any_concerns:
                print("\n🚀 You're doing really well with your budgets - keep up the good work!")
            elif any_concerns and not any_good_news:
                print("\n📊 Some areas need attention - that's why we track! Small adjustments can make big differences.")

        # Add a motivational touch based on session activity
        if hasattr(self, '_expenses_logged_session'):
            if self._expenses_logged_session == 0:
                print("\n🚀 Ready to make your first expense entry? Just tell me what you spent!")
            elif self._expenses_logged_session < 5:
                print(f"\n💪 You've logged {self._expenses_logged_session} expenses this session - building that awareness muscle!")
            elif self._expenses_logged_session < 15:
                print(f"\n🔥 You're on a roll with {self._expenses_logged_session} expenses tracked - great consistency!")
            else:
                print(f"\n🏆 {self._expenses_logged_session} expenses tracked this session - you're really making this a habit!")

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

    def _handle_fix_transaction(self, user_input: str):
        """Handle fix transaction command"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        # Parse: "fix transaction_id field=value"
        parts = user_input.split()
        if len(parts) < 3:
            print("\n🤖 Please specify: fix <transaction_id> <field>=<value>")
            print("   Example: fix abc123 category=Food")
            print("   Fields: amount, category, merchant, notes")
            return

        transaction_id = parts[1]

        # Parse the field=value pairs
        updates = {}
        for part in parts[2:]:
            if '=' in part:
                field, value = part.split('=', 1)
                field = field.strip()
                value = value.strip()
                updates[field] = value
            else:
                print(f"\n🤖 Invalid format: {part}. Use field=value format.")
                return

        if not updates:
            print("\n🤖 No updates specified. Use format: field=value")
            return

        # Convert amount to float if specified
        if 'amount' in updates:
            try:
                updates['amount'] = float(updates['amount'])
            except ValueError:
                print("\n🤖 Amount must be a valid number.")
                return

        # Call the update service
        from src.services import TransactionService
        result = TransactionService.update_transaction(transaction_id, **updates)

        if result["success"]:
            print(f"\n✅ Transaction {transaction_id[:8]}... updated successfully!")
            if "transaction" in result:
                trans = result["transaction"]
                print(f"   💰 Amount: ₹{trans['amount']:.0f}")
                print(f"   🏷️  Category: {trans['category']}")
                if trans['merchant'] and trans['merchant'] != "Unknown":
                    print(f"   🏪 Merchant: {trans['merchant']}")
                print(f"   📝 Notes: {trans['notes'] or '(none)'}")
        else:
            print(f"\n🤖 {result['message']}")

    def _handle_remove_transaction(self, user_input: str):
        """Handle remove transaction command"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        # Parse: "remove transaction_id"
        parts = user_input.split()
        if len(parts) < 2:
            print("\n🤖 Please specify: remove <transaction_id>")
            print("   Example: remove abc123")
            return

        transaction_id = parts[1]

        # Call the delete service
        from src.services import TransactionService
        result = TransactionService.delete_transaction(transaction_id)

        if result["success"]:
            print(f"\n🗑️  Transaction {transaction_id[:8]}... deleted successfully!")
        else:
            print(f"\n🤖 {result['message']}")

    def _handle_rollover_command(self, user_input: str):
        """Handle rollover command for pocket configuration"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        # Parse: "rollover <pocket_name> <on/off> [percentage]"
        parts = user_input.split()
        if len(parts) < 3:
            print("\n🤖 Please specify: rollover <pocket_name> <on/off> [percentage]")
            print("   Examples: rollover Food on, rollover Food off 50, rollover Food on 100")
            return

        pocket_name = parts[1]
        enabled_str = parts[2].lower()

        # Parse enabled/disabled
        if enabled_str in ['on', 'true', 'yes', '1']:
            enabled = True
        elif enabled_str in ['off', 'false', 'no', '0']:
            enabled = False
        else:
            print("\n🤖 Please specify 'on' or 'off' for rollover status")
            return

        # Parse optional percentage
        percentage = None
        if len(parts) >= 4:
            try:
                percentage = float(parts[3])
                if percentage < 0 or percentage > 100:
                    print("\n🤖 Percentage must be between 0 and 100")
                    return
            except ValueError:
                print("\n🤖 Percentage must be a valid number")
                return

        # Find the pocket ID by name
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

        # Configure the rollover settings
        result = PocketService.configure_pocket_rollover(pocket_id, enabled, percentage)

        if result["success"]:
            status = "enabled" if result["rollover_enabled"] else "disabled"
            print(f"\n🔄 Rollover {status} for pocket '{result['pocket_id'][:8]}...'")
            print(f"   📊 Rollover percentage: {result['rollover_percentage']}%")
            if result["rollover_enabled"]:
                print(f"   💡 Unspent funds will roll over to next month according to this percentage")
            else:
                print(f"   💡 Rollover disabled - unspent funds will not carry over")
        else:
            print(f"\n🤖 {result['message']}")

    def _handle_apply_rollover(self, user_input: str):
        """Handle apply rollover command"""
        if not self.current_user:
            print("\n🤖 Please complete onboarding first.")
            return

        # Call the apply rollover service
        from src.services import PocketService
        result = PocketService.apply_monthly_rollover()

        if result["success"]:
            print(f"\n🔄 {result['message']}")
            if result["rolled_over_count"] > 0:
                print(f"   💰 Total amount rolled over: ₹{result['total_rolled_over_amount']:.2f}")
                print(f"   📊 Pockets affected: {result['rolled_over_count']}")
            else:
                print(f"   💡 No rollover needed at this time")
        else:
            print(f"\n🤖 {result['message']}")

    def _add_to_conversation_history(self, user_input: str, bot_response_type: str = ""):
        """Add exchange to conversation history for light contextual awareness"""
        self._conversation_history.append({
            'user': user_input,
            'bot_response_type': bot_response_type,
            'timestamp': datetime.now()
        })
        # Keep only last 5 exchanges to keep it lightweight
        if len(self._conversation_history) > 5:
            self._conversation_history = self._conversation_history[-5:]

    def _get_recent_context(self) -> dict:
        """Get lightweight context from recent conversation"""
        if not self._conversation_history:
            return {}

        last_exchange = self._conversation_history[-1] if self._conversation_history else {}
        return {
            'last_user_input': last_exchange.get('user', ''),
            'last_bot_response_type': last_exchange.get('bot_response_type', ''),
            'exchange_count': len(self._conversation_history)
        }

# Import regex here to avoid issues
import re
from datetime import datetime


if __name__ == "__main__":
    cli = BudgetBotCLI()
    cli.start()