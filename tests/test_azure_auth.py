"""
Tests for Azure AD authentication decorators.
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
    AzureADAuth, AuthConfig, AuthError,
    azure_ad_authenticated, require_azure_roles, azure_ad_protected,
    require_roles, get_auth_manager
)


class TestAzureADAuthTokenMethods:
    """Tests for AzureADAuth token extraction methods."""
    
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
    
    @pytest.fixture
    def sample_token(self):
        """Create a sample Azure AD-like JWT token."""
        payload = {
            "oid": "user-object-id-123",
            "sub": "user-subject-id",
            "name": "Test User",
            "preferred_username": "test@company.com",
            "email": "test@company.com",
            "given_name": "Test",
            "family_name": "User",
            "roles": ["Admin", "Reader"],
            "groups": ["group-1", "group-2"],
            "tid": "tenant-id",
            "azp": "app-id",
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=1)
        }
        return jwt.encode(payload, "secret", algorithm="HS256")
    
    def test_decode_token_claims(self, azure_auth, sample_token):
        """Should decode token claims without validation."""
        claims = azure_auth.decode_token_claims(sample_token)
        
        assert claims["oid"] == "user-object-id-123"
        assert claims["name"] == "Test User"
        assert claims["preferred_username"] == "test@company.com"
    
    def test_decode_invalid_token(self, azure_auth):
        """Should raise error for invalid token."""
        with pytest.raises(AuthError) as exc_info:
            azure_auth.decode_token_claims("invalid.token")
        
        assert "decode" in str(exc_info.value).lower()
    
    def test_extract_roles(self, azure_auth, sample_token):
        """Should extract roles from token."""
        roles = azure_auth.extract_roles(sample_token)
        
        assert isinstance(roles, list)
        assert "Admin" in roles
        assert "Reader" in roles
        assert len(roles) == 2
    
    def test_extract_roles_empty(self, azure_auth):
        """Should return empty list when no roles."""
        token_without_roles = jwt.encode(
            {"sub": "user", "exp": datetime.utcnow() + timedelta(hours=1)},
            "secret",
            algorithm="HS256"
        )
        
        roles = azure_auth.extract_roles(token_without_roles)
        
        assert roles == []
    
    def test_extract_groups(self, azure_auth, sample_token):
        """Should extract groups from token."""
        groups = azure_auth.extract_groups(sample_token)
        
        assert isinstance(groups, list)
        assert "group-1" in groups
        assert "group-2" in groups
    
    def test_extract_user_info_from_token(self, azure_auth, sample_token):
        """Should extract user info from token."""
        user_info = azure_auth.extract_user_info_from_token(sample_token)
        
        assert user_info["oid"] == "user-object-id-123"
        assert user_info["name"] == "Test User"
        assert user_info["email"] == "test@company.com"
        assert user_info["roles"] == ["Admin", "Reader"]
        assert user_info["groups"] == ["group-1", "group-2"]
        assert user_info["tenant_id"] == "tenant-id"


class TestAzureADAuthenticatedDecorator:
    """Tests for @azure_ad_authenticated decorator."""
    
    @pytest.fixture
    def mock_handler(self):
        """Create mock handler."""
        handler = MagicMock()
        handler._current_user = None
        handler._azure_roles = None
        handler._azure_token = None
        return handler
    
    @pytest.fixture
    def valid_token(self):
        """Create valid token with user info."""
        payload = {
            "oid": "user-123",
            "sub": "subject-123",
            "name": "Test User",
            "preferred_username": "test@example.com",
            "roles": ["Admin", "Reader"],
            "exp": datetime.utcnow() + timedelta(hours=1)
        }
        return jwt.encode(payload, "secret", algorithm="HS256")
    
    @pytest.mark.asyncio
    async def test_valid_token(self, mock_handler, valid_token):
        """Should authenticate with valid token."""
        mock_handler.request.headers.get.return_value = f"Bearer {valid_token}"
        
        @azure_ad_authenticated
        async def test_method(self):
            return "success"
        
        with patch("pyrest.auth.get_auth_manager") as mock_manager:
            mock_azure = MagicMock()
            mock_azure.extract_user_info_from_token.return_value = {
                "oid": "user-123",
                "sub": "subject-123",
                "name": "Test User",
                "email": "test@example.com",
                "roles": ["Admin", "Reader"]
            }
            mock_azure.extract_roles.return_value = ["Admin", "Reader"]
            mock_manager.return_value.azure_auth = mock_azure
            
            result = await test_method(mock_handler)
            
            assert result == "success"
            assert mock_handler._current_user["oid"] == "user-123"
            assert mock_handler._azure_roles == ["Admin", "Reader"]
    
    @pytest.mark.asyncio
    async def test_missing_auth_header(self, mock_handler):
        """Should reject request without auth header."""
        mock_handler.request.headers.get.return_value = ""
        
        @azure_ad_authenticated
        async def test_method(self):
            return "success"
        
        await test_method(mock_handler)
        
        mock_handler.set_status.assert_called_with(401)
    
    @pytest.mark.asyncio
    async def test_invalid_auth_format(self, mock_handler):
        """Should reject non-Bearer auth."""
        mock_handler.request.headers.get.return_value = "Basic credentials"
        
        @azure_ad_authenticated
        async def test_method(self):
            return "success"
        
        await test_method(mock_handler)
        
        mock_handler.set_status.assert_called_with(401)


class TestRequireAzureRolesDecorator:
    """Tests for @require_azure_roles decorator."""
    
    @pytest.fixture
    def mock_handler(self):
        """Create mock handler with Azure auth."""
        handler = MagicMock()
        handler._current_user = {"email": "test@example.com"}
        handler._azure_roles = ["Reader", "DataViewer"]
        return handler
    
    @pytest.mark.asyncio
    async def test_allowed_role(self, mock_handler):
        """Should allow access with matching role."""
        @require_azure_roles(["Reader", "Admin"])
        async def test_method(self):
            return "success"
        
        result = await test_method(mock_handler)
        
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_denied_role(self, mock_handler):
        """Should deny access without matching role."""
        mock_handler._azure_roles = ["Viewer"]
        
        @require_azure_roles(["Admin", "SuperUser"])
        async def test_method(self):
            return "success"
        
        await test_method(mock_handler)
        
        mock_handler.set_status.assert_called_with(403)
    
    @pytest.mark.asyncio
    async def test_multiple_required_roles(self, mock_handler):
        """Should allow if user has any of the required roles."""
        mock_handler._azure_roles = ["DataViewer", "OtherRole"]
        
        @require_azure_roles(["Admin", "DataViewer", "SuperUser"])
        async def test_method(self):
            return "success"
        
        result = await test_method(mock_handler)
        
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_no_azure_auth(self):
        """Should deny if not Azure authenticated."""
        handler = MagicMock()
        handler._azure_roles = None  # Not authenticated
        handler._current_user = None
        
        @require_azure_roles(["Admin"])
        async def test_method(self):
            return "success"
        
        await test_method(handler)
        
        handler.set_status.assert_called_with(401)
    
    @pytest.mark.asyncio
    async def test_empty_user_roles(self, mock_handler):
        """Should deny if user has no roles."""
        mock_handler._azure_roles = []
        
        @require_azure_roles(["Admin"])
        async def test_method(self):
            return "success"
        
        await test_method(mock_handler)
        
        mock_handler.set_status.assert_called_with(403)


class TestAzureADProtectedDecorator:
    """Tests for @azure_ad_protected combined decorator."""
    
    @pytest.fixture
    def valid_token(self):
        """Create valid token."""
        payload = {
            "oid": "user-123",
            "sub": "subject-123",
            "name": "Test User",
            "preferred_username": "test@example.com",
            "roles": ["Admin", "Reader"],
            "exp": datetime.utcnow() + timedelta(hours=1)
        }
        return jwt.encode(payload, "secret", algorithm="HS256")
    
    @pytest.mark.asyncio
    async def test_auth_only_no_roles(self, valid_token):
        """Should authenticate without role check when no roles specified."""
        mock_handler = MagicMock()
        mock_handler.request.headers.get.return_value = f"Bearer {valid_token}"
        mock_handler._current_user = None
        mock_handler._azure_roles = None
        
        @azure_ad_protected()
        async def test_method(self):
            return "success"
        
        with patch("pyrest.auth.get_auth_manager") as mock_manager:
            mock_azure = MagicMock()
            mock_azure.extract_user_info_from_token.return_value = {
                "oid": "user-123",
                "email": "test@example.com"
            }
            mock_azure.extract_roles.return_value = ["Admin"]
            mock_manager.return_value.azure_auth = mock_azure
            
            result = await test_method(mock_handler)
            
            assert result == "success"
    
    @pytest.mark.asyncio
    async def test_auth_with_valid_role(self, valid_token):
        """Should authenticate and check roles when specified."""
        mock_handler = MagicMock()
        mock_handler.request.headers.get.return_value = f"Bearer {valid_token}"
        mock_handler._current_user = None
        mock_handler._azure_roles = None
        
        @azure_ad_protected(["Admin", "SuperUser"])
        async def test_method(self):
            return "success"
        
        with patch("pyrest.auth.get_auth_manager") as mock_manager:
            mock_azure = MagicMock()
            mock_azure.extract_user_info_from_token.return_value = {
                "oid": "user-123",
                "email": "test@example.com"
            }
            mock_azure.extract_roles.return_value = ["Admin", "Reader"]
            mock_manager.return_value.azure_auth = mock_azure
            
            result = await test_method(mock_handler)
            
            assert result == "success"
    
    @pytest.mark.asyncio
    async def test_auth_with_invalid_role(self, valid_token):
        """Should deny when user doesn't have required role."""
        mock_handler = MagicMock()
        mock_handler.request.headers.get.return_value = f"Bearer {valid_token}"
        mock_handler._current_user = None
        mock_handler._azure_roles = None
        
        @azure_ad_protected(["SuperUser", "Executive"])
        async def test_method(self):
            return "success"
        
        with patch("pyrest.auth.get_auth_manager") as mock_manager:
            mock_azure = MagicMock()
            mock_azure.extract_user_info_from_token.return_value = {
                "oid": "user-123",
                "email": "test@example.com"
            }
            mock_azure.extract_roles.return_value = ["Reader"]  # Doesn't have required role
            mock_manager.return_value.azure_auth = mock_azure
            
            await test_method(mock_handler)
            
            mock_handler.set_status.assert_called_with(403)


