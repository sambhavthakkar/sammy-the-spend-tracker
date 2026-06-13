# BudgetBot - WhatsApp Native Financial OS

**BudgetBot** is a WhatsApp-native financial management platform that helps users track expenses, manage budgets, and gain financial intelligence without leaving their favorite messaging app.

This repository contains the **MVP core implementation** with production-ready architecture. API integrations (WhatsApp, Google Sheets, Voice/OCR services) will be incorporated in later phases.

## Features Implemented (MVP Core)

✅ **Data Models**: Users, Transactions, Pockets, Commitments  
✅ **Expense Parser**: Natural language processing for text/voice/bill inputs  
✅ **Budget Manager**: Envelope budget pockets, commitment tracking, alerts  
✅ **Service Layer**: Clean separation of concerns with business logic  
✅ **API Skeleton**: REST endpoints ready for webhook integration  
✅ **Database Abstraction**: SQLAlchemy models with migration support  
✅ **Configuration Management**: Environment-based configuration  
✅ **Structured Logging**: JSON logging with rotation  
✅ **Docker Support**: Containerized deployment ready  
✅ **Test Suite**: Basic unit tests for core functionality  

## P0 Features Ready for Integration

- Text/voice/bill expense logging with Claude-style NLU
- Envelope budget pocket system with threshold alerts
- SIP/EMI/subscription commitment tracking with pre-deduction reminders
- Committed spend dashboard and discretionary income calculation
- User-defined reminders and budget threshold notifications
- On-demand queries (balance, commitments, spending)
- Subscription registry and renewal alert framework
- Member onboarding and privacy-tier separation
- GST tagging framework and CA-export readiness
- Google Sheets sync and WhatsApp API integration foundations
- Context-aware conversation and noise filtering frameworks

## Project Structure

```
budgetbot/
├── src/                    # Source code
│   ├── api.py             # Flask API endpoints & webhooks
│   ├── budget_manager.py  # Core budget logic (refactored into services)
│   ├── cli_interface.py   # CLI simulator for testing
│   ├── config.py          # Environment configuration
│   ├── database.py        # SQLAlchemy models & DB abstraction
│   ├── expense_parser.py  # Natural language expense processing
│   ├── logging_config.py  # Structured logging setup
│   └── services.py        # Business logic service layer
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

### Transactions
- `POST /api/transactions/expense` - Log expense from text
- `GET /api/users/<user_id>/transactions` - Get user transactions

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

## Next Steps for API Integration Phase

As mentioned in the requirements, the following integrations will be added in subsequent phases:

1. **WhatsApp Business API** - Replace CLI with actual WhatsApp messaging
2. **Google Sheets API** - Real-time transaction sync to spreadsheets
3. **Voice Processing** - Whisper/Sarvam AI for Hindi/English transcription
4. **OCR Processing** - Google Vision/Tesseract for bill/receipt scanning
5. **Database Migration** - Switch from SQLite to PostgreSQL for production
6. **Caching Layer** - Redis for session management and rate limiting
7. **Async Tasks** - Celery for background processing (reminders, reports)
8. **Authentication** - JWT-based security for API endpoints
9. **Monitoring** - Health checks, metrics, and error tracking
10. **Deployment** - Kubernetes Helm charts and CI/CD pipelines

## License

This is proprietary and confidential software developed for BudgetBot.

---

**Ready for API Integration** - The MVP core is complete and ready for the next phase of adding actual API integrations as specified in the requirements.