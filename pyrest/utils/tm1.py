"""
TM1 Connection Utilities for PyRest Framework.

Provides connection management for multiple TM1 instances supporting both:
- TM1 On-Premise (traditional TM1 servers)
- TM1 Cloud (IBM Planning Analytics as a Service)

Usage:
    from pyrest.utils import TM1ConnectionManager, TM1InstanceConfig
    
    # Initialize with app config
    TM1ConnectionManager.initialize(app_config)
    
    # Get connection to a specific instance
    tm1 = TM1ConnectionManager.get_connection("production")
    
    # Use the connection
    cubes = tm1.cubes.get_all_names()
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List

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
    
    def __init__(self, name: str, config: Dict[str, Any]):
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
            env_expr = value[start + 2:end]
            
            if ":-" in env_expr:
                var_name, default = env_expr.split(":-", 1)
                result = os.environ.get(var_name.strip(), default)
            else:
                result = os.environ.get(env_expr.strip(), "")
            
            # Handle prefix/suffix around the ${...}
            prefix = value[:start]
            suffix = value[end + 1:]
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
    
    def is_cloud(self) -> bool:
        """Check if this is a cloud instance."""
        return self.connection_type in ("cloud", "paas")
    
    def is_onprem(self) -> bool:
        """Check if this is an on-premise instance."""
        return not self.is_cloud()
    
    def build_connection_params(self, session_context: str = "PyRest TM1 App") -> Dict[str, Any]:
        """
        Build TM1py connection parameters for this instance.
        
        Args:
            session_context: Session context string for TM1 server
            
        Returns:
            Dictionary of parameters for TM1Service constructor
        """
        if self.is_cloud():
            return self._build_cloud_params(session_context)
        else:
            return self._build_onprem_params(session_context)
    
    def _build_onprem_params(self, session_context: str) -> Dict[str, Any]:
        """Build connection parameters for TM1 On-Premise."""
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
            logger.debug(f"Instance {self.name}: Using Windows Integrated Authentication")
        elif cam_passport:
            params["cam_passport"] = cam_passport
            if namespace:
                params["namespace"] = namespace
            logger.debug(f"Instance {self.name}: Using CAM Passport Authentication")
        elif namespace:
            params["user"] = self.get("user", "")
            params["password"] = self.get("password", "")
            params["namespace"] = namespace
            gateway = self.get("gateway", "")
            if gateway:
                params["gateway"] = gateway
            logger.debug(f"Instance {self.name}: Using CAM Authentication")
        else:
            params["user"] = self.get("user", "")
            params["password"] = self.get("password", "")
            logger.debug(f"Instance {self.name}: Using Basic TM1 Authentication")
        
        return params
    
    def _build_cloud_params(self, session_context: str) -> Dict[str, Any]:
        """Build connection parameters for TM1 Cloud (IBM Planning Analytics as a Service)."""
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
        
        logger.debug(f"Instance {self.name}: Using TM1 Cloud (region: {region})")
        return params
    
    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """
        Convert instance config to dictionary (for API responses).
        
        Args:
            include_sensitive: Include sensitive fields like username
            
        Returns:
            Dictionary representation of the instance
        """
        if self.is_cloud():
            info = {
                "name": self.name,
                "description": self.description,
                "connection_type": "cloud",
                "cloud_region": self.get("cloud_region", ""),
                "cloud_tenant": self.get("cloud_tenant", ""),
                "instance": self.get("instance", ""),
            }
        else:
            info = {
                "name": self.name,
                "description": self.description,
                "connection_type": "onprem",
                "server": self.get("server", "localhost"),
                "port": self.get_int("port", 8010),
                "ssl": self.get_bool("ssl", True),
            }
        
        if include_sensitive:
            if not self.is_cloud():
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
    
    _instances: Dict[str, TM1InstanceConfig] = {}
    _connections: Dict[str, Any] = {}  # instance_name -> TM1Service
    _default_instance: str = "default"
    _session_context: str = "PyRest TM1 App"
    _initialized: bool = False
    _app_logger: Optional[logging.Logger] = None
    
    @classmethod
    def initialize(cls, app_config: Dict[str, Any], app_logger: Optional[logging.Logger] = None) -> None:
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
            cls._app_logger.info(f"Registered TM1 instance: {name} ({cls._instances[name].connection_type})")
        
        cls._initialized = True
        cls._app_logger.info(f"TM1ConnectionManager initialized with {len(cls._instances)} instances")
    
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
    def get_instance_config(cls, instance_name: str = None) -> Optional[TM1InstanceConfig]:
        """Get the configuration for a specific instance."""
        name = instance_name or cls._default_instance
        return cls._instances.get(name)
    
    @classmethod
    def get_all_instances(cls) -> Dict[str, TM1InstanceConfig]:
        """Get all configured instances."""
        return cls._instances.copy()
    
    @classmethod
    def list_instance_names(cls) -> List[str]:
        """Get list of all instance names."""
        return list(cls._instances.keys())
    
    @classmethod
    def has_instance(cls, instance_name: str) -> bool:
        """Check if an instance is configured."""
        return instance_name in cls._instances
    
    @classmethod
    def get_connection(cls, instance_name: str = None) -> Optional[Any]:
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
                log.info(f"Connecting to TM1 Cloud instance '{name}' (region: {instance_config.get('cloud_region')})")
            else:
                log.info(f"Connecting to TM1 On-Premise instance '{name}' (server: {params['address']}:{params['port']})")
            
            cls._connections[name] = TM1Service(**params)
            log.info(f"TM1 connection established for instance '{name}'")
            
            return cls._connections[name]
            
        except Exception as e:
            log.error(f"TM1 connection error for instance '{name}': {e}")
            import traceback
            log.debug(traceback.format_exc())
            cls._connections[name] = None
            return None
    
    @classmethod
    def close_connection(cls, instance_name: str = None) -> None:
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
    def reset_connection(cls, instance_name: str = None) -> None:
        """Reset a connection (close and allow reconnection)."""
        cls.close_connection(instance_name)
    
    @classmethod
    def get_default_instance(cls) -> str:
        """Get the default instance name."""
        return cls._default_instance
    
    @classmethod
    def is_connected(cls, instance_name: str = None) -> bool:
        """Check if a connection exists for the given instance."""
        name = instance_name or cls._default_instance
        return name in cls._connections and cls._connections[name] is not None
    
    @classmethod
    def get_connection_status(cls, instance_name: str = None) -> Dict[str, Any]:
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
                "error": f"Instance '{name}' not found"
            }
        
        status = {
            "instance": name,
            "configured": True,
            "connected": cls.is_connected(name),
            "config": config.to_dict()
        }
        
        if status["connected"]:
            try:
                tm1 = cls._connections[name]
                status["server_name"] = tm1.server.get_server_name()
            except Exception as e:
                status["connected"] = False
                status["error"] = str(e)
        
        return status
