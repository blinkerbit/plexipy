"""
Tests for the logging utilities module.
"""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.utils.logging import (
    AppLogger,
    JSONFormatter,
    SmartFormatter,
    _app_loggers,
    get_app_logger,
    get_or_create_app_logger,
    setup_app_logging,
)


class TestSmartFormatter:
    """Tests for SmartFormatter class."""

    def test_basic_format(self):
        """Should format log record with basic format."""
        formatter = SmartFormatter(
            fmt="%(asctime)s | %(levelname)s | %(message)s", use_colors=False
        )

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        assert "INFO" in result
        assert "Test message" in result

    def test_location_for_errors(self):
        """Should include location info for errors."""
        formatter = SmartFormatter(
            fmt="%(levelname)s | %(name)s | %(message)s", use_colors=False, include_location=True
        )

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=25,
            msg="Error message",
            args=(),
            exc_info=None,
        )
        record.filename = "test.py"

        result = formatter.format(record)

        assert "[test.py:25]" in result

    def test_no_location_for_info(self):
        """Should not include location for INFO level."""
        formatter = SmartFormatter(
            fmt="%(levelname)s | %(message)s", use_colors=False, include_location=True
        )

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Info message",
            args=(),
            exc_info=None,
        )
        record.filename = "test.py"

        result = formatter.format(record)

        assert "[test.py:" not in result


class TestJSONFormatter:
    """Tests for JSONFormatter class."""

    def test_json_output(self):
        """Should output valid JSON."""
        formatter = JSONFormatter(app_name="testapp")

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.filename = "test.py"
        record.funcName = "test_func"

        result = formatter.format(record)

        # Should be valid JSON
        data = json.loads(result)

        assert data["level"] == "INFO"
        assert data["message"] == "Test message"
        assert data["app"] == "testapp"
        assert "timestamp" in data
        assert data["location"]["file"] == "test.py"
        assert data["location"]["line"] == 10

    def test_json_with_exception(self):
        """Should include exception info in JSON output."""
        formatter = JSONFormatter(app_name="testapp")

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )
        record.filename = "test.py"
        record.funcName = "test_func"

        result = formatter.format(record)
        data = json.loads(result)

        assert "exception" in data
        assert data["exception"]["type"] == "ValueError"
        assert "Test error" in data["exception"]["message"]


