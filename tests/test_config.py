"""
Tests for the configuration module.
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.config import EnvConfig, FrameworkConfig


class TestEnvConfig:
    """Tests for EnvConfig class."""
    
    def test_singleton_pattern(self):
        """EnvConfig should be a singleton."""
        # Reset singleton for test
        EnvConfig._instance = None
        
        config1 = EnvConfig()
        config2 = EnvConfig()
        
        assert config1 is config2
    
    def test_get_env_variable(self):
        """Should get environment variables."""
        EnvConfig._instance = None
        config = EnvConfig()
        
        os.environ["TEST_VAR"] = "test_value"
        
        assert config.get("TEST_VAR") == "test_value"
        assert config.get("NONEXISTENT", "default") == "default"
        
        del os.environ["TEST_VAR"]
    
    def test_set_env_variable(self):
        """Should set environment variables."""
        EnvConfig._instance = None
        config = EnvConfig()
        
        config.set("CUSTOM_VAR", "custom_value")
        
        assert os.environ.get("CUSTOM_VAR") == "custom_value"
        assert config.get("CUSTOM_VAR") == "custom_value"
        
        del os.environ["CUSTOM_VAR"]
    
    def test_load_env_file(self, temp_dir: Path):
        """Should load variables from .env file."""
        EnvConfig._instance = None
        EnvConfig._env_file_loaded = False
        config = EnvConfig()
        
        # Create .env file
        env_file = temp_dir / ".env"
        env_file.write_text("TEST_FROM_FILE=file_value\nANOTHER_VAR=another")
        
        config.load_env_file(str(env_file))
        
        assert config.get("TEST_FROM_FILE") == "file_value"
        assert config.get("ANOTHER_VAR") == "another"
    
    def test_get_prefixed(self):
        """Should get variables with specific prefix."""
        EnvConfig._instance = None
        config = EnvConfig()
        
        os.environ["PYREST_VAR1"] = "value1"
        os.environ["PYREST_VAR2"] = "value2"
        os.environ["OTHER_VAR"] = "other"
        
        prefixed = config.get_prefixed("PYREST_")
        
        assert "PYREST_VAR1" in prefixed
        assert "PYREST_VAR2" in prefixed
        assert "OTHER_VAR" not in prefixed
        
        del os.environ["PYREST_VAR1"]
        del os.environ["PYREST_VAR2"]
        del os.environ["OTHER_VAR"]


class TestFrameworkConfig:
    """Tests for FrameworkConfig class."""
    
    def test_default_config(self, temp_dir: Path):
        """Should use default config when no file exists."""
        os.chdir(temp_dir)
        
        config = FrameworkConfig("nonexistent.json")
        
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.debug is False
        assert config.base_path == "/pyrest"
    
    def test_load_config_file(self, temp_dir: Path):
        """Should load configuration from file."""
        config_data = {
            "host": "127.0.0.1",
            "port": 9000,
            "debug": True,
            "custom_option": "custom_value"
        }
        
        config_file = temp_dir / "test_config.json"
        with open(config_file, "w") as f:
            json.dump(config_data, f)
        
        config = FrameworkConfig(str(config_file))
        
        assert config.host == "127.0.0.1"
        assert config.port == 9000
        assert config.debug is True
        assert config.get("custom_option") == "custom_value"
    
    def test_get_and_set(self, temp_dir: Path):
        """Should get and set configuration values."""
        os.chdir(temp_dir)
        config = FrameworkConfig("nonexistent.json")
        
        config.set("custom_key", "custom_value")
        
        assert config.get("custom_key") == "custom_value"
        assert config.get("nonexistent", "default") == "default"
    
    def test_jwt_secret_from_env(self, temp_dir: Path, mock_env_vars):
        """Should prefer JWT_SECRET from environment."""
        os.chdir(temp_dir)
        
        # Clear singleton
        from pyrest.config import get_config
        get_config.cache_clear()
        EnvConfig._instance = None
        EnvConfig._env_file_loaded = False
        
        config = FrameworkConfig("nonexistent.json")
        
        assert config.jwt_secret == "test-jwt-secret"
    
    def test_save_config(self, temp_dir: Path):
        """Should save configuration to file."""
        config_file = temp_dir / "save_test.json"
        
        config = FrameworkConfig(str(config_file))
        config.set("test_key", "test_value")
        config.save()
        
        # Reload and verify
        with open(config_file) as f:
            saved = json.load(f)
        
        assert saved["test_key"] == "test_value"
