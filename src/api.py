"""
API skeleton for BudgetBot
Provides REST endpoints and webhook handlers for integration with external services
(WhatsApp Business API, Google Sheets, etc.)
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from src.services import (
    UserService, PocketService, TransactionService,
    CommitmentService, BudgetService, SavingsGoalService,
    BudgetIntelligenceService, SplitService, AnomalyDetectionService,
    NetWorthService, GamificationService
)
from src.logging_config import get_logger
from src.config import Config
import logging
import os
import json
from datetime import datetime

logger = get_logger(__name__)

def create_app():
    """Application factory pattern"""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Enable CORS for all routes
    CORS(app)

    # Health check endpoint
    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0-mvp"
        }), 200

    # User endpoints
    @app.route('/api/users', methods=['POST'])
    def create_user():
        """Create a new user"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        phone = data.get('phone')
        name = data.get('name')
        language = data.get('language', 'en')
        mode = data.get('mode', 'personal')

        if not phone or not name:
            return jsonify({"error": "Phone and name are required"}), 400

        result = UserService.create_user(phone, name, language, mode)
        status_code = 201 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>', methods=['GET'])
    def get_user(user_id):
        """Get user by ID"""
        result = UserService.get_user(user_id)
        if result:
            return jsonify(result), 200
        else:
            return jsonify({"error": "User not found"}), 404

    @app.route('/api/users/phone/<phone>', methods=['GET'])
    def get_user_by_phone(phone):
        """Get user by phone number"""
        result = UserService.get_user_by_phone(phone)
        if result:
            return jsonify(result), 200
        else:
            return jsonify({"error": "User not found"}), 404

    @app.route('/api/users/<user_id>/income', methods=['PUT'])
    def update_income(user_id):
        """Update user's monthly income"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        income = data.get('income')
        if income is None:
            return jsonify({"error": "Income is required"}), 400

        try:
            income = float(income)
            if income < 0:
                return jsonify({"error": "Income must be non-negative"}), 400
        except ValueError:
            return jsonify({"error": "Income must be a valid number"}), 400

        result = UserService.update_income(user_id, income)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code

    # Pocket endpoints
    @app.route('/api/pockets', methods=['POST'])
    def create_pocket():
        """Create a new budget pocket"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        user_id = data.get('user_id')
        name = data.get('name')
        monthly_limit = data.get('monthly_limit')
        is_shared = data.get('is_shared', False)

        if not user_id or not name or monthly_limit is None:
            return jsonify({"error": "User ID, name, and monthly limit are required"}), 400

        try:
            monthly_limit = float(monthly_limit)
            if monthly_limit < 0:
                return jsonify({"error": "Monthly limit must be non-negative"}), 400
        except ValueError:
            return jsonify({"error": "Monthly limit must be a valid number"}), 400

        result = PocketService.create_pocket(user_id, name, monthly_limit, is_shared)
        status_code = 201 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/pockets', methods=['GET'])
    def get_user_pockets(user_id):
        """Get all pockets for a user"""
        result = PocketService.get_user_pockets(user_id)
        return jsonify({"pockets": result}), 200

    # Transaction endpoints
    @app.route('/api/transactions/expense', methods=['POST'])
    def log_expense():
        """Log an expense from text/voice/bill"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        user_id = data.get('user_id')
        text = data.get('text')
        mode = data.get('mode', 'personal')
        source = data.get('source', 'text')  # text, voice, bill

        if not user_id or not text:
            return jsonify({"error": "User ID and text are required"}), 400

        # For now, we only handle text parsing in the service
        # Voice and bill processing will be added later as stubs
        if source in ['voice', 'bill']:
            # Stub for future implementation
            return jsonify({
                "success": False,
                "message": f"{source} processing will be implemented in API integration phase"
            }), 501

        result = TransactionService.log_expense_text(user_id, text, mode)
        status_code = 201 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/transactions', methods=['GET'])
    def get_user_transactions(user_id):
        """Get transactions for a user"""
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        result = TransactionService.get_user_transactions(user_id, limit, offset)
        return jsonify({"transactions": result}), 200

    # Commitment endpoints
    @app.route('/api/commitments', methods=['POST'])
    def add_commitment():
        """Add a recurring commitment"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        user_id = data.get('user_id')
        name = data.get('name')
        amount = data.get('amount')
        commitment_type = data.get('type', 'sip')
        frequency = data.get('frequency', 'monthly')
        day_of_month = data.get('day_of_month', 1)

        if not user_id or not name or amount is None:
            return jsonify({"error": "User ID, name, and amount are required"}), 400

        try:
            amount = float(amount)
            if amount <= 0:
                return jsonify({"error": "Amount must be positive"}), 400

            day_of_month = int(day_of_month)
            if day_of_month < 1 or day_of_month > 31:
                return jsonify({"error": "Day of month must be between 1 and 31"}), 400
        except ValueError:
            return jsonify({"error": "Amount and day of month must be valid numbers"}), 400

        valid_types = ['sip', 'emi', 'subscription', 'insurance']
        if commitment_type not in valid_types:
            return jsonify({"error": f"Commitment type must be one of: {', '.join(valid_types)}"}), 400

        valid_frequencies = ['monthly', 'quarterly', 'yearly']
        if frequency not in valid_frequencies:
            return jsonify({"error": f"Frequency must be one of: {', '.join(valid_frequencies)}"}), 400

        result = CommitmentService.add_commitment(
            user_id, name, amount, commitment_type, frequency, day_of_month
        )
        status_code = 201 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/commitments', methods=['GET'])
    def get_user_commitments(user_id):
        """Get all commitments for a user"""
        result = CommitmentService.get_user_commitments(user_id)
        return jsonify({"commitments": result}), 200

    @app.route('/api/users/<user_id>/committed-spending', methods=['GET'])
    def get_committed_spending(user_id):
        """Get user's committed spending"""
        result = CommitmentService.get_committed_spending(user_id)
        return jsonify(result), 200

    # Budget endpoints
    @app.route('/api/users/<user_id>/budget-snapshot', methods=['GET'])
    def get_budget_snapshot(user_id):
        """Get budget snapshot for user"""
        result = BudgetService.get_budget_snapshot(user_id)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/budget-alerts', methods=['GET'])
    def get_budget_alerts(user_id):
        """Get budget threshold alerts for user"""
        result = BudgetService.check_budget_alerts(user_id)
        return jsonify({"alerts": result}), 200

    @app.route('/api/users/<user_id>/upcoming-deductions', methods=['GET'])
    def get_upcoming_deductions(user_id):
        """Get upcoming deductions for user"""
        days_ahead = request.args.get('days_ahead', 3, type=int)
        result = BudgetService.get_upcoming_deductions(user_id, days_ahead)
        return jsonify({"upcoming_deductions": result}), 200

    # Savings Goal endpoints
    @app.route('/api/savings-goals', methods=['POST'])
    def create_savings_goal():
        """Create a new savings goal"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        user_id = data.get('user_id')
        pocket_id = data.get('pocket_id')
        name = data.get('name')
        target_amount = data.get('target_amount')
        target_date_str = data.get('target_date')

        if not user_id or not pocket_id or not name or target_amount is None:
            return jsonify({"error": "User ID, pocket ID, name, and target amount are required"}), 400

        try:
            target_amount = float(target_amount)
            if target_amount <= 0:
                return jsonify({"error": "Target amount must be positive"}), 400

            target_date = None
            if target_date_str:
                target_date = datetime.fromisoformat(target_date_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({"error": "Target amount must be a valid number and target date must be ISO format"}), 400

        result = SavingsGoalService.create_savings_goal(user_id, pocket_id, name, target_amount, target_date)
        status_code = 201 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/savings-goals', methods=['GET'])
    def get_user_savings_goals(user_id):
        """Get all savings goals for a user"""
        result = SavingsGoalService.get_user_savings_goals(user_id)
        return jsonify({"savings_goals": result}), 200

    @app.route('/api/savings-goals/<goal_id>/progress', methods=['POST'])
    def update_savings_goal_progress(goal_id):
        """Update savings goal progress"""
        result = SavingsGoalService.update_savings_goal_progress(goal_id)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code

    # Budget Intelligence endpoints
    @app.route('/api/users/<user_id>/budget-suggestions', methods=['GET'])
    def get_budget_suggestions(user_id):
        """Get budget suggestions for a user"""
        result = BudgetIntelligenceService.get_budget_suggestions(user_id)
        return jsonify({"suggestions": result}), 200

    @app.route('/api/users/<user_id>/budget-suggestions/generate', methods=['POST'])
    def generate_budget_suggestions(user_id):
        """Generate new budget suggestions for a user"""
        result = BudgetIntelligenceService.generate_budget_suggestions(user_id)
        return jsonify({"suggestions": result}), 200

    @app.route('/api/budget-suggestions/<suggestion_id>/respond', methods=['POST'])
    def respond_to_budget_suggestion(suggestion_id):
        """Respond to a budget suggestion (accept/dismiss)"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        accept = data.get('accept', False)
        if not isinstance(accept, bool):
            return jsonify({"error": "Accept must be a boolean value"}), 400

        result = BudgetIntelligenceService.respond_to_suggestion(suggestion_id, accept)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code

    # Bill Splitting endpoints
    @app.route('/api/splits', methods=['POST'])
    def create_group_split():
        """Create a new group split for bill splitting"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        user_id = data.get('user_id')
        group_name = data.get('group_name')
        description = data.get('description', '')
        total_amount = data.get('total_amount')
        split_method = data.get('split_method', 'equal')
        splits = data.get('splits', [])

        if not user_id or not group_name or total_amount is None:
            return jsonify({"error": "User ID, group name, and total amount are required"}), 400

        try:
            total_amount = float(total_amount)
            if total_amount <= 0:
                return jsonify({"error": "Total amount must be positive"}), 400
        except ValueError:
            return jsonify({"error": "Total amount must be a valid number"}), 400

        result = SplitService.create_group_split(user_id, group_name, description, total_amount, split_method, splits)
        status_code = 201 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/splits', methods=['GET'])
    def get_user_group_splits(user_id):
        """Get group splits for a user"""
        include_settled = request.args.get('include_settled', 'false').lower() == 'true'
        result = SplitService.get_user_group_splits(user_id, include_settled)
        return jsonify({"group_splits": result}), 200

    @app.route('/api/split-transactions/<split_transaction_id>/payment', methods=['POST'])
    def record_split_payment(split_transaction_id):
        """Record a payment towards a split transaction"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        amount_paid = data.get('amount')
        if amount_paid is None:
            return jsonify({"error": "Amount paid is required"}), 400

        try:
            amount_paid = float(amount_paid)
            if amount_paid < 0:
                return jsonify({"error": "Amount paid cannot be negative"}), 400
        except ValueError:
            return jsonify({"error": "Amount paid must be a valid number"}), 400

        result = SplitService.record_split_payment(split_transaction_id, amount_paid)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/owe-summary', methods=['GET'])
    def get_owe_summary(user_id):
        """Get summary of what user owes and is owed"""
        result = SplitService.get_owe_summary(user_id)
        return jsonify(result), 200

    # Anomaly Detection endpoints
    @app.route('/api/users/<user_id>/anomalies/detect', methods=['POST'])
    def detect_anomalies(user_id):
        """Detect anomalies in user's spending"""
        data = request.get_json() or {}
        lookback_days = data.get('lookback_days', 30)
        try:
            lookback_days = int(lookback_days)
            if lookback_days <= 0:
                return jsonify({"error": "Lookback days must be positive"}), 400
        except ValueError:
            return jsonify({"error": "Lookback days must be a valid integer"}), 400

        result = AnomalyDetectionService.detect_anomalies(user_id, lookback_days)
        return jsonify({"anomalies": result}), 200

    @app.route('/api/users/<user_id>/anomalies', methods=['GET'])
    def get_user_anomalies(user_id):
        """Get anomaly alerts for a user"""
        include_resolved = request.args.get('include_resolved', 'false').lower() == 'true'
        result = AnomalyDetectionService.get_user_anomalies(user_id, include_resolved)
        return jsonify({"anomalies": result}), 200

    @app.route('/api/anomalies/<alert_id>/resolve', methods=['POST'])
    def resolve_anomaly(alert_id):
        """Mark an anomaly as resolved"""
        data = request.get_json() or {}
        resolution_note = data.get('resolution_note')
        result = AnomalyDetectionService.resolve_anomaly(alert_id, resolution_note)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code

    # Net Worth endpoints
    @app.route('/api/assets', methods=['POST'])
    def add_asset():
        """Add an asset for net worth tracking"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        user_id = data.get('user_id')
        name = data.get('name')
        asset_type = data.get('asset_type')
        value = data.get('value')
        description = data.get('description')

        if not user_id or not name or not asset_type or value is None:
            return jsonify({"error": "User ID, name, asset type, and value are required"}), 400

        try:
            value = float(value)
            if value < 0:
                return jsonify({"error": "Asset value cannot be negative"}), 400
        except ValueError:
            return jsonify({"error": "Value must be a valid number"}), 400

        result = NetWorthService.add_asset(user_id, name, asset_type, value, description)
        status_code = 201 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/liabilities', methods=['POST'])
    def add_liability():
        """Add a liability for net worth tracking"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        user_id = data.get('user_id')
        name = data.get('name')
        liability_type = data.get('liability_type')
        amount_owed = data.get('amount_owed')
        interest_rate = data.get('interest_rate')
        minimum_payment = data.get('minimum_payment')
        due_date_str = data.get('due_date')
        description = data.get('description')

        if not user_id or not name or not liability_type or amount_owed is None:
            return jsonify({"error": "User ID, name, liability type, and amount owed are required"}), 400

        try:
            amount_owed = float(amount_owed)
            if amount_owed <= 0:
                return jsonify({"error": "Amount owed must be positive"}), 400

            if interest_rate is not None:
                interest_rate = float(interest_rate)
                if interest_rate < 0:
                    return jsonify({"error": "Interest rate cannot be negative"}), 400

            if minimum_payment is not None:
                minimum_payment = float(minimum_payment)
                if minimum_payment < 0:
                    return jsonify({"error": "Minimum payment cannot be negative"}), 400

            due_date = None
            if due_date_str:
                due_date = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({"error": "Financial values must be valid numbers and dates must be ISO format"}), 400

        result = NetWorthService.add_liability(user_id, name, liability_type, amount_owed, interest_rate, minimum_payment, due_date, description)
        status_code = 201 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/net-worth', methods=['GET'])
    def get_net_worth(user_id):
        """Get net worth for a user"""
        result = NetWorthService.get_net_worth(user_id)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/assets', methods=['GET'])
    def get_user_assets(user_id):
        """Get all assets for a user"""
        result = NetWorthService.get_user_assets(user_id)
        return jsonify({"assets": result}), 200

    @app.route('/api/users/<user_id>/liabilities', methods=['GET'])
    def get_user_liabilities(user_id):
        """Get all liabilities for a user"""
        result = NetWorthService.get_user_liabilities(user_id)
        return jsonify({"liabilities": result}), 200

    # Gamification endpoints
    @app.route('/api/users/<user_id>/streaks/<streak_type>', methods=['POST'])
    def update_streak(user_id, streak_type):
        """Update a user's streak for a given type"""
        valid_streak_types = ['expense_logging', 'budget_adherence', 'savings']
        if streak_type not in valid_streak_types:
            return jsonify({"error": f"Streak type must be one of: {', '.join(valid_streak_types)}"}), 400

        result = GamificationService.update_streak(user_id, streak_type)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code

    @app.route('/api/users/<user_id>/streaks', methods=['GET'])
    def get_user_streaks(user_id):
        """Get all streaks for a user"""
        result = GamificationService.get_user_streaks(user_id)
        return jsonify({"streaks": result}), 200

    @app.route('/api/users/<user_id>/achievements', methods=['GET'])
    def get_user_achievements(user_id):
        """Get achievements for a user"""
        result = GamificationService.check_and_award_achievements(user_id)
        return jsonify({"achievements": result}), 200

    # WhatsApp webhook endpoints (stubs for future implementation)
    @app.route('/webhook/whatsapp', methods=['GET'])
    def whatsapp_verify():
        """WhatsApp webhook verification (GET challenge)"""
        # This will be implemented when integrating with WhatsApp Business API
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode and token:
            if mode == 'subscribe' and token == Config.WHATSAPP_VERIFY_TOKEN:
                logger.info("WhatsApp webhook verified")
                return challenge, 200
            else:
                logger.warning("WhatsApp webhook verification failed")
                return jsonify({"error": "Verification failed"}), 403
        return jsonify({"error": "Missing parameters"}), 400

    @app.route('/webhook/whatsapp', methods=['POST'])
    def whatsapp_webhook():
        """WhatsApp webhook for incoming messages"""
        # This will be implemented when integrating with WhatsApp Business API
        # For now, just log the incoming data and return success
        data = request.get_json()
        logger.info(f"Received WhatsApp webhook: {json.dumps(data)}")

        # TODO: Process incoming WhatsApp messages and route to appropriate services
        # This will involve:
        # 1. Extracting message content and sender info
        # 2. Finding or creating user based on phone number
        # 3. Parsing message for expenses, commands, etc.
        # 4. Calling appropriate service methods
        # 5. Sending responses back via WhatsApp API

        return jsonify({"status": "received"}), 200

    # Google Sheets webhook endpoint (stub)
    @app.route('/webhook/google-sheets', methods=['POST'])
    def google_sheets_webhook():
        """Google Sheets webhook for sync notifications"""
        # This will be implemented when integrating with Google Sheets API
        data = request.get_json()
        logger.info(f"Received Google Sheets webhook: {json.dumps(data)}")
        return jsonify({"status": "received"}), 200

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Endpoint not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}")
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({"error": "Bad request"}), 400

    return app

# For running directly (development)
if __name__ == '__main__':
    app = create_app()
    app.run(
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('FLASK_PORT', 5000)),
        debug=Config.DEBUG
    )