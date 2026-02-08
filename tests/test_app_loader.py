"""
Tests for the app loader module.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.app_loader import AppConfig, AppLoader


class TestAppConfig:
    """Tests for AppConfig class."""

    def test_basic_config(self, temp_dir: Path, sample_app_config):
        """Should create AppConfig from config data."""
        app_path = temp_dir / "testapp"
        app_path.mkdir()

        config = AppConfig(app_path, sample_app_config)

        assert config.name == "testapp"
        assert config.version == "1.0.0"
        assert config.enabled is True
        assert config.prefix == "/testapp"

    def test_custom_prefix(self, temp_dir: Path):
        """Should use custom prefix if specified."""
        app_path = temp_dir / "myapp"
        app_path.mkdir()

        config_data = {"name": "myapp", "prefix": "/custom/path"}

        config = AppConfig(app_path, config_data)

        assert config.prefix == "/custom/path"

    def test_has_requirements(self, temp_dir: Path):
        """Should detect requirements.txt file."""
        app_path = temp_dir / "app_with_reqs"
        app_path.mkdir()

        # No requirements.txt
        config = AppConfig(app_path, {"name": "app_with_reqs"})
        assert config.has_requirements is False

        # With requirements.txt
        (app_path / "requirements.txt").write_text("tornado>=6.4")
        assert config.has_requirements is True

    def test_is_isolated(self, temp_dir: Path):
        """Should be isolated if has requirements.txt."""
        app_path = temp_dir / "isolated_app"
        app_path.mkdir()

        config = AppConfig(app_path, {"name": "isolated_app"})
        assert config.is_isolated is False

        (app_path / "requirements.txt").write_text("somepackage")
        assert config.is_isolated is True

    def test_port_assignment(self, temp_dir: Path):
        """Should handle port configuration."""
        app_path = temp_dir / "portapp"
        app_path.mkdir()

        # With explicit port
        config = AppConfig(app_path, {"name": "portapp", "port": 9000})
        assert config.port == 9000

        # Without port
        config2 = AppConfig(app_path, {"name": "portapp2"})
        assert config2.port is None

        # Assign port
        config2.port = 8005
        assert config2.port == 8005

    def test_get_settings(self, temp_dir: Path, sample_app_config):
        """Should get settings from config."""
        app_path = temp_dir / "settingsapp"
        app_path.mkdir()

        config = AppConfig(app_path, sample_app_config)

        assert config.settings["custom_setting"] == "value"
        assert config.get("settings") == {"custom_setting": "value"}


class TestAppLoader:
    """Tests for AppLoader class."""

    @pytest.fixture
    def app_loader(self, temp_dir: Path):
        """Create AppLoader with temp apps folder."""
        apps_folder = temp_dir / "apps"
        apps_folder.mkdir()

        with patch("pyrest.app_loader.get_config") as mock_config:
            mock_config.return_value.apps_folder = str(apps_folder)
            mock_config.return_value.isolated_app_base_port = 8001
            mock_config.return_value.port = 8000

            return AppLoader(str(apps_folder))

    def test_discover_empty_folder(self, app_loader):
        """Should handle empty apps folder."""
        apps = app_loader.discover_apps()

        assert apps == []

    def test_discover_apps(self, app_loader):
        """Should discover apps with config.json."""
        # Create test app
        app_dir = app_loader.apps_folder / "myapp"
        app_dir.mkdir()

        with open(app_dir / "config.json", "w") as f:
            json.dump({"name": "myapp", "enabled": True}, f)

        apps = app_loader.discover_apps()

        assert len(apps) == 1
        assert apps[0].name == "myapp"

    def test_discover_disabled_app(self, app_loader):
        """Should skip disabled apps."""
        app_dir = app_loader.apps_folder / "disabled_app"
        app_dir.mkdir()

        with open(app_dir / "config.json", "w") as f:
            json.dump({"name": "disabled_app", "enabled": False}, f)

        apps = app_loader.discover_apps()

        assert len(apps) == 0

    def test_discover_without_config(self, app_loader):
        """Should skip folders without config.json."""
        app_dir = app_loader.apps_folder / "no_config"
        app_dir.mkdir()

        apps = app_loader.discover_apps()

        assert len(apps) == 0

    def test_skip_underscore_folders(self, app_loader):
        """Should skip folders starting with underscore."""
        app_dir = app_loader.apps_folder / "_private"
        app_dir.mkdir()

        with open(app_dir / "config.json", "w") as f:
            json.dump({"name": "_private", "enabled": True}, f)

        apps = app_loader.discover_apps()

        assert len(apps) == 0

    def test_load_app_module(self, app_loader, temp_app_dir: Path):
        """Should load app module from handlers.py."""
        # Move app to loader's folder
        import shutil

        dest = app_loader.apps_folder / "testapp"
        shutil.copytree(temp_app_dir, dest)

        apps = app_loader.discover_apps()
        assert len(apps) == 1

        module = app_loader.load_app_module(apps[0])

        assert module is not None
        assert hasattr(module, "get_handlers")

    def test_get_app_handlers(self, app_loader, temp_app_dir: Path):
        """Should get handlers from app module."""
        import shutil

        dest = app_loader.apps_folder / "testapp"
        shutil.copytree(temp_app_dir, dest)

        apps = app_loader.discover_apps()
        module = app_loader.load_app_module(apps[0])

        handlers = app_loader.get_app_handlers(apps[0], module)

        assert len(handlers) > 0
        assert "/pyrest/testapp/" in handlers[0][0]

    def test_load_all_apps_embedded(self, app_loader, temp_app_dir: Path):
        """Should load embedded apps into handlers list."""
        import shutil

        dest = app_loader.apps_folder / "testapp"
        shutil.copytree(temp_app_dir, dest)

        handlers = app_loader.load_all_apps()

        assert len(handlers) > 0
        assert "testapp" in app_loader.loaded_apps
        assert len(app_loader.isolated_apps) == 0

    def test_load_all_apps_isolated(self, app_loader, temp_isolated_app_dir: Path):
        """Should detect isolated apps and not load handlers."""
        import shutil

        dest = app_loader.apps_folder / "isolatedapp"
        shutil.copytree(temp_isolated_app_dir, dest)

        handlers = app_loader.load_all_apps()

        # Isolated apps don't add handlers to main process
        assert len(handlers) == 0
        assert "isolatedapp" in app_loader.isolated_apps
        assert len(app_loader.loaded_apps) == 0

    def test_port_assignment_auto(self, app_loader, temp_isolated_app_dir: Path):
        """Should auto-assign ports to isolated apps without explicit port."""
        import shutil

        dest = app_loader.apps_folder / "isolatedapp"
        shutil.copytree(temp_isolated_app_dir, dest)

        # Remove explicit port from config
        config_file = dest / "config.json"
        with open(config_file) as f:
            config = json.load(f)
        del config["port"]
        with open(config_file, "w") as f:
            json.dump(config, f)

        app_loader.load_all_apps()

        isolated_app = app_loader.isolated_apps["isolatedapp"]
        assert isolated_app.port == 8001  # First auto-assigned port

    def test_get_loaded_apps_info(self, app_loader, temp_app_dir: Path):
        """Should return info about all loaded apps."""
        import shutil

        dest = app_loader.apps_folder / "testapp"
        shutil.copytree(temp_app_dir, dest)

        app_loader.load_all_apps()

        info = app_loader.get_loaded_apps_info()

        assert len(info) == 1
        assert info[0]["name"] == "testapp"
        assert info[0]["isolated"] is False
