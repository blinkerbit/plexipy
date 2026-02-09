"""
Integration tests for the PyRest framework.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import tornado.testing
import tornado.web

from pyrest.handlers import BASE_PATH
from pyrest.server import create_app
from pyrest.server import create_app
from tests.conftest import TEST_JWT_SECRET

TEST_PASSWORD = "testpass"
ADMIN_PASSWORD = "adminpass"
FLOW_PASSWORD = "flowpass"
WRONG_PASSWORD = "wrong"


class TestServerIntegration(tornado.testing.AsyncHTTPTestCase):
    """Integration tests for the PyRest server."""

    def get_app(self):
        """Create test application with mocked config."""
        with patch("pyrest.server.get_config") as mock_config:
            mock_config.return_value.debug = True
            mock_config.return_value.apps_folder = "test_apps"
            mock_config.return_value.jwt_secret = TEST_JWT_SECRET
            mock_config.return_value.isolated_app_base_port = 9001
            mock_config.return_value.port = 8000
            mock_config.return_value.base_path = "/pyrest"
            mock_config.return_value.auth_config_file = "auth_config.json"
            mock_config.return_value.get.return_value = None

            with patch("pyrest.server.get_env"):
                with patch("pyrest.server.AppLoader") as mock_loader:
                    mock_loader.return_value.load_all_apps.return_value = []
                    mock_loader.return_value.loaded_apps = {}
                    mock_loader.return_value.isolated_apps = {}
                    mock_loader.return_value.get_embedded_apps.return_value = []
                    mock_loader.return_value.get_isolated_apps.return_value = []
                    mock_loader.return_value.get_loaded_apps_info.return_value = []

                    return create_app()

    def test_root_endpoint(self):
        """Root endpoint should return API info (HTML template or JSON fallback)."""
        response = self.fetch(f"{BASE_PATH}/")

        assert response.code == 200

        body = response.body.decode("utf-8")
        try:
            data = json.loads(body)
            # JSON fallback when no template is available
            assert data["success"] is True
            assert "PyRest" in data["data"]["name"]
            assert data["data"]["base_path"] == BASE_PATH
        except json.JSONDecodeError:
            # HTML template rendered successfully
            assert "PyRest" in body

    def test_health_endpoint(self):
        """Health endpoint should return healthy status."""
        response = self.fetch(f"{BASE_PATH}/health")

        assert response.code == 200

        data = json.loads(response.body)
        assert data["data"]["status"] == "healthy"

    def test_apps_endpoint(self):
        """Apps endpoint should list apps."""
        response = self.fetch(f"{BASE_PATH}/apps")

        assert response.code == 200

        data = json.loads(response.body)
        assert "apps" in data["data"]

    def test_status_endpoint(self):
        """Status endpoint should return system status."""
        response = self.fetch(f"{BASE_PATH}/status")

        assert response.code == 200

        data = json.loads(response.body)
        assert "framework" in data["data"]
        assert "embedded_apps" in data["data"]
        assert "isolated_apps" in data["data"]

    def test_cors_headers_not_sent_by_default(self):
        """CORS headers should NOT be sent when cors_origins is empty (S5122)."""
        response = self.fetch(f"{BASE_PATH}/health")

        # Default cors_origins is now [] — no CORS headers should be set
        assert "Access-Control-Allow-Origin" not in response.headers

    def test_options_request(self):
        """Should handle CORS preflight requests."""
        response = self.fetch(
            f"{BASE_PATH}/health", method="OPTIONS", allow_nonstandard_methods=True
        )

        assert response.code == 204

    def test_404_for_unknown_path(self):
        """Should return 404 for unknown paths."""
        response = self.fetch(f"{BASE_PATH}/unknown/path")

        assert response.code == 404


class TestAuthIntegration(tornado.testing.AsyncHTTPTestCase):
    """Integration tests for authentication endpoints."""

    def setUp(self):
        self._orig_jwt = os.environ.get("PYREST_JWT_SECRET")
        os.environ["PYREST_JWT_SECRET"] = TEST_JWT_SECRET
        import pyrest.auth as _auth_mod

        _auth_mod._auth_manager = None
        if hasattr(_auth_mod, "AuthConfig"):
            _auth_mod.AuthConfig._instance = None
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if self._orig_jwt is not None:
            os.environ["PYREST_JWT_SECRET"] = self._orig_jwt
        else:
            os.environ.pop("PYREST_JWT_SECRET", None)

    def get_app(self):
        """Create test application."""
        with patch("pyrest.server.get_config") as mock_config:
            mock_config.return_value.debug = True
            mock_config.return_value.apps_folder = "test_apps"
            mock_config.return_value.jwt_secret = TEST_JWT_SECRET
            mock_config.return_value.isolated_app_base_port = 9001
            mock_config.return_value.port = 8000
            mock_config.return_value.base_path = "/pyrest"
            mock_config.return_value.auth_config_file = "auth_config.json"
            mock_config.return_value.get.return_value = None

            with patch("pyrest.server.get_env"):
                with patch("pyrest.server.AppLoader") as mock_loader:
                    mock_loader.return_value.load_all_apps.return_value = []
                    mock_loader.return_value.loaded_apps = {}
                    mock_loader.return_value.isolated_apps = {}
                    mock_loader.return_value.get_embedded_apps.return_value = []
                    mock_loader.return_value.get_isolated_apps.return_value = []

                    with patch("pyrest.auth.get_auth_config") as mock_auth:
                        mock_auth.return_value.jwt_secret = TEST_JWT_SECRET
                        mock_auth.return_value.jwt_expiry_hours = 24
                        mock_auth.return_value.jwt_algorithm = "HS256"
                        mock_auth.return_value.tenant_id = ""
                        mock_auth.return_value.client_id = ""
                        mock_auth.return_value.client_secret = ""
                        mock_auth.return_value.is_configured = False

                        return create_app()

    def _get_admin_token(self) -> str:
        """Seed a bootstrap admin user and return a JWT token."""
        from pyrest.auth import get_auth_manager

        mgr = get_auth_manager()
        mgr.register_user("admin", ADMIN_PASSWORD)
        token = mgr.authenticate_user("admin", ADMIN_PASSWORD)
        return token

    def test_register_requires_auth(self):
        """Registration should require a valid JWT (S4834)."""
        response = self.fetch(
            f"{BASE_PATH}/auth/register",
            method="POST",
            body=json.dumps(
                {"username": "testuser", "password": TEST_PASSWORD, "email": "test@example.com"}
            ),
            headers={"Content-Type": "application/json"},
        )

        assert response.code == 401

    def test_register_user_with_auth(self):
        """Should register new user when caller has valid JWT."""
        token = self._get_admin_token()

        response = self.fetch(
            f"{BASE_PATH}/auth/register",
            method="POST",
            body=json.dumps(
                {"username": "testuser", "password": "testpass", "email": "test@example.com"}
            ),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )

        assert response.code == 201

        data = json.loads(response.body)
        assert data["success"] is True
        assert data["data"]["username"] == "testuser"

    def test_register_missing_fields_with_auth(self):
        """Should reject registration with missing fields (even with valid JWT)."""
        token = self._get_admin_token()

        response = self.fetch(
            f"{BASE_PATH}/auth/register",
            method="POST",
            body=json.dumps({"username": "testuser"}),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )

        assert response.code == 400

    def test_login_invalid_credentials(self):
        """Should reject invalid credentials."""
        response = self.fetch(
            f"{BASE_PATH}/auth/login",
            method="POST",
            body=json.dumps({"username": "nonexistent", "password": WRONG_PASSWORD}),
            headers={"Content-Type": "application/json"},
        )

        assert response.code == 401

    def test_auth_me_without_token(self):
        """Should reject /auth/me without token."""
        response = self.fetch(f"{BASE_PATH}/auth/me")

        assert response.code == 401

    def test_azure_login_not_configured(self):
        """Should return error if Azure AD not configured."""
        response = self.fetch(f"{BASE_PATH}/auth/azure/login")

        # Should return error since Azure AD is not configured
        assert response.code == 500


class TestFullWorkflow(tornado.testing.AsyncHTTPTestCase):
    """End-to-end workflow tests."""

    def setUp(self):
        # Ensure JWT secret is set for the full test lifecycle (not just get_app)
        self._orig_jwt = os.environ.get("PYREST_JWT_SECRET")
        os.environ["PYREST_JWT_SECRET"] = TEST_JWT_SECRET
        # Reset auth singletons so they pick up the env var
        import pyrest.auth as _auth_mod

        _auth_mod._auth_manager = None
        if hasattr(_auth_mod, "AuthConfig"):
            _auth_mod.AuthConfig._instance = None
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if self._orig_jwt is not None:
            os.environ["PYREST_JWT_SECRET"] = self._orig_jwt
        else:
            os.environ.pop("PYREST_JWT_SECRET", None)

    def get_app(self):
        """Create test application."""
        with patch("pyrest.server.get_config") as mock_config:
            mock_config.return_value.debug = True
            mock_config.return_value.apps_folder = "test_apps"
            mock_config.return_value.jwt_secret = TEST_JWT_SECRET
            mock_config.return_value.isolated_app_base_port = 9001
            mock_config.return_value.port = 8000
            mock_config.return_value.base_path = "/pyrest"
            mock_config.return_value.auth_config_file = "auth_config.json"
            mock_config.return_value.get.return_value = None

            with patch("pyrest.server.get_env"):
                with patch("pyrest.server.AppLoader") as mock_loader:
                    mock_loader.return_value.load_all_apps.return_value = []
                    mock_loader.return_value.loaded_apps = {}
                    mock_loader.return_value.isolated_apps = {}
                    mock_loader.return_value.get_embedded_apps.return_value = []
                    mock_loader.return_value.get_isolated_apps.return_value = []

                    with patch("pyrest.auth.get_auth_config") as mock_auth:
                        mock_auth.return_value.jwt_secret = TEST_JWT_SECRET
                        mock_auth.return_value.jwt_expiry_hours = 24
                        mock_auth.return_value.jwt_algorithm = "HS256"
                        mock_auth.return_value.is_configured = False

                        return create_app()

    def test_register_login_access_flow(self):
        """Test complete user flow: bootstrap admin -> register user -> login -> access protected."""
        from pyrest.auth import get_auth_manager

        # 0. Seed a bootstrap admin directly (simulates initial setup / CLI provisioning)
        mgr = get_auth_manager()
        mgr.register_user("admin", ADMIN_PASSWORD)
        admin_token = mgr.authenticate_user("admin", ADMIN_PASSWORD)

        # 1. Register a new user via the API (now requires auth)
        register_response = self.fetch(
            f"{BASE_PATH}/auth/register",
            method="POST",
            body=json.dumps({"username": "flowuser", "password": FLOW_PASSWORD}),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {admin_token}",
            },
        )
        assert register_response.code == 201

        # 2. Login as the new user
        login_response = self.fetch(
            f"{BASE_PATH}/auth/login",
            method="POST",
            body=json.dumps({"username": "flowuser", "password": FLOW_PASSWORD}),
            headers={"Content-Type": "application/json"},
        )
        assert login_response.code == 200

        login_data = json.loads(login_response.body)
        token = login_data["data"]["access_token"]

        # 3. Access protected endpoint
        me_response = self.fetch(
            f"{BASE_PATH}/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me_response.code == 200

        me_data = json.loads(me_response.body)
        assert me_data["data"]["sub"] == "flowuser"
