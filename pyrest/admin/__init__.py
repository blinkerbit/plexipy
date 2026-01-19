"""
PyRest Admin Module
Provides admin UI and API endpoints for framework management.
"""

from .handlers import get_admin_handlers, AdminDashboardHandler

__all__ = ["get_admin_handlers", "AdminDashboardHandler"]
