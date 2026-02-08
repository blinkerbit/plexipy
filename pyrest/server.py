"""
Main server module for PyRest framework.
"""

import logging
from pathlib import Path

import tornado.httpserver
import tornado.ioloop
import tornado.web

from .admin import get_admin_handlers
from .app_loader import AppLoader, AppsInfoHandler
from .config import get_config, get_env
from .handlers import BASE_PATH, BaseHandler, get_auth_handlers
from .nginx_generator import get_nginx_generator
from .process_manager import ProcessManager, get_process_manager
from .venv_manager import get_venv_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("pyrest.server")


class IndexHandler(BaseHandler):
    """Root index handler."""

    def initialize(self, app_loader: AppLoader = None, **kwargs) -> None:
        super().initialize(**kwargs)
        self.app_loader = app_loader

    async def get(self) -> None:
        """Render landing page or return JSON if template unavailable."""
        embedded_apps = []
        isolated_apps = []
        failed_apps = []

        if self.app_loader:
            embedded_apps = self.app_loader.get_embedded_apps()
            isolated_apps = self.app_loader.get_isolated_apps()
            failed_apps = self.app_loader.get_failed_apps()

        # Try to render template, fall back to JSON
        try:
            from types import SimpleNamespace

            failed_objs = [SimpleNamespace(**app) for app in failed_apps]
            self.render(
                "landing.html",
                version="1.0.0",
                base_path=BASE_PATH,
                embedded_apps=embedded_apps,
                isolated_apps=isolated_apps,
                failed_apps=failed_objs,
            )
        except Exception as e:
            logger.warning(f"Template rendering failed, returning JSON: {e}")
            self.success(
                data={
                    "name": "PyRest API Framework",
                    "version": "1.0.0",
                    "base_path": BASE_PATH,
                    "embedded_apps": [{"name": a.name, "prefix": a.prefix} for a in embedded_apps],
                    "isolated_apps": [
                        {"name": a.name, "prefix": a.prefix, "port": a.port} for a in isolated_apps
                    ],
                    "failed_apps": failed_apps,
                    "endpoints": {
                        "health": f"{BASE_PATH}/health",
                        "apps": f"{BASE_PATH}/apps",
                        "status": f"{BASE_PATH}/status",
                        "admin": f"{BASE_PATH}/admin",
                    },
                }
            )


