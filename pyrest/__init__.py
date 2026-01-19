"""
PyRest - A Tornado-based REST API Framework
============================================

A modular framework that allows developers to easily create and deploy REST APIs.
Supports both embedded apps (in main process) and isolated apps (separate venv/process).

Features:
- Azure AD authentication
- JWT token support
- Automatic virtual environment management for isolated apps
- Nginx configuration generation
- Simple decorator-based routing

Quick Start:
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

# Main exports
from .handlers import BaseHandler, BASE_PATH
from .auth import authenticated, require_roles, get_auth_manager, get_auth_config
from .config import get_config, get_env
from .decorators import RestHandler, get, post, put, patch, delete, route, authenticated, roles
from .app_loader import AppLoader, AppConfig
from .venv_manager import get_venv_manager
from .process_manager import get_process_manager
from .nginx_generator import get_nginx_generator
from .server import create_app, run_server, PyRestApplication

__all__ = [
    # Version
    "__version__",
    
    # Handlers
    "BaseHandler",
    "RestHandler",
    "BASE_PATH",
    
    # Auth
    "authenticated",
    "require_roles",
    "roles",
    "get_auth_manager",
    "get_auth_config",
    
    # Config
    "get_config",
    "get_env",
    
    # Decorators
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "route",
    
    # App management
    "AppLoader",
    "AppConfig",
    "get_venv_manager",
    "get_process_manager",
    "get_nginx_generator",
    
    # Server
    "create_app",
    "run_server",
    "PyRestApplication",
]
