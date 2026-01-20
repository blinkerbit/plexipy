"""
Admin API handlers for PyRest framework.
Provides endpoints for managing settings, viewing apps, and monitoring status.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

import tornado.web

from ..handlers import BaseHandler, BASE_PATH
from ..config import get_config, get_env
from ..auth import authenticated, require_roles, get_auth_config

logger = logging.getLogger("pyrest.admin")

# Admin base path
ADMIN_PATH = f"{BASE_PATH}/admin"


class AdminBaseHandler(BaseHandler):
    """Base handler for admin endpoints."""
    
    def initialize(self, app_loader=None, process_manager=None, **kwargs):
        super().initialize(**kwargs)
        self.app_loader = app_loader
        self.process_manager = process_manager


class AdminDashboardHandler(AdminBaseHandler):
    """Serves the admin dashboard HTML page."""
    
    async def get(self):
        """Serve the admin dashboard."""
        # Get the admin UI HTML file
        admin_html = Path(__file__).parent / "static" / "index.html"
        
        if admin_html.exists():
            self.set_header("Content-Type", "text/html")
            with open(admin_html, "r", encoding="utf-8") as f:
                self.write(f.read())
        else:
            self.set_header("Content-Type", "text/html")
            self.write(self._get_inline_dashboard())
    
    def _get_inline_dashboard(self) -> str:
        """Return inline dashboard HTML if static file not found."""
        return f'''<!DOCTYPE html>
<html><head><title>PyRest Admin</title></head>
<body>
<h1>PyRest Admin Dashboard</h1>
<p>Static files not found. Please ensure admin/static/index.html exists.</p>
<p><a href="{ADMIN_PATH}/api/status">View API Status</a></p>
</body></html>'''


class AdminAPIStatusHandler(AdminBaseHandler):
    """Get complete system status."""
    
    async def get(self):
        """Return full system status."""
        config = get_config()
        
        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "framework": {
                "name": "PyRest",
                "version": "1.0.0",
                "base_path": BASE_PATH,
                "host": config.host,
                "port": config.port,
                "debug": config.debug
            },
            "apps": {
                "embedded": [],
                "isolated": [],
                "failed": []
            },
            "processes": []
        }
        
        # Get embedded apps
        if self.app_loader:
            for app in self.app_loader.get_embedded_apps():
                status["apps"]["embedded"].append({
                    "name": app.name,
                    "version": app.version,
                    "description": app.description,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "enabled": app.enabled,
                    "auth_required": app.auth_required,
                    "status": "loaded"
                })
            
            # Get isolated apps
            for app in self.app_loader.get_isolated_apps():
                app_info = {
                    "name": app.name,
                    "version": app.version,
                    "description": app.description,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "port": app.port,
                    "enabled": app.enabled,
                    "status": "loaded"
                }
                
                # Get process status
                if self.process_manager:
                    proc_status = self.process_manager.get_app_status(app.name)
                    if proc_status:
                        app_info["process"] = {
                            "running": proc_status["is_running"],
                            "pid": proc_status["pid"],
                            "started_at": proc_status.get("started_at")
                        }
                
                status["apps"]["isolated"].append(app_info)
            
            # Get failed apps
            for failed_app in self.app_loader.get_failed_apps():
                status["apps"]["failed"].append({
                    "name": failed_app.get("name", "unknown"),
                    "path": failed_app.get("path", "unknown"),
                    "error": failed_app.get("error", "Unknown error"),
                    "error_type": failed_app.get("error_type", "unknown"),
                    "isolated": failed_app.get("isolated", False),
                    "port": failed_app.get("port"),
                    "status": "failed"
                })
        
        # Get all process statuses
        if self.process_manager:
            status["processes"] = self.process_manager.get_all_status()
        
        self.success(data=status)


class AdminAPIConfigHandler(AdminBaseHandler):
    """Get and update framework configuration."""
    
    async def get(self):
        """Return current configuration."""
        config = get_config()
        
        # Return safe config (exclude secrets)
        safe_config = {
            "host": config.host,
            "port": config.port,
            "debug": config.debug,
            "base_path": config.base_path,
            "apps_folder": config.apps_folder,
            "cors_enabled": config.get("cors_enabled", True),
            "cors_origins": config.get("cors_origins", ["*"]),
            "log_level": config.get("log_level", "INFO"),
            "isolated_app_base_port": config.isolated_app_base_port,
            "jwt_expiry_hours": config.jwt_expiry_hours
        }
        
        self.success(data=safe_config)
    
    @authenticated
    async def put(self):
        """Update configuration (requires authentication)."""
        body = self.get_json_body()
        config = get_config()
        
        # Only allow updating certain fields
        allowed_fields = [
            "debug", "cors_enabled", "cors_origins", 
            "log_level", "jwt_expiry_hours"
        ]
        
        updated = {}
        for field in allowed_fields:
            if field in body:
                config.set(field, body[field])
                updated[field] = body[field]
        
        if updated:
            try:
                config.save()
                self.success(data=updated, message="Configuration updated")
            except Exception as e:
                self.error(f"Failed to save configuration: {str(e)}", 500)
        else:
            self.error("No valid fields to update", 400)


class AdminAPIAuthConfigHandler(AdminBaseHandler):
    """Get and update auth configuration."""
    
    async def get(self):
        """Return auth configuration (secrets masked)."""
        auth_config = get_auth_config()
        
        # Mask sensitive values
        safe_config = {
            "provider": auth_config.get("provider", "azure_ad"),
            "tenant_id": self._mask_value(auth_config.tenant_id),
            "client_id": self._mask_value(auth_config.client_id),
            "client_secret": "********" if auth_config.client_secret else "",
            "redirect_uri": auth_config.redirect_uri,
            "scopes": auth_config.scopes,
            "is_configured": auth_config.is_configured,
            "jwt_expiry_hours": auth_config.jwt_expiry_hours
        }
        
        self.success(data=safe_config)
    
    def _mask_value(self, value: str) -> str:
        """Mask a sensitive value."""
        if not value or len(value) < 8:
            return "****"
        return value[:4] + "****" + value[-4:]


class AdminAPIAppsHandler(AdminBaseHandler):
    """Get all apps information."""
    
    async def get(self):
        """Return list of all apps with details."""
        apps = []
        
        if self.app_loader:
            # Embedded apps
            for app in self.app_loader.get_embedded_apps():
                apps.append({
                    "name": app.name,
                    "type": "embedded",
                    "version": app.version,
                    "description": app.description,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "path": str(app.path),
                    "enabled": app.enabled,
                    "auth_required": app.auth_required,
                    "settings": app.settings
                })
            
            # Isolated apps
            for app in self.app_loader.get_isolated_apps():
                app_info = {
                    "name": app.name,
                    "type": "isolated",
                    "version": app.version,
                    "description": app.description,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "path": str(app.path),
                    "port": app.port,
                    "enabled": app.enabled,
                    "auth_required": app.auth_required,
                    "settings": app.settings,
                    "has_requirements": app.has_requirements
                }
                
                # Check process status
                if self.process_manager:
                    proc_status = self.process_manager.get_app_status(app.name)
                    app_info["running"] = proc_status["is_running"] if proc_status else False
                
                apps.append(app_info)
        
        self.success(data={"apps": apps, "count": len(apps)})


class AdminAPIAppDetailHandler(AdminBaseHandler):
    """Get details for a specific app."""
    
    async def get(self, app_name: str):
        """Return details for a specific app."""
        if not self.app_loader:
            self.error("App loader not available", 500)
            return
        
        # Check embedded apps
        if app_name in self.app_loader.loaded_apps:
            app = self.app_loader.loaded_apps[app_name]
            self.success(data={
                "name": app.name,
                "type": "embedded",
                "version": app.version,
                "description": app.description,
                "prefix": f"{BASE_PATH}{app.prefix}",
                "path": str(app.path),
                "enabled": app.enabled,
                "settings": app.settings
            })
            return
        
        # Check isolated apps
        if app_name in self.app_loader.isolated_apps:
            app = self.app_loader.isolated_apps[app_name]
            app_info = {
                "name": app.name,
                "type": "isolated",
                "version": app.version,
                "description": app.description,
                "prefix": f"{BASE_PATH}{app.prefix}",
                "path": str(app.path),
                "port": app.port,
                "enabled": app.enabled,
                "settings": app.settings
            }
            
            if self.process_manager:
                proc_status = self.process_manager.get_app_status(app_name)
                if proc_status:
                    app_info["process"] = proc_status
            
            self.success(data=app_info)
            return
        
        self.error(f"App '{app_name}' not found", 404)


class AdminAPIAppControlHandler(AdminBaseHandler):
    """Control isolated apps (start/stop/restart)."""
    
    @authenticated
    async def post(self, app_name: str, action: str):
        """Control an isolated app."""
        if not self.app_loader or not self.process_manager:
            self.error("Required services not available", 500)
            return
        
        if app_name not in self.app_loader.isolated_apps:
            self.error(f"Isolated app '{app_name}' not found", 404)
            return
        
        app = self.app_loader.isolated_apps[app_name]
        
        if action == "start":
            from ..venv_manager import get_venv_manager
            venv_manager = get_venv_manager()
            
            # Ensure venv
            success, venv_path, msg = venv_manager.ensure_venv(app.path, app.venv_path)
            if not success:
                self.error(f"Failed to setup venv: {msg}", 500)
                return
            
            # Spawn app
            proc = self.process_manager.spawn_app(
                app_name=app.name,
                app_path=app.path,
                port=app.port,
                venv_path=venv_path if venv_path.exists() else None
            )
            
            if proc:
                self.success(message=f"App '{app_name}' started on port {app.port}")
            else:
                self.error(f"Failed to start app '{app_name}'", 500)
        
        elif action == "stop":
            if self.process_manager.stop_app(app_name):
                self.success(message=f"App '{app_name}' stopped")
            else:
                self.error(f"Failed to stop app '{app_name}'", 500)
        
        elif action == "restart":
            self.process_manager.stop_app(app_name)
            
            from ..venv_manager import get_venv_manager
            venv_manager = get_venv_manager()
            
            success, venv_path, msg = venv_manager.ensure_venv(app.path, app.venv_path)
            
            proc = self.process_manager.spawn_app(
                app_name=app.name,
                app_path=app.path,
                port=app.port,
                venv_path=venv_path if success and venv_path.exists() else None
            )
            
            if proc:
                self.success(message=f"App '{app_name}' restarted")
            else:
                self.error(f"Failed to restart app '{app_name}'", 500)
        
        else:
            self.error(f"Unknown action: {action}", 400)


class AdminAPILogsHandler(AdminBaseHandler):
    """Get recent logs."""
    
    async def get(self):
        """Return recent log entries."""
        # For now, return a placeholder
        # In production, you'd read from a log file or logging service
        self.success(data={
            "logs": [],
            "message": "Log viewing not yet implemented"
        })


class AdminStaticHandler(tornado.web.StaticFileHandler):
    """Serve admin static files."""
    
    def set_default_headers(self):
        # Allow caching for static files
        pass


def get_admin_handlers(app_loader=None, process_manager=None) -> list:
    """Get all admin handlers.
    All routes use /? pattern for optional trailing slash support.
    """
    init_kwargs = {
        "app_loader": app_loader,
        "process_manager": process_manager
    }
    
    # Get static path
    static_path = Path(__file__).parent / "static"
    
    handlers = [
        # Dashboard UI
        (rf"{ADMIN_PATH}/?", AdminDashboardHandler, init_kwargs),
        
        # API endpoints
        (rf"{ADMIN_PATH}/api/status/?", AdminAPIStatusHandler, init_kwargs),
        (rf"{ADMIN_PATH}/api/config/?", AdminAPIConfigHandler, init_kwargs),
        (rf"{ADMIN_PATH}/api/auth-config/?", AdminAPIAuthConfigHandler, init_kwargs),
        (rf"{ADMIN_PATH}/api/apps/?", AdminAPIAppsHandler, init_kwargs),
        (rf"{ADMIN_PATH}/api/apps/(?P<app_name>[^/]+)/?", AdminAPIAppDetailHandler, init_kwargs),
        (rf"{ADMIN_PATH}/api/apps/(?P<app_name>[^/]+)/(?P<action>start|stop|restart)/?", 
         AdminAPIAppControlHandler, init_kwargs),
        (rf"{ADMIN_PATH}/api/logs/?", AdminAPILogsHandler, init_kwargs),
        
        # Static files
        (rf"{ADMIN_PATH}/static/(.*)", AdminStaticHandler, {"path": str(static_path)}),
    ]
    
    return handlers
