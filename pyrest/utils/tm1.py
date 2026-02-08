"""
TM1 Connection Utilities for PyRest Framework.

Provides connection management for multiple TM1 instances supporting:
- TM1 v12 (primary target - latest version)
- TM1 v12 with Azure AD authentication
- TM1 v12 PAaaS (IBM Planning Analytics as a Service)
- TM1 On-Premise (legacy, for backward compatibility)
- TM1 Cloud (legacy, for backward compatibility)

TM1 v12 Connection Types:
- v12: TM1 v12 with basic authentication
- v12_azure_ad: TM1 v12 with Azure AD OAuth2 authentication
- v12_paas: IBM Planning Analytics as a Service (TM1 v12)

Simple Usage (Recommended):
    from pyrest.utils.tm1 import get_tm1_instance

    # Get connection to a specific instance (defined in tm1_config.json)
    with get_tm1_instance("production") as tm1:
        cubes = tm1.cubes.get_all_names()

    # Or without context manager
    tm1 = get_tm1_instance("development")
    cubes = tm1.cubes.get_all_names()
    tm1.logout()

Advanced Usage:
    from pyrest.utils import TM1ConnectionManager, TM1InstanceConfig

    # Initialize with app config
    TM1ConnectionManager.initialize(app_config)

    # Get connection to a specific instance
    tm1 = TM1ConnectionManager.get_connection("production")

    # Use the connection
    cubes = tm1.cubes.get_all_names()
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("pyrest.utils.tm1")

# TM1py import (available when running in isolated venv with tm1py installed)
try:
    from TM1py import TM1Service

    TM1_AVAILABLE = True
except ImportError:
    TM1_AVAILABLE = False
    TM1Service = None


def is_tm1_available() -> bool:
    """Check if TM1py is available."""
    return TM1_AVAILABLE


class TM1InstanceConfig:
    """
    Configuration for a single TM1 instance.

    Handles both On-Premise and Cloud connection types with environment
    variable resolution for sensitive values.
    """

    def __init__(self, name: str, config: dict[str, Any]):
        """
        Initialize TM1 instance configuration.

        Args:
            name: Unique identifier for this instance
            config: Configuration dictionary with connection parameters
        """
        self.name = name
        self.description = config.get("description", "")
        self.connection_type = config.get("connection_type", "onprem").lower()
        self._config = config
        logger.debug(f"Created TM1InstanceConfig: {name} ({self.connection_type})")

    @staticmethod
    def _resolve_env_value(value: Any) -> Any:
        """
        Resolve environment variable references in config values.

        Supports ${VAR_NAME} and ${VAR_NAME:-default} syntax.
        """
        if not isinstance(value, str):
            return value

        if value.startswith("${") and "}" in value:
            # Extract ${VAR:-default} syntax
            start = value.find("${")
            end = value.find("}")
            env_expr = value[start + 2 : end]

            if ":-" in env_expr:
                var_name, default = env_expr.split(":-", 1)
                result = os.environ.get(var_name.strip(), default)
            else:
                result = os.environ.get(env_expr.strip(), "")

            # Handle prefix/suffix around the ${...}
            prefix = value[:start]
            suffix = value[end + 1 :]
            resolved = prefix + result + suffix

            # Recursively resolve if there are more references
            if "${" in resolved:
                return TM1InstanceConfig._resolve_env_value(resolved)
            return resolved

        return value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value with environment variable resolution."""
        value = self._config.get(key, default)
        return self._resolve_env_value(value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean config value."""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer config value."""
        value = self.get(key, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def is_v12(self) -> bool:
        """Check if this is a TM1 v12 instance (any v12 connection type)."""
        return self.connection_type.startswith("v12")

    def is_v12_azure_ad(self) -> bool:
        """Check if this is a TM1 v12 instance with Azure AD authentication."""
        return self.connection_type == "v12_azure_ad"

    def is_v12_paas(self) -> bool:
        """Check if this is a TM1 v12 PAaaS instance."""
        return self.connection_type == "v12_paas"

    def is_cloud(self) -> bool:
        """Check if this is a cloud instance (legacy or v12 PAaaS)."""
        return self.connection_type in ("cloud", "paas", "v12_paas")

    def is_onprem(self) -> bool:
        """Check if this is a legacy on-premise instance."""
        return self.connection_type == "onprem"

    def build_connection_params(self, session_context: str = "PyRest TM1 App") -> dict[str, Any]:
        """
        Build TM1py connection parameters for this instance.

        Supports TM1 v12 connection types as the primary target:
        - v12: TM1 v12 with basic authentication
        - v12_azure_ad: TM1 v12 with Azure AD OAuth2 authentication
        - v12_paas: IBM Planning Analytics as a Service (TM1 v12)

        Also supports legacy connection types for backward compatibility:
        - onprem: Traditional TM1 on-premise servers
        - cloud: Legacy IBM Planning Analytics Cloud

        Args:
            session_context: Session context string for TM1 server

        Returns:
            Dictionary of parameters for TM1Service constructor
        """
        # TM1 v12 connection types (primary target)
        if self.connection_type == "v12":
            return self._build_v12_params(session_context)
        elif self.connection_type == "v12_azure_ad":
            return self._build_v12_azure_ad_params(session_context)
        elif self.connection_type == "v12_paas":
            return self._build_v12_paas_params(session_context)
        # Legacy connection types (backward compatibility)
        elif self.is_cloud():
            return self._build_cloud_params(session_context)
        else:
            return self._build_onprem_params(session_context)

    def _build_v12_params(self, session_context: str) -> dict[str, Any]:
        """
        Build connection parameters for TM1 v12 with basic authentication.

        TM1 v12 uses base_url instead of address/port, and may include
        instance and database in the URL structure.
        """
        params = {
            "base_url": self.get("base_url", ""),
            "user": self.get("user", ""),
            "password": self.get("password", ""),
            "ssl": self.get_bool("ssl", True),
            "session_context": session_context,
        }

        # Optional TM1 v12 specific parameters
        instance = self.get("instance", "")
        database = self.get("database", "")
        if instance:
            params["instance"] = instance
        if database:
            params["database"] = database

        # SSL certificate verification (v12 often uses self-signed certs)
        if not self.get_bool("verify_ssl_cert", True):
            params["verify"] = False

        logger.debug(f"Instance {self.name}: Using TM1 v12 with basic authentication")
        return params

    def _build_v12_azure_ad_params(self, session_context: str) -> dict[str, Any]:
        """
        Build connection parameters for TM1 v12 with Azure AD authentication.

        Uses OAuth2 client credentials flow to acquire access token.
        """
        params = {
            "base_url": self.get("base_url", ""),
            "ssl": True,
            "session_context": session_context,
        }

        # Azure AD authentication parameters
        tenant_id = self.get("tenant_id", "")
        client_id = self.get("client_id", "")
        client_secret = self.get("client_secret", "")

        if tenant_id and client_id and client_secret:
            params["tenant"] = tenant_id
            params["client_id"] = client_id
            params["client_secret"] = client_secret

            # Custom auth URL if provided
            auth_url = self.get("auth_url", "")
            if auth_url:
                params["auth_url"] = auth_url

        # Optional TM1 v12 specific parameters
        instance = self.get("instance", "")
        database = self.get("database", "")
        if instance:
            params["instance"] = instance
        if database:
            params["database"] = database

        # SSL certificate verification
        if not self.get_bool("verify_ssl_cert", True):
            params["verify"] = False

        logger.debug(f"Instance {self.name}: Using TM1 v12 with Azure AD authentication")
        return params

    def _build_v12_paas_params(self, session_context: str) -> dict[str, Any]:
        """
        Build connection parameters for TM1 v12 Planning Analytics as a Service.

        PAaaS uses IBM IAM authentication with API key.
        """
        params = {
            "base_url": self.get("base_url", ""),
            "api_key": self.get("api_key", ""),
            "ssl": True,
            "session_context": session_context,
        }

        # IBM IAM URL
        iam_url = self.get("iam_url", "")
        if iam_url:
            params["iam_url"] = iam_url

        # Tenant for PAaaS
        tenant = self.get("tenant", "")
        if tenant:
            params["tenant"] = tenant

        # TM1 v12 specific parameters
        instance = self.get("instance", "")
        database = self.get("database", "")
        if instance:
            params["instance"] = instance
        if database:
            params["database"] = database

        logger.debug(f"Instance {self.name}: Using TM1 v12 PAaaS with IBM IAM authentication")
        return params

    def _build_onprem_params(self, session_context: str) -> dict[str, Any]:
        """
        Build connection parameters for legacy TM1 On-Premise (pre-v12).

        Kept for backward compatibility with older TM1 installations.
        """
        params = {
            "address": self.get("server", "localhost"),
            "port": self.get_int("port", 8010),
            "ssl": self.get_bool("ssl", True),
            "session_context": session_context,
        }

        # Check authentication method
        integrated_login = self.get_bool("integrated_login", False)
        namespace = self.get("namespace", "")
        cam_passport = self.get("cam_passport", "")

        if integrated_login:
            params["integrated_login"] = True
            logger.debug(
                f"Instance {self.name}: Using Windows Integrated Authentication (legacy on-prem)"
            )
        elif cam_passport:
            params["cam_passport"] = cam_passport
            if namespace:
                params["namespace"] = namespace
            logger.debug(
                f"Instance {self.name}: Using CAM Passport Authentication (legacy on-prem)"
            )
        elif namespace:
            params["user"] = self.get("user", "")
            params["password"] = self.get("password", "")
            params["namespace"] = namespace
            gateway = self.get("gateway", "")
            if gateway:
                params["gateway"] = gateway
            logger.debug(f"Instance {self.name}: Using CAM Authentication (legacy on-prem)")
        else:
            params["user"] = self.get("user", "")
            params["password"] = self.get("password", "")
            logger.debug(f"Instance {self.name}: Using Basic TM1 Authentication (legacy on-prem)")

        return params

    def _build_cloud_params(self, session_context: str) -> dict[str, Any]:
        """
        Build connection parameters for legacy TM1 Cloud (IBM Planning Analytics).

        Note: For TM1 v12 PAaaS, use connection_type 'v12_paas' instead.
        This is kept for backward compatibility.
        """
        region = self.get("cloud_region", "")
        tenant = self.get("cloud_tenant", "")

        params = {
            "base_url": f"https://{region}.planninganalytics.ibmcloud.com/tm1/api/{tenant}/v1",
            "ipm_url": f"https://{region}.planninganalytics.ibmcloud.com",
            "api_key": self.get("cloud_api_key", ""),
            "tenant": tenant,
            "session_context": session_context,
            "ssl": True,
        }

        instance = self.get("instance", "")
        if instance:
            params["instance"] = instance

        logger.debug(
            f"Instance {self.name}: Using legacy TM1 Cloud (region: {region}) - consider migrating to v12_paas"
        )
        return params

    def to_dict(self, include_sensitive: bool = False) -> dict[str, Any]:
        """
        Convert instance config to dictionary (for API responses).

        Args:
            include_sensitive: Include sensitive fields like username

        Returns:
            Dictionary representation of the instance
        """
        base_info = {
            "name": self.name,
            "description": self.description,
            "connection_type": self.connection_type,
            "is_v12": self.is_v12(),
        }

        if self.connection_type == "v12":
            info = {
                **base_info,
                "base_url": self.get("base_url", ""),
                "instance": self.get("instance", ""),
                "database": self.get("database", ""),
                "ssl": self.get_bool("ssl", True),
            }
        elif self.connection_type == "v12_azure_ad":
            info = {
                **base_info,
                "base_url": self.get("base_url", ""),
                "instance": self.get("instance", ""),
                "database": self.get("database", ""),
                "tenant_id": self.get("tenant_id", ""),
                "auth_type": "azure_ad",
            }
        elif self.connection_type == "v12_paas":
            info = {
                **base_info,
                "base_url": self.get("base_url", ""),
                "iam_url": self.get("iam_url", ""),
                "tenant": self.get("tenant", ""),
                "instance": self.get("instance", ""),
                "database": self.get("database", ""),
            }
        elif self.connection_type in ("cloud", "paas"):
            info = {
                **base_info,
                "cloud_region": self.get("cloud_region", ""),
                "cloud_tenant": self.get("cloud_tenant", ""),
                "instance": self.get("instance", ""),
            }
        else:  # onprem (legacy)
            info = {
                **base_info,
                "server": self.get("server", "localhost"),
                "port": self.get_int("port", 8010),
                "ssl": self.get_bool("ssl", True),
            }

        if include_sensitive and self.connection_type in ("v12", "onprem"):
            info["user"] = self.get("user", "")

        return info

    def __repr__(self) -> str:
        return f"<TM1InstanceConfig name={self.name} type={self.connection_type}>"


class TM1ConnectionManager:
    """
    Manages multiple TM1 server connections.

    This is a singleton-style class that manages connections across all
    configured TM1 instances. It supports lazy connection creation and
    connection pooling per instance.

    Supports both TM1 Cloud and TM1 On-Premise connections.
    Each instance is configured in the tm1_instances section of config.json.

    Example config.json:
    ```json
    {
        "tm1_instances": {
            "production": {
                "connection_type": "onprem",
                "server": "prod-tm1.company.com",
                "port": 8010,
                "ssl": true,
                "user": "${PROD_TM1_USER}",
                "password": "${PROD_TM1_PASSWORD}"
            },
            "development": {
                "connection_type": "cloud",
                "cloud_region": "us-east",
                "cloud_tenant": "${DEV_TENANT}",
                "cloud_api_key": "${DEV_API_KEY}"
            }
        }
    }
    ```
    """

    _instances: dict[str, TM1InstanceConfig] = {}
    _connections: dict[str, Any] = {}  # instance_name -> TM1Service
    _default_instance: str = "default"
    _session_context: str = "PyRest TM1 App"
    _initialized: bool = False
    _app_logger: logging.Logger | None = None

    @classmethod
    def initialize(
        cls, app_config: dict[str, Any], app_logger: logging.Logger | None = None
    ) -> None:
        """
        Initialize the connection manager with app configuration.

        Args:
            app_config: The app's config.json loaded as a dictionary
            app_logger: Optional logger for this app's TM1 operations
        """
        if cls._initialized:
            return

        cls._app_logger = app_logger or logger

        # Get settings
        settings = app_config.get("settings", {})
        cls._default_instance = settings.get("default_instance", "default")
        cls._session_context = settings.get("session_context", "PyRest TM1 App")

        # Resolve environment variables in default_instance
        if isinstance(cls._default_instance, str) and cls._default_instance.startswith("${"):
            cls._default_instance = TM1InstanceConfig._resolve_env_value(cls._default_instance)

        # Load instance configurations
        tm1_instances = app_config.get("tm1_instances", {})
        for name, config in tm1_instances.items():
            cls._instances[name] = TM1InstanceConfig(name, config)
            cls._app_logger.info(
                f"Registered TM1 instance: {name} ({cls._instances[name].connection_type})"
            )

        cls._initialized = True
        cls._app_logger.info(
            f"TM1ConnectionManager initialized with {len(cls._instances)} instances"
        )

    @classmethod
    def reset(cls) -> None:
        """Reset the connection manager (close all connections and clear state)."""
        cls.close_all_connections()
        cls._instances.clear()
        cls._connections.clear()
        cls._initialized = False
        cls._default_instance = "default"
        cls._session_context = "PyRest TM1 App"
        logger.info("TM1ConnectionManager reset")

    @classmethod
    def get_instance_config(cls, instance_name: str | None = None) -> TM1InstanceConfig | None:
        """Get the configuration for a specific instance."""
        name = instance_name or cls._default_instance
        return cls._instances.get(name)

    @classmethod
    def get_all_instances(cls) -> dict[str, TM1InstanceConfig]:
        """Get all configured instances."""
        return cls._instances.copy()

    @classmethod
    def list_instance_names(cls) -> list[str]:
        """Get list of all instance names."""
        return list(cls._instances.keys())

    @classmethod
    def has_instance(cls, instance_name: str) -> bool:
        """Check if an instance is configured."""
        return instance_name in cls._instances

    @classmethod
    def get_connection(cls, instance_name: str | None = None) -> Any | None:
        """
        Get or create a TM1 connection for the specified instance.

        Args:
            instance_name: Name of the TM1 instance (uses default if not specified)

        Returns:
            TM1Service instance or None if connection fails
        """
        if not TM1_AVAILABLE:
            cls._app_logger.error("TM1py is not available. Install it with: pip install TM1py")
            return None

        name = instance_name or cls._default_instance
        log = cls._app_logger or logger

        # Return existing connection if available
        if name in cls._connections and cls._connections[name] is not None:
            return cls._connections[name]

        # Get instance config
        instance_config = cls.get_instance_config(name)
        if not instance_config:
            log.error(f"TM1 instance '{name}' not found in configuration")
            return None

        try:
            params = instance_config.build_connection_params(cls._session_context)

            if instance_config.is_cloud():
                log.info(
                    f"Connecting to TM1 Cloud instance '{name}' (region: {instance_config.get('cloud_region')})"
                )
            else:
                log.info(
                    f"Connecting to TM1 On-Premise instance '{name}' (server: {params['address']}:{params['port']})"
                )

            cls._connections[name] = TM1Service(**params)
            log.info(f"TM1 connection established for instance '{name}'")

            return cls._connections[name]

        except Exception as e:
            log.exception(f"TM1 connection error for instance '{name}': {e}")
            import traceback

            log.debug(traceback.format_exc())
            cls._connections[name] = None
            return None

    @classmethod
    def close_connection(cls, instance_name: str | None = None) -> None:
        """Close a specific TM1 connection."""
        name = instance_name or cls._default_instance
        log = cls._app_logger or logger

        if name in cls._connections and cls._connections[name] is not None:
            try:
                cls._connections[name].logout()
                log.info(f"Closed TM1 connection for instance '{name}'")
            except Exception as e:
                log.warning(f"Error closing TM1 connection for '{name}': {e}")
            finally:
                cls._connections[name] = None

    @classmethod
    def close_all_connections(cls) -> None:
        """Close all TM1 connections."""
        for name in list(cls._connections.keys()):
            cls.close_connection(name)

    @classmethod
    def reset_connection(cls, instance_name: str | None = None) -> None:
        """Reset a connection (close and allow reconnection)."""
        cls.close_connection(instance_name)

    @classmethod
    def get_default_instance(cls) -> str:
        """Get the default instance name."""
        return cls._default_instance

    @classmethod
    def is_connected(cls, instance_name: str | None = None) -> bool:
        """Check if a connection exists for the given instance."""
        name = instance_name or cls._default_instance
        return name in cls._connections and cls._connections[name] is not None

    @classmethod
    def get_connection_status(cls, instance_name: str | None = None) -> dict[str, Any]:
        """
        Get detailed connection status for an instance.

        Returns:
            Dictionary with connection status details
        """
        name = instance_name or cls._default_instance
        config = cls.get_instance_config(name)

        if not config:
            return {
                "instance": name,
                "configured": False,
                "connected": False,
                "error": f"Instance '{name}' not found",
            }

        status = {
            "instance": name,
            "configured": True,
            "connected": cls.is_connected(name),
            "config": config.to_dict(),
        }

        if status["connected"]:
            try:
                tm1 = cls._connections[name]
                status["server_name"] = tm1.server.get_server_name()
            except Exception as e:
                status["connected"] = False
                status["error"] = str(e)

        return status


# =============================================================================
# Simple Interface Functions
# =============================================================================

# Global config path (can be overridden)
_TM1_CONFIG_PATH: str | None = None
_TM1_CONFIG_LOADED: bool = False


def set_tm1_config_path(path: str) -> None:
    """
    Set custom path for tm1_config.json.

    Args:
        path: Absolute or relative path to the config file
    """
    global _TM1_CONFIG_PATH, _TM1_CONFIG_LOADED
    _TM1_CONFIG_PATH = path
    _TM1_CONFIG_LOADED = False


def _load_central_config() -> None:
    """Load the central tm1_config.json file."""
    global _TM1_CONFIG_LOADED

    if _TM1_CONFIG_LOADED:
        return

    # Determine config path
    config_path = _TM1_CONFIG_PATH

    if not config_path:
        # Try common locations
        possible_paths = [
            str(Path.cwd() / "tm1_config.json"),
            str(Path(__file__).parent.parent.parent / "tm1_config.json"),
            "/app/tm1_config.json",  # Docker path
        ]

        for path in possible_paths:
            if Path(path).exists():
                config_path = path
                break

    if not config_path or not Path(config_path).exists():
        logger.warning("tm1_config.json not found. Use set_tm1_config_path() or create the file.")
        _TM1_CONFIG_LOADED = True
        return

    try:
        with Path(config_path).open(encoding="utf-8") as f:
            config = json.load(f)

        # Convert to app_config format for TM1ConnectionManager
        app_config = {
            "settings": config.get("settings", {}),
            "tm1_instances": config.get("instances", {}),
        }

        # Reset and reinitialize
        TM1ConnectionManager.reset()
        TM1ConnectionManager.initialize(app_config)

        logger.info(f"Loaded TM1 config from: {config_path}")
        _TM1_CONFIG_LOADED = True

    except Exception as e:
        logger.exception(f"Error loading tm1_config.json: {e}")
        _TM1_CONFIG_LOADED = True


def get_tm1_instance(instance_name: str | None = None) -> Any | None:
    """
    Get a TM1 connection by instance name.

    This is the simplest way to connect to TM1. Instance configurations
    are defined in tm1_config.json at the project root.

    Args:
        instance_name: Name of the TM1 instance (uses 'default' if not specified)

    Returns:
        TM1Service instance ready to use

    Example:
        # Connect to development server
        tm1 = get_tm1_instance("development")
        cubes = tm1.cubes.get_all_names()
        tm1.logout()

        # Or use context manager for automatic cleanup
        with get_tm1_instance("production") as tm1:
            value = tm1.cubes.cells.get_value("SalesCube", "2024,North,Sales")

    Raises:
        RuntimeError: If TM1py is not installed
        ConnectionError: If connection fails
    """
    if not TM1_AVAILABLE:
        raise RuntimeError("TM1py is not installed. Install with: pip install TM1py")

    # Ensure config is loaded
    _load_central_config()

    # Get connection
    name = instance_name or TM1ConnectionManager.get_default_instance()
    tm1 = TM1ConnectionManager.get_connection(name)

    if tm1 is None:
        available = TM1ConnectionManager.list_instance_names()
        raise ConnectionError(
            f"Failed to connect to TM1 instance '{name}'. Available instances: {available}"
        )

    return tm1


def list_tm1_instances() -> list[str]:
    """
    List all configured TM1 instance names.

    Returns:
        List of instance names from tm1_config.json
    """
    _load_central_config()
    return TM1ConnectionManager.list_instance_names()


def get_tm1_instance_info(instance_name: str | None = None) -> dict[str, Any]:
    """
    Get configuration info for a TM1 instance (without connecting).

    Args:
        instance_name: Name of the instance (uses default if not specified)

    Returns:
        Dictionary with instance configuration (sensitive data masked)
    """
    _load_central_config()
    config = TM1ConnectionManager.get_instance_config(instance_name)
    if config:
        return config.to_dict()
    return {"error": f"Instance '{instance_name}' not found"}


def close_tm1_instance(instance_name: str | None = None) -> None:
    """
    Close a TM1 connection.

    Args:
        instance_name: Name of the instance to close (uses default if not specified)
    """
    TM1ConnectionManager.close_connection(instance_name)


def close_all_tm1_instances() -> None:
    """Close all active TM1 connections."""
    TM1ConnectionManager.close_all_connections()
