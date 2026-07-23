"""
Configuration management for BudgetBot
Handles environment variables and application settings
"""
import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Application configuration class"""

    # Flask/Application settings
    FLASK_ENV: str = os.getenv('FLASK_ENV', 'development')
    DEBUG: bool = os.getenv('DEBUG', 'False').lower() == 'true'
    SECRET_KEY: str = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Database settings
    # Prefer absolute sqlite path so cwd changes don't split data across files
    _default_db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'budgetbot.db')
    DATABASE_URL: str = os.getenv('DATABASE_URL', f'sqlite:///{_default_db}')
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ECHO: bool = os.getenv('SQLALCHEMY_ECHO', 'False').lower() == 'true'

    # Redis settings (for caching/sessions)
    REDIS_URL: str = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

    # WhatsApp Business API settings (stubbed for now)
    WHATSAPP_TOKEN: Optional[str] = os.getenv('WHATSAPP_TOKEN')
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
    WHATSAPP_VERIFY_TOKEN: str = os.getenv('WHATSAPP_VERIFY_TOKEN', 'budgetbot_verify_token')

    # Google Cloud / Sheets settings (stubbed for now)
    GOOGLE_SHEETS_CREDENTIALS: Optional[str] = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
    GOOGLE_SHEETS_SPREADSHEET_ID: Optional[str] = os.getenv('GOOGLE_SHEETS_SPREADSHEET_ID')

    # AI/ML settings (legacy / optional)
    CLAUDE_API_KEY: Optional[str] = os.getenv('CLAUDE_API_KEY')
    WHISPER_MODEL_PATH: str = os.getenv('WHISPER_MODEL_PATH', './models/whisper')
    SARVAM_AI_KEY: Optional[str] = os.getenv('SARVAM_AI_KEY')

    # Ollama Cloud / OpenAI-compatible LLM
    OLLAMA_BASE_URL: str = os.getenv('OLLAMA_BASE_URL', 'https://ollama.com/v1')
    OLLAMA_API_KEY: Optional[str] = os.getenv('OLLAMA_API_KEY')
    OLLAMA_MODEL: str = os.getenv('OLLAMA_MODEL', 'gemma4:31b-cloud')
    OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv('OLLAMA_TIMEOUT_SECONDS', '45'))
    OLLAMA_MAX_TOOL_ROUNDS: int = int(os.getenv('OLLAMA_MAX_TOOL_ROUNDS', '4'))
    LLM_TOOL_MODE: str = os.getenv('LLM_TOOL_MODE', 'native')  # native | json
    # Local rule shortcut for simple "lunch 250" — OFF by default (smart agent owns intent)
    AGENT_FAST_PATH: bool = os.getenv('AGENT_FAST_PATH', 'False').lower() == 'true'
    # Max edge length for bill photos before Gemma vision (smaller = faster)
    BILL_IMAGE_MAX_SIDE: int = int(os.getenv('BILL_IMAGE_MAX_SIDE', '1280'))
    BILL_IMAGE_JPEG_QUALITY: int = int(os.getenv('BILL_IMAGE_JPEG_QUALITY', '75'))

    # Telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_MODE: str = os.getenv('TELEGRAM_MODE', 'polling')  # polling | webhook
    TELEGRAM_WEBHOOK_URL: Optional[str] = os.getenv('TELEGRAM_WEBHOOK_URL')
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = os.getenv('TELEGRAM_WEBHOOK_SECRET')
    TELEGRAM_ALLOWED_USER_IDS: str = os.getenv('TELEGRAM_ALLOWED_USER_IDS', '')

    # Agent settings
    AGENT_TIMEZONE_DEFAULT: str = os.getenv('AGENT_TIMEZONE_DEFAULT', 'Asia/Kolkata')
    AGENT_CURRENCY_DEFAULT: str = os.getenv('AGENT_CURRENCY_DEFAULT', 'INR')
    AGENT_CONFIRM_AMOUNT_THRESHOLD: float = float(os.getenv('AGENT_CONFIRM_AMOUNT_THRESHOLD', '10000'))
    AGENT_CONFIRM_INCOME_FRACTION: float = float(os.getenv('AGENT_CONFIRM_INCOME_FRACTION', '0.2'))
    AGENT_MEMORY_TURNS: int = int(os.getenv('AGENT_MEMORY_TURNS', '8'))
    AGENT_RECENT_TXNS: int = int(os.getenv('AGENT_RECENT_TXNS', '3'))

    # Voice / STT
    # auto | faster_whisper | openai | none
    STT_PROVIDER: str = os.getenv('STT_PROVIDER', 'auto')
    # faster-whisper: tiny|base|small|…  openai: whisper-1
    STT_MODEL: str = os.getenv('STT_MODEL', 'tiny')
    STT_LANGUAGE: str = os.getenv('STT_LANGUAGE', '')  # empty = auto-detect
    STT_DEVICE: str = os.getenv('STT_DEVICE', 'cpu')  # cpu | cuda
    STT_BASE_URL: Optional[str] = os.getenv('STT_BASE_URL')  # OpenAI-compatible base
    STT_API_KEY: Optional[str] = os.getenv('STT_API_KEY')
    STT_TIMEOUT_SECONDS: int = int(os.getenv('STT_TIMEOUT_SECONDS', '120'))
    STT_SHOW_TRANSCRIPT: bool = os.getenv('STT_SHOW_TRANSCRIPT', 'True').lower() == 'true'

    # OCR settings (stubbed for now)
    TESSERACT_PATH: Optional[str] = os.getenv('TESSERACT_PATH')
    GOOGLE_VISION_CREDENTIALS: Optional[str] = os.getenv('GOOGLE_VISION_CREDENTIALS')

    # File upload settings
    MAX_CONTENT_LENGTH: int = int(os.getenv('MAX_CONTENT_LENGTH', '16777216'))  # 16MB
    UPLOAD_FOLDER: str = os.getenv('UPLOAD_FOLDER', './uploads')
    ALLOWED_EXTENSIONS: set = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'pdf'}

    # BudgetBot specific settings
    DEFAULT_ALERT_THRESHOLDS: list = [0.7, 0.9, 1.0]  # 70%, 90%, 100%
    CURRENCY: str = os.getenv('CURRENCY', 'INR')
    DATE_FORMAT: str = '%Y-%m-%d'
    DATETIME_FORMAT: str = '%Y-%m-%d %H:%M:%S'

    # Feature flags
    ENABLE_VOICE_PROCESSING: bool = os.getenv('ENABLE_VOICE_PROCESSING', 'True').lower() == 'true'
    # Bill photos via Gemma vision (Ollama) — not classic OCR
    ENABLE_BILL_VISION: bool = os.getenv('ENABLE_BILL_VISION', 'True').lower() == 'true'
    ENABLE_OCR_PROCESSING: bool = os.getenv('ENABLE_OCR_PROCESSING', 'False').lower() == 'true'
    ENABLE_ANALYTICS: bool = os.getenv('ENABLE_ANALYTICS', 'True').lower() == 'true'
    ENABLE_AGENT: bool = os.getenv('ENABLE_AGENT', 'True').lower() == 'true'
    ENABLE_RULE_PARSER_FALLBACK: bool = os.getenv('ENABLE_RULE_PARSER_FALLBACK', 'True').lower() == 'true'

    # Cached allowlist: re-read .env only when file mtime changes
    _allowlist_cache: set = set()
    _allowlist_mtime: float = -1.0

    @classmethod
    def telegram_allowlist(cls) -> set:
        """
        Parse TELEGRAM_ALLOWED_USER_IDS (comma-separated).

        Hot-reloads when `.env` is saved; otherwise uses a tiny in-memory cache
        so every message is not re-parsing the file from disk.
        """
        env_path = os.path.join(os.getcwd(), '.env')
        try:
            mtime = os.path.getmtime(env_path) if os.path.isfile(env_path) else 0.0
        except OSError:
            mtime = 0.0

        if mtime == cls._allowlist_mtime and cls._allowlist_mtime >= 0:
            return set(cls._allowlist_cache)

        load_dotenv(override=True)
        raw = (os.getenv('TELEGRAM_ALLOWED_USER_IDS') or '').strip()
        if not raw:
            ids: set = set()
        else:
            ids = {part.strip() for part in raw.split(',') if part.strip()}
        cls._allowlist_cache = ids
        cls._allowlist_mtime = mtime
        return set(ids)

    @staticmethod
    def init_app(app):
        """Initialize application with configuration"""
        pass

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = True

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SQLALCHEMY_ECHO = False

class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DATABASE_URL = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}