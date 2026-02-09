"""
Base handlers and authentication endpoints for PyRest framework.
"""

import json
import logging
from typing import Any

import tornado.web

from .auth import AuthError, authenticated, get_auth_manager
from .config import get_config, get_env

logger = logging.getLogger("pyrest.handlers")


class BaseHandler(tornado.web.RequestHandler):
    """
    Base handler with common functionality for all API endpoints.
    """

    def initialize(self, app_config: dict[str, Any] | None = None, app_config_parser: Any = None):
        """Initialize handler with optional app configuration."""
        self.app_config = app_config or {}
        self.app_config_parser = app_config_parser
        self.framework_config = get_config()
        self.env = get_env()
        self._current_user = None

    def set_default_headers(self):
        """Set default headers including CORS if enabled."""
        self.set_header("Content-Type", "application/json")

        # Ensure framework_config is available (set_default_headers runs before initialize)
        if not hasattr(self, "framework_config"):
            self.framework_config = get_config()

        if self.framework_config.get("cors_enabled", True):
            origin = self.request.headers.get("Origin", "*")
            allowed_origins = self.framework_config.get("cors_origins", ["*"])

            if "*" in allowed_origins or origin in allowed_origins:
                self.set_header("Access-Control-Allow-Origin", origin)

            self.set_header(
                "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS"
            )
            self.set_header(
                "Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With"
            )
            self.set_header("Access-Control-Allow-Credentials", "true")
            self.set_header("Access-Control-Max-Age", "86400")

    def options(self, *args, **kwargs):
        """Handle preflight CORS requests."""
        self.set_status(204)
        self.finish()

    def get_current_user(self) -> dict[str, Any] | None:
        """Get the current authenticated user."""
        return self._current_user

    @property
    def current_user(self) -> dict[str, Any] | None:
        """Property to access current user."""
        return self._current_user

    def get_json_body(self) -> dict[str, Any]:
        """Parse and return the JSON request body."""
        try:
            return json.loads(self.request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def load_args(self) -> dict[str, Any]:
        """
        Load all request arguments into a unified dictionary.

        Returns a dict with:
            - args['path']  - URL path parameters (e.g., /instance/{name} -> args['path']['name'])
            - args['query'] - URL query parameters (e.g., ?limit=10 -> args['query']['limit'])
            - args['body']  - JSON request body as dict

        Example usage in handler:
            args = self.load_args()
            instance_name = args['path'].get('instance_name')
            limit = args['query'].get('limit', '100')
            data = args['body']
        """
        # Path parameters (from URL pattern captures)
        path_args = dict(self.path_kwargs) if hasattr(self, "path_kwargs") else {}

        # Query parameters (flatten single-value lists)
        query_args = {}
        for key, values in self.request.arguments.items():
            if len(values) == 1:
                # Single value - decode and return as string
                query_args[key] = (
                    values[0].decode("utf-8") if isinstance(values[0], bytes) else values[0]
                )
            else:
                # Multiple values - return as list of strings
                query_args[key] = [v.decode("utf-8") if isinstance(v, bytes) else v for v in values]

        # Body (JSON parsed)
        body = self.get_json_body()

        return {"path": path_args, "query": query_args, "body": body}

    def write_error(self, status_code: int, **kwargs):
        """Write error response as JSON."""
        error_message = kwargs.get("reason", self._reason)

        if "exc_info" in kwargs:
            exc = kwargs["exc_info"][1]
            if isinstance(exc, tornado.web.HTTPError):
                error_message = exc.log_message or str(exc)
            else:
                # S5131: Never expose internal exception details to clients
                logger.exception("Unhandled exception", exc_info=kwargs["exc_info"])
                error_message = "Internal server error"

        self.write({"error": True, "status_code": status_code, "message": error_message})

    def success(self, data: Any = None, message: str = "Success", status_code: int = 200):
        """Send a success response."""
        self.set_status(status_code)
        response = {"success": True, "message": message}
        if data is not None:
            response["data"] = data
        self.write(response)

    def error(self, message: str, status_code: int = 400, data: Any = None):
        """Send an error response."""
        self.set_status(status_code)
        response = {"success": False, "error": message}
        if data is not None:
            response["data"] = data
        self.write(response)


class HealthHandler(BaseHandler):
    """Health check endpoint."""

    async def get(self):
        """Return service health status."""
        self.success(data={"status": "healthy", "version": "1.0.0"})


class AuthLoginHandler(BaseHandler):
    """JWT authentication login endpoint."""

    async def post(self):
        """Authenticate user with username and password."""
        body = self.get_json_body()
        username = body.get("username")
        password = body.get("password")

        if not username or not password:
            self.error("Username and password are required", 400)
            return

        auth_manager = get_auth_manager()
        token = auth_manager.authenticate_user(username, password)

        if not token:
            self.error("Invalid credentials", 401)
            return

        self.success(data={"access_token": token, "token_type": "Bearer"})


class AuthRegisterHandler(BaseHandler):
    """User registration endpoint."""

    async def post(self):
        """Register a new user."""
        body = self.get_json_body()
        username = body.get("username")
        password = body.get("password")
        email = body.get("email")

        if not username or not password:
            self.error("Username and password are required", 400)
            return

        try:
            auth_manager = get_auth_manager()
            user = auth_manager.register_user(username, password, email=email)
            self.success(data=user, message="User registered successfully", status_code=201)
        except AuthError as e:
            self.error(str(e), 400)


class AuthRefreshHandler(BaseHandler):
    """Token refresh endpoint."""

    @authenticated
    async def post(self):
        """Refresh the current token."""
        auth_header = self.request.headers.get("Authorization", "")
        token = auth_header[7:]  # Remove "Bearer " prefix

        auth_manager = get_auth_manager()
        new_token = auth_manager.jwt_auth.refresh_token(token)

        self.success(data={"access_token": new_token, "token_type": "Bearer"})


class AuthMeHandler(BaseHandler):
    """Get current user info endpoint."""

    @authenticated
    async def get(self):
        """Get the current authenticated user's information."""
        self.success(data=self.current_user)


class AzureADLoginHandler(BaseHandler):
    """Azure AD OAuth login initiation."""

    async def get(self):
        """Redirect to Azure AD login page."""
        auth_manager = get_auth_manager()

        if not auth_manager.azure_auth.is_configured:
            self.error("Azure AD authentication is not configured", 500)
            return

        # Generate state for CSRF protection
        import secrets

        state = secrets.token_urlsafe(32)

        # Store state in secure cookie
        self.set_secure_cookie("oauth_state", state, expires_days=1)

        auth_url = auth_manager.azure_auth.get_authorization_url(state=state)
        self.redirect(auth_url)


class AzureADCallbackHandler(BaseHandler):
    """Azure AD OAuth callback handler."""

    async def get(self):
        """Handle Azure AD OAuth callback."""
        code = self.get_argument("code", None)
        state = self.get_argument("state", None)
        error = self.get_argument("error", None)
        error_description = self.get_argument("error_description", None)

        if error:
            self.error(f"Azure AD error: {error_description or error}", 400)
            return

        if not code:
            self.error("Authorization code not provided", 400)
            return

        # Verify state for CSRF protection
        stored_state = self.get_secure_cookie("oauth_state")
        if stored_state:
            stored_state = stored_state.decode()
            if state != stored_state:
                self.error("Invalid state parameter", 400)
                return

        try:
            auth_manager = get_auth_manager()
            result = await auth_manager.authenticate_azure_code(code)

            # Clear the state cookie
            self.clear_cookie("oauth_state")

            # You can either redirect to frontend with token or return JSON
            # For API usage, return JSON:
            self.success(
                data={
                    "access_token": result["access_token"],
                    "token_type": "Bearer",
                    "user": result["user"],
                }
            )

        except AuthError as e:
            self.error(str(e), 401)


class AzureADLogoutHandler(BaseHandler):
    """Azure AD logout handler."""

    async def get(self):
        """Logout from Azure AD."""
        auth_manager = get_auth_manager()

        if not auth_manager.azure_auth.is_configured:
            self.error("Azure AD authentication is not configured", 500)
            return

        # Azure AD logout URL — validate redirect_uri to prevent open redirects (S5146)
        post_logout_redirect = self.get_argument("redirect_uri", "/")
        if not post_logout_redirect.startswith("/"):
            post_logout_redirect = "/"
        logout_url = (
            f"{auth_manager.azure_auth.authority}/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={post_logout_redirect}"
        )

        self.redirect(logout_url)


# Base path prefix for all PyRest routes
BASE_PATH = "/pyrest"


def get_auth_handlers():
    """Get all authentication-related handlers with /pyrest prefix.
    All routes use /? pattern for optional trailing slash support.
    """
    return [
        (rf"{BASE_PATH}/auth/login/?", AuthLoginHandler),
        (rf"{BASE_PATH}/auth/register/?", AuthRegisterHandler),
        (rf"{BASE_PATH}/auth/refresh/?", AuthRefreshHandler),
        (rf"{BASE_PATH}/auth/me/?", AuthMeHandler),
        (rf"{BASE_PATH}/auth/azure/login/?", AzureADLoginHandler),
        (rf"{BASE_PATH}/auth/azure/callback/?", AzureADCallbackHandler),
        (rf"{BASE_PATH}/auth/azure/logout/?", AzureADLogoutHandler),
        (rf"{BASE_PATH}/health/?", HealthHandler),
    ]
