# BudgetBot - WhatsApp Native Financial OS

**BudgetBot** is a WhatsApp-native financial management platform that helps users track expenses, manage budgets, and gain financial intelligence without leaving their favorite messaging app.

This repository contains the **enhanced MVP implementation** with production-ready architecture. API integrations (WhatsApp, Google Sheets, Voice/OCR services) are planned for later phases.

## Features Implemented

✅ **Data Models**: Users, Transactions, Pockets, Commitments, Savings Goals, Assets, Liabilities, Group Splits, Spending Patterns, Budget Suggestions, Anomaly Alerts, User Streaks, User Category Preferences  
✅ **Expense Parser**: Natural language processing for text/voice/bill inputs with user preference learning  
✅ **Budget Manager**: Envelope budget pockets with rollover controls, commitment tracking, alerts  
✅ **Service Layer**: Clean separation of concerns with business logic including transaction management, expense learning, and rollover controls  
✅ **API Skeleton**: REST endpoints ready for webhook integration including transaction CRUD, pocket rollover configuration, and apply rollover  
✅ **Database Abstraction**: SQLAlchemy models with migration support  
✅ **Configuration Management**: Environment-based configuration  
✅ **Structured Logging**: JSON logging with rotation  
✅ **Docker Support**: Containerized deployment ready  
✅ **Test Suite**: Basic unit tests for core functionality  
✅ **Human-Comfort CLI**: Enhanced conversational interface with helpful error recovery and contextual guidance  

## Features Ready for Integration

- Text/voice/bill expense logging with Claude-style NLU and user preference learning
- Envelope budget pocket system with threshold alerts and configurable rollover
- SIP/EMI/subscription commitment tracking with pre-deduction reminders
- Committed spend dashboard and discretionary income calculation
- User-defined reminders and budget threshold notifications
- On-demand queries (balance, commitments, spending)
- Subscription registry and renewal alert framework
- Member onboarding and privacy-tier separation
- GST tagging framework and CA-export readiness
- Google Sheets sync and WhatsApp API integration foundations
- Context-aware conversation and noise filtering frameworks
- Transaction update/delete capabilities
- Expense categorization learning from user corrections
- Budget pocket rollover controls (enable/disable, percentage configuration)

## Project Structure

```
budgetbot/
├── src/                    # Source code
│   ├── api.py             # Flask API endpoints & webhooks
│   ├── budget_manager.py  # Core budget logic (refactored into services)
│   ├── cli_interface.py   # CLI simulator for testing
│   ├── config.py          # Environment configuration
│   ├── database.py        # SQLAlchemy models & DB abstraction
│   ├── expense_parser.py  # Natural language expense processing with user preference learning
│   ├── logging_config.py  # Structured logging setup
│   └── services.py        # Business logic service layer (including transaction management, expense learning, rollover controls)
├── tests/                 # Unit tests
├── Dockerfile             # Containerization
├── docker-compose.yml     # Local development with PostgreSQL/Redis
├── requirements.txt       # Python dependencies
├── .env.example           # Environment variables template
├── main.py                # Application entry point (CLI or API)
└── README.md              # This file
```

## Quick Start

### Option 1: CLI Interface (for testing & development)

```bash
# Clone the repository
git clone <repository-url>
cd budgetbot

# Install dependencies
pip install -r requirements.txt

# Run the CLI interface
python main.py cli
```

Then interact with BudgetBot using commands like:
- `My name is Priya and my number is 9876543210`
- `lunch 250`
- `add pocket Food 5000`
- `add sip HDFC Flexi Cap 3000 on 10`
- `fix abc123 category=Food` (correct a transaction)
- `remove abc123` (delete a transaction)
- `rollover Food on 80` (configure rollover for Food pocket)
- `apply rollover` (apply monthly rollover to all pockets)
- `balance`
- `help`

### Option 2: API Server (for production)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (copy .env.example to .env first)
cp .env.example .env
# Edit .env with your configuration

# Run the API server
python main.py api
```

The API will be available at `http://localhost:5000` with endpoints like:
- `POST /api/users` - Create user
- `POST /api/transactions/expense` - Log expense
- `GET /api/users/<user_id>/budget-snapshot` - Get budget status
- `POST /api/commitments` - Add SIP/EMI/subscription
- Webhook endpoints for WhatsApp and Google Sheets (stubs)

