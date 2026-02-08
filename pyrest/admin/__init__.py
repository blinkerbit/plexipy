"""
PyRest Admin Module
Provides admin UI and API endpoints for framework management.
"""

from .handlers import AdminDashboardHandler, get_admin_handlers

__all__ = ["AdminDashboardHandler", "get_admin_handlers"]
