"""
Tests for the AppConfigParser class.
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.config import AppConfigParser


class TestAppConfigParser:
    """Tests for AppConfigParser class."""
    
    def setup_method(self):
        """Clean up environment before each test."""
        # Remove any test env vars
        for key in list(os.environ.keys()):
            if key.startswith("TEST_") or key.startswith("testapp."):
                del os.environ[key]
    
    def teardown_method(self):
        """Clean up environment after each test."""
        for key in list(os.environ.keys()):
            if key.startswith("TEST_") or key.startswith("testapp."):
                del os.environ[key]
    
    def test_basic_config(self):
        """Should parse basic configuration."""
        config_data = {
            "name": "testapp",
            "version": "1.0.0",
            "enabled": True,
            "settings": {
                "timeout": 30
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        assert parser.get("name") == "testapp"
        assert parser.get("version") == "1.0.0"
        assert parser.get("enabled") is True
        assert parser.get("settings")["timeout"] == 30
    
    def test_os_vars_prefixed(self):
        """Should set prefixed environment variables."""
        config_data = {
            "name": "testapp",
            "os_vars": {
                "API_KEY": "secret123",
                "DEBUG": "true"
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        assert os.environ.get("testapp.API_KEY") == "secret123"
        assert os.environ.get("testapp.DEBUG") == "true"
    
    def test_os_vars_isolated(self):
        """Should set direct env vars for isolated apps."""
        config_data = {
            "name": "testapp",
            "os_vars": {
                "API_KEY": "secret123"
            }
        }
        
        parser = AppConfigParser("testapp", config_data, is_isolated=True)
        
        # Should have both prefixed and direct
        assert os.environ.get("testapp.API_KEY") == "secret123"
        assert os.environ.get("API_KEY") == "secret123"
    
    def test_get_os_var(self):
        """Should get os_var by parameter name."""
        config_data = {
            "os_vars": {
                "MY_VAR": "my_value"
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        assert parser.get_os_var("MY_VAR") == "my_value"
        assert parser.get_os_var("NONEXISTENT", "default") == "default"
    
    def test_get_all_os_vars(self):
        """Should return all set os_vars."""
        config_data = {
            "os_vars": {
                "VAR1": "value1",
                "VAR2": "value2"
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        all_vars = parser.get_all_os_vars()
        
        assert "testapp.VAR1" in all_vars
        assert "testapp.VAR2" in all_vars
    
    def test_env_var_resolution_simple(self):
        """Should resolve ${VAR} syntax."""
        os.environ["TEST_VALUE"] = "resolved_value"
        
        config_data = {
            "settings": {
                "my_setting": "${TEST_VALUE}"
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        assert parser.get("settings")["my_setting"] == "resolved_value"
    
    def test_env_var_resolution_with_default(self):
        """Should resolve ${VAR:-default} syntax."""
        config_data = {
            "settings": {
                "with_default": "${NONEXISTENT_VAR:-default_value}",
                "empty_default": "${ANOTHER_MISSING:-}"
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        settings = parser.get("settings")
        assert settings["with_default"] == "default_value"
        assert settings["empty_default"] == ""
    
    def test_env_var_resolution_with_set_var(self):
        """Should use env var when set, not default."""
        os.environ["TEST_OVERRIDE"] = "from_env"
        
        config_data = {
            "settings": {
                "my_setting": "${TEST_OVERRIDE:-default}"
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        assert parser.get("settings")["my_setting"] == "from_env"
    
    def test_nested_dict_resolution(self):
        """Should resolve env vars in nested dicts."""
        os.environ["TEST_NESTED"] = "nested_value"
        
        config_data = {
            "settings": {
                "level1": {
                    "level2": {
                        "value": "${TEST_NESTED}"
                    }
                }
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        assert parser.get("settings")["level1"]["level2"]["value"] == "nested_value"
    
    def test_list_resolution(self):
        """Should resolve env vars in lists."""
        os.environ["TEST_LIST_VAL"] = "list_value"
        
        config_data = {
            "settings": {
                "my_list": ["static", "${TEST_LIST_VAL}", "another"]
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        result = parser.get("settings")["my_list"]
        assert result[0] == "static"
        assert result[1] == "list_value"
        assert result[2] == "another"
    
    def test_tm1_instances(self):
        """Should process tm1_instances section."""
        config_data = {
            "tm1_instances": {
                "prod": {
                    "server": "prod.local",
                    "port": "8010"
                },
                "dev": {
                    "server": "dev.local",
                    "port": "8011"
                }
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        instances = parser.get_tm1_instances()
        assert "prod" in instances
        assert "dev" in instances
        assert instances["prod"]["server"] == "prod.local"
    
    def test_get_tm1_instance(self):
        """Should get specific TM1 instance config."""
        config_data = {
            "tm1_instances": {
                "prod": {"server": "prod.local"}
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        prod = parser.get_tm1_instance("prod")
        assert prod is not None
        assert prod["server"] == "prod.local"
        
        missing = parser.get_tm1_instance("missing")
        assert missing is None
    
    def test_get_tm1_instance_names(self):
        """Should return list of TM1 instance names."""
        config_data = {
            "tm1_instances": {
                "prod": {},
                "dev": {},
                "test": {}
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        names = parser.get_tm1_instance_names()
        assert len(names) == 3
        assert "prod" in names
        assert "dev" in names
        assert "test" in names
    
    def test_tm1_instance_env_vars(self):
        """Should set env vars for TM1 instances."""
        config_data = {
            "tm1_instances": {
                "prod": {
                    "server": "prod.local",
                    "port": "8010"
                }
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        assert os.environ.get("testapp.tm1.prod.server") == "prod.local"
        assert os.environ.get("testapp.tm1.prod.port") == "8010"
    
    def test_tm1_instance_env_resolution(self):
        """Should resolve env vars in TM1 instance config."""
        os.environ["TEST_TM1_SERVER"] = "resolved-server.local"
        
        config_data = {
            "tm1_instances": {
                "prod": {
                    "server": "${TEST_TM1_SERVER}"
                }
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        instances = parser.get_tm1_instances()
        assert instances["prod"]["server"] == "resolved-server.local"
    
    def test_get_resolved_config(self):
        """Should return fully resolved configuration."""
        os.environ["TEST_RESOLVED"] = "resolved"
        
        config_data = {
            "name": "testapp",
            "settings": {
                "value": "${TEST_RESOLVED}"
            },
            "os_vars": {
                "IGNORED": "value"
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        resolved = parser.get_resolved_config()
        
        assert resolved["name"] == "testapp"
        assert resolved["settings"]["value"] == "resolved"
        assert "os_vars" not in resolved  # os_vars is handled specially
    
    def test_to_env_dict(self):
        """Should convert config to environment dictionary."""
        config_data = {
            "os_vars": {
                "VAR1": "value1"
            },
            "settings": {
                "timeout": 30
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        env_dict = parser.to_env_dict()
        
        assert "testapp.VAR1" in env_dict
        assert "testapp.timeout" in env_dict
    
    def test_from_file(self, temp_dir):
        """Should create parser from config file."""
        app_dir = temp_dir / "myapp"
        app_dir.mkdir()
        
        config_data = {
            "name": "myapp",
            "version": "2.0.0"
        }
        
        config_file = app_dir / "config.json"
        with open(config_file, "w") as f:
            json.dump(config_data, f)
        
        parser = AppConfigParser.from_file(config_file)
        
        assert parser.app_name == "myapp"
        assert parser.get("version") == "2.0.0"
    
    def test_complex_os_vars(self):
        """Should handle complex types in os_vars."""
        config_data = {
            "os_vars": {
                "SIMPLE": "value",
                "LIST_VAR": ["a", "b", "c"],
                "DICT_VAR": {"key": "value"}
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        # Lists and dicts should be JSON-encoded
        assert os.environ.get("testapp.SIMPLE") == "value"
        assert json.loads(os.environ.get("testapp.LIST_VAR")) == ["a", "b", "c"]
        assert json.loads(os.environ.get("testapp.DICT_VAR")) == {"key": "value"}
    
    def test_boolean_in_tm1_instances(self):
        """Should handle boolean values in TM1 instances."""
        config_data = {
            "tm1_instances": {
                "prod": {
                    "ssl": True,
                    "integrated_login": False
                }
            }
        }
        
        parser = AppConfigParser("testapp", config_data)
        
        assert os.environ.get("testapp.tm1.prod.ssl") == "true"
        assert os.environ.get("testapp.tm1.prod.integrated_login") == "false"
