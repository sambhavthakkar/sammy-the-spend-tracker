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
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'sqlite:///budgetbot.db')
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

    # AI/ML settings (stubbed for now)
    CLAUDE_API_KEY: Optional[str] = os.getenv('CLAUDE_API_KEY')
    WHISPER_MODEL_PATH: str = os.getenv('WHISPER_MODEL_PATH', './models/whisper')
    SARVAM_AI_KEY: Optional[str] = os.getenv('SARVAM_AI_KEY')

    # OCR settings (stubbed for now)
    TESSERACT_PATH: Optional[str] = os.getenv('TESSERACT_PATH')
    GOOGLE_VISION_CREDENTIALS: Optional[str] = os.getenv('GOOGLE_VISION_CREDENTIALS')

    # File upload settings
    MAX_CONTENT_LENGTH: int = int(os.getenv('MAX_CONTENT_LENGTH', '16777216'))  # 16MB
    UPLOAD_FOLDER: str = os.getenv('UPLOAD_FOLDER', './uploads')
    ALLOWED_EXTENSIONS: set = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'pdf'}

    # BudgetBot specific settings
    DEFAULT_ALERT_THRESHOLDS: list = [0.7, 0.9, 1.0]  # 70%, 90%, 100%
    CURRENCY: str = 'INR'
    DATE_FORMAT: str = '%Y-%m-%d'
    DATETIME_FORMAT: str = '%Y-%m-%d %H:%M:%S'

    # Feature flags
    ENABLE_VOICE_PROCESSING: bool = os.getenv('ENABLE_VOICE_PROCESSING', 'False').lower() == 'true'
    ENABLE_OCR_PROCESSING: bool = os.getenv('ENABLE_OCR_PROCESSING', 'False').lower() == 'true'
    ENABLE_ANALYTICS: bool = os.getenv('ENABLE_ANALYTICS', 'True').lower() == 'true'

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