### Option 3: Docker Development

```bash
# Start all services (BudgetBot API + PostgreSQL + Redis)
docker-compose up --build

# Access the API at http://localhost:5000
# Access Adminer at http://localhost:8080 (for DB management)
```

## API Endpoints Reference

### Users
- `POST /api/users` - Create new user
- `GET /api/users/<user_id>` - Get user details
- `GET /api/users/phone/<phone>` - Get user by phone
- `PUT /api/users/<user_id>/income` - Update monthly income

### Pockets
- `POST /api/pockets` - Create budget pocket
- `GET /api/users/<user_id>/pockets` - Get user's pockets
- `PUT /api/pockets/<pocket_id>/rollover` - Configure pocket rollover settings
- `POST /api/pockets/rollover/apply` - Apply monthly rollover to all pockets

### Transactions
- `POST /api/transactions/expense` - Log expense from text
- `GET /api/users/<user_id>/transactions` - Get user transactions
- `PUT /api/transactions/<transaction_id>` - Update transaction (amount, category, merchant, notes)
- `DELETE /api/transactions/<transaction_id>` - Delete transaction

### Commitments
- `POST /api/commitments` - Add recurring commitment
- `GET /api/users/<user_id>/commitments` - Get user commitments
- `GET /api/users/<user_id>/committed-spending` - Get committed spending

### Budget
- `GET /api/users/<user_id>/budget-snapshot` - Get budget snapshot
- `GET /api/users/<user_id>/budget-alerts` - Get budget alerts
- `GET /api/users/<user_id>/upcoming-deductions` - Get upcoming deductions

### Webhooks (Stubs for Future)
- `GET /webhook/whatsapp` - WhatsApp verification
- `POST /webhook/whatsapp` - WhatsApp incoming messages
- `POST /webhook/google-sheets` - Google Sheets sync notifications

## Testing

Run the test suite:
```bash
python -m pytest tests/ -v
```

## Configuration

Copy `.env.example` to `.env` and customize the values:
- Database connection strings
- API keys for external services (to be added later)
- Feature flags
- Security settings

## Ready for API Integration Phase

The enhanced MVP core is now complete and ready for API integration. The following core functionality has been implemented:

✅ **Core Financial Features**: All original MVP features plus enhancements
✅ **Data Models**: Complete set including transactions, pockets, commitments, goals, assets, liabilities, etc.
✅ **Service Layer**: Business logic with transaction management, expense learning, rollover controls
✅ **API Skeleton**: REST endpoints ready for webhook integration including new transaction CRUD and pocket rollover endpoints
✅ **Database Abstraction**: SQLAlchemy models with proper indexing and relationships
✅ **Human-Comfort CLI**: Enhanced conversational interface for testing and development

## Next Steps for API Integration

As mentioned in the requirements, the following integrations will be added in subsequent phases:

1. **WhatsApp Business API** - Replace CLI with actual WhatsApp messaging (webhook endpoints already stubbed)
2. **Google Sheets API** - Real-time transaction sync to spreadsheets (webhook endpoint already stubbed)
3. **Voice Processing** - Whisper/Sarvam AI for Hindi/English transcription
4. **OCR Processing** - Google Vision/Tesseract for bill/receipt scanning
5. **Database Migration** - Switch from SQLite to PostgreSQL for production
6. **Caching Layer** - Redis for session management and rate limiting
7. **Async Tasks** - Celery for background processing (reminders, reports)
8. **Authentication** - JWT-based security for API endpoints
9. **Monitoring** - Health checks, metrics, and error tracking
10. **Deployment** - Kubernetes Helm charts and CI/CD pipelines

**Ready to begin**: Simply implement the WhatsApp and Google Sheets webhook handlers to start receiving/sending messages and syncing data to spreadsheets.

## License

This is proprietary and confidential software developed for BudgetBot.

---

**Ready for API Integration** - The MVP core is complete and ready for the next phase of adding actual API integrations as specified in the requirements.