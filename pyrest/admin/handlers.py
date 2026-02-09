"""
Admin API handlers for PyRest framework.
Provides endpoints for managing settings, viewing apps, and monitoring status.
Supports full app lifecycle: stop, clear-venv, create-venv, start, rebuild-venv.
"""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tornado.web

from ..auth import authenticated, get_auth_config
from ..config import get_config
from ..handlers import BASE_PATH, BaseHandler

logger = logging.getLogger("pyrest.admin")

# Admin base path
ADMIN_PATH = f"{BASE_PATH}/admin"


def _get_venv_info(app_path) -> dict[str, Any]:
    """Get venv status info for an isolated app."""
    app_path = Path(app_path)
    venv_path = app_path / ".venv"
    info = {
        "path": str(venv_path),
        "exists": venv_path.exists(),
        "valid": False,
        "has_requirements": (app_path / "requirements.txt").exists(),
    }
    if venv_path.exists():
        python_exe = venv_path / "bin" / "python"
        info["valid"] = python_exe.exists()
        # Calculate venv size
        try:
            total_size = sum(f.stat().st_size for f in venv_path.rglob("*") if f.is_file())
            info["size_mb"] = round(total_size / (1024 * 1024), 1)
        except OSError:
            info["size_mb"] = None
    return info


class AdminBaseHandler(BaseHandler):
    """Base handler for admin endpoints."""

    def initialize(self, app_loader=None, process_manager=None, **kwargs):
        super().initialize(**kwargs)
        self.app_loader = app_loader
        self.process_manager = process_manager


class AdminDashboardHandler(AdminBaseHandler):
    """Serves the admin dashboard HTML page."""

    @authenticated
    async def get(self):
        """Serve the admin dashboard."""
        admin_html = Path(__file__).parent / "static" / "index.html"

        if admin_html.exists():
            self.set_header("Content-Type", "text/html")
            content = await asyncio.to_thread(admin_html.read_text, encoding="utf-8")
            self.write(content)
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

    @authenticated
    async def get(self):
        """Return full system status (requires authentication)."""
        config = get_config()

        status = {
            "timestamp": datetime.now(UTC).isoformat(),
            "framework": {
                "name": "PyRest",
                "version": "1.0.0",
                "base_path": BASE_PATH,
                "host": config.host,
                "port": config.port,
                "debug": config.debug,
            },
            "apps": {"embedded": [], "isolated": [], "failed": []},
            "processes": [],
        }

        # Get embedded apps
        if self.app_loader:
            for app in self.app_loader.get_embedded_apps():
                status["apps"]["embedded"].append(
                    {
                        "name": app.name,
                        "version": app.version,
                        "description": app.description,
                        "prefix": f"{BASE_PATH}{app.prefix}",
                        "enabled": app.enabled,
                        "auth_required": app.auth_required,
                        "status": "loaded",
                    }
                )

            # Get isolated apps
            for app in self.app_loader.get_isolated_apps():
                app_info = {
                    "name": app.name,
                    "version": app.version,
                    "description": app.description,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "port": app.port,
                    "enabled": app.enabled,
                    "status": "loaded",
                }

                # Get process status (includes child worker PIDs)
                if self.process_manager:
                    proc_status = self.process_manager.get_app_status(app.name)
                    if proc_status:
                        app_info["process"] = {
                            "running": proc_status["is_running"],
                            "pid": proc_status["pid"],
                            "child_pids": proc_status.get("child_pids", []),
                            "total_processes": proc_status.get("total_processes", 0),
                            "started_at": proc_status.get("started_at"),
                        }

                # Venv status
                app_info["venv"] = _get_venv_info(app.path)

                status["apps"]["isolated"].append(app_info)

            # Get failed apps
            for failed_app in self.app_loader.get_failed_apps():
                status["apps"]["failed"].append(
                    {
                        "name": failed_app.get("name", "unknown"),
                        "path": failed_app.get("path", "unknown"),
                        "error": failed_app.get("error", "Unknown error"),
                        "error_type": failed_app.get("error_type", "unknown"),
                        "isolated": failed_app.get("isolated", False),
                        "port": failed_app.get("port"),
                        "status": "failed",
                    }
                )

        # Get all process statuses
        if self.process_manager:
            status["processes"] = self.process_manager.get_all_status()

        self.success(data=status)


class AdminAPIConfigHandler(AdminBaseHandler):
    """Get and update framework configuration."""

    @authenticated
    async def get(self):
        """Return current configuration (requires authentication)."""
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
            "jwt_expiry_hours": config.jwt_expiry_hours,
        }

        self.success(data=safe_config)

    @authenticated
    async def put(self):
        """Update configuration (requires authentication)."""
        body = self.get_json_body()
        config = get_config()

        # Only allow updating certain fields
        allowed_fields = ["debug", "cors_enabled", "cors_origins", "log_level", "jwt_expiry_hours"]

        updated = {}
        for field in allowed_fields:
            if field in body:
                config.set(field, body[field])
                updated[field] = body[field]

        if updated:
            try:
                config.save()
                self.success(data=updated, message="Configuration updated")
            except (OSError, ValueError, TypeError) as e:
                self.error(f"Failed to save configuration: {e!s}", 500)
        else:
            self.error("No valid fields to update", 400)


class AdminAPIAuthConfigHandler(AdminBaseHandler):
    """Get and update auth configuration."""

    @authenticated
    async def get(self):
        """Return auth configuration (secrets masked, requires authentication)."""
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
            "jwt_expiry_hours": auth_config.jwt_expiry_hours,
        }

        self.success(data=safe_config)

    def _mask_value(self, value: str) -> str:
        """Mask a sensitive value."""
        if not value or len(value) < 8:
            return "****"
        return value[:4] + "****" + value[-4:]


class AdminAPIAppsHandler(AdminBaseHandler):
    """Get all apps information."""

    @authenticated
    async def get(self):
        """Return list of all apps with details (requires authentication)."""
        apps: list[dict[str, Any]] = []

        if self.app_loader:
            # Embedded apps
            apps.extend(
                {
                    "name": app.name,
                    "type": "embedded",
                    "version": app.version,
                    "description": app.description,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "path": str(app.path),
                    "enabled": app.enabled,
                    "auth_required": app.auth_required,
                    "settings": app.settings,
                }
                for app in self.app_loader.get_embedded_apps()
            )

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
                    "has_requirements": app.has_requirements,
                }

                # Check process status (with child PIDs)
                if self.process_manager:
                    proc_status = self.process_manager.get_app_status(app.name)
                    if proc_status:
                        app_info["running"] = proc_status["is_running"]
                        app_info["process"] = {
                            "pid": proc_status["pid"],
                            "child_pids": proc_status.get("child_pids", []),
                            "total_processes": proc_status.get("total_processes", 0),
                        }
                    else:
                        app_info["running"] = False

                # Venv status
                app_info["venv"] = _get_venv_info(app.path)

                apps.append(app_info)

        self.success(data={"apps": apps, "count": len(apps)})


class AdminAPIAppDetailHandler(AdminBaseHandler):
    """Get details for a specific app."""

    @authenticated
    async def get(self, app_name: str):
        """Return details for a specific app (requires authentication)."""
        if not self.app_loader:
            self.error("App loader not available", 500)
            return

        # Check embedded apps
        if app_name in self.app_loader.loaded_apps:
            app = self.app_loader.loaded_apps[app_name]
            self.success(
                data={
                    "name": app.name,
                    "type": "embedded",
                    "version": app.version,
                    "description": app.description,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "path": str(app.path),
                    "enabled": app.enabled,
                    "settings": app.settings,
                }
            )
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
                "settings": app.settings,
            }

            if self.process_manager:
                proc_status = self.process_manager.get_app_status(app_name)
                if proc_status:
                    app_info["process"] = proc_status

            self.success(data=app_info)
            return

        self.error(f"App '{app_name}' not found", 404)


class AdminAPIAppControlHandler(AdminBaseHandler):
    """
    Control isolated apps lifecycle.

    Supported actions:
      - start:         Ensure venv + install deps + start app
      - stop:          Stop app (kills parent + all forked worker processes)
      - restart:       Stop + start
      - clear-venv:    Stop app if running, then delete .venv directory
      - create-venv:   Create .venv and install deps (does NOT start the app)
      - rebuild-venv:  Stop app, delete .venv, create fresh .venv, install deps, start app
      - processes:     Return detailed process tree (parent + worker PIDs)
      - venv-status:   Return venv info (exists, valid, size)
    """

    @authenticated
    async def post(self, app_name: str, action: str):
        """Control an isolated app (requires authentication)."""
        if not self.app_loader:
            self.error("App loader not available", 500)
            return

        if app_name not in self.app_loader.isolated_apps:
            self.error(f"Isolated app '{app_name}' not found", 404)
            return

        app = self.app_loader.isolated_apps[app_name]

        if action == "start":
            await self._action_start(app_name, app)
        elif action == "stop":
            await self._action_stop(app_name)
        elif action == "restart":
            await self._action_restart(app_name, app)
        elif action == "clear-venv":
            await self._action_clear_venv(app_name, app)
        elif action == "create-venv":
            await self._action_create_venv(app_name, app)
        elif action == "rebuild-venv":
            await self._action_rebuild_venv(app_name, app)
        elif action == "processes":
            await self._action_processes(app_name)
        elif action == "venv-status":
            await self._action_venv_status(app_name, app)
        else:
            self.error(f"Unknown action: {action}", 400)

    async def _action_start(self, app_name, app) -> None:
        """Ensure venv and start the app."""
        if not self.process_manager:
            self.error("Process manager not available", 500)
            return

        from ..venv_manager import get_venv_manager

        venv_manager = get_venv_manager()

        # Natively async -- no run_in_executor needed
        success, venv_path, msg = await venv_manager.ensure_venv(app.path)
        if not success:
            self.error(f"Failed to setup venv: {msg}", 500)
            return

        proc = await self.process_manager.spawn_app(
            app_name=app.name,
            app_path=app.path,
            port=app.port,
            venv_path=venv_path if venv_path.exists() else None,
        )

        if proc:
            self.success(
                message=f"App '{app_name}' started on port {app.port}",
                data={"pid": proc.pid, "port": app.port},
            )
        else:
            self.error(f"Failed to start app '{app_name}'", 500)

    async def _action_stop(self, app_name) -> None:
        """Stop the app and all its worker processes."""
        if not self.process_manager:
            self.error("Process manager not available", 500)
            return

        # Get process info before stopping
        proc_status = self.process_manager.get_app_status(app_name)
        killed_pids = []
        if proc_status:
            killed_pids = [proc_status["pid"], *proc_status.get("child_pids", [])]

        if await self.process_manager.stop_app(app_name):
            self.success(
                message=f"App '{app_name}' stopped",
                data={"killed_pids": killed_pids, "total_killed": len(killed_pids)},
            )
        else:
            self.error(f"Failed to stop app '{app_name}' (may not be running)", 500)

    async def _action_restart(self, app_name, app) -> None:
        """Stop app then start it again."""
        if self.process_manager:
            await self.process_manager.stop_app(app_name)
        await self._action_start(app_name, app)

    async def _action_clear_venv(self, app_name, app) -> None:
        """Stop app if running, then delete the .venv directory."""
        # Stop first if running
        if self.process_manager:
            proc_status = self.process_manager.get_app_status(app_name)
            if proc_status and proc_status.get("is_running"):
                await self.process_manager.stop_app(app_name)
                logger.info(f"Stopped {app_name} before clearing venv")

        from ..venv_manager import get_venv_manager

        venv_manager = get_venv_manager()

        venv_path = Path(app.path) / ".venv"
        if not venv_path.exists():
            self.success(
                message=f"No .venv found for '{app_name}'",
                data={"venv_path": str(venv_path), "existed": False},
            )
            return

        ok, msg = await venv_manager.remove_venv(venv_path)
        if ok:
            logger.info(f"Cleared venv for {app_name}: {venv_path}")
            self.success(
                message=f"Venv cleared for '{app_name}'",
                data={"venv_path": str(venv_path), "existed": True},
            )
        else:
            logger.error(f"Failed to clear venv for {app_name}: {msg}")
            self.error(f"Failed to clear venv: {msg}", 500)

    async def _action_create_venv(self, app_name, app) -> None:
        """Create .venv and install dependencies (does NOT start the app)."""
        from ..venv_manager import get_venv_manager

        venv_manager = get_venv_manager()
        venv_path = Path(app.path) / ".venv"

        if venv_path.exists():
            self.success(
                message=f"Venv already exists for '{app_name}'",
                data={"venv": _get_venv_info(app.path), "created": False},
            )
            return

        success, new_venv_path, msg = await venv_manager.ensure_venv(app.path)
        if success:
            logger.info(f"Created venv for {app_name}: {new_venv_path}")
            self.success(
                message=f"Venv created for '{app_name}'",
                data={"venv": _get_venv_info(app.path), "created": True},
            )
        else:
            logger.error(f"Failed to create venv for {app_name}: {msg}")
            self.error(f"Failed to create venv: {msg}", 500)

    async def _action_rebuild_venv(self, app_name, app) -> None:
        """Full lifecycle: stop -> clear venv -> create venv -> install deps -> start."""
        steps = []

        # Step 1: Stop if running
        if self.process_manager:
            proc_status = self.process_manager.get_app_status(app_name)
            if proc_status and proc_status.get("is_running"):
                await self.process_manager.stop_app(app_name)
                steps.append("stopped")
                logger.info(f"[rebuild] Stopped {app_name}")

        # Step 2: Clear venv
        from ..venv_manager import get_venv_manager

        venv_manager = get_venv_manager()

        venv_path = Path(app.path) / ".venv"
        if venv_path.exists():
            ok, msg = await venv_manager.remove_venv(venv_path)
            if not ok:
                self.error(f"Failed to clear venv during rebuild: {msg}", 500)
                return
            steps.append("venv_cleared")
            logger.info(f"[rebuild] Cleared venv for {app_name}")

        # Step 3: Create venv and install deps (natively async)
        success, new_venv_path, msg = await venv_manager.ensure_venv(app.path)
        if not success:
            self.error(f"Failed to create venv during rebuild: {msg}", 500)
            return
        steps.append("venv_created")
        steps.append("deps_installed")
        logger.info(f"[rebuild] Venv created and deps installed for {app_name}")

        # Step 4: Start app
        if not self.process_manager:
            self.error("Process manager not available", 500)
            return

        proc = await self.process_manager.spawn_app(
            app_name=app.name,
            app_path=app.path,
            port=app.port,
            venv_path=new_venv_path if new_venv_path.exists() else None,
        )

        if proc:
            steps.append("started")
            logger.info(f"[rebuild] App {app_name} started on port {app.port}")
            self.success(
                message=f"App '{app_name}' rebuilt and started",
                data={
                    "steps": steps,
                    "pid": proc.pid,
                    "port": app.port,
                    "venv": _get_venv_info(app.path),
                },
            )
        else:
            steps.append("start_failed")
            self.error(f"Venv rebuilt but failed to start app '{app_name}'", 500)

    async def _action_processes(self, app_name) -> None:
        """Return detailed process tree for the app."""
        if not self.process_manager:
            self.error("Process manager not available", 500)
            return

        proc_status = self.process_manager.get_app_status(app_name)
        if not proc_status:
            self.success(
                data={"running": False, "pid": None, "child_pids": [], "total_processes": 0}
            )
            return

        self.success(
            data={
                "running": proc_status["is_running"],
                "pid": proc_status["pid"],
                "child_pids": proc_status.get("child_pids", []),
                "total_processes": proc_status.get("total_processes", 0),
                "started_at": proc_status.get("started_at"),
                "port": proc_status.get("port"),
            }
        )

    async def _action_venv_status(self, app_name, app) -> None:
        """Return venv status for the app."""
        self.success(data=_get_venv_info(app.path))


