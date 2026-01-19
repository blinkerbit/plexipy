"""
Authentication module for PyRest framework.
Supports JWT tokens and Microsoft Azure AD authentication.
"""

import jwt
import time
import json
import functools
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime, timedelta
from urllib.parse import urlencode
import tornado.web
import tornado.httpclient
from tornado import gen

from .config import get_config, get_env


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
    
    def _load_config(self) -> Dict[str, Any]:
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
            "jwt_algorithm": "HS256"
        }
        
        config_path = Path(config_file)
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    file_config = json.load(f)
                    default_config.update(file_config)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load {config_file}: {e}")
        
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
                "AZURE_AD_REDIRECT_URI", 
                default_config["redirect_uri"]
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
    def scopes(self) -> List[str]:
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
    
    def __init__(self):
        self.auth_config = get_auth_config()
        self.secret = self.auth_config.jwt_secret
        self.expiry_hours = self.auth_config.jwt_expiry_hours
        self.algorithm = self.auth_config.jwt_algorithm
    
    def generate_token(self, payload: Dict[str, Any]) -> str:
        """Generate a JWT token with the given payload."""
        now = datetime.utcnow()
        token_payload = {
            **payload,
            "iat": now,
            "exp": now + timedelta(hours=self.expiry_hours),
            "iss": "pyrest"
        }
        return jwt.encode(token_payload, self.secret, algorithm=self.algorithm)
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            raise AuthError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise AuthError(f"Invalid token: {str(e)}")
    
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
            "state": state or str(time.time()),
            "nonce": nonce or str(time.time())
        }
        return f"{self.authorize_endpoint}?{urlencode(params)}"
    
    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        if not self.is_configured:
            raise AuthError("Azure AD is not configured")
        
        http_client = tornado.httpclient.AsyncHTTPClient()
        
        body = urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "scope": " ".join(self.scopes)
        })
        
        try:
            response = await http_client.fetch(
                self.token_endpoint,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=body
            )
            return json.loads(response.body.decode())
        except tornado.httpclient.HTTPError as e:
            error_body = e.response.body.decode() if e.response else str(e)
            raise AuthError(f"Failed to exchange code for token: {error_body}")
    
    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh the access token using a refresh token."""
        if not self.is_configured:
            raise AuthError("Azure AD is not configured")
        
        http_client = tornado.httpclient.AsyncHTTPClient()
        
        body = urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": " ".join(self.scopes)
        })
        
        try:
            response = await http_client.fetch(
                self.token_endpoint,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=body
            )
            return json.loads(response.body.decode())
        except tornado.httpclient.HTTPError as e:
            error_body = e.response.body.decode() if e.response else str(e)
            raise AuthError(f"Failed to refresh token: {error_body}")
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get user information from Microsoft Graph API."""
        http_client = tornado.httpclient.AsyncHTTPClient()
        
        try:
            response = await http_client.fetch(
                f"{self.graph_endpoint}/me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            return json.loads(response.body.decode())
        except tornado.httpclient.HTTPError as e:
            error_body = e.response.body.decode() if e.response else str(e)
            raise AuthError(f"Failed to get user info: {error_body}")
    
    async def validate_token(self, token: str) -> Dict[str, Any]:
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
            
            return {
                "valid": True,
                "user": user_info,
                "token_claims": unverified
            }
        except Exception as e:
            raise AuthError(f"Token validation failed: {str(e)}")


class AuthManager:
    """
    Unified authentication manager that supports multiple auth methods.
    """
    
    def __init__(self):
        self.jwt_auth = JWTAuth()
        self.azure_auth = AzureADAuth()
        self._user_store: Dict[str, Dict[str, Any]] = {}  # Simple in-memory store
    
    def register_user(self, username: str, password: str, **extra) -> Dict[str, Any]:
        """Register a new user (for JWT auth)."""
        if username in self._user_store:
            raise AuthError("User already exists")
        
        # In production, use proper password hashing (bcrypt, argon2)
        import hashlib
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        user = {
            "username": username,
            "password_hash": password_hash,
            "created_at": datetime.utcnow().isoformat(),
            **extra
        }
        self._user_store[username] = user
        return {"username": username, **extra}
    
    def authenticate_user(self, username: str, password: str) -> Optional[str]:
        """Authenticate a user and return a JWT token."""
        import hashlib
        
        user = self._user_store.get(username)
        if not user:
            return None
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if user["password_hash"] != password_hash:
            return None
        
        return self.jwt_auth.generate_token({
            "sub": username,
            "type": "jwt"
        })
    
    async def authenticate_azure_code(self, code: str) -> Dict[str, Any]:
        """Authenticate using Azure AD authorization code."""
        tokens = await self.azure_auth.exchange_code_for_token(code)
        user_info = await self.azure_auth.get_user_info(tokens["access_token"])
        
        # Generate a local JWT that includes Azure user info
        local_token = self.jwt_auth.generate_token({
            "sub": user_info.get("userPrincipalName", user_info.get("mail")),
            "name": user_info.get("displayName"),
            "email": user_info.get("mail"),
            "azure_id": user_info.get("id"),
            "type": "azure_ad"
        })
        
        return {
            "access_token": local_token,
            "azure_tokens": tokens,
            "user": user_info
        }
    
    def verify_request_token(self, token: str) -> Dict[str, Any]:
        """Verify a token from a request (JWT)."""
        return self.jwt_auth.verify_token(token)


# Global auth manager instance
_auth_manager: Optional[AuthManager] = None


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
            return
        
        token = auth_header[7:]  # Remove "Bearer " prefix
        
        try:
            auth_manager = get_auth_manager()
            payload = auth_manager.verify_request_token(token)
            self._current_user = payload
        except AuthError as e:
            self.set_status(401)
            self.write({"error": str(e)})
            return
        
        return await method(self, *args, **kwargs)
    
    return wrapper


def require_roles(*roles: str) -> Callable:
    """
    Decorator for requiring specific roles.
    
    Usage:
        class AdminHandler(BaseHandler):
            @authenticated
            @require_roles("admin", "superuser")
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
                return
            
            user_roles = user.get("roles", [])
            if not any(role in user_roles for role in roles):
                self.set_status(403)
                self.write({"error": "Insufficient permissions"})
                return
            
            return await method(self, *args, **kwargs)
        
        return wrapper
    return decorator
