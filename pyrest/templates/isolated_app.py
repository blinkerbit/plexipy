#!/usr/bin/env python3
"""
Isolated App Runner for PyRest framework.

This script is used to run isolated apps as standalone Tornado servers.
It reads configuration from environment variables set by the ProcessManager.

Environment variables:
- PYREST_APP_NAME: Name of the app
- PYREST_APP_PATH: Path to the app directory
- PYREST_APP_PORT: Port to run the app on
- PYREST_MAIN_PORT: Main PyRest server port
- PYREST_BASE_PATH: Base URL path (e.g., /pyrest)
- PYREST_AUTH_CONFIG: Path to auth_config.json
"""

import os
import sys
import json
import logging
import importlib.util
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import tornado.ioloop
import tornado.web
import tornado.httpserver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("pyrest.isolated")


class IsolatedBaseHandler(tornado.web.RequestHandler):
    """
    Base handler for isolated apps.
    Provides common functionality and JWT validation.
    """
    
    def initialize(self, app_config: Optional[Dict[str, Any]] = None):
        """Initialize handler with app configuration."""
        self.app_config = app_config or {}
        self._current_user = None
    
    def set_default_headers(self):
        """Set default headers including CORS."""
        self.set_header("Content-Type", "application/json")
        
        # CORS headers
        origin = self.request.headers.get("Origin", "*")
        self.set_header("Access-Control-Allow-Origin", origin)
        self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.set_header("Access-Control-Allow-Credentials", "true")
        self.set_header("Access-Control-Max-Age", "86400")
    
    def options(self, *args, **kwargs):
        """Handle preflight CORS requests."""
        self.set_status(204)
        self.finish()
    
    @property
    def current_user(self) -> Optional[Dict[str, Any]]:
        """Property to access current user."""
        return self._current_user
    
    def get_json_body(self) -> Dict[str, Any]:
        """Parse and return the JSON request body."""
        try:
            return json.loads(self.request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    
    def load_args(self) -> Dict[str, Any]:
        """
        Load all request arguments into a unified dictionary.
        
        Returns a dict with:
            - args['path']  - URL path parameters (e.g., /instance/{name} -> args['path']['name'])
            - args['query'] - URL query parameters (e.g., ?limit=10 -> args['query']['limit'])
            - args['body']  - JSON request body as dict
        
        Example usage in handler:
            args = self.load_args()
            instance_name = args['path'].get('instance_name')
            limit = args['query'].get('limit', '100')
            data = args['body']
        """
        # Path parameters (from URL pattern captures)
        path_args = dict(self.path_kwargs) if hasattr(self, 'path_kwargs') else {}
        
        # Query parameters (flatten single-value lists)
        query_args = {}
        for key, values in self.request.arguments.items():
            if len(values) == 1:
                # Single value - decode and return as string
                query_args[key] = values[0].decode('utf-8') if isinstance(values[0], bytes) else values[0]
            else:
                # Multiple values - return as list of strings
                query_args[key] = [v.decode('utf-8') if isinstance(v, bytes) else v for v in values]
        
        # Body (JSON parsed)
        body = self.get_json_body()
        
        return {
            'path': path_args,
            'query': query_args,
            'body': body
        }
    
    def success(self, data: Any = None, message: str = "Success", status_code: int = 200):
        """Send a success response."""
        self.set_status(status_code)
        response = {"success": True, "message": message}
        if data is not None:
            response["data"] = data
        self.write(response)
    
    def error(self, message: str, status_code: int = 400, data: Any = None):
        """Send an error response."""
        self.set_status(status_code)
        response = {"success": False, "error": message}
        if data is not None:
            response["data"] = data
        self.write(response)


class AuthConfig:
    """Load and cache auth configuration."""
    
    _instance = None
    _config = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """Load auth configuration from file."""
        auth_config_path = os.environ.get("PYREST_AUTH_CONFIG", "auth_config.json")
        
        default_config = {
            "jwt_secret": "change-this-secret",
            "jwt_algorithm": "HS256"
        }
        
        try:
            config_path = Path(auth_config_path)
            if config_path.exists():
                with open(config_path, "r") as f:
                    file_config = json.load(f)
                    default_config.update(file_config)
        except Exception as e:
            logger.warning(f"Could not load auth config: {e}")
        
        self._config = default_config
    
    @property
    def jwt_secret(self) -> str:
        return self._config.get("jwt_secret", "")
    
    @property
    def jwt_algorithm(self) -> str:
        return self._config.get("jwt_algorithm", "HS256")


def authenticated(method):
    """
    Decorator for requiring authentication.
    Validates JWT tokens using the shared auth configuration.
    """
    import functools
    
    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        auth_header = self.request.headers.get("Authorization", "")
        
        if not auth_header.startswith("Bearer "):
            self.set_status(401)
            self.write({"error": "Missing or invalid Authorization header"})
            return
        
        token = auth_header[7:]
        
        try:
            import jwt
            auth_config = AuthConfig()
            payload = jwt.decode(
                token, 
                auth_config.jwt_secret, 
                algorithms=[auth_config.jwt_algorithm]
            )
            self._current_user = payload
        except Exception as e:
            self.set_status(401)
            self.write({"error": f"Invalid token: {str(e)}"})
            return
        
        return await method(self, *args, **kwargs)
    
    return wrapper


class HealthHandler(IsolatedBaseHandler):
    """Health check endpoint for the isolated app."""
    
    async def get(self):
        app_name = os.environ.get("PYREST_APP_NAME", "unknown")
        self.success(data={
            "status": "healthy",
            "app": app_name,
            "isolated": True
        })


def load_app_handlers(app_path: Path) -> List[Tuple]:
    """Load handlers from the app's handlers.py file."""
    handlers_file = app_path / "handlers.py"
    
    if not handlers_file.exists():
        logger.error(f"handlers.py not found in {app_path}")
        return []
    
    try:
        spec = importlib.util.spec_from_file_location("app_handlers", handlers_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules["app_handlers"] = module
        spec.loader.exec_module(module)
        
        # Get handlers
        if hasattr(module, "get_handlers"):
            return module.get_handlers()
        elif hasattr(module, "handlers"):
            return module.handlers
        else:
            logger.warning("No get_handlers() or handlers list found")
            return []
            
    except Exception as e:
        logger.error(f"Error loading handlers: {e}")
        import traceback
        traceback.print_exc()
        return []


def load_app_config(app_path: Path) -> Dict[str, Any]:
    """Load the app's config.json."""
    config_file = app_path / "config.json"
    
    if config_file.exists():
        try:
            with open(config_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load config.json: {e}")
    
    return {}


def create_application(app_path: Path, base_path: str, app_name: str) -> tornado.web.Application:
    """Create the Tornado application for the isolated app."""
    
    # Load app config
    app_config = load_app_config(app_path)
    
    # Load handlers from app
    raw_handlers = load_app_handlers(app_path)
    
    # Build full URL paths with base_path and app prefix
    prefix = app_config.get("prefix", f"/{app_name}")
    handlers = []
    
    # Add health check
    handlers.append((f"{base_path}{prefix}/health", HealthHandler))
    
    for handler_tuple in raw_handlers:
        if len(handler_tuple) >= 2:
            path = handler_tuple[0]
            handler_class = handler_tuple[1]
            
            # Ensure path starts with /
            if not path.startswith("/"):
                path = "/" + path
            
            # Build full path
            full_path = f"{base_path}{prefix}{path}"
            
            # Handle init kwargs
            if len(handler_tuple) >= 3:
                init_kwargs = handler_tuple[2].copy() if isinstance(handler_tuple[2], dict) else {}
            else:
                init_kwargs = {}
            
            init_kwargs["app_config"] = app_config
            
            handlers.append((full_path, handler_class, init_kwargs))
            logger.info(f"Registered handler: {full_path}")
            
            # Also register without trailing slash for paths ending with /
            if full_path.endswith("/") and len(full_path) > 1:
                no_slash_path = full_path.rstrip("/")
                handlers.append((no_slash_path, handler_class, init_kwargs))
                logger.info(f"Registered handler: {no_slash_path} (no trailing slash)")
    
    # Application settings
    settings = {
        "debug": app_config.get("debug", False),
        "xsrf_cookies": False
    }
    
    return tornado.web.Application(handlers, **settings)


def main():
    """Main entry point for isolated app."""
    
    # Read configuration from environment
    app_name = os.environ.get("PYREST_APP_NAME")
    app_path_str = os.environ.get("PYREST_APP_PATH")
    port_str = os.environ.get("PYREST_APP_PORT")
    base_path = os.environ.get("PYREST_BASE_PATH", "/pyrest")
    num_processes = int(os.environ.get("PYREST_NUM_PROCESSES", "8"))
    
    if not app_name or not app_path_str or not port_str:
        logger.error("Missing required environment variables")
        logger.error(f"PYREST_APP_NAME={app_name}")
        logger.error(f"PYREST_APP_PATH={app_path_str}")
        logger.error(f"PYREST_APP_PORT={port_str}")
        sys.exit(1)
    
    try:
        port = int(port_str)
    except ValueError:
        logger.error(f"Invalid port: {port_str}")
        sys.exit(1)
    
    app_path = Path(app_path_str)
    
    if not app_path.exists():
        logger.error(f"App path does not exist: {app_path}")
        sys.exit(1)
    
    # Add app path to sys.path
    if str(app_path) not in sys.path:
        sys.path.insert(0, str(app_path))
    if str(app_path.parent) not in sys.path:
        sys.path.insert(0, str(app_path.parent))
    
    # Create application
    app = create_application(app_path, base_path, app_name)
    
    # Create server with forking support
    server = tornado.httpserver.HTTPServer(app)
    server.bind(port, "0.0.0.0")  # Bind on all interfaces (needed for Docker networking)
    
    # Fork multiple processes for handling requests
    # Note: start() must be called before IOLoop.start()
    server.start(num_processes)  # Fork 8 processes by default
    
    logger.info("=" * 50)
    logger.info(f"Isolated app '{app_name}' starting...")
    logger.info(f"Listening on http://0.0.0.0:{port}")
    logger.info(f"Base path: {base_path}/{app_name}")
    logger.info(f"Worker processes: {num_processes}")
    logger.info("=" * 50)
    
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        logger.info(f"App '{app_name}' shutting down...")
        tornado.ioloop.IOLoop.current().stop()


if __name__ == "__main__":
    main()