class AdminAPILogsHandler(AdminBaseHandler):
    """Get recent logs."""

    @authenticated
    async def get(self):
        """Return recent log entries (requires authentication)."""
        # For now, return a placeholder
        # In production, you'd read from a log file or logging service
        self.success(data={"logs": [], "message": "Log viewing not yet implemented"})


class AdminStaticHandler(tornado.web.StaticFileHandler):
    """Serve admin static files."""

    def set_default_headers(self):
        # Allow caching for static files
        pass


def get_admin_handlers(app_loader=None, process_manager=None) -> list:
    """Get all admin handlers.
    All routes use /? pattern for optional trailing slash support.
    """
    init_kwargs = {"app_loader": app_loader, "process_manager": process_manager}

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
        (
            rf"{ADMIN_PATH}/api/apps/(?P<app_name>[^/]+)/(?P<action>start|stop|restart|clear-venv|create-venv|rebuild-venv|processes|venv-status)/?",
            AdminAPIAppControlHandler,
            init_kwargs,
        ),
        (rf"{ADMIN_PATH}/api/logs/?", AdminAPILogsHandler, init_kwargs),
        # Static files
        (rf"{ADMIN_PATH}/static/(.*)", AdminStaticHandler, {"path": str(static_path)}),
    ]

    return handlers
