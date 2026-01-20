"""
PyRest Utils Package

Shared utilities that can be used across multiple apps.

Available modules:
- tm1: TM1 connection management for both Cloud and On-Premise instances
- logging: App-specific file logging with smart formatting
"""

from .tm1 import TM1InstanceConfig, TM1ConnectionManager
from .logging import AppLogger, get_app_logger, setup_app_logging

__all__ = [
    # TM1 utilities
    "TM1InstanceConfig",
    "TM1ConnectionManager",
    # Logging utilities
    "AppLogger",
    "get_app_logger",
    "setup_app_logging",
]
