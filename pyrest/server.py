"""
Main server module for PyRest framework.
"""

import os
import sys
import logging
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any

import tornado.ioloop
import tornado.web
import tornado.httpserver

from .config import get_config, get_env
from .handlers import get_auth_handlers, BaseHandler, BASE_PATH
from .app_loader import AppLoader, AppsInfoHandler
from .venv_manager import get_venv_manager
from .process_manager import get_process_manager
from .nginx_generator import get_nginx_generator
from .admin import get_admin_handlers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("pyrest.server")


class IndexHandler(BaseHandler):
    """Root index handler."""
    
    async def get(self):
        """Return API information."""
        self.success(data={
            "name": "PyRest API Framework",
            "version": "1.0.0",
            "base_path": BASE_PATH,
            "endpoints": {
                "health": f"{BASE_PATH}/health",
                "apps": f"{BASE_PATH}/apps",
                "status": f"{BASE_PATH}/status",
                "admin": f"{BASE_PATH}/admin",
                "auth": {
                    "login": f"{BASE_PATH}/auth/login (POST)",
                    "register": f"{BASE_PATH}/auth/register (POST)",
                    "refresh": f"{BASE_PATH}/auth/refresh (POST)",
                    "me": f"{BASE_PATH}/auth/me (GET)",
                    "azure_login": f"{BASE_PATH}/auth/azure/login (GET)",
                    "azure_callback": f"{BASE_PATH}/auth/azure/callback (GET)"
                }
            }
        })


class StatusHandler(BaseHandler):
    """System status handler showing all apps and processes."""
    
    def initialize(self, app_loader: AppLoader = None, process_manager=None, **kwargs):
        super().initialize(**kwargs)
        self.app_loader = app_loader
        self.process_manager = process_manager
    
    async def get(self):
        """Return system status including all apps and processes."""
        status = {
            "framework": {
                "name": "PyRest",
                "version": "1.0.0",
                "base_path": BASE_PATH
            },
            "embedded_apps": [],
            "isolated_apps": []
        }
        
        if self.app_loader:
            # Embedded apps
            for app in self.app_loader.get_embedded_apps():
                status["embedded_apps"].append({
                    "name": app.name,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "version": app.version
                })
            
            # Isolated apps
            for app in self.app_loader.get_isolated_apps():
                app_status = {
                    "name": app.name,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "version": app.version,
                    "port": app.port
                }
                
                # Get process status
                if self.process_manager:
                    proc_status = self.process_manager.get_app_status(app.name)
                    if proc_status:
                        app_status["running"] = proc_status["is_running"]
                        app_status["pid"] = proc_status["pid"]
                    else:
                        app_status["running"] = False
                
                status["isolated_apps"].append(app_status)
        
        self.success(data=status)


