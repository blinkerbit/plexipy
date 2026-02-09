"""
Configuration management for PyRest framework.
Handles environment variables and framework settings.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("pyrest.config")


class AppConfigParser:
    """
    Enhanced JSON config parser for app-wise configuration.

    Supports the following format in app config.json:
    {
        "param1": "value1",
        "param2": "value2",
        "os_vars": {
            "os_param1": "os_value1",
            "os_param2": "os_value2"
        },
        "tm1_instances": {
            "instance1": {
                "connection_type": "onprem",
                "server": "localhost",
                ...
            },
            "instance2": {
                "connection_type": "cloud",
                ...
            }
        }
    }

    The os_vars section will be set as environment variables in the format:
    <app_name>.os_param1 = os_value1

    The tm1_instances section will be set as environment variables in the format:
    <app_name>.tm1.<instance_name>.<param> = value

    For isolated apps (with requirements.txt), environment variables are also
    available directly without the app prefix in their context.
    """

    # Reserved config keys that are handled specially
    RESERVED_KEYS = {"os_vars", "tm1_instances"}

    def __init__(self, app_name: str, config_data: dict[str, Any], is_isolated: bool = False):
        self.app_name = app_name
        self.config_data = config_data
        self.is_isolated = is_isolated
        self._os_vars: dict[str, str] = {}
        self._instance_vars: dict[str, dict[str, str]] = {}  # instance_name -> vars
        self._resolved_config: dict[str, Any] = {}
        self._parse_config()

    def _parse_config(self) -> None:
        """Parse the config and process special sections."""
        # Copy all non-reserved config to resolved config
        for key, value in self.config_data.items():
            if key not in self.RESERVED_KEYS:
                # Check if value should be resolved from environment
                resolved_value = self._resolve_value(key, value)
                self._resolved_config[key] = resolved_value

        # Process os_vars section
        os_vars = self.config_data.get("os_vars", {})
        if isinstance(os_vars, dict):
            self._process_os_vars(os_vars)

        # Process tm1_instances section
        tm1_instances = self.config_data.get("tm1_instances", {})
        if isinstance(tm1_instances, dict):
            self._process_tm1_instances(tm1_instances)

    def _process_tm1_instances(self, tm1_instances: dict[str, dict[str, Any]]) -> None:
        """
        Process tm1_instances section and set environment variables.

        Each instance parameter is set as:
        1. <app_name>.tm1.<instance_name>.<param> = value
        2. For isolated apps: TM1_<INSTANCE_NAME>_<PARAM> = value
        """
        for instance_name, instance_config in tm1_instances.items():
            if not isinstance(instance_config, dict):
                continue

            self._instance_vars[instance_name] = {}

            for param, value in instance_config.items():
                # Convert value to string
                if isinstance(value, (dict, list)):
                    str_value = json.dumps(value)
                elif isinstance(value, bool):
                    str_value = str(value).lower()
                else:
                    str_value = str(value)

                # Resolve any environment variable references
                resolved_value = self._resolve_value(param, str_value)
                if isinstance(resolved_value, str):
                    str_value = resolved_value
                elif isinstance(resolved_value, bool):
                    str_value = str(resolved_value).lower()
                else:
                    str_value = str(resolved_value)

                # Store in instance vars
                self._instance_vars[instance_name][param] = str_value

                # Set prefixed environment variable: <app_name>.tm1.<instance>.<param>
                prefixed_key = f"{self.app_name}.tm1.{instance_name}.{param}"
                os.environ[prefixed_key] = str_value
                self._os_vars[prefixed_key] = str_value
                _sensitive = {"password", "client_secret", "api_key", "secret", "token"}
                safe_value = "****" if param.lower() in _sensitive else str_value
                logger.debug("Set instance env var: %s=%s", prefixed_key, safe_value)

                # For isolated apps, also set in TM1_<INSTANCE>_<PARAM> format
                if self.is_isolated:
                    instance_env_key = f"TM1_{instance_name.upper()}_{param.upper()}"
                    if instance_env_key not in os.environ:
                        os.environ[instance_env_key] = str_value
                        self._os_vars[instance_env_key] = str_value
                        logger.debug(
                            f"Set isolated instance env var: {instance_env_key}={str_value}"
                        )

        # Also store the resolved tm1_instances in the config
        self._resolved_config["tm1_instances"] = {
            name: {k: self._resolve_value(k, v) for k, v in config.items()}
            for name, config in tm1_instances.items()
        }

        logger.info(f"Processed {len(tm1_instances)} TM1 instances for app '{self.app_name}'")

    def _resolve_value(self, key: str, value: Any) -> Any:
        """
        Resolve a configuration value.

        If the value is a string starting with '$', try to resolve it from environment.
        Supports ${VAR_NAME} and ${VAR_NAME:-default} syntax.
        """
        if isinstance(value, str):
            if value.startswith("${") and "}" in value:
                return self._resolve_env_reference(value)
            elif value.startswith("$") and len(value) > 1:
                # Simple $VAR_NAME format
                var_name = value[1:]
                return os.environ.get(var_name, value)
        elif isinstance(value, dict):
            return {k: self._resolve_value(k, v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._resolve_value(str(i), v) for i, v in enumerate(value)]
        return value

    def _resolve_env_reference(self, value: str) -> str:
        """
        Resolve ${VAR_NAME} or ${VAR_NAME:-default} syntax.
        """
        # Extract content between ${ and }
        start = value.find("${")
        end = value.find("}")
        if start == -1 or end == -1:
            return value

        env_expr = value[start + 2 : end]

        # Check for default value syntax: VAR_NAME:-default
        if ":-" in env_expr:
            var_name, default = env_expr.split(":-", 1)
            result = os.environ.get(var_name.strip(), default)
        else:
            var_name = env_expr.strip()
            result = os.environ.get(var_name, "")

        # Replace the ${...} with the resolved value
        prefix = value[:start]
        suffix = value[end + 1 :]
        resolved = prefix + result + suffix

        # Recursively resolve if there are more references
        if "${" in resolved:
            return self._resolve_env_reference(resolved)
        return resolved

    def _process_os_vars(self, os_vars: dict[str, Any]) -> None:
        """
        Process os_vars section and set environment variables.

        Each os_var is set with two formats:
        1. <app_name>.<param> = value (prefixed format for global access)
        2. For isolated apps: <param> = value (direct access in isolated context)
        """
        for param, value in os_vars.items():
            if isinstance(value, (dict, list)):
                # Convert complex values to JSON string
                str_value = json.dumps(value)
            else:
                str_value = str(value)

            # Resolve any environment variable references in the value
            resolved_value = self._resolve_value(param, str_value)
            if isinstance(resolved_value, str):
                str_value = resolved_value

            # Set prefixed environment variable
            prefixed_key = f"{self.app_name}.{param}"
            os.environ[prefixed_key] = str_value
            self._os_vars[prefixed_key] = str_value
            logger.debug(f"Set env var: {prefixed_key}={str_value}")

            # For isolated apps, also set without prefix for direct access
            if self.is_isolated and param not in os.environ:
                os.environ[param] = str_value
                self._os_vars[param] = str_value
                logger.debug(f"Set isolated env var: {param}={str_value}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a resolved configuration value."""
        return self._resolved_config.get(key, default)

    def get_os_var(self, param: str, default: str | None = None) -> str | None:
        """
        Get an os_var by parameter name.

        Tries both prefixed and non-prefixed versions.
        """
        prefixed_key = f"{self.app_name}.{param}"
        return os.environ.get(prefixed_key, os.environ.get(param, default))

    def get_all_os_vars(self) -> dict[str, str]:
        """Get all os_vars set by this parser."""
        return self._os_vars.copy()

    def get_app_env_vars(self) -> dict[str, str]:
        """
        Get all environment variables for this app.

        Returns all env vars that start with <app_name>. prefix.
        """
        prefix = f"{self.app_name}."
        return {k: v for k, v in os.environ.items() if k.startswith(prefix)}

    def get_resolved_config(self) -> dict[str, Any]:
        """Get the fully resolved configuration."""
        return self._resolved_config.copy()

    def get_tm1_instances(self) -> dict[str, dict[str, Any]]:
        """Get all TM1 instance configurations (resolved)."""
        return self._resolved_config.get("tm1_instances", {})

    def get_tm1_instance(self, instance_name: str) -> dict[str, Any] | None:
        """Get a specific TM1 instance configuration (resolved)."""
        return self.get_tm1_instances().get(instance_name)

    def get_tm1_instance_names(self) -> list[str]:
        """Get list of all TM1 instance names."""
        return list(self.get_tm1_instances().keys())

    def get_tm1_instance_var(
        self, instance_name: str, param: str, default: str | None = None
    ) -> str | None:
        """
        Get a specific TM1 instance variable.

        Tries both prefixed and isolated formats.
        """
        # Try prefixed format: <app_name>.tm1.<instance>.<param>
        prefixed_key = f"{self.app_name}.tm1.{instance_name}.{param}"
        value = os.environ.get(prefixed_key)
        if value is not None:
            return value

        # Try isolated format: TM1_<INSTANCE>_<PARAM>
        isolated_key = f"TM1_{instance_name.upper()}_{param.upper()}"
        value = os.environ.get(isolated_key)
        if value is not None:
            return value

        return default

    def to_env_dict(self) -> dict[str, str]:
        """
        Convert the entire app config to environment variable format.

        Useful for passing configuration to isolated app processes.
        """
        env_dict = {}

        # Add os_vars
        env_dict.update(self._os_vars)

        # Add settings as environment variables
        settings = self._resolved_config.get("settings", {})
        if isinstance(settings, dict):
            for key, value in settings.items():
                env_key = f"{self.app_name}.{key}"
                if isinstance(value, (dict, list)):
                    env_dict[env_key] = json.dumps(value)
                else:
                    env_dict[env_key] = str(value)

        return env_dict

    @classmethod
    def from_file(cls, config_path: Path, is_isolated: bool = False) -> AppConfigParser:
        """
        Create an AppConfigParser from a config.json file.
        """
        app_name = config_path.parent.name

        with config_path.open() as f:
            config_data = json.load(f)

        # Override app_name if specified in config
        if "name" in config_data:
            app_name = config_data["name"]

        return cls(app_name, config_data, is_isolated)


