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

from .tm1 import (
    TM1InstanceConfig,
    TM1ConnectionManager,
    # Simple interface functions
    get_tm1_instance,
    list_tm1_instances,
    get_tm1_instance_info,
    close_tm1_instance,
    close_all_tm1_instances,
    set_tm1_config_path,
    is_tm1_available,
)
from .logging import AppLogger, get_app_logger, setup_app_logging

__all__ = [
    # TM1 simple interface (recommended)
    "get_tm1_instance",
    "list_tm1_instances",
    "get_tm1_instance_info",
    "close_tm1_instance",
    "close_all_tm1_instances",
    "set_tm1_config_path",
    "is_tm1_available",
    # TM1 advanced interface
    "TM1InstanceConfig",
    "TM1ConnectionManager",
    # Logging utilities
    "AppLogger",
    "get_app_logger",
    "setup_app_logging",
]
