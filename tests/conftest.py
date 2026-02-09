"""
Pytest configuration and shared fixtures for PyRest tests.
"""

import json
import os
import shutil
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Minimum 32-byte secret for HMAC-SHA256 — shared across all test modules
TEST_JWT_SECRET = "pyrest-test-jwt-secret-key-32b!!"  # 32 bytes


@pytest.fixture
def temp_dir() -> Generator[Path]:
    """Create a temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def sample_config() -> dict[str, Any]:
    """Sample framework configuration."""
    return {
        "host": "0.0.0.0",
        "port": 8000,
        "debug": True,
        "base_path": "/pyrest",
        "apps_folder": "apps",
        "env_file": ".env",
        "auth_config_file": "auth_config.json",
        "jwt_secret": TEST_JWT_SECRET,
        "jwt_expiry_hours": 24,
        "cors_enabled": True,
        "cors_origins": ["*"],
        "isolated_app_base_port": 8001,
    }


@pytest.fixture
def sample_auth_config() -> dict[str, Any]:
    """Sample auth configuration."""
    return {
        "provider": "azure_ad",
        "tenant_id": "test-tenant-id",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "redirect_uri": "http://localhost:8000/pyrest/auth/azure/callback",
        "scopes": ["openid", "profile", "email"],
        "jwt_secret": TEST_JWT_SECRET,
        "jwt_expiry_hours": 24,
        "jwt_algorithm": "HS256",
    }


@pytest.fixture
def sample_app_config() -> dict[str, Any]:
    """Sample app configuration."""
    return {
        "name": "testapp",
        "version": "1.0.0",
        "description": "Test application",
        "enabled": True,
        "auth_required": False,
        "settings": {"custom_setting": "value"},
    }


@pytest.fixture
def temp_config_file(temp_dir: Path, sample_config: dict[str, Any]) -> Path:
    """Create a temporary config.json file."""
    config_path = temp_dir / "config.json"
    with open(config_path, "w") as f:
        json.dump(sample_config, f)
    return config_path


@pytest.fixture
def temp_auth_config_file(temp_dir: Path, sample_auth_config: dict[str, Any]) -> Path:
    """Create a temporary auth_config.json file."""
    config_path = temp_dir / "auth_config.json"
    with open(config_path, "w") as f:
        json.dump(sample_auth_config, f)
    return config_path


@pytest.fixture
def temp_app_dir(temp_dir: Path, sample_app_config: dict[str, Any]) -> Path:
    """Create a temporary app directory with config and handlers."""
    # Use source_apps to avoid conflict with app_loader's apps folder
    apps_dir = temp_dir / "source_apps"
    app_dir = apps_dir / "testapp"
    app_dir.mkdir(parents=True)

    # Create config.json
    with open(app_dir / "config.json", "w") as f:
        json.dump(sample_app_config, f)

    # Create handlers.py
    handlers_content = """
from pyrest.handlers import BaseHandler

class TestHandler(BaseHandler):
    async def get(self):
        self.success(data={"message": "Test handler"})

def get_handlers():
    return [
        (r"/", TestHandler),
    ]
"""
    with open(app_dir / "handlers.py", "w") as f:
        f.write(handlers_content)

    return app_dir


@pytest.fixture
def temp_isolated_app_dir(temp_dir: Path) -> Path:
    """Create a temporary isolated app directory with requirements.txt."""
    # Use source_apps to avoid conflict with app_loader's apps folder
    apps_dir = temp_dir / "source_apps"
    app_dir = apps_dir / "isolatedapp"
    app_dir.mkdir(parents=True)

    # Create config.json
    config = {
        "name": "isolatedapp",
        "version": "1.0.0",
        "description": "Isolated test application",
        "enabled": True,
        "port": 8002,
    }
    with open(app_dir / "config.json", "w") as f:
        json.dump(config, f)

    # Create requirements.txt (triggers isolated mode)
    with open(app_dir / "requirements.txt", "w") as f:
        f.write("tornado>=6.4\n")

    # Create handlers.py
    handlers_content = """
from pyrest.handlers import BaseHandler

class IsolatedHandler(BaseHandler):
    async def get(self):
        self.success(data={"message": "Isolated handler"})

def get_handlers():
    return [
        (r"/", IsolatedHandler),
    ]
"""
    with open(app_dir / "handlers.py", "w") as f:
        f.write(handlers_content)

    return app_dir


@pytest.fixture
def mock_env_vars():
    """Set up mock environment variables for testing."""
    original_env = os.environ.copy()

    os.environ["AZURE_AD_TENANT_ID"] = "test-tenant"
    os.environ["AZURE_AD_CLIENT_ID"] = "test-client"
    os.environ["AZURE_AD_CLIENT_SECRET"] = "test-secret"
    os.environ["PYREST_JWT_SECRET"] = TEST_JWT_SECRET

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def sample_tm1_config() -> dict[str, Any]:
    """Sample TM1 app configuration with multiple instances."""
    return {
        "name": "tm1app",
        "version": "1.0.0",
        "settings": {"default_instance": "production", "session_context": "Test Session"},
        "os_vars": {"TM1_DEFAULT_INSTANCE": "production"},
        "tm1_instances": {
            "production": {
                "description": "Production TM1 Server",
                "connection_type": "onprem",
                "server": "prod-tm1.local",
                "port": "8010",
                "ssl": True,
                "user": "admin",
                "password": "secret",
            },
            "development": {
                "description": "Development TM1 Server",
                "connection_type": "onprem",
                "server": "dev-tm1.local",
                "port": "8011",
                "ssl": True,
            },
            "cloud": {
                "description": "Cloud TM1 Instance",
                "connection_type": "cloud",
                "cloud_region": "us-east",
                "cloud_tenant": "test-tenant",
                "cloud_api_key": "test-api-key",
            },
        },
    }


@pytest.fixture
def temp_log_dir(temp_dir: Path) -> Path:
    """Create a temporary log directory."""
    log_dir = temp_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


@pytest.fixture
def reset_tm1_manager():
    """Reset TM1ConnectionManager before and after test."""
    from pyrest.utils.tm1 import TM1ConnectionManager

    # Reset before test
    TM1ConnectionManager._instances.clear()
    TM1ConnectionManager._connections.clear()
    TM1ConnectionManager._initialized = False
    TM1ConnectionManager._default_instance = "default"

    yield

    # Reset after test
    TM1ConnectionManager._instances.clear()
    TM1ConnectionManager._connections.clear()
    TM1ConnectionManager._initialized = False
    TM1ConnectionManager._default_instance = "default"


@pytest.fixture
def reset_auth_config():
    """Reset AuthConfig singleton before test."""
    from pyrest.auth import AuthConfig

    AuthConfig._instance = None
    yield
    AuthConfig._instance = None