class EnvConfig:
    """
    Environment variable manager that exposes OS variables to apps.
    """

    _instance = None
    _env_file_loaded = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._custom_vars = {}
        return cls._instance

    def load_env_file(self, env_file: str = ".env") -> None:
        """Load environment variables from a .env file."""
        if self._env_file_loaded:
            return

        env_path = Path(env_file)
        if not env_path.is_file():
            # Skip if missing, or if it's a directory (e.g. Docker mount created .env as dir)
            return

        try:
            with env_path.open() as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        os.environ[key] = value
                        self._custom_vars[key] = value
        except OSError as e:
            logger.warning("Could not read env file %s: %s", env_file, e)
        self._env_file_loaded = True

    def get(self, key: str, default: str | None = None) -> str | None:
        """Get an environment variable."""
        return os.environ.get(key, default)

    def set(self, key: str, value: str) -> None:
        """Set an environment variable."""
        os.environ[key] = value
        self._custom_vars[key] = value

    def get_all(self) -> dict[str, str]:
        """Get all environment variables."""
        return dict(os.environ)

    def get_custom(self) -> dict[str, str]:
        """Get only custom/loaded environment variables."""
        return self._custom_vars.copy()

    def get_prefixed(self, prefix: str) -> dict[str, str]:
        """Get all environment variables with a specific prefix."""
        return {k: v for k, v in os.environ.items() if k.startswith(prefix)}


