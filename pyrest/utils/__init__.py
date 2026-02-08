"""
PyRest Utils Package

Shared utilities that can be used across multiple apps.

Available modules:
- tm1: TM1 connection management for both Cloud and On-Premise instances
- logging: App-specific file logging with smart formatting

Simple TM1 Usage:
    from pyrest.utils import get_tm1_instance

    # Connect to a configured instance
    tm1 = get_tm1_instance("production")
    cubes = tm1.cubes.get_all_names()
"""

from .logging import AppLogger, get_app_logger, setup_app_logging
from .tm1 import (
    TM1ConnectionManager,
    TM1InstanceConfig,
    close_all_tm1_instances,
    close_tm1_instance,
    # Simple interface functions
    get_tm1_instance,
    get_tm1_instance_info,
    is_tm1_available,
    list_tm1_instances,
    set_tm1_config_path,
)

__all__ = [
    # Logging utilities
    "AppLogger",
    "TM1ConnectionManager",
    # TM1 advanced interface
    "TM1InstanceConfig",
    "close_all_tm1_instances",
    "close_tm1_instance",
    "get_app_logger",
    # TM1 simple interface (recommended)
    "get_tm1_instance",
    "get_tm1_instance_info",
    "is_tm1_available",
    "list_tm1_instances",
    "set_tm1_config_path",
    "setup_app_logging",
]
