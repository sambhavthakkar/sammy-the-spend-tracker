"""
Logging configuration for BudgetBot
Provides structured logging with different levels and formatters
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pythonjsonlogger import jsonlogger
from src.config import Config

def setup_logger(name: str = 'budgetbot', level: int = logging.INFO) -> logging.Logger:
    """
    Set up and configure logger with JSON formatting and file rotation

    Args:
        name: Logger name
        level: Logging level

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    # Create formatters
    json_formatter = jsonlogger.JsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s %(pathname)s %(lineno)d',
        rename_fields={'level': 'levelname', 'timestamp': '@timestamp'}
    )

    standard_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(standard_formatter)
    logger.addHandler(console_handler)

    # File handler with rotation (JSON format)
    log_dir = './logs'
    os.makedirs(log_dir, exist_ok=True)

    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, f'{name}.log'),
        when='midnight',
        interval=1,
        backupCount=30
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(json_formatter)
    logger.addHandler(file_handler)

    # Error file handler (separate file for errors)
    error_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, f'{name}_error.log'),
        when='midnight',
        interval=1,
        backupCount=30
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(json_formatter)
    logger.addHandler(error_handler)

    return logger

def get_logger(name: str = 'budgetbot') -> logging.Logger:
    """
    Get a logger instance

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return logging.getLogger(name)

# Initialize default logger
logger = setup_logger()