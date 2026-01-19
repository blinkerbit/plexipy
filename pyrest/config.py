"""
Configuration management for PyRest framework.
Handles environment variables and framework settings.
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional
from functools import lru_cache


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
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        os.environ[key] = value
                        self._custom_vars[key] = value
            self._env_file_loaded = True
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get an environment variable."""
        return os.environ.get(key, default)
    
    def set(self, key: str, value: str) -> None:
        """Set an environment variable."""
        os.environ[key] = value
        self._custom_vars[key] = value
    
    def get_all(self) -> Dict[str, str]:
        """Get all environment variables."""
        return dict(os.environ)
    
    def get_custom(self) -> Dict[str, str]:
        """Get only custom/loaded environment variables."""
        return self._custom_vars.copy()
    
    def get_prefixed(self, prefix: str) -> Dict[str, str]:
        """Get all environment variables with a specific prefix."""
        return {
            k: v for k, v in os.environ.items() 
            if k.startswith(prefix)
        }


class FrameworkConfig:
    """
    Main framework configuration.
    """
    
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self._config = self._load_config()
        self.env = EnvConfig()
        self.env.load_env_file(self._config.get("env_file", ".env"))
    
    def _load_config(self) -> Dict[str, Any]:
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
            "jwt_secret": "change-this-secret-in-production",
            "jwt_expiry_hours": 24,
            "cors_enabled": True,
            "cors_origins": ["*"],
            "log_level": "INFO",
            "static_path": "static",
            "template_path": "templates",
            "isolated_app_base_port": 8001
        }
        
        if config_path.exists():
            with open(config_path, "r") as f:
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
        with open(self.config_file, "w") as f:
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
        return self._config["apps_folder"]
    
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


@lru_cache()
def get_config() -> FrameworkConfig:
    """Get the singleton framework configuration."""
    return FrameworkConfig()


@lru_cache()
def get_env() -> EnvConfig:
    """Get the singleton environment configuration."""
    return EnvConfig()