class FrameworkConfig:
    """
    Main framework configuration.
    """

    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self._config = self._load_config()
        self.env = EnvConfig()
        self.env.load_env_file(self._config.get("env_file", ".env"))

    def _load_config(self) -> dict[str, Any]:
        """Load the main framework configuration."""
        config_path = Path(self.config_file)
        default_config = {
            "host": "0.0.0.0",
            "port": 8000,
            "debug": False,
            "base_path": "/pyrest",
            "apps_folder": "apps",
            "env_file": ".env",
            "auth_config_file": "auth_config.json",
            "jwt_secret": os.environ.get("PYREST_JWT_SECRET", ""),
            "jwt_expiry_hours": 24,
            "cors_enabled": True,
            "cors_origins": ["*"],
            "log_level": "INFO",
            "static_path": "static",
            "template_path": "templates",
            "isolated_app_base_port": 8001,
        }

        if config_path.exists():
            with config_path.open() as f:
                user_config = json.load(f)
                default_config.update(user_config)

        return default_config

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value."""
        self._config[key] = value

    def save(self) -> None:
        """Save the current configuration to file."""
        with Path(self.config_file).open("w") as f:
            json.dump(self._config, f, indent=2)

    @property
    def host(self) -> str:
        return self._config["host"]

    @property
    def port(self) -> int:
        return self._config["port"]

    @property
    def debug(self) -> bool:
        return self._config["debug"]

    @property
    def apps_folder(self) -> str:
        # Allow override via environment variable
        return os.environ.get("PYREST_APPS_FOLDER", self._config["apps_folder"])

    @property
    def jwt_secret(self) -> str:
        return self.env.get("JWT_SECRET", self._config["jwt_secret"])

    @property
    def jwt_expiry_hours(self) -> int:
        return self._config["jwt_expiry_hours"]

    @property
    def base_path(self) -> str:
        return self._config["base_path"]

    @property
    def auth_config_file(self) -> str:
        return self._config["auth_config_file"]

    @property
    def isolated_app_base_port(self) -> int:
        return self._config["isolated_app_base_port"]


@lru_cache
def get_config() -> FrameworkConfig:
    """Get the singleton framework configuration."""
    return FrameworkConfig()


@lru_cache
def get_env() -> EnvConfig:
    """Get the singleton environment configuration."""
    return EnvConfig()
