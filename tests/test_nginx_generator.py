"""
Tests for the nginx configuration generator module.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.app_loader import AppConfig
from pyrest.nginx_generator import NginxGenerator, get_nginx_generator


class TestNginxGenerator:
    """Tests for NginxGenerator class."""

    @pytest.fixture
    def nginx_generator(self, temp_dir: Path):
        """Create NginxGenerator with temp output dir."""
        with patch("pyrest.nginx_generator.get_config") as mock_config:
            mock_config.return_value.port = 8000
            mock_config.return_value.base_path = "/pyrest"

            return NginxGenerator(str(temp_dir / "nginx"))

    @pytest.fixture
    def sample_embedded_apps(self, temp_dir: Path):
        """Create sample embedded app configs."""
        app_path = temp_dir / "hello"
        app_path.mkdir(parents=True)

        return [
            AppConfig(app_path, {"name": "hello", "prefix": "/hello"}),
        ]

    @pytest.fixture
    def sample_isolated_apps(self, temp_dir: Path):
        """Create sample isolated app configs."""
        app_path = temp_dir / "tm1data"
        app_path.mkdir(parents=True)
        (app_path / "requirements.txt").write_text("tm1py")

        config = AppConfig(app_path, {"name": "tm1data", "prefix": "/tm1data", "port": 8001})
        config.port = 8001

        return [config]

    def test_output_dir_creation(self, temp_dir: Path):
        """Should create output directory if not exists."""
        output_dir = temp_dir / "new_nginx_dir"

        with patch("pyrest.nginx_generator.get_config") as mock_config:
            mock_config.return_value.port = 8000
            mock_config.return_value.base_path = "/pyrest"

            NginxGenerator(str(output_dir))

            assert output_dir.exists()

    def test_generate_upstream_config(self, nginx_generator, sample_isolated_apps):
        """Should generate upstream blocks."""
        config = nginx_generator.generate_upstream_config(
            main_port=8000, isolated_apps=sample_isolated_apps
        )

        assert "upstream pyrest_main" in config
        assert "127.0.0.1:8000" in config
        assert "upstream pyrest_tm1data" in config
        assert "127.0.0.1:8001" in config

    def test_generate_location_config(
        self, nginx_generator, sample_embedded_apps, sample_isolated_apps
    ):
        """Should generate location blocks."""
        config = nginx_generator.generate_location_config(
            base_path="/pyrest",
            embedded_apps=sample_embedded_apps,
            isolated_apps=sample_isolated_apps,
        )

        assert "location /pyrest/tm1data/" in config
        assert "proxy_pass http://pyrest_tm1data" in config
        assert "location /pyrest/" in config
        assert "proxy_pass http://pyrest_main" in config

    def test_generate_full_config(
        self, nginx_generator, sample_embedded_apps, sample_isolated_apps
    ):
        """Should generate complete nginx configuration."""
        config = nginx_generator.generate_full_config(
            main_port=8000, embedded_apps=sample_embedded_apps, isolated_apps=sample_isolated_apps
        )

        # Check header
        assert "PyRest Nginx Configuration" in config

        # Check upstreams
        assert "upstream pyrest_main" in config
        assert "upstream pyrest_tm1data" in config

        # Check server block
        assert "server {" in config
        assert "listen 80" in config

        # Check locations
        assert "location ~ ^/pyrest/tm1data" in config
        assert "location /pyrest/" in config

        # Check health endpoint
        assert "location /nginx-health" in config

    @pytest.mark.asyncio
    async def test_generate_and_save(
        self, nginx_generator, sample_embedded_apps, sample_isolated_apps
    ):
        """Should save configuration to file (async)."""
        output_path = await nginx_generator.generate_and_save(
            embedded_apps=sample_embedded_apps,
            isolated_apps=sample_isolated_apps,
            filename="test_pyrest.conf",
        )

        assert output_path.exists()

        content = output_path.read_text()
        assert "upstream pyrest_main" in content

    def test_generate_app_summary(
        self, nginx_generator, sample_embedded_apps, sample_isolated_apps
    ):
        """Should generate app routing summary."""
        summary = nginx_generator.generate_app_summary(
            embedded_apps=sample_embedded_apps, isolated_apps=sample_isolated_apps
        )

        assert "Embedded Apps" in summary
        assert "hello" in summary
        assert "Isolated Apps" in summary
        assert "tm1data" in summary
        assert "port 8001" in summary

    def test_no_isolated_apps(self, nginx_generator, sample_embedded_apps):
        """Should handle case with no isolated apps."""
        config = nginx_generator.generate_full_config(
            main_port=8000, embedded_apps=sample_embedded_apps, isolated_apps=[]
        )

        assert "upstream pyrest_main" in config
        assert "pyrest_tm1data" not in config

    def test_no_embedded_apps(self, nginx_generator, sample_isolated_apps):
        """Should handle case with no embedded apps."""
        config = nginx_generator.generate_full_config(
            main_port=8000, embedded_apps=[], isolated_apps=sample_isolated_apps
        )

        assert "upstream pyrest_main" in config
        assert "upstream pyrest_tm1data" in config


class TestGetNginxGenerator:
    """Tests for get_nginx_generator singleton."""

    def test_singleton(self):
        """Should return same instance."""
        import pyrest.nginx_generator as ng

        ng._nginx_generator = None

        with patch("pyrest.nginx_generator.get_config") as mock_config:
            mock_config.return_value.port = 8000
            mock_config.return_value.base_path = "/pyrest"

            generator1 = get_nginx_generator()
            generator2 = get_nginx_generator()

            assert generator1 is generator2
