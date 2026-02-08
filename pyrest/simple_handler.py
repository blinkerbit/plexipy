"""
PyRest Simple Handler Module

Provides a simplified base handler class for non-Python developers.
Handles JSON parsing, validation, errors, and async operations automatically.

Example Usage (Simple):
    from pyrest.simple_handler import SimpleHandler

    class MyHandler(SimpleHandler):
        async def post(self):
            # Get validated data
            data = self.get_data(required=["cube", "element1"])
            if not data:
                return  # Error already sent

            # Do something
            result = {"value": 123}
            self.ok(result)

Example Usage (With Pydantic):
    from pyrest.simple_handler import SimpleHandler
    from pyrest.validation import RequestModel, field

    class FetchInput(RequestModel):
        cube: str = field(description="Cube name")
        element1: str = field(description="First element")

    class MyHandler(SimpleHandler):
        async def post(self):
            data = self.get_data(model=FetchInput)
            if not data:
                return

            result = fetch_something(data.cube, data.element1)
            self.ok(result)
"""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

import tornado.ioloop
import tornado.web

# Thread pool for async operations
_EXECUTOR = ThreadPoolExecutor(max_workers=16)


class SimpleHandler(tornado.web.RequestHandler):
    """
    Simplified handler base class for PyRest apps.

    Features:
    - Automatic JSON parsing
    - Simple validation with clear error messages
    - Easy async operation support
    - Consistent response format
    """

    # ==========================================================================
    # Setup
    # ==========================================================================

    def initialize(self, app_config=None, **kwargs) -> None:
        """Initialize handler with app configuration."""
        self.app_config = app_config or {}
        self._body_cache = None

    def set_default_headers(self) -> None:
        """Set default response headers."""
        self.set_header("Content-Type", "application/json")
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def options(self, *args, **kwargs) -> None:
        """Handle CORS preflight requests."""
        self.set_status(204)
        self.finish()

    # ==========================================================================
    # Request Data
    # ==========================================================================

    def get_json_body(self) -> dict[str, Any]:
        """
        Get request body as JSON dictionary.

        Returns:
            Parsed JSON body, or empty dict if no body/invalid JSON
        """
        if self._body_cache is not None:
            return self._body_cache

        try:
            self._body_cache = json.loads(self.request.body) if self.request.body else {}
        except json.JSONDecodeError:
            self._body_cache = {}
        return self._body_cache

    def get_data(
        self,
        required: list[str] | None = None,
        model: type | None = None,
    ) -> Any | None:
        """
        Get and validate request data.

        Args:
            required: List of required field names (simple validation)
            model: Pydantic model class for validation

        Returns:
            Validated data object, or None if validation failed (error sent)

        Example (simple):
            data = self.get_data(required=["cube", "element1", "element2"])
            if not data:
                return  # Error already sent

            cube = data["cube"]
            element1 = data["element1"]

        Example (with model):
            data = self.get_data(model=FetchRequest)
            if not data:
                return

            cube = data.cube
            element1 = data.element1
        """
        body = self.get_json_body()

        # Pydantic model validation
        if model is not None:
            if hasattr(model, "validate_request"):
                data, error = model.validate_request(body)
                if error:
                    self.set_status(400)
                    self.write(error)
                    return None
                return data
            else:
                # Fallback for non-Pydantic models
                try:
                    return model(**body)
                except Exception as e:
                    self.error(f"Invalid data: {e!s}")
                    return None

        # Simple required fields validation
        if required:
            missing = []
            for field in required:
                value = body.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing.append(field)

            if missing:
                self.error(f"Missing required fields: {', '.join(missing)}")
                return None

        return body

    def get_param(self, name: str, default: Any = None) -> Any:
        """
        Get a single parameter from body, query string, or path.

        Args:
            name: Parameter name
            default: Default value if not found

        Returns:
            Parameter value or default
        """
        # Check body first
        body = self.get_json_body()
        if name in body:
            return body[name]

        # Check query string
        value = self.get_argument(name, None)
        if value is not None:
            return value

        # Check path kwargs
        if hasattr(self, "path_kwargs") and name in self.path_kwargs:
            return self.path_kwargs[name]

        return default

    # ==========================================================================
    # Responses
    # ==========================================================================

    def ok(self, data: Any = None, message: str = "Success") -> None:
        """
        Send success response.

        Args:
            data: Response data (dict, list, or any JSON-serializable)
            message: Success message

        Example:
            self.ok({"value": 123})
            self.ok({"users": [...]}, message="Found 10 users")
        """
        response = {"success": True, "message": message}
        if data is not None:
            if hasattr(data, "to_dict"):
                response["data"] = data.to_dict()
            elif hasattr(data, "__dict__"):
                response["data"] = data.__dict__
            else:
                response["data"] = data
        self.write(response)

    def error(self, message: str, status: int = 400, details: Any = None) -> None:
        """
        Send error response.

        Args:
            message: Error message
            status: HTTP status code (default 400)
            details: Additional error details

        Example:
            self.error("Cube not found")
            self.error("Server error", status=500)
            self.error("Validation failed", details={"field": "cube", "issue": "required"})
        """
        self.set_status(status)
        response = {"success": False, "error": message}
        if details:
            response["details"] = details
        self.write(response)

    def not_found(self, message: str = "Not found") -> None:
        """Send 404 not found response."""
        self.error(message, status=404)

    def unauthorized(self, message: str = "Unauthorized") -> None:
        """Send 401 unauthorized response."""
        self.error(message, status=401)

    def forbidden(self, message: str = "Forbidden") -> None:
        """Send 403 forbidden response."""
        self.error(message, status=403)

    def server_error(self, message: str = "Internal server error") -> None:
        """Send 500 server error response."""
        self.error(message, status=500)

    # ==========================================================================
    # Async Operations
    # ==========================================================================

    async def run_async(self, func: Callable, *args, **kwargs) -> Any:
        """
        Run a blocking function asynchronously.

        Use this for any blocking operations (TM1, database, file I/O, etc.)

        Args:
            func: Function to run
            *args: Arguments to pass to function
            **kwargs: Keyword arguments to pass to function

        Returns:
            Function result

        Example:
            result = await self.run_async(tm1_ops.fetch_data, params, cube, elem1, elem2)
        """
        loop = tornado.ioloop.IOLoop.current()
        return await loop.run_in_executor(_EXECUTOR, partial(func, *args, **kwargs))

    async def try_async(
        self, func: Callable, *args, error_message: str = "Operation failed", **kwargs
    ) -> Any | None:
        """
        Run async operation with automatic error handling.

        Args:
            func: Function to run
            *args: Arguments
            error_message: Message to show on error
            **kwargs: Keyword arguments

        Returns:
            Function result, or None if error (error response sent)

        Example:
            result = await self.try_async(tm1_ops.fetch_data, params, cube, elem1, elem2)
            if result is None:
                return  # Error already sent
            self.ok(result)
        """
        try:
            return await self.run_async(func, *args, **kwargs)
        except Exception as e:
            self.error(f"{error_message}: {e!s}")
            return None

    # ==========================================================================
    # Utility
    # ==========================================================================

    def log(self, message: str, level: str = "info") -> None:
        """
        Log a message.

        Args:
            message: Log message
            level: Log level (debug, info, warning, error)
        """
        import logging

        logger = logging.getLogger(self.__class__.__name__)
        getattr(logger, level, logger.info)(message)


