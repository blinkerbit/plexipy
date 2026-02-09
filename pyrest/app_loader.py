"""
App discovery and loading module for PyRest framework.
Dynamically loads apps from the apps folder and mounts their handlers.
"""

import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .config import AppConfigParser, get_config
from .handlers import BASE_PATH, BaseHandler
from .utils.logging import AppLogger, setup_app_logging

logger = logging.getLogger("pyrest.app_loader")


class AppConfig:
    """
    Configuration for a loaded app.

    Uses AppConfigParser to handle os_vars and environment variable resolution.
    Each app gets its own file logger for isolated logging.
    """

    # Default log directory for all apps
    LOG_DIR = "logs"

    def __init__(self, app_path: Path, config_data: dict[str, Any]):
        self.path = app_path
        self.name = config_data.get("name", app_path.name)
        self._raw_config = config_data

        # Check if isolated before parsing (needed for os_vars handling)
        self._check_isolated = (self.path / "requirements.txt").exists()

        # Use AppConfigParser for enhanced config parsing with os_vars support
        self._config_parser = AppConfigParser(
            app_name=self.name, config_data=config_data, is_isolated=self._check_isolated
        )

        # Get resolved config values
        resolved = self._config_parser.get_resolved_config()

        self.version = resolved.get("version", "1.0.0")
        self.description = resolved.get("description", "")
        self.enabled = resolved.get("enabled", True)
        self.prefix = resolved.get("prefix", f"/{self.name}")
        self.settings = resolved.get("settings", {})
        self.auth_required = resolved.get("auth_required", False)
        self.allowed_roles = resolved.get("allowed_roles", [])
        self.venv_path = resolved.get("venv_path", ".venv")

        # Port configuration (None means auto-assign)
        self._port = resolved.get("port", None)
        self._assigned_port: int | None = None

        # Setup app-specific logging
        log_level = self.settings.get("log_level", "INFO")
        log_dir = self.settings.get("log_dir", self.LOG_DIR)
        self._app_logger = setup_app_logging(
            app_name=self.name, log_dir=log_dir, log_level=log_level, console_output=False
        )

        self._app_logger.info(f"App '{self.name}' v{self.version} initialized")
        self._app_logger.info(f"Loaded {len(self._config_parser.get_all_os_vars())} os_vars")

        logger.info(
            f"Loaded app config for '{self.name}' with {len(self._config_parser.get_all_os_vars())} os_vars"
        )

    @property
    def has_requirements(self) -> bool:
        """Check if the app has a requirements.txt file."""
        return (self.path / "requirements.txt").exists()

    @property
    def is_isolated(self) -> bool:
        """
        Check if the app should run in isolation.
        An app is isolated if it has a requirements.txt file.
        """
        return self.has_requirements

    @property
    def port(self) -> int | None:
        """Get the configured or assigned port."""
        return self._assigned_port or self._port

    @port.setter
    def port(self, value: int) -> None:
        """Set the assigned port."""
        self._assigned_port = value

    @property
    def config_parser(self) -> AppConfigParser:
        """Get the config parser for this app."""
        return self._config_parser

    @property
    def app_logger(self) -> AppLogger:
        """Get the app-specific logger."""
        return self._app_logger

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value (resolved)."""
        return self._config_parser.get(key, default)

    def get_os_var(self, param: str, default: str | None = None) -> str | None:
        """Get an os_var by parameter name."""
        return self._config_parser.get_os_var(param, default)

    def get_env_dict(self) -> dict[str, str]:
        """
        Get environment variables for this app.

        Useful for passing to isolated app processes.
        """
        return self._config_parser.to_env_dict()

    def __repr__(self):
        isolated_str = " [isolated]" if self.is_isolated else ""
        port_str = f" port={self.port}" if self.port else ""
        os_vars_count = len(self._config_parser.get_all_os_vars())
        os_vars_str = f" os_vars={os_vars_count}" if os_vars_count > 0 else ""
        return f"<AppConfig name={self.name} prefix={self.prefix}{isolated_str}{port_str}{os_vars_str}>"


class AppLoader:
    """
    Discovers and loads apps from the apps folder.
    Supports both embedded apps (loaded into main process) and
    isolated apps (run as separate processes with their own venv).
    """

    def __init__(self, apps_folder: str | None = None):
        self.config = get_config()
        apps_folder_path = apps_folder or self.config.apps_folder
        # Resolve to absolute path - supports both relative and absolute paths
        self.apps_folder = Path(apps_folder_path).resolve()
        self.loaded_apps: dict[str, AppConfig] = {}
        self.isolated_apps: dict[str, AppConfig] = {}
        self.failed_apps: dict[str, dict[str, Any]] = {}  # Track failed apps with error info
        self._handlers: list[tuple] = []
        self._next_port = self.config.isolated_app_base_port

    def discover_apps(self) -> list[AppConfig]:
        """
        Discover all apps in the apps folder.
        Each app should have a config.json file.
        """
        apps = []

        if not self.apps_folder.exists():
            logger.warning(f"Apps folder '{self.apps_folder}' does not exist. Creating it.")
            self.apps_folder.mkdir(parents=True, exist_ok=True)
            return apps

        # Sort directories alphabetically for consistent port assignment
        for item in sorted(self.apps_folder.iterdir(), key=lambda x: x.name):
            if item.is_dir() and not item.name.startswith("_"):
                config_file = item / "config.json"

                if config_file.exists():
                    try:
                        with config_file.open() as f:
                            config_data = json.load(f)

                        app_config = AppConfig(item, config_data)

                        if app_config.enabled:
                            apps.append(app_config)
                            logger.info(f"Discovered app: {app_config.name} at {app_config.prefix}")
                        else:
                            logger.info(f"Skipping disabled app: {app_config.name}")

                    except json.JSONDecodeError as e:
                        error_msg = f"Invalid config.json: {e!s}"
                        logger.exception(f"Invalid config.json in {item.name}: {e}")
                        self.failed_apps[item.name] = {
                            "name": item.name,
                            "path": str(item),
                            "error": error_msg,
                            "error_type": "config_error",
                        }
                    except Exception as e:
                        error_msg = f"Error loading app: {e!s}"
                        logger.exception(f"Error loading app {item.name}: {e}")
                        self.failed_apps[item.name] = {
                            "name": item.name,
                            "path": str(item),
                            "error": error_msg,
                            "error_type": "load_error",
                        }
                else:
                    logger.warning(f"No config.json found in {item.name}, skipping")

        return apps

    def load_app_module(self, app_config: AppConfig) -> Any | None:
        """
        Load the main module of an app.
        The app should have a handlers.py or __init__.py with a 'get_handlers' function.
        """
        app_path = app_config.path

        # Add app path to sys.path temporarily
        if str(app_path.parent) not in sys.path:
            sys.path.insert(0, str(app_path.parent))

        # Try to load handlers.py first, then __init__.py
        handlers_file = app_path / "handlers.py"
        init_file = app_path / "__init__.py"

        module = None
        module_name = f"apps.{app_config.name}"

        try:
            if handlers_file.exists():
                spec = importlib.util.spec_from_file_location(
                    f"{module_name}.handlers", handlers_file
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
            elif init_file.exists():
                spec = importlib.util.spec_from_file_location(module_name, init_file)
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
            else:
                logger.warning(f"No handlers.py or __init__.py found in {app_config.name}")
                return None

        except Exception as e:
            logger.exception(f"Error loading module for {app_config.name}: {e}")
            return None

        return module

    def get_app_handlers(self, app_config: AppConfig, module: Any) -> list[tuple]:
        """
        Get handlers from an app module.
        The module should have a 'get_handlers' function or a 'handlers' list.
        """
        handlers = []

        # Try get_handlers function first
        if hasattr(module, "get_handlers"):
            try:
                raw_handlers = module.get_handlers()
            except Exception as e:
                logger.exception(f"Error calling get_handlers in {app_config.name}: {e}")
                return handlers
        elif hasattr(module, "handlers"):
            raw_handlers = module.handlers
        else:
            logger.warning(f"No get_handlers() or handlers list in {app_config.name}")
            return handlers

        # Prefix all handler paths with BASE_PATH and app prefix
        prefix = app_config.prefix.rstrip("/")

        for handler_tuple in raw_handlers:
            if len(handler_tuple) >= 2:
                path = handler_tuple[0]
                handler_class = handler_tuple[1]

                # Ensure path starts with /
                if not path.startswith("/"):
                    path = "/" + path

                # Create the full path with BASE_PATH and app prefix
                # Use regex pattern with optional trailing slash for flexible matching
                base_path = f"{BASE_PATH}{prefix}{path}".rstrip("/")
                full_path = rf"{base_path}/?"

                # Handle additional init kwargs
                if len(handler_tuple) >= 3:
                    init_kwargs = (
                        handler_tuple[2].copy() if isinstance(handler_tuple[2], dict) else {}
                    )
                else:
                    init_kwargs = {}

                # Add app config to init kwargs (both raw and resolved)
                init_kwargs["app_config"] = app_config._raw_config
                init_kwargs["app_config_parser"] = app_config.config_parser

                handlers.append((full_path, handler_class, init_kwargs))
                logger.debug(f"Registered handler: {full_path} -> {handler_class.__name__}")

        return handlers

    def _assign_port(self, app_config: AppConfig) -> int:
        """Assign a port to an isolated app."""
        if app_config.port is not None:
            return app_config.port

        port = self._next_port
        self._next_port += 1
        app_config.port = port
        return port

    def load_all_apps(self, app_filter: str | None = None) -> list[tuple]:
        """
        Discover and load all apps, returning handlers for embedded apps.
        Isolated apps are stored separately for later spawning.
        Failed apps are tracked but don't prevent other apps from loading.

        Args:
            app_filter: If set, only load the app whose name matches (case-insensitive).
                        All other apps are skipped entirely. Useful for single-app dev mode.
        """
        all_handlers = []
        apps = self.discover_apps()

        if app_filter:
            matched = [a for a in apps if a.name.lower() == app_filter.lower()]
            if not matched:
                available = ", ".join(a.name for a in apps)
                logger.error(
                    f"App '{app_filter}' not found. Available apps: {available}"
                )
                return all_handlers
            logger.info(f"Single-app mode: loading only '{matched[0].name}'")
            apps = matched

        for app_config in apps:
            try:
                if app_config.is_isolated:
                    # Isolated app - assign port and store for later spawning
                    try:
                        self._assign_port(app_config)
                        self.isolated_apps[app_config.name] = app_config
                        logger.info(
                            f"Discovered isolated app '{app_config.name}' (port: {app_config.port})"
                        )
                    except Exception as e:
                        error_msg = f"Failed to setup isolated app: {e!s}"
                        logger.exception(f"Error setting up isolated app {app_config.name}: {e}")
                        self.failed_apps[app_config.name] = {
                            "name": app_config.name,
                            "path": str(app_config.path),
                            "error": error_msg,
                            "error_type": "isolated_setup_error",
                            "isolated": True,
                        }
                else:
                    # Embedded app - load handlers into main process
                    try:
                        module = self.load_app_module(app_config)

                        if module:
                            handlers = self.get_app_handlers(app_config, module)
                            if handlers:
                                all_handlers.extend(handlers)
                                self.loaded_apps[app_config.name] = app_config
                                logger.info(
                                    f"Loaded embedded app '{app_config.name}' with {len(handlers)} handlers"
                                )
                            else:
                                # Module loaded but no handlers found
                                error_msg = "No handlers found in module"
                                logger.warning(f"App {app_config.name} loaded but has no handlers")
                                self.failed_apps[app_config.name] = {
                                    "name": app_config.name,
                                    "path": str(app_config.path),
                                    "error": error_msg,
                                    "error_type": "no_handlers",
                                }
                        # Module failed to load
                        elif app_config.name not in self.failed_apps:
                            self.failed_apps[app_config.name] = {
                                "name": app_config.name,
                                "path": str(app_config.path),
                                "error": "Failed to load module",
                                "error_type": "module_load_error",
                            }
                    except Exception as e:
                        error_msg = f"Error loading embedded app: {e!s}"
                        logger.exception(f"Error loading embedded app {app_config.name}: {e}")
                        self.failed_apps[app_config.name] = {
                            "name": app_config.name,
                            "path": str(app_config.path),
                            "error": error_msg,
                            "error_type": "load_error",
                        }
            except Exception as e:
                # Catch any unexpected errors during app processing
                error_msg = f"Unexpected error processing app: {e!s}"
                logger.exception(f"Unexpected error processing app {app_config.name}: {e}")
                self.failed_apps[app_config.name] = {
                    "name": app_config.name,
                    "path": str(app_config.path) if hasattr(app_config, "path") else "unknown",
                    "error": error_msg,
                    "error_type": "unexpected_error",
                }

        self._handlers = all_handlers

        # Log summary
        if self.failed_apps:
            logger.warning(
                f"Failed to load {len(self.failed_apps)} app(s): {list(self.failed_apps.keys())}"
            )
        else:
            logger.info("All apps loaded successfully")

        return all_handlers

    def get_isolated_apps(self) -> list[AppConfig]:
        """Get list of isolated apps that need to be spawned."""
        return list(self.isolated_apps.values())

    def get_embedded_apps(self) -> list[AppConfig]:
        """Get list of embedded apps loaded into main process."""
        return list(self.loaded_apps.values())

    def get_loaded_apps_info(self) -> list[dict[str, Any]]:
        """Get information about all loaded apps (embedded and isolated)."""
        apps_info = [
            {
                "name": app.name,
                "version": app.version,
                "description": app.description,
                "prefix": f"{BASE_PATH}{app.prefix}",
                "enabled": app.enabled,
                "isolated": False,
                "port": self.config.port,
                "status": "loaded",
            }
            for app in self.loaded_apps.values()
        ]
        apps_info.extend(
            {
                "name": app.name,
                "version": app.version,
                "description": app.description,
                "prefix": f"{BASE_PATH}{app.prefix}",
                "enabled": app.enabled,
                "isolated": True,
                "port": app.port,
                "status": "loaded",
            }
            for app in self.isolated_apps.values()
        )
        return apps_info

    def get_failed_apps(self) -> list[dict[str, Any]]:
        """Get information about apps that failed to load."""
        return list(self.failed_apps.values())


class AppsInfoHandler(BaseHandler):
    """Handler to list all loaded apps."""

    def initialize(self, app_loader: AppLoader = None, **kwargs) -> None:
        super().initialize(**kwargs)
        self.app_loader = app_loader

    async def get(self) -> None:
        """Return information about all loaded apps."""
        if self.app_loader:
            apps_info = self.app_loader.get_loaded_apps_info()
        else:
            apps_info = []

        self.success(data={"apps": apps_info})
