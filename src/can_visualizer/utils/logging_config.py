"""
Logging configuration with rotating file handlers.

Provides structured logging for:
- Parsing lifecycle events
- Decode failures
- Cache operations
- Performance metrics
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def setup_logging(
    log_dir: Optional[Path] = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    Configure application logging with rotating file handler.

    Args:
        log_dir: Directory for log files. Defaults to ~/.can_visualizer/logs
        console_level: Logging level for console output
        file_level: Logging level for file output
        max_bytes: Maximum size of each log file before rotation
        backup_count: Number of backup log files to keep

    Returns:
        Configured root logger for the application
    """
    if log_dir is None:
        log_dir = Path.home() / ".can_visualizer" / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)

    # Create custom logger for our application
    logger = logging.getLogger("can_visualizer")
    logger.setLevel(logging.DEBUG)

    # Clear any existing handlers
    logger.handlers.clear()

    # Detailed format for file logging
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Concise format for console
    console_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S"
    )

    # Rotating file handler
    log_file = log_dir / "can_visualizer.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Log startup
    logger.info("=" * 60)
    logger.info("CAN Visualizer logging initialized")
    logger.info(f"Log file: {log_file}")
    logger.info("=" * 60)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger with the given name."""
    return logging.getLogger(f"can_visualizer.{name}")