class PyRestApplication(tornado.web.Application):
    """
    Main PyRest application class.
    """
    
    def __init__(self, extra_handlers: List = None, **settings):
        self.framework_config = get_config()
        self.env = get_env()
        self.app_loader = AppLoader()
        self.venv_manager = get_venv_manager()
        self.process_manager = get_process_manager()
        self.nginx_generator = get_nginx_generator()
        
        # Load and discover all apps
        app_handlers = self.app_loader.load_all_apps()
        
        # Combine all handlers with /pyrest base path
        handlers = [
            (rf"{BASE_PATH}", IndexHandler),
            (rf"{BASE_PATH}/", IndexHandler),
            (rf"{BASE_PATH}/apps", AppsInfoHandler, {"app_loader": self.app_loader}),
            (rf"{BASE_PATH}/status", StatusHandler, {
                "app_loader": self.app_loader,
                "process_manager": self.process_manager
            }),
        ]
        
        # Add auth handlers
        handlers.extend(get_auth_handlers())
        
        # Add admin handlers
        handlers.extend(get_admin_handlers(
            app_loader=self.app_loader,
            process_manager=self.process_manager
        ))
        
        # Add embedded app handlers
        handlers.extend(app_handlers)
        
        # Add any extra handlers
        if extra_handlers:
            handlers.extend(extra_handlers)
        
        # Application settings
        app_settings = {
            "debug": self.framework_config.debug,
            "cookie_secret": self.framework_config.jwt_secret,
            "xsrf_cookies": False,  # Disabled for API usage
            **settings
        }
        
        # Add static and template paths if they exist
        static_path = self.framework_config.get("static_path")
        if static_path and os.path.exists(static_path):
            app_settings["static_path"] = static_path
        
        template_path = self.framework_config.get("template_path")
        if template_path and os.path.exists(template_path):
            app_settings["template_path"] = template_path
        
        super().__init__(handlers, **app_settings)
        
        # Log loaded apps
        embedded_count = len(self.app_loader.loaded_apps)
        isolated_count = len(self.app_loader.isolated_apps)
        logger.info(f"PyRest application initialized with {len(handlers)} handlers")
        logger.info(f"Embedded apps: {list(self.app_loader.loaded_apps.keys())}")
        logger.info(f"Isolated apps: {list(self.app_loader.isolated_apps.keys())}")
    
    def setup_isolated_apps(self) -> bool:
        """
        Setup virtual environments and spawn isolated apps.
        Should be called before starting the server.
        
        Returns:
            True if all apps were set up successfully
        """
        isolated_apps = self.app_loader.get_isolated_apps()
        
        if not isolated_apps:
            logger.info("No isolated apps to set up")
            return True
        
        all_success = True
        
        for app_config in isolated_apps:
            logger.info(f"Setting up isolated app: {app_config.name}")
            
            # Ensure venv exists and dependencies are installed
            success, venv_path, message = self.venv_manager.ensure_venv(
                app_config.path,
                app_config.venv_path
            )
            
            if not success:
                logger.error(f"Failed to setup venv for {app_config.name}: {message}")
                all_success = False
                continue
            
            logger.info(f"Venv ready for {app_config.name}: {message}")
            
            # Spawn the isolated app
            app_process = self.process_manager.spawn_app(
                app_name=app_config.name,
                app_path=app_config.path,
                port=app_config.port,
                venv_path=venv_path if venv_path.exists() else None
            )
            
            if not app_process:
                logger.error(f"Failed to spawn isolated app: {app_config.name}")
                all_success = False
            else:
                logger.info(
                    f"Isolated app '{app_config.name}' spawned on port {app_config.port}"
                )
        
        return all_success
    
    def generate_nginx_config(self) -> Path:
        """Generate nginx configuration for all apps."""
        embedded_apps = self.app_loader.get_embedded_apps()
        isolated_apps = self.app_loader.get_isolated_apps()
        
        return self.nginx_generator.generate_and_save(
            embedded_apps=embedded_apps,
            isolated_apps=isolated_apps
        )


def create_app(**settings) -> PyRestApplication:
    """Create and return a PyRest application instance."""
    return PyRestApplication(**settings)


def run_server(
    host: Optional[str] = None,
    port: Optional[int] = None,
    debug: Optional[bool] = None,
    setup_isolated: bool = True,
    generate_nginx: bool = True
):
    """
    Run the PyRest server.
    
    Args:
        host: Host to bind to (default from config)
        port: Port to listen on (default from config)
        debug: Enable debug mode (default from config)
        setup_isolated: Whether to setup and spawn isolated apps
        generate_nginx: Whether to generate nginx configuration
    """
    config = get_config()
    
    host = host or config.host
    port = port or config.port
    debug = debug if debug is not None else config.debug
    
    # Update config if overridden
    if debug:
        config.set("debug", True)
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create application
    app = create_app()
    
    # Setup isolated apps
    if setup_isolated:
        logger.info("Setting up isolated apps...")
        app.setup_isolated_apps()
    
    # Generate nginx configuration
    if generate_nginx:
        nginx_config = app.generate_nginx_config()
        logger.info(f"Nginx configuration generated: {nginx_config}")
    
    # Create HTTP server
    server = tornado.httpserver.HTTPServer(app)
    server.listen(port, host)
    
    # Print startup summary
    logger.info("=" * 60)
    logger.info("PyRest Server starting...")
    logger.info(f"Main server: http://{host}:{port}{BASE_PATH}")
    logger.info(f"Debug mode: {debug}")
    logger.info("-" * 60)
    
    # Print app summary
    logger.info("Embedded Apps:")
    for app_info in app.app_loader.get_embedded_apps():
        logger.info(f"  - {app_info.name}: {BASE_PATH}{app_info.prefix}")
    
    if app.app_loader.get_isolated_apps():
        logger.info("Isolated Apps:")
        for app_info in app.app_loader.get_isolated_apps():
            logger.info(
                f"  - {app_info.name}: {BASE_PATH}{app_info.prefix} (port {app_info.port})"
            )
    
    logger.info("=" * 60)
    
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
        # Process manager will clean up via atexit
        tornado.ioloop.IOLoop.current().stop()


if __name__ == "__main__":
    run_server()