class TestAppLogger:
    """Tests for AppLogger class."""

    @pytest.fixture
    def log_dir(self, temp_dir):
        """Create a temporary log directory."""
        log_path = temp_dir / "logs"
        log_path.mkdir()
        return log_path

    def test_create_logger(self, log_dir):
        """Should create app-specific logger."""
        app_logger = AppLogger(app_name="testapp", log_dir=log_dir, log_level=logging.INFO)

        assert app_logger.app_name == "testapp"
        assert app_logger.logger.name == "pyrest.app.testapp"
        assert app_logger.logger.level == logging.INFO

    def test_creates_log_files(self, log_dir):
        """Should create log files in directory."""
        app_logger = AppLogger(app_name="testapp", log_dir=log_dir, log_level=logging.INFO)

        # Write some logs to trigger file creation
        app_logger.info("Test message")
        app_logger.error("Error message")

        # Force flush
        for handler in app_logger.logger.handlers:
            handler.flush()

        # Check files exist
        log_file = log_dir / "testapp.log"
        error_log_file = log_dir / "testapp.error.log"

        assert log_file.exists()
        assert error_log_file.exists()

    def test_log_methods(self, log_dir):
        """Should have all standard log methods."""
        app_logger = AppLogger(app_name="testapp", log_dir=log_dir, log_level=logging.DEBUG)

        # These should not raise
        app_logger.debug("Debug message")
        app_logger.info("Info message")
        app_logger.warning("Warning message")
        app_logger.error("Error message")
        app_logger.critical("Critical message")

    def test_get_logger(self, log_dir):
        """Should return underlying Python logger."""
        app_logger = AppLogger(app_name="testapp", log_dir=log_dir)

        logger = app_logger.get_logger()

        assert isinstance(logger, logging.Logger)
        assert logger.name == "pyrest.app.testapp"

    def test_log_request(self, log_dir):
        """Should log HTTP requests with structured data."""
        app_logger = AppLogger(app_name="testapp", log_dir=log_dir, log_level=logging.DEBUG)

        # Should not raise
        app_logger.log_request(
            method="GET", path="/api/data", status_code=200, duration_ms=45.5, user="testuser"
        )

        app_logger.log_request(
            method="POST", path="/api/update", status_code=500, duration_ms=120.0
        )

    def test_log_tm1_operation(self, log_dir):
        """Should log TM1 operations with structured data."""
        app_logger = AppLogger(app_name="testapp", log_dir=log_dir, log_level=logging.DEBUG)

        # Should not raise
        app_logger.log_tm1_operation(
            operation="get_cubes",
            instance="production",
            success=True,
            duration_ms=50.0,
            details={"cube_count": 10},
        )

        app_logger.log_tm1_operation(
            operation="execute_mdx",
            instance="production",
            success=False,
            details={"error": "Connection failed"},
        )

    def test_json_format(self, log_dir):
        """Should use JSON formatter when specified."""
        app_logger = AppLogger(app_name="testapp", log_dir=log_dir, use_json=True)

        # Check that file handler uses JSONFormatter
        file_handlers = [
            h
            for h in app_logger.logger.handlers
            if hasattr(h, "baseFilename") and "error" not in h.baseFilename
        ]

        assert len(file_handlers) > 0
        assert isinstance(file_handlers[0].formatter, JSONFormatter)

    def test_no_propagation(self, log_dir):
        """Should not propagate to root logger."""
        app_logger = AppLogger(app_name="testapp", log_dir=log_dir)

        assert app_logger.logger.propagate is False


class TestLoggingFunctions:
    """Tests for module-level logging functions."""

    def setup_method(self):
        """Clear logger registry before each test."""
        _app_loggers.clear()

    def test_setup_app_logging(self, temp_dir):
        """Should setup and return app logger."""
        log_dir = temp_dir / "logs"

        logger = setup_app_logging(app_name="myapp", log_dir=log_dir, log_level="INFO")

        assert isinstance(logger, AppLogger)
        assert logger.app_name == "myapp"
        assert "myapp" in _app_loggers

    def test_setup_app_logging_string_level(self, temp_dir):
        """Should accept string log level."""
        log_dir = temp_dir / "logs"

        logger = setup_app_logging(app_name="myapp", log_dir=log_dir, log_level="DEBUG")

        assert logger.log_level == logging.DEBUG

    def test_get_app_logger(self, temp_dir):
        """Should get existing app logger."""
        log_dir = temp_dir / "logs"

        # First create it
        setup_app_logging("myapp", log_dir)

        # Then get it
        logger = get_app_logger("myapp")

        assert logger is not None
        assert logger.app_name == "myapp"

    def test_get_app_logger_not_found(self):
        """Should return None for non-existent logger."""
        logger = get_app_logger("nonexistent")

        assert logger is None

    def test_get_or_create_app_logger(self, temp_dir):
        """Should get existing or create new logger."""
        log_dir = temp_dir / "logs"

        # First call creates
        logger1 = get_or_create_app_logger("myapp", log_dir)

        # Second call returns same
        logger2 = get_or_create_app_logger("myapp", log_dir)

        assert logger1 is logger2

    def test_multiple_app_loggers(self, temp_dir):
        """Should handle multiple app loggers."""
        log_dir = temp_dir / "logs"

        logger1 = setup_app_logging("app1", log_dir)
        logger2 = setup_app_logging("app2", log_dir)

        assert logger1.app_name == "app1"
        assert logger2.app_name == "app2"
        assert get_app_logger("app1") is logger1
        assert get_app_logger("app2") is logger2
