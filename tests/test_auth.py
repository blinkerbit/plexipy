"""
Tests for the authentication module.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import jwt
from pyrest.auth import (
    JWTAuth, AzureADAuth, AuthManager, AuthConfig,
    AuthError, authenticated, require_roles, get_auth_config
)


class TestAuthConfig:
    """Tests for AuthConfig class."""
    
    def test_load_from_file(self, temp_dir: Path, sample_auth_config):
        """Should load auth config from file."""
        # Reset singleton
        AuthConfig._instance = None
        
        config_file = temp_dir / "auth_config.json"
        with open(config_file, "w") as f:
            json.dump(sample_auth_config, f)
        
        # Mock get_config to return our test config
        with patch("pyrest.auth.get_config") as mock_config:
            mock_config.return_value.auth_config_file = str(config_file)
            mock_config.return_value.jwt_secret = "default-secret"
            mock_config.return_value.jwt_expiry_hours = 24
            
            with patch("pyrest.auth.get_env") as mock_env:
                mock_env.return_value.get.return_value = None
                
                auth_config = AuthConfig()
                
                assert auth_config.tenant_id == "test-tenant-id"
                assert auth_config.client_id == "test-client-id"
                assert auth_config.jwt_algorithm == "HS256"
    
    def test_is_configured(self, temp_dir: Path):
        """Should check if Azure AD is properly configured."""
        AuthConfig._instance = None
        
        # Not configured
        config_file = temp_dir / "auth_config.json"
        with open(config_file, "w") as f:
            json.dump({"tenant_id": "", "client_id": "", "client_secret": ""}, f)
        
        with patch("pyrest.auth.get_config") as mock_config:
            mock_config.return_value.auth_config_file = str(config_file)
            mock_config.return_value.jwt_secret = "secret"
            mock_config.return_value.jwt_expiry_hours = 24
            
            with patch("pyrest.auth.get_env") as mock_env:
                mock_env.return_value.get.return_value = None
                
                auth_config = AuthConfig()
                assert auth_config.is_configured is False


class TestJWTAuth:
    """Tests for JWTAuth class."""
    
    @pytest.fixture
    def jwt_auth(self):
        """Create JWTAuth instance with mocked config."""
        AuthConfig._instance = None
        
        with patch("pyrest.auth.get_auth_config") as mock:
            mock.return_value.jwt_secret = "test-secret"
            mock.return_value.jwt_expiry_hours = 24
            mock.return_value.jwt_algorithm = "HS256"
            
            return JWTAuth()
    
    def test_generate_token(self, jwt_auth):
        """Should generate a valid JWT token."""
        payload = {"sub": "testuser", "role": "admin"}
        
        token = jwt_auth.generate_token(payload)
        
        assert token is not None
        assert isinstance(token, str)
        
        # Decode and verify
        decoded = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert decoded["sub"] == "testuser"
        assert decoded["role"] == "admin"
        assert "exp" in decoded
        assert "iat" in decoded
    
    def test_verify_valid_token(self, jwt_auth):
        """Should verify a valid token."""
        payload = {"sub": "testuser"}
        token = jwt_auth.generate_token(payload)
        
        decoded = jwt_auth.verify_token(token)
        
        assert decoded["sub"] == "testuser"
    
    def test_verify_expired_token(self, jwt_auth):
        """Should raise error for expired token."""
        # Create an expired token manually
        expired_payload = {
            "sub": "testuser",
            "exp": datetime.utcnow() - timedelta(hours=1),
            "iat": datetime.utcnow() - timedelta(hours=2)
        }
        expired_token = jwt.encode(expired_payload, "test-secret", algorithm="HS256")
        
        with pytest.raises(AuthError) as exc_info:
            jwt_auth.verify_token(expired_token)
        
        assert "expired" in str(exc_info.value).lower()
    
    def test_verify_invalid_token(self, jwt_auth):
        """Should raise error for invalid token."""
        with pytest.raises(AuthError) as exc_info:
            jwt_auth.verify_token("invalid.token.here")
        
        assert "invalid" in str(exc_info.value).lower()
    
    def test_refresh_token(self, jwt_auth):
        """Should refresh a valid token."""
        payload = {"sub": "testuser"}
        original_token = jwt_auth.generate_token(payload)
        
        new_token = jwt_auth.refresh_token(original_token)
        
        assert new_token != original_token
        
        decoded = jwt_auth.verify_token(new_token)
        assert decoded["sub"] == "testuser"


class TestAzureADAuth:
    """Tests for AzureADAuth class."""
    
    @pytest.fixture
    def azure_auth(self):
        """Create AzureADAuth instance with mocked config."""
        AuthConfig._instance = None
        
        with patch("pyrest.auth.get_auth_config") as mock:
            mock.return_value.tenant_id = "test-tenant"
            mock.return_value.client_id = "test-client"
            mock.return_value.client_secret = "test-secret"
            mock.return_value.redirect_uri = "http://localhost/callback"
            mock.return_value.scopes = ["openid", "profile"]
            mock.return_value.is_configured = True
            
            return AzureADAuth()
    
    def test_get_authorization_url(self, azure_auth):
        """Should generate Azure AD authorization URL."""
        url = azure_auth.get_authorization_url(state="test-state")
        
        assert "login.microsoftonline.com" in url
        assert "test-tenant" in url
        assert "client_id=test-client" in url
        assert "state=test-state" in url
    
    def test_get_authorization_url_not_configured(self):
        """Should raise error if not configured."""
        AuthConfig._instance = None
        
        with patch("pyrest.auth.get_auth_config") as mock:
            mock.return_value.tenant_id = ""
            mock.return_value.client_id = ""
            mock.return_value.client_secret = ""
            mock.return_value.is_configured = False
            
            azure_auth = AzureADAuth()
            
            with pytest.raises(AuthError):
                azure_auth.get_authorization_url()
    
    @pytest.mark.asyncio
    async def test_exchange_code_for_token(self, azure_auth):
        """Should exchange authorization code for token."""
        mock_response = MagicMock()
        mock_response.body = json.dumps({
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "expires_in": 3600
        }).encode()
        
        with patch("tornado.httpclient.AsyncHTTPClient") as mock_client:
            mock_client.return_value.fetch = AsyncMock(return_value=mock_response)
            
            result = await azure_auth.exchange_code_for_token("test-code")
            
            assert result["access_token"] == "test-access-token"
            assert result["refresh_token"] == "test-refresh-token"
    
    @pytest.mark.asyncio
    async def test_get_user_info(self, azure_auth):
        """Should get user info from Microsoft Graph."""
        mock_response = MagicMock()
        mock_response.body = json.dumps({
            "id": "user-id",
            "displayName": "Test User",
            "mail": "test@example.com"
        }).encode()
        
        with patch("tornado.httpclient.AsyncHTTPClient") as mock_client:
            mock_client.return_value.fetch = AsyncMock(return_value=mock_response)
            
            result = await azure_auth.get_user_info("test-token")
            
            assert result["displayName"] == "Test User"
            assert result["mail"] == "test@example.com"


class TestAuthManager:
    """Tests for AuthManager class."""
    
    @pytest.fixture
    def auth_manager(self):
        """Create AuthManager instance with mocked dependencies."""
        AuthConfig._instance = None
        
        with patch("pyrest.auth.get_auth_config") as mock:
            mock.return_value.jwt_secret = "test-secret"
            mock.return_value.jwt_expiry_hours = 24
            mock.return_value.jwt_algorithm = "HS256"
            mock.return_value.tenant_id = "test-tenant"
            mock.return_value.client_id = "test-client"
            mock.return_value.client_secret = "test-secret"
            mock.return_value.redirect_uri = "http://localhost/callback"
            mock.return_value.scopes = ["openid"]
            mock.return_value.is_configured = True
            
            return AuthManager()
    
    def test_register_user(self, auth_manager):
        """Should register a new user."""
        result = auth_manager.register_user("testuser", "password123", email="test@example.com")
        
        assert result["username"] == "testuser"
        assert result["email"] == "test@example.com"
        assert "password" not in result
    
    def test_register_duplicate_user(self, auth_manager):
        """Should raise error for duplicate registration."""
        auth_manager.register_user("testuser", "password123")
        
        with pytest.raises(AuthError):
            auth_manager.register_user("testuser", "password456")
    
    def test_authenticate_user(self, auth_manager):
        """Should authenticate user and return token."""
        auth_manager.register_user("testuser", "password123")
        
        token = auth_manager.authenticate_user("testuser", "password123")
        
        assert token is not None
        
        # Verify token
        decoded = auth_manager.verify_request_token(token)
        assert decoded["sub"] == "testuser"
    
    def test_authenticate_wrong_password(self, auth_manager):
        """Should return None for wrong password."""
        auth_manager.register_user("testuser", "password123")
        
        token = auth_manager.authenticate_user("testuser", "wrongpassword")
        
        assert token is None
    
    def test_authenticate_nonexistent_user(self, auth_manager):
        """Should return None for nonexistent user."""
        token = auth_manager.authenticate_user("nonexistent", "password")
        
        assert token is None


class TestAuthDecorators:
    """Tests for authentication decorators."""
    
    @pytest.mark.asyncio
    async def test_authenticated_decorator_valid_token(self):
        """Should allow access with valid token."""
        AuthConfig._instance = None
        
        with patch("pyrest.auth.get_auth_config") as mock:
            mock.return_value.jwt_secret = "test-secret"
            mock.return_value.jwt_expiry_hours = 24
            mock.return_value.jwt_algorithm = "HS256"
            
            jwt_auth = JWTAuth()
            token = jwt_auth.generate_token({"sub": "testuser"})
            
            # Create mock handler
            mock_handler = MagicMock()
            mock_handler.request.headers.get.return_value = f"Bearer {token}"
            mock_handler._current_user = None
            
            @authenticated
            async def test_method(self):
                return "success"
            
            with patch("pyrest.auth.get_auth_manager") as mock_manager:
                mock_manager.return_value.verify_request_token.return_value = {"sub": "testuser"}
                
                result = await test_method(mock_handler)
                
                assert result == "success"
                assert mock_handler._current_user == {"sub": "testuser"}
    
    @pytest.mark.asyncio
    async def test_authenticated_decorator_missing_token(self):
        """Should deny access without token."""
        mock_handler = MagicMock()
        mock_handler.request.headers.get.return_value = ""
        
        @authenticated
        async def test_method(self):
            return "success"
        
        await test_method(mock_handler)
        
        mock_handler.set_status.assert_called_with(401)
    
    @pytest.mark.asyncio
    async def test_require_roles_decorator(self):
        """Should check user roles."""
        mock_handler = MagicMock()
        mock_handler._current_user = {"sub": "testuser", "roles": ["admin"]}
        
        @require_roles("admin")
        async def test_method(self):
            return "success"
        
        result = await test_method(mock_handler)
        
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_require_roles_decorator_insufficient(self):
        """Should deny access without required role."""
        mock_handler = MagicMock()
        mock_handler._current_user = {"sub": "testuser", "roles": ["user"]}
        
        @require_roles("admin")
        async def test_method(self):
            return "success"
        
        await test_method(mock_handler)
        
        mock_handler.set_status.assert_called_with(403)
