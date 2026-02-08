"""
PyRest - A Tornado-based REST API Framework
============================================

A modular framework that allows developers to easily create and deploy REST APIs.
Supports both embedded apps (in main process) and isolated apps (separate venv/process).

Features:
- Pydantic-based request validation
- Simple handler base class for easy development
- Azure AD authentication
- JWT token support
- Automatic virtual environment management for isolated apps
- Nginx configuration generation
- Simple decorator-based routing

Quick Start (Simple - Recommended for beginners):
    from pyrest.simple_handler import SimpleHandler
    from pyrest.validation import RequestModel, field

    class FetchInput(RequestModel):
        cube: str = field(description="Cube name")
        element: str = field(description="Element")

    class MyHandler(SimpleHandler):
        async def post(self):
            data = self.get_data(model=FetchInput)
            if not data:
                return

            result = await self.run_async(do_something, data.cube, data.element)
            self.ok(result)

Quick Start (Advanced):
    from pyrest.handlers import BaseHandler
    from pyrest.auth import authenticated
    from pyrest.decorators import RestHandler, get, post

    class MyHandler(BaseHandler):
        async def get(self):
            self.success(data={"message": "Hello!"})

        @authenticated
        async def post(self):
            body = self.get_json_body()
            self.success(data=body)
"""

__version__ = "1.0.0"
__author__ = "PyRest Team"

# Main exports - Simple API (recommended for beginners)
from .app_loader import AppConfig, AppLoader
from .auth import authenticated, get_auth_config, get_auth_manager, require_roles
from .config import get_config, get_env
from .decorators import RestHandler, delete, get, patch, post, put, roles, route

# Main exports - Advanced API
from .handlers import BASE_PATH, BaseHandler
from .nginx_generator import get_nginx_generator
from .process_manager import get_process_manager
from .server import PyRestApplication, create_app, run_server
from .simple_handler import SimpleHandler
from .validation import RequestModel, field, validate, validate_required
from .venv_manager import get_venv_manager

__all__ = [
    "BASE_PATH",
    "AppConfig",
    # App management
    "AppLoader",
    # Handlers
    "BaseHandler",
    "PyRestApplication",
    "RequestModel",
    "RestHandler",
    # Simple API (recommended)
    "SimpleHandler",
    # Version
    "__version__",
    # Auth
    "authenticated",
    # Server
    "create_app",
    "delete",
    "field",
    # Decorators
    "get",
    "get_auth_config",
    "get_auth_manager",
    # Config
    "get_config",
    "get_env",
    "get_nginx_generator",
    "get_process_manager",
    "get_venv_manager",
    "patch",
    "post",
    "put",
    "require_roles",
    "roles",
    "route",
    "run_server",
    "validate",
    "validate_required",
]