# =============================================================================
# Handler Decorator for Quick Route Definition
# =============================================================================


def handler(
    method: str = "POST",
    required: list[str] | None = None,
    model: type | None = None,
):
    """
    Decorator to create a simple handler function.

    Example:
        @handler(method="POST", required=["cube", "element1"])
        async def fetch_values(data, handler):
            result = await handler.run_async(fetch_data, data["cube"], data["element1"])
            return {"value": result}
    """

    def decorator(func):
        class GeneratedHandler(SimpleHandler):
            pass

        async def handle_request(self) -> None:
            data = self.get_data(required=required, model=model)
            if data is None:
                return

            try:
                result = await func(data, self)
                if result is not None:
                    self.ok(result)
            except Exception as e:
                self.error(str(e))

        setattr(GeneratedHandler, method.lower(), handle_request)
        GeneratedHandler.__name__ = func.__name__
        GeneratedHandler.__doc__ = func.__doc__

        return GeneratedHandler

    return decorator


# =============================================================================
# Example Usage Documentation
# =============================================================================

r"""
QUICK START GUIDE FOR NON-PYTHON DEVELOPERS
===========================================

1. SIMPLE HANDLER (No Validation)
---------------------------------

from pyrest.simple_handler import SimpleHandler

class HelloHandler(SimpleHandler):
    async def get(self):
        self.ok({"message": "Hello World!"})

    async def post(self):
        data = self.get_json_body()
        name = data.get("name", "Guest")
        self.ok({"greeting": f"Hello, {name}!"})


2. HANDLER WITH REQUIRED FIELDS
-------------------------------

class FetchHandler(SimpleHandler):
    async def post(self):
        # Validate required fields
        data = self.get_data(required=["cube", "element1", "element2"])
        if not data:
            return  # Error already sent

        # Use the data
        result = await self.run_async(
            fetch_from_tm1,
            data["cube"],
            data["element1"],
            data["element2"]
        )

        self.ok(result)


3. HANDLER WITH PYDANTIC VALIDATION
-----------------------------------

from pyrest.validation import RequestModel, field

class FetchInput(RequestModel):
    cube: str = field(description="Cube name")
    element1: str = field(description="First element", min_length=1)
    element2: str = field(description="Second element", min_length=1)

class FetchHandler(SimpleHandler):
    async def post(self):
        # Validate with Pydantic model
        data = self.get_data(model=FetchInput)
        if not data:
            return

        # data.cube, data.element1, data.element2 are now validated
        result = await self.run_async(fetch_from_tm1, data.cube, data.element1, data.element2)
        self.ok(result)


4. HANDLER WITH ERROR HANDLING
------------------------------

class SafeHandler(SimpleHandler):
    async def post(self):
        data = self.get_data(required=["cube"])
        if not data:
            return

        # Automatic error handling
        result = await self.try_async(
            risky_operation,
            data["cube"],
            error_message="Failed to process cube"
        )

        if result is None:
            return  # Error already sent

        self.ok(result)


5. REGISTERING HANDLERS
-----------------------

def get_handlers():
    return [
        (r"/", InfoHandler),
        (r"/fetch", FetchHandler),
        (r"/user/(?P<user_id>\d+)", UserHandler),
    ]
"""