class StatusHandler(BaseHandler):
    """System status handler showing all apps and processes."""

    def initialize(
        self,
        app_loader: AppLoader | None = None,
        process_manager: ProcessManager | None = None,
        **kwargs,
    ) -> None:
        super().initialize(**kwargs)
        self.app_loader = app_loader
        self.process_manager = process_manager

    async def get(self) -> None:
        """Return system status including all apps and processes."""
        status = {
            "framework": {"name": "PyRest", "version": "1.0.0", "base_path": BASE_PATH},
            "embedded_apps": [],
            "isolated_apps": [],
            "failed_apps": [],
        }

        if self.app_loader:
            # Embedded apps
            for app in self.app_loader.get_embedded_apps():
                status["embedded_apps"].append(
                    {
                        "name": app.name,
                        "prefix": f"{BASE_PATH}{app.prefix}",
                        "version": app.version,
                        "status": "loaded",
                    }
                )

            # Isolated apps
            for app in self.app_loader.get_isolated_apps():
                app_status = {
                    "name": app.name,
                    "prefix": f"{BASE_PATH}{app.prefix}",
                    "version": app.version,
                    "port": app.port,
                    "status": "loaded",
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

            # Failed apps
            for failed_app in self.app_loader.get_failed_apps():
                status["failed_apps"].append(
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

        self.success(data=status)


class PyRestApplication(tornado.web.Application):
    """
    Main PyRest application class.
    """

    def __init__(self, extra_handlers: list | None = None, **settings):
        self.framework_config = get_config()
        self.env = get_env()
        self.app_loader = AppLoader()
        self.venv_manager = get_venv_manager()
        self.process_manager = get_process_manager()
        self.nginx_generator = get_nginx_generator()

        # Load and discover all apps
        app_handlers = self.app_loader.load_all_apps()

        # Combine all handlers with /pyrest base path
        # Use /? pattern for optional trailing slash support
        handlers = [
            (rf"{BASE_PATH}/?", IndexHandler, {"app_loader": self.app_loader}),
            (rf"{BASE_PATH}/apps/?", AppsInfoHandler, {"app_loader": self.app_loader}),
            (
                rf"{BASE_PATH}/status/?",
                StatusHandler,
                {"app_loader": self.app_loader, "process_manager": self.process_manager},
            ),
        ]

        # Add auth handlers
        handlers.extend(get_auth_handlers())

        # Add admin handlers
        handlers.extend(
            get_admin_handlers(app_loader=self.app_loader, process_manager=self.process_manager)
        )

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
            **settings,
        }

        # Add static and template paths if they exist
        static_path = self.framework_config.get("static_path")
        if static_path and Path(static_path).exists():
            app_settings["static_path"] = static_path

        # Determine template path: config > package default
        template_path = self.framework_config.get("template_path")
        default_template_path = str(Path(__file__).parent / "templates")

        if template_path and Path(template_path).exists():
            app_settings["template_path"] = template_path
            logger.info(f"Using config template path: {template_path}")
        elif Path(default_template_path).exists():
            app_settings["template_path"] = default_template_path
            logger.info(f"Using default template path: {default_template_path}")
        else:
            logger.warning(f"No template path found (checked: {default_template_path})")

        super().__init__(handlers, **app_settings)

        # Log loaded apps
        len(self.app_loader.loaded_apps)
        len(self.app_loader.isolated_apps)
        logger.info(f"PyRest application initialized with {len(handlers)} handlers")
        logger.info(f"Embedded apps: {list(self.app_loader.loaded_apps.keys())}")
        logger.info(f"Isolated apps: {list(self.app_loader.isolated_apps.keys())}")

    async def setup_isolated_apps(self) -> bool:
        """
        Async: setup virtual environments and spawn isolated apps.
        Should be called before starting the server (via run_sync).
        Failed apps are tracked but don't prevent other apps from starting.

        Returns:
            True if at least one app was set up successfully (or no apps to setup)
        """
        isolated_apps = self.app_loader.get_isolated_apps()

        if not isolated_apps:
            logger.info("No isolated apps to set up")
            return True

        success_count = 0

        for app_config in isolated_apps:
            try:
                logger.info(f"Setting up isolated app: {app_config.name}")

                app_path = app_config.path.resolve()
                venv_name = app_config.venv_path if app_config.venv_path else ".venv"

                # Async venv setup
                success, venv_path, message = await self.venv_manager.ensure_venv(
                    app_path, venv_name
                )
                if venv_path:
                    venv_path = venv_path.resolve()

                if not success:
                    error_msg = f"Failed to setup venv: {message}"
                    logger.error(f"Failed to setup venv for {app_config.name}: {message}")
                    self.app_loader.failed_apps[app_config.name] = {
                        "name": app_config.name,
                        "path": str(app_config.path),
                        "error": error_msg,
                        "error_type": "venv_setup_error",
                        "isolated": True,
                        "port": app_config.port,
                    }
                    self.app_loader.isolated_apps.pop(app_config.name, None)
                    continue

                logger.info(f"Venv ready for {app_config.name}: {message}")

                if not venv_path or not venv_path.exists():
                    error_msg = f"Venv path invalid or missing: {venv_path}"
                    logger.error(error_msg)
                    self.app_loader.failed_apps[app_config.name] = {
                        "name": app_config.name,
                        "path": str(app_config.path),
                        "error": error_msg,
                        "error_type": "venv_setup_error",
                        "isolated": True,
                        "port": app_config.port,
                    }
                    self.app_loader.isolated_apps.pop(app_config.name, None)
                    continue

                # Async spawn
                try:
                    app_process = await self.process_manager.spawn_app(
                        app_name=app_config.name,
                        app_path=app_path,
                        port=app_config.port,
                        venv_path=venv_path,
                    )

                    if not app_process:
                        error_msg = "Failed to spawn process"
                        logger.error(f"Failed to spawn isolated app: {app_config.name}")
                        self.app_loader.failed_apps[app_config.name] = {
                            "name": app_config.name,
                            "path": str(app_config.path),
                            "error": error_msg,
                            "error_type": "spawn_error",
                            "isolated": True,
                            "port": app_config.port,
                        }
                        self.app_loader.isolated_apps.pop(app_config.name, None)
                    else:
                        logger.info(
                            f"Isolated app '{app_config.name}' spawned on port {app_config.port}"
                        )
                        success_count += 1
                except Exception as e:
                    error_msg = f"Error spawning process: {e}"
                    logger.exception(f"Error spawning isolated app {app_config.name}: {e}")
                    import traceback

                    logger.debug(traceback.format_exc())
                    self.app_loader.failed_apps[app_config.name] = {
                        "name": app_config.name,
                        "path": str(app_config.path),
                        "error": error_msg,
                        "error_type": "spawn_error",
                        "isolated": True,
                        "port": app_config.port,
                    }
                    self.app_loader.isolated_apps.pop(app_config.name, None)

            except Exception as e:
                error_msg = f"Unexpected error during setup: {e}"
                logger.exception(f"Unexpected error setting up {app_config.name}: {e}")
                import traceback

                logger.debug(traceback.format_exc())
                self.app_loader.failed_apps[app_config.name] = {
                    "name": app_config.name,
                    "path": str(app_config.path),
                    "error": error_msg,
                    "error_type": "setup_error",
                    "isolated": True,
                    "port": getattr(app_config, "port", None),
                }
                self.app_loader.isolated_apps.pop(app_config.name, None)

        # Summary
        failed_count = sum(1 for v in self.app_loader.failed_apps.values() if v.get("isolated"))
        if failed_count:
            logger.warning(f"Failed to setup {failed_count} isolated app(s)")
        if success_count:
            logger.info(f"Successfully set up {success_count} isolated app(s)")

        return success_count > 0 or len(isolated_apps) == 0

    async def generate_nginx_config(self) -> Path | None:
        """
        Async: generate nginx configuration for all apps.
        Returns None if generation fails (doesn't prevent server startup).
        """
        try:
            embedded_apps = self.app_loader.get_embedded_apps()
            isolated_apps = self.app_loader.get_isolated_apps()

            return await self.nginx_generator.generate_and_save(
                embedded_apps=embedded_apps,
                isolated_apps=isolated_apps,
            )
        except Exception as e:
            logger.exception(f"Failed to generate nginx configuration: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            return None


def create_app(**settings) -> PyRestApplication:
    """Create and return a PyRest application instance."""
    return PyRestApplication(**settings)


def run_server(
    host: str | None = None,
    port: int | None = None,
    debug: bool | None = None,
    setup_isolated: bool = True,
    generate_nginx: bool = True,
) -> None:
    """
    Run the PyRest server.

    Async startup tasks (venv setup, spawn, nginx gen) are executed via
    IOLoop.run_sync before the persistent loop starts.
    """
    config = get_config()

    host = host or config.host
    port = port or config.port
    debug = debug if debug is not None else config.debug

    if debug:
        config.set("debug", True)
        logging.getLogger().setLevel(logging.DEBUG)

    app = create_app()
    io_loop = tornado.ioloop.IOLoop.current()

    # Run async setup tasks before the loop starts
    if setup_isolated:
        logger.info("Setting up isolated apps...")
        io_loop.run_sync(app.setup_isolated_apps)

    if generate_nginx:

        async def _gen_nginx() -> None:
            try:
                nginx_config = await app.generate_nginx_config()
                if nginx_config:
                    logger.info(f"Nginx configuration generated: {nginx_config}")
                else:
                    logger.warning("Nginx configuration generation failed (continuing)")
            except Exception as e:
                logger.exception(f"Nginx generation error: {e}")
                logger.warning("Server will continue without nginx configuration")

        io_loop.run_sync(_gen_nginx)

    # Start HTTP server
    server = tornado.httpserver.HTTPServer(app)
    server.listen(port, host)

    # Startup summary
    logger.info("=" * 60)
    logger.info("PyRest Server starting...")
    logger.info(f"Main server: http://{host}:{port}{BASE_PATH}")
    logger.info(f"Debug mode: {debug}")
    logger.info("-" * 60)

    embedded_apps = app.app_loader.get_embedded_apps()
    isolated_apps = app.app_loader.get_isolated_apps()
    failed_apps = app.app_loader.get_failed_apps()

    if embedded_apps:
        logger.info("Embedded Apps:")
        for ai in embedded_apps:
            logger.info(f"  ✓ {ai.name}: {BASE_PATH}{ai.prefix}")
    else:
        logger.info("Embedded Apps: None")

    if isolated_apps:
        logger.info("Isolated Apps:")
        for ai in isolated_apps:
            logger.info(f"  ✓ {ai.name}: {BASE_PATH}{ai.prefix} (port {ai.port})")
    else:
        logger.info("Isolated Apps: None")

    if failed_apps:
        logger.warning("Failed Apps:")
        for fa in failed_apps:
            app_type = "isolated" if fa.get("isolated") else "embedded"
            port_info = f" (port {fa.get('port')})" if fa.get("port") else ""
            logger.warning(
                f"  ✗ {fa.get('name', 'unknown')} ({app_type}){port_info}: "
                f"{fa.get('error', 'Unknown error')}"
            )

    logger.info("=" * 60)

    try:
        io_loop.start()
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
        io_loop.stop()


if __name__ == "__main__":
    run_server()
