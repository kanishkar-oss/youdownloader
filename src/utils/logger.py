"""Logging system for YouDownloader"""
import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional


class Logger:
    """Centralized logging system"""
    
    _instance: Optional['Logger'] = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._setup_logger()
            Logger._initialized = True
    
    def _setup_logger(self) -> None:
        """Setup logging configuration"""
        # Project logs/ from source, the per-user logs folder when installed
        # (YOUDOWNLOADER_LOG_DIR overrides both, for tests).
        from src.utils import paths
        log_dir = Path(paths.log_dir())
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / "youdownloader.log"
        
        # Configure named logger
        self.logger = logging.getLogger("YouDownloader")
        self.logger.setLevel(logging.DEBUG)
        # Don't bubble records up to the root logger; otherwise a root handler
        # configured elsewhere (tests, embedding hosts) would emit every line twice.
        self.logger.propagate = False

        # logging.getLogger returns a process-wide singleton, so guard against
        # stacking handlers if this module is imported/initialized more than once.
        if self.logger.handlers:
            return
        
        # File handler with rotation
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        
        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def debug(self, message: str) -> None:
        """Log debug message"""
        self.logger.debug(message)
    
    def info(self, message: str) -> None:
        """Log info message"""
        self.logger.info(message)
    
    def warning(self, message: str) -> None:
        """Log warning message"""
        self.logger.warning(message)
    
    def error(self, message: str, exc_info: bool = False) -> None:
        """Log error message"""
        self.logger.error(message, exc_info=exc_info)
    
    def critical(self, message: str, exc_info: bool = False) -> None:
        """Log critical message"""
        self.logger.critical(message, exc_info=exc_info)


def get_logger() -> logging.Logger:
    """Get the application logger instance"""
    logger_instance = Logger()
    return logger_instance.logger