class TestRequireRolesWithListParam:
    """Tests for @require_roles with List[str] parameter."""
    
    @pytest.mark.asyncio
    async def test_list_parameter(self):
        """Should accept list of roles."""
        mock_handler = MagicMock()
        mock_handler._current_user = {"sub": "user", "roles": ["admin"]}
        
        @require_roles(["admin", "superuser"])
        async def test_method(self):
            return "success"
        
        result = await test_method(mock_handler)
        
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_list_deny(self):
        """Should deny when no matching role in list."""
        mock_handler = MagicMock()
        mock_handler._current_user = {"sub": "user", "roles": ["viewer"]}
        
        @require_roles(["admin", "superuser"])
        async def test_method(self):
            return "success"
        
        await test_method(mock_handler)
        
        mock_handler.set_status.assert_called_with(403)
    
    @pytest.mark.asyncio
    async def test_response_includes_role_info(self):
        """Should include role information in error response."""
        mock_handler = MagicMock()
        mock_handler._current_user = {"sub": "user", "roles": ["viewer"]}
        
        written_data = {}
        def capture_write(data):
            written_data.update(data)
        
        mock_handler.write = capture_write
        
        @require_roles(["admin", "superuser"])
        async def test_method(self):
            return "success"
        
        await test_method(mock_handler)
        
        assert "required_roles" in written_data
        assert written_data["required_roles"] == ["admin", "superuser"]
        assert written_data["user_roles"] == ["viewer"]
