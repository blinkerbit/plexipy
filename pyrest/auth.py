"""
Authentication module for PyRest framework.
Supports JWT tokens and Microsoft Azure AD authentication.
"""

import functools
import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import jwt
import tornado.httpclient
import tornado.web

from .config import get_config, get_env

logger = logging.getLogger("pyrest.auth")


class AuthConfig:
    """
    Authentication configuration loaded from auth_config.json.
    Provides centralized auth settings for all apps.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = cls._instance._load_config()
        return cls._instance

    def _load_config(self) -> dict[str, Any]:
        """Load authentication configuration from auth_config.json."""
        framework_config = get_config()
        config_file = framework_config.auth_config_file

        default_config = {
            "provider": "azure_ad",
            "tenant_id": "",
            "client_id": "",
            "client_secret": "",
            "redirect_uri": "http://localhost:8000/pyrest/auth/azure/callback",
            "scopes": ["openid", "profile", "email", "User.Read"],
            "jwt_secret": framework_config.jwt_secret,
            "jwt_expiry_hours": framework_config.jwt_expiry_hours,
            "jwt_algorithm": "HS256",
        }

        config_path = Path(config_file)
        if config_path.exists():
            try:
                with config_path.open() as f:
                    file_config = json.load(f)
                    default_config.update(file_config)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Could not load %s: %s", config_file, e)

        # Also check environment variables as fallback
        env = get_env()
        if not default_config["tenant_id"]:
            default_config["tenant_id"] = env.get("AZURE_AD_TENANT_ID", "")
        if not default_config["client_id"]:
            default_config["client_id"] = env.get("AZURE_AD_CLIENT_ID", "")
        if not default_config["client_secret"]:
            default_config["client_secret"] = env.get("AZURE_AD_CLIENT_SECRET", "")
        if default_config["redirect_uri"] == "http://localhost:8000/pyrest/auth/azure/callback":
            default_config["redirect_uri"] = env.get(
                "AZURE_AD_REDIRECT_URI", default_config["redirect_uri"]
            )

        return default_config

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._config.get(key, default)

    @property
    def tenant_id(self) -> str:
        return self._config["tenant_id"]

    @property
    def client_id(self) -> str:
        return self._config["client_id"]

    @property
    def client_secret(self) -> str:
        return self._config["client_secret"]

    @property
    def redirect_uri(self) -> str:
        return self._config["redirect_uri"]

    @property
    def scopes(self) -> list[str]:
        return self._config["scopes"]

    @property
    def jwt_secret(self) -> str:
        return self._config["jwt_secret"]

    @property
    def jwt_expiry_hours(self) -> int:
        return self._config["jwt_expiry_hours"]

    @property
    def jwt_algorithm(self) -> str:
        return self._config["jwt_algorithm"]

    @property
    def is_configured(self) -> bool:
        """Check if Azure AD is properly configured."""
        return bool(self.tenant_id and self.client_id and self.client_secret)


def get_auth_config() -> AuthConfig:
    """Get the singleton auth configuration."""
    return AuthConfig()


class AuthError(Exception):
    """Authentication error."""

    pass


class JWTAuth:
    """
    JWT-based authentication handler.
    """

    #: Minimum recommended key length for HMAC-SHA256 (bytes)
    _MIN_SECRET_LENGTH = 32

    def __init__(self):
        self.auth_config = get_auth_config()
        self.secret = self.auth_config.jwt_secret
        self.expiry_hours = self.auth_config.jwt_expiry_hours
        self.algorithm = self.auth_config.jwt_algorithm

        # S2068 / S5527: warn about weak or missing secrets at startup
        if not self.secret:
            logger.warning(
                "JWT secret is empty — set PYREST_JWT_SECRET env var before production use"
            )
        elif len(self.secret) < self._MIN_SECRET_LENGTH:
            logger.warning(
                "JWT secret is shorter than %d bytes — consider using a stronger key",
                self._MIN_SECRET_LENGTH,
            )

    def generate_token(self, payload: dict[str, Any]) -> str:
        """Generate a JWT token with the given payload."""
        now = datetime.now(UTC)
        token_payload = {
            **payload,
            "iat": now,
            "exp": now + timedelta(hours=self.expiry_hours),
            "iss": "pyrest",
        }
        return jwt.encode(token_payload, self.secret, algorithm=self.algorithm)

    def verify_token(self, token: str) -> dict[str, Any]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            raise AuthError("Token has expired") from None
        except jwt.InvalidTokenError as e:
            raise AuthError(f"Invalid token: {e!s}") from e

    def refresh_token(self, token: str) -> str:
        """Refresh an existing token."""
        payload = self.verify_token(token)
        # Remove old timing claims
        payload.pop("iat", None)
        payload.pop("exp", None)
        return self.generate_token(payload)


class AzureADAuth:
    """
    Microsoft Azure AD authentication handler using OAuth 2.0.

    Configuration is read from auth_config.json file.
    See auth_config.json for required settings.
    """

    def __init__(self):
        self.auth_config = get_auth_config()
        self.tenant_id = self.auth_config.tenant_id
        self.client_id = self.auth_config.client_id
        self.client_secret = self.auth_config.client_secret
        self.redirect_uri = self.auth_config.redirect_uri
        self.scopes = self.auth_config.scopes

        # Azure AD endpoints
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self.authorize_endpoint = f"{self.authority}/oauth2/v2.0/authorize"
        self.token_endpoint = f"{self.authority}/oauth2/v2.0/token"
        self.graph_endpoint = "https://graph.microsoft.com/v1.0"

        # JWKS endpoint for token validation
        self.jwks_uri = f"{self.authority}/discovery/v2.0/keys"
        self._jwks_cache = None
        self._jwks_cache_time = 0

    @property
    def is_configured(self) -> bool:
        """Check if Azure AD is properly configured."""
        return self.auth_config.is_configured

    def get_authorization_url(self, state: str = "", nonce: str = "") -> str:
        """Generate the Azure AD authorization URL."""
        if not self.is_configured:
            raise AuthError("Azure AD is not configured. Set required environment variables.")

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "response_mode": "query",
            "state": state or secrets.token_urlsafe(32),
            "nonce": nonce or secrets.token_urlsafe(32),
        }
        return f"{self.authorize_endpoint}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access token."""
        if not self.is_configured:
            raise AuthError("Azure AD is not configured")

        http_client = tornado.httpclient.AsyncHTTPClient()

        body = urlencode(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
                "scope": " ".join(self.scopes),
            }
        )

        try:
            response = await http_client.fetch(
                self.token_endpoint,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=body,
            )
            return json.loads(response.body.decode())
        except tornado.httpclient.HTTPError as e:
            error_body = e.response.body.decode() if e.response else str(e)
            raise AuthError(f"Failed to exchange code for token: {error_body}") from e

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token using a refresh token."""
        if not self.is_configured:
            raise AuthError("Azure AD is not configured")

        http_client = tornado.httpclient.AsyncHTTPClient()

        body = urlencode(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": " ".join(self.scopes),
            }
        )

        try:
            response = await http_client.fetch(
                self.token_endpoint,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=body,
            )
            return json.loads(response.body.decode())
        except tornado.httpclient.HTTPError as e:
            error_body = e.response.body.decode() if e.response else str(e)
            raise AuthError(f"Failed to refresh token: {error_body}") from e

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """Get user information from Microsoft Graph API."""
        http_client = tornado.httpclient.AsyncHTTPClient()

        try:
            response = await http_client.fetch(
                f"{self.graph_endpoint}/me", headers={"Authorization": f"Bearer {access_token}"}
            )
            return json.loads(response.body.decode())
        except tornado.httpclient.HTTPError as e:
            error_body = e.response.body.decode() if e.response else str(e)
            raise AuthError(f"Failed to get user info: {error_body}") from e

    async def validate_token(self, token: str) -> dict[str, Any]:
        """
        Validate an Azure AD access token.
        Returns the decoded token payload if valid.
        """
        try:
            # Decode without verification first to get the header
            unverified = jwt.decode(token, options={"verify_signature": False})

            # For access tokens from Azure AD, we validate by calling Graph API
            # If the token is valid, this will succeed
            user_info = await self.get_user_info(token)

            return {"valid": True, "user": user_info, "token_claims": unverified}
        except (AuthError, jwt.InvalidTokenError, tornado.httpclient.HTTPError) as e:
            raise AuthError(f"Token validation failed: {e!s}") from e

    def decode_token_claims(self, token: str) -> dict[str, Any]:
        """
        Decode an Azure AD token without full validation.
        Useful for extracting claims like roles.

        Returns decoded token claims including:
        - roles: App roles assigned to the user
        - groups: Group memberships (if configured)
        - oid: Object ID of the user
        - preferred_username: User's email/UPN
        """
        try:
            # Decode without verification to get claims
            claims = jwt.decode(token, options={"verify_signature": False})
            return claims
        except jwt.DecodeError as e:
            raise AuthError(f"Failed to decode token: {e!s}") from e

    def extract_roles(self, token: str) -> list[str]:
        """
        Extract Azure AD app roles from a token.

        Roles are configured in Azure AD App Registration under
        "App roles" and assigned to users/groups.

        Returns list of role names assigned to the user.
        """
        try:
            claims = self.decode_token_claims(token)
            # Azure AD puts roles in the 'roles' claim
            roles = claims.get("roles", [])
            if isinstance(roles, str):
                roles = [roles]
            return roles
        except AuthError:
            return []

    def extract_groups(self, token: str) -> list[str]:
        """
        Extract Azure AD group memberships from a token.

        Requires "groups" claim to be configured in Azure AD.

        Returns list of group IDs the user belongs to.
        """
        try:
            claims = self.decode_token_claims(token)
            groups = claims.get("groups", [])
            if isinstance(groups, str):
                groups = [groups]
            return groups
        except AuthError:
            return []

    def extract_user_info_from_token(self, token: str) -> dict[str, Any]:
        """
        Extract user information from token claims.

        Returns a dictionary with user details.
        """
        try:
            claims = self.decode_token_claims(token)
            return {
                "oid": claims.get("oid"),  # Object ID
                "sub": claims.get("sub"),  # Subject
                "name": claims.get("name"),
                "email": claims.get("preferred_username")
                or claims.get("email")
                or claims.get("upn"),
                "given_name": claims.get("given_name"),
                "family_name": claims.get("family_name"),
                "roles": claims.get("roles", []),
                "groups": claims.get("groups", []),
                "tenant_id": claims.get("tid"),
                "app_id": claims.get("azp") or claims.get("appid"),
            }
        except AuthError:
            return {}


class AuthManager:
    """
    Unified authentication manager that supports multiple auth methods.
    """

    def __init__(self):
        self.jwt_auth = JWTAuth()
        self.azure_auth = AzureADAuth()
        self._user_store: dict[str, dict[str, Any]] = {}  # Simple in-memory store

    def register_user(self, username: str, password: str, **extra) -> dict[str, Any]:
        """Register a new user (for JWT auth)."""
        if username in self._user_store:
            raise AuthError("User already exists")

        password_hash = self._hash_password(password)

        user = {
            "username": username,
            "password_hash": password_hash,
            "created_at": datetime.now(UTC).isoformat(),
            **extra,
        }
        self._user_store[username] = user
        return {"username": username, **extra}

    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash a password using salted HMAC-SHA256.

        For production deployments requiring offline brute-force resistance,
        consider upgrading to bcrypt or argon2 (requires additional dependency).
        """
        salt = secrets.token_hex(16)
        digest = hmac.new(salt.encode(), password.encode(), hashlib.sha256).hexdigest()
        return f"{salt}${digest}"

    @staticmethod
    def _verify_password(password: str, stored_hash: str) -> bool:
        """Verify a password against a stored salted HMAC-SHA256 hash."""
        if "$" not in stored_hash:
            # Legacy unsalted SHA-256 hash — compare with constant-time comparison
            legacy_hash = hashlib.sha256(password.encode()).hexdigest()
            return hmac.compare_digest(legacy_hash, stored_hash)
        salt, digest = stored_hash.split("$", 1)
        candidate = hmac.new(salt.encode(), password.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(candidate, digest)

    def authenticate_user(self, username: str, password: str) -> str | None:
        """Authenticate a user and return a JWT token."""
        user = self._user_store.get(username)
        if not user:
            return None

        if not self._verify_password(password, user["password_hash"]):
            return None

        return self.jwt_auth.generate_token({"sub": username, "type": "jwt"})

    async def authenticate_azure_code(self, code: str) -> dict[str, Any]:
        """Authenticate using Azure AD authorization code."""
        tokens = await self.azure_auth.exchange_code_for_token(code)
        user_info = await self.azure_auth.get_user_info(tokens["access_token"])

        # Generate a local JWT that includes Azure user info
        local_token = self.jwt_auth.generate_token(
            {
                "sub": user_info.get("userPrincipalName", user_info.get("mail")),
                "name": user_info.get("displayName"),
                "email": user_info.get("mail"),
                "azure_id": user_info.get("id"),
                "type": "azure_ad",
            }
        )

        return {"access_token": local_token, "azure_tokens": tokens, "user": user_info}

    def verify_request_token(self, token: str) -> dict[str, Any]:
        """Verify a token from a request (JWT)."""
        return self.jwt_auth.verify_token(token)


# Global auth manager instance
_auth_manager: AuthManager | None = None


def get_auth_manager() -> AuthManager:
    """Get the global auth manager instance."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


def authenticated(method: Callable) -> Callable:
    """
    Decorator for requiring authentication on handler methods.

    Usage:
        class MyHandler(BaseHandler):
            @authenticated
            async def get(self):
                user = self.current_user
                ...
    """

    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        auth_header = self.request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            self.set_status(401)
            self.write({"error": "Missing or invalid Authorization header"})
            return None

        token = auth_header[7:]  # Remove "Bearer " prefix

        try:
            auth_manager = get_auth_manager()
            payload = auth_manager.verify_request_token(token)
            self._current_user = payload
        except AuthError as e:
            self.set_status(401)
            self.write({"error": str(e)})
            return None

        return await method(self, *args, **kwargs)

    return wrapper


def require_roles(allowed_roles: list[str]) -> Callable:
    """
    Decorator for requiring specific roles (works with JWT tokens).

    Args:
        allowed_roles: List of role names that are allowed access

    Usage:
        class AdminHandler(BaseHandler):
            @authenticated
            @require_roles(["admin", "superuser"])
            async def get(self):
                ...
    """

    def decorator(method: Callable) -> Callable:
        @functools.wraps(method)
        async def wrapper(self, *args, **kwargs):
            user = getattr(self, "_current_user", None)
            if not user:
                self.set_status(401)
                self.write({"error": "Not authenticated"})
                return None

            user_roles = user.get("roles", [])
            if not any(role in user_roles for role in allowed_roles):
                self.set_status(403)
                self.write({"error": "Insufficient permissions"})
                return None

            return await method(self, *args, **kwargs)

        return wrapper

    return decorator


def azure_ad_authenticated(method: Callable) -> Callable:
    """
    Decorator for requiring Azure AD authentication on handler methods.

    Validates the Azure AD token and extracts user info including roles.
    Sets self._current_user with user details and self._azure_roles with roles.

    Usage:
        class MyHandler(BaseHandler):
            @azure_ad_authenticated
            async def get(self):
                user = self._current_user
                roles = self._azure_roles
                ...
    """

    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        auth_header = self.request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            self.set_status(401)
            self.write({"error": "Missing or invalid Authorization header"})
            return None

        token = auth_header[7:]  # Remove "Bearer " prefix

        try:
            auth_manager = get_auth_manager()
            azure_auth = auth_manager.azure_auth

            # Extract user info and roles from Azure AD token
            user_info = azure_auth.extract_user_info_from_token(token)
            roles = azure_auth.extract_roles(token)

            if not user_info.get("oid") and not user_info.get("sub"):
                raise AuthError("Invalid token: missing user identifier")

            # Set user info on handler
            self._current_user = user_info
            self._azure_roles = roles
            self._azure_token = token

        except AuthError as e:
            self.set_status(401)
            self.write({"error": str(e)})
            return None
        except (jwt.InvalidTokenError, KeyError, ValueError) as e:
            self.set_status(401)
            self.write({"error": "Token validation failed"})
            logger.debug("Azure AD token validation failed: %s", e)
            return None

        return await method(self, *args, **kwargs)

    return wrapper


def require_azure_roles(allowed_roles: list[str]) -> Callable:
    """
    Decorator for requiring specific Azure AD app roles.

    Must be used after @azure_ad_authenticated decorator.
    Checks if the user has any of the specified roles configured
    in Azure AD App Registration.

    Args:
        allowed_roles: List of Azure AD app role names that are allowed access

    Usage:
        class AdminHandler(BaseHandler):
            @azure_ad_authenticated
            @require_azure_roles(["Admin", "DataManager"])
            async def get(self):
                ...

    Azure AD Setup:
        1. Go to Azure Portal > App Registrations > Your App
        2. Click "App roles" in the left menu
        3. Create roles (e.g., "Admin", "Reader", "DataManager")
        4. Assign roles to users/groups in "Enterprise Applications"
    """

    def decorator(method: Callable) -> Callable:
        @functools.wraps(method)
        async def wrapper(self, *args, **kwargs):
            # Check if azure_ad_authenticated was applied
            azure_roles = getattr(self, "_azure_roles", None)

            if azure_roles is None:
                self.set_status(401)
                self.write({"error": "Azure AD authentication required"})
                return None

            # Check if user has any of the allowed roles
            if not any(role in azure_roles for role in allowed_roles):
                self.set_status(403)
                self.write({"error": "Insufficient permissions"})
                return None

            return await method(self, *args, **kwargs)

        return wrapper

    return decorator


def azure_ad_protected(allowed_roles: list[str] | None = None) -> Callable:
    """
    Combined decorator for Azure AD authentication with optional role checking.

    This is a convenience decorator that combines @azure_ad_authenticated
    and @require_azure_roles into a single decorator.

    Args:
        allowed_roles: Optional list of Azure AD app role names.
                      If None or empty, only authentication is required.

    Usage:
        # Require authentication only
        class PublicHandler(BaseHandler):
            @azure_ad_protected()
            async def get(self):
                ...

        # Require authentication + specific roles
        class AdminHandler(BaseHandler):
            @azure_ad_protected(["Admin", "SuperUser"])
            async def get(self):
                ...
    """

    def decorator(method: Callable) -> Callable:
        @functools.wraps(method)
        async def wrapper(self, *args, **kwargs):
            auth_header = self.request.headers.get("Authorization", "")

            if not auth_header.startswith("Bearer "):
                self.set_status(401)
                self.write({"error": "Missing or invalid Authorization header"})
                return None

            token = auth_header[7:]  # Remove "Bearer " prefix

            try:
                auth_manager = get_auth_manager()
                azure_auth = auth_manager.azure_auth

                # Extract user info and roles from Azure AD token
                user_info = azure_auth.extract_user_info_from_token(token)
                roles = azure_auth.extract_roles(token)

                if not user_info.get("oid") and not user_info.get("sub"):
                    raise AuthError("Invalid token: missing user identifier")

                # Set user info on handler
                self._current_user = user_info
                self._azure_roles = roles
                self._azure_token = token

            except AuthError as e:
                self.set_status(401)
                self.write({"error": str(e)})
                return None
            except (jwt.InvalidTokenError, KeyError, ValueError) as e:
                self.set_status(401)
                self.write({"error": "Token validation failed"})
                logger.debug("Azure AD protected token validation failed: %s", e)
                return None

            # Check roles if specified
            if allowed_roles and not any(role in roles for role in allowed_roles):
                self.set_status(403)
                self.write({"error": "Insufficient permissions"})
                return None

            return await method(self, *args, **kwargs)

        return wrapper

    return decorator
