"""
App-Specific File Logging for PyRest Framework.

Provides smart file logging with separate log files for each app,
structured formatting, and log rotation.

Usage:
    from pyrest.utils import get_app_logger, setup_app_logging
    
    # Setup logging for an app
    logger = setup_app_logging("myapp", log_dir="logs")
    
    # Use the logger
    logger.info("Application started")
    logger.error("Something went wrong", exc_info=True)
"""

import os
import sys
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Union
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


# Default log directory
DEFAULT_LOG_DIR = "logs"

# Default log format
DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# JSON format for structured logging
JSON_FORMAT_FIELDS = ["timestamp", "level", "logger", "message", "app", "extra"]


class SmartFormatter(logging.Formatter):
    """
    Smart log formatter that adapts output based on log level and content.
    
    Features:
    - Colored output for console (when supported)
    - Compact format for INFO, detailed for ERROR/WARNING
    - Automatic exception formatting
    - Request context inclusion when available
    """
    
    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",      # Reset
    }
    
    def __init__(
        self,
        fmt: str = DEFAULT_FORMAT,
        datefmt: str = DEFAULT_DATE_FORMAT,
        use_colors: bool = False,
        include_location: bool = True,
    ):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors and self._supports_color()
        self.include_location = include_location
    
    @staticmethod
    def _supports_color() -> bool:
        """Check if the terminal supports colors."""
        # Windows 10+ supports ANSI, but check anyway
        if sys.platform == "win32":
            return os.environ.get("TERM") is not None or \
                   os.environ.get("WT_SESSION") is not None
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    
    def format(self, record: logging.LogRecord) -> str:
        # Add app name if available
        if not hasattr(record, "app"):
            record.app = record.name.split(".")[0] if "." in record.name else "pyrest"
        
        # Format the base message
        formatted = super().format(record)
        
        # Add location for errors and warnings
        if self.include_location and record.levelno >= logging.WARNING:
            location = f" [{record.filename}:{record.lineno}]"
            # Insert location after the level
            parts = formatted.split(" | ", 3)
            if len(parts) >= 3:
                formatted = f"{parts[0]} | {parts[1]}{location} | {' | '.join(parts[2:])}"
        
        # Apply colors if enabled
        if self.use_colors:
            color = self.COLORS.get(record.levelname, "")
            reset = self.COLORS["RESET"]
            formatted = f"{color}{formatted}{reset}"
        
        return formatted


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.
    
    Outputs each log record as a single JSON line, suitable for
    log aggregation systems like ELK, Splunk, or CloudWatch.
    """
    
    def __init__(self, app_name: str = "pyrest"):
        super().__init__()
        self.app_name = app_name
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "app": getattr(record, "app", self.app_name),
        }
        
        # Add location info
        log_data["location"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info) if record.exc_info[0] else None,
            }
        
        # Add any extra fields
        extra = {}
        for key, value in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                if key not in ["message", "asctime", "app"]:
                    try:
                        json.dumps(value)  # Check if serializable
                        extra[key] = value
                    except (TypeError, ValueError):
                        extra[key] = str(value)
        
        if extra:
            log_data["extra"] = extra
        
        return json.dumps(log_data, default=str)


class AppLogger:
    """
    App-specific logger with file and optional console output.
    
    Creates a dedicated log file for each app with proper rotation
    and formatting.
    """
    
    def __init__(
        self,
        app_name: str,
        log_dir: Union[str, Path] = DEFAULT_LOG_DIR,
        log_level: int = logging.INFO,
        max_bytes: int = 10 * 1024 * 1024,  # 10 MB
        backup_count: int = 5,
        use_json: bool = False,
        console_output: bool = False,
    ):
        """
        Initialize app-specific logger.
        
        Args:
            app_name: Name of the app (used for log file name)
            log_dir: Directory for log files
            log_level: Minimum log level to capture
            max_bytes: Maximum size per log file before rotation
            backup_count: Number of backup files to keep
            use_json: Use JSON formatting for structured logs
            console_output: Also output to console
        """
        self.app_name = app_name
        self.log_dir = Path(log_dir)
        self.log_level = log_level
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.use_json = use_json
        self.console_output = console_output
        
        # Create logger
        self.logger = logging.getLogger(f"pyrest.app.{app_name}")
        self.logger.setLevel(log_level)
        self.logger.propagate = False  # Don't propagate to root logger
        
        # Setup handlers
        self._setup_handlers()
    
    def _setup_handlers(self) -> None:
        """Setup file and console handlers."""
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create log file path
        log_file = self.log_dir / f"{self.app_name}.log"
        
        # File handler with rotation
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(self.log_level)
        
        # Set formatter
        if self.use_json:
            file_handler.setFormatter(JSONFormatter(self.app_name))
        else:
            file_handler.setFormatter(SmartFormatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                include_location=True,
            ))
        
        self.logger.addHandler(file_handler)
        
        # Optional console handler
        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self.log_level)
            console_handler.setFormatter(SmartFormatter(
                fmt="%(asctime)s | %(levelname)-8s | %(message)s",
                use_colors=True,
                include_location=False,
            ))
            self.logger.addHandler(console_handler)
        
        # Also create an error-only log file
        error_log_file = self.log_dir / f"{self.app_name}.error.log"
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(SmartFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | [%(filename)s:%(lineno)d] | %(message)s",
            include_location=True,
        ))
        self.logger.addHandler(error_handler)
    
    def get_logger(self) -> logging.Logger:
        """Get the underlying Python logger."""
        return self.logger
    
    # Convenience methods that delegate to the logger
    def debug(self, msg: str, *args, **kwargs) -> None:
        self.logger.debug(msg, *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs) -> None:
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs) -> None:
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs) -> None:
        self.logger.error(msg, *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs) -> None:
        self.logger.critical(msg, *args, **kwargs)
    
    def exception(self, msg: str, *args, **kwargs) -> None:
        self.logger.exception(msg, *args, **kwargs)
    
    def log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        user: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log an HTTP request with structured data.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path
            status_code: Response status code
            duration_ms: Request duration in milliseconds
            user: Optional user identifier
            extra: Optional extra data to include
        """
        log_data = {
            "method": method,
            "path": path,
            "status": status_code,
            "duration_ms": round(duration_ms, 2),
        }
        if user:
            log_data["user"] = user
        if extra:
            log_data.update(extra)
        
        # Determine log level based on status code
        if status_code >= 500:
            level = logging.ERROR
        elif status_code >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO
        
        self.logger.log(level, f"{method} {path} -> {status_code} ({duration_ms:.2f}ms)", extra=log_data)
    
    def log_tm1_operation(
        self,
        operation: str,
        instance: str,
        success: bool,
        duration_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log a TM1 operation with structured data.
        
        Args:
            operation: Operation name (e.g., "get_cubes", "execute_mdx")
            instance: TM1 instance name
            success: Whether the operation succeeded
            duration_ms: Optional operation duration
            details: Optional extra details
        """
        log_data = {
            "tm1_operation": operation,
            "tm1_instance": instance,
            "success": success,
        }
        if duration_ms is not None:
            log_data["duration_ms"] = round(duration_ms, 2)
        if details:
            log_data.update(details)
        
        if success:
            self.logger.info(f"TM1 [{instance}] {operation}: success", extra=log_data)
        else:
            self.logger.error(f"TM1 [{instance}] {operation}: failed", extra=log_data)


# Registry of app loggers
_app_loggers: Dict[str, AppLogger] = {}


def setup_app_logging(
    app_name: str,
    log_dir: Union[str, Path] = DEFAULT_LOG_DIR,
    log_level: Union[int, str] = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    use_json: bool = False,
    console_output: bool = False,
) -> AppLogger:
    """
    Setup logging for an app and return the AppLogger.
    
    Args:
        app_name: Name of the app
        log_dir: Directory for log files
        log_level: Minimum log level (int or string like "INFO")
        max_bytes: Maximum size per log file before rotation
        backup_count: Number of backup files to keep
        use_json: Use JSON formatting for structured logs
        console_output: Also output to console
        
    Returns:
        AppLogger instance
    """
    # Convert string log level to int
    if isinstance(log_level, str):
        log_level = getattr(logging, log_level.upper(), logging.INFO)
    
    app_logger = AppLogger(
        app_name=app_name,
        log_dir=log_dir,
        log_level=log_level,
        max_bytes=max_bytes,
        backup_count=backup_count,
        use_json=use_json,
        console_output=console_output,
    )
    
    _app_loggers[app_name] = app_logger
    return app_logger


def get_app_logger(app_name: str) -> Optional[AppLogger]:
    """
    Get an existing app logger by name.
    
    Args:
        app_name: Name of the app
        
    Returns:
        AppLogger instance or None if not found
    """
    return _app_loggers.get(app_name)


def get_or_create_app_logger(
    app_name: str,
    log_dir: Union[str, Path] = DEFAULT_LOG_DIR,
    **kwargs,
) -> AppLogger:
    """
    Get an existing app logger or create a new one.
    
    Args:
        app_name: Name of the app
        log_dir: Directory for log files
        **kwargs: Additional arguments for setup_app_logging
        
    Returns:
        AppLogger instance
    """
    if app_name in _app_loggers:
        return _app_loggers[app_name]
    return setup_app_logging(app_name, log_dir, **kwargs)
