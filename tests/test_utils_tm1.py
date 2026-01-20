"""
Tests for the TM1 utilities module.
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.utils.tm1 import (
    TM1InstanceConfig,
    TM1ConnectionManager,
    is_tm1_available
)


class TestTM1InstanceConfig:
    """Tests for TM1InstanceConfig class."""
    
    def test_basic_config(self):
        """Should create instance config with basic settings."""
        config = {
            "description": "Test TM1 Server",
            "connection_type": "onprem",
            "server": "localhost",
            "port": "8010",
            "ssl": True
        }
        
        instance = TM1InstanceConfig("test", config)
        
        assert instance.name == "test"
        assert instance.description == "Test TM1 Server"
        assert instance.connection_type == "onprem"
        assert instance.is_onprem() is True
        assert instance.is_cloud() is False
    
    def test_cloud_config(self):
        """Should identify cloud connection type."""
        config = {
            "connection_type": "cloud",
            "cloud_region": "us-east",
            "cloud_tenant": "my-tenant"
        }
        
        instance = TM1InstanceConfig("cloud", config)
        
        assert instance.is_cloud() is True
        assert instance.is_onprem() is False
    
    def test_get_with_default(self):
        """Should return default value for missing keys."""
        config = {"connection_type": "onprem"}
        
        instance = TM1InstanceConfig("test", config)
        
        assert instance.get("nonexistent", "default") == "default"
        assert instance.get("connection_type") == "onprem"
    
    def test_get_bool(self):
        """Should convert values to boolean."""
        config = {
            "ssl": "true",
            "integrated_login": "false",
            "enabled": True
        }
        
        instance = TM1InstanceConfig("test", config)
        
        assert instance.get_bool("ssl") is True
        assert instance.get_bool("integrated_login") is False
        assert instance.get_bool("enabled") is True
        assert instance.get_bool("nonexistent", False) is False
    
    def test_get_int(self):
        """Should convert values to integer."""
        config = {"port": "8010", "timeout": 30}
        
        instance = TM1InstanceConfig("test", config)
        
        assert instance.get_int("port") == 8010
        assert instance.get_int("timeout") == 30
        assert instance.get_int("nonexistent", 5000) == 5000
    
    def test_env_var_resolution(self):
        """Should resolve environment variable references."""
        os.environ["TEST_SERVER"] = "prod-server.com"
        os.environ["TEST_PORT"] = "9010"
        
        config = {
            "server": "${TEST_SERVER}",
            "port": "${TEST_PORT:-8010}"
        }
        
        instance = TM1InstanceConfig("test", config)
        
        assert instance.get("server") == "prod-server.com"
        assert instance.get("port") == "9010"
        
        del os.environ["TEST_SERVER"]
        del os.environ["TEST_PORT"]
    
    def test_env_var_default(self):
        """Should use default when env var not set."""
        config = {"server": "${NONEXISTENT_VAR:-localhost}"}
        
        instance = TM1InstanceConfig("test", config)
        
        assert instance.get("server") == "localhost"
    
    def test_build_onprem_params(self):
        """Should build on-premise connection parameters."""
        config = {
            "connection_type": "onprem",
            "server": "tm1server.local",
            "port": "8010",
            "ssl": True,
            "user": "admin",
            "password": "secret"
        }
        
        instance = TM1InstanceConfig("test", config)
        params = instance.build_connection_params("TestSession")
        
        assert params["address"] == "tm1server.local"
        assert params["port"] == 8010
        assert params["ssl"] is True
        assert params["user"] == "admin"
        assert params["password"] == "secret"
        assert params["session_context"] == "TestSession"
    
    def test_build_onprem_params_integrated(self):
        """Should build params for Windows integrated auth."""
        config = {
            "connection_type": "onprem",
            "server": "localhost",
            "integrated_login": True
        }
        
        instance = TM1InstanceConfig("test", config)
        params = instance.build_connection_params()
        
        assert params["integrated_login"] is True
    
    def test_build_onprem_params_cam(self):
        """Should build params for CAM authentication."""
        config = {
            "connection_type": "onprem",
            "server": "localhost",
            "user": "admin",
            "password": "secret",
            "namespace": "LDAP",
            "gateway": "https://cam.local"
        }
        
        instance = TM1InstanceConfig("test", config)
        params = instance.build_connection_params()
        
        assert params["namespace"] == "LDAP"
        assert params["gateway"] == "https://cam.local"
    
    def test_build_cloud_params(self):
        """Should build cloud connection parameters."""
        config = {
            "connection_type": "cloud",
            "cloud_region": "us-east",
            "cloud_tenant": "my-tenant",
            "cloud_api_key": "api-key-123",
            "instance": "MyTM1"
        }
        
        instance = TM1InstanceConfig("test", config)
        params = instance.build_connection_params("CloudSession")
        
        assert "us-east" in params["base_url"]
        assert "my-tenant" in params["base_url"]
        assert params["api_key"] == "api-key-123"
        assert params["tenant"] == "my-tenant"
        assert params["instance"] == "MyTM1"
        assert params["ssl"] is True
    
    def test_to_dict_onprem(self):
        """Should convert on-premise config to dictionary."""
        config = {
            "description": "Test Server",
            "connection_type": "onprem",
            "server": "localhost",
            "port": "8010",
            "ssl": True
        }
        
        instance = TM1InstanceConfig("test", config)
        result = instance.to_dict()
        
        assert result["name"] == "test"
        assert result["description"] == "Test Server"
        assert result["connection_type"] == "onprem"
        assert result["server"] == "localhost"
        assert result["port"] == 8010
        assert "user" not in result  # Sensitive by default
    
    def test_to_dict_cloud(self):
        """Should convert cloud config to dictionary."""
        config = {
            "connection_type": "cloud",
            "cloud_region": "us-east",
            "cloud_tenant": "tenant-123"
        }
        
        instance = TM1InstanceConfig("cloud", config)
        result = instance.to_dict()
        
        assert result["connection_type"] == "cloud"
        assert result["cloud_region"] == "us-east"
        assert result["cloud_tenant"] == "tenant-123"


class TestTM1ConnectionManager:
    """Tests for TM1ConnectionManager class."""
    
    def setup_method(self):
        """Reset connection manager before each test."""
        TM1ConnectionManager._instances.clear()
        TM1ConnectionManager._connections.clear()
        TM1ConnectionManager._initialized = False
        TM1ConnectionManager._default_instance = "default"
    
    def test_initialize(self):
        """Should initialize with app configuration."""
        app_config = {
            "settings": {
                "default_instance": "production",
                "session_context": "TestApp"
            },
            "tm1_instances": {
                "production": {
                    "connection_type": "onprem",
                    "server": "prod.local"
                },
                "development": {
                    "connection_type": "onprem",
                    "server": "dev.local"
                }
            }
        }
        
        TM1ConnectionManager.initialize(app_config)
        
        assert TM1ConnectionManager._initialized is True
        assert TM1ConnectionManager.get_default_instance() == "production"
        assert len(TM1ConnectionManager.get_all_instances()) == 2
    
    def test_initialize_once(self):
        """Should only initialize once."""
        app_config = {
            "settings": {"default_instance": "first"},
            "tm1_instances": {"first": {"server": "first.local"}}
        }
        
        TM1ConnectionManager.initialize(app_config)
        
        # Try to initialize again with different config
        second_config = {
            "settings": {"default_instance": "second"},
            "tm1_instances": {"second": {"server": "second.local"}}
        }
        
        TM1ConnectionManager.initialize(second_config)
        
        # Should still have first config
        assert TM1ConnectionManager.get_default_instance() == "first"
    
    def test_get_instance_config(self):
        """Should get instance configuration by name."""
        app_config = {
            "tm1_instances": {
                "prod": {"server": "prod.local"},
                "dev": {"server": "dev.local"}
            }
        }
        
        TM1ConnectionManager.initialize(app_config)
        
        prod = TM1ConnectionManager.get_instance_config("prod")
        assert prod is not None
        assert prod.get("server") == "prod.local"
        
        # Non-existent
        missing = TM1ConnectionManager.get_instance_config("missing")
        assert missing is None
    
    def test_list_instance_names(self):
        """Should list all instance names."""
        app_config = {
            "tm1_instances": {
                "prod": {},
                "dev": {},
                "test": {}
            }
        }
        
        TM1ConnectionManager.initialize(app_config)
        
        names = TM1ConnectionManager.list_instance_names()
        assert len(names) == 3
        assert "prod" in names
        assert "dev" in names
        assert "test" in names
    
    def test_has_instance(self):
        """Should check if instance exists."""
        app_config = {
            "tm1_instances": {"existing": {}}
        }
        
        TM1ConnectionManager.initialize(app_config)
        
        assert TM1ConnectionManager.has_instance("existing") is True
        assert TM1ConnectionManager.has_instance("missing") is False
    
    def test_is_connected(self):
        """Should check connection status."""
        app_config = {
            "tm1_instances": {"test": {}}
        }
        
        TM1ConnectionManager.initialize(app_config)
        
        assert TM1ConnectionManager.is_connected("test") is False
        
        # Simulate connection
        TM1ConnectionManager._connections["test"] = MagicMock()
        assert TM1ConnectionManager.is_connected("test") is True
    
    def test_reset(self):
        """Should reset connection manager state."""
        app_config = {
            "settings": {"default_instance": "test"},
            "tm1_instances": {"test": {}}
        }
        
        TM1ConnectionManager.initialize(app_config)
        TM1ConnectionManager._connections["test"] = MagicMock()
        
        TM1ConnectionManager.reset()
        
        assert TM1ConnectionManager._initialized is False
        assert len(TM1ConnectionManager._instances) == 0
        assert len(TM1ConnectionManager._connections) == 0
    
    def test_get_connection_status(self):
        """Should return detailed connection status."""
        app_config = {
            "tm1_instances": {
                "prod": {
                    "server": "prod.local",
                    "port": "8010"
                }
            }
        }
        
        TM1ConnectionManager.initialize(app_config)
        
        status = TM1ConnectionManager.get_connection_status("prod")
        
        assert status["instance"] == "prod"
        assert status["configured"] is True
        assert status["connected"] is False
        assert "config" in status
    
    def test_get_connection_status_not_configured(self):
        """Should return error for non-configured instance."""
        TM1ConnectionManager.initialize({"tm1_instances": {}})
        
        status = TM1ConnectionManager.get_connection_status("missing")
        
        assert status["configured"] is False
        assert "error" in status
    
    @patch("pyrest.utils.tm1.TM1_AVAILABLE", False)
    def test_get_connection_tm1_not_available(self):
        """Should return None when TM1py not installed."""
        app_config = {"tm1_instances": {"test": {}}}
        TM1ConnectionManager.initialize(app_config)
        
        result = TM1ConnectionManager.get_connection("test")
        
        assert result is None


class TestTM1AvailabilityCheck:
    """Tests for TM1 availability checking."""
    
    def test_is_tm1_available(self):
        """Should check if TM1py is available."""
        # This will be True if TM1py is installed, False otherwise
        result = is_tm1_available()
        assert isinstance(result, bool)
