"""
PyRest Validation Module

Provides Pydantic-based validation for request data with automatic error handling.
Designed to be simple for non-Python developers.

Example Usage:
    from pyrest.validation import RequestModel, field

    class FetchRequest(RequestModel):
        cube: str = field(description="Cube name")
        element1: str = field(description="First element coordinates")
        element2: str = field(description="Second element coordinates")

    # In handler:
    data = FetchRequest.from_request(self)  # Auto-validates and returns errors
"""

from dataclasses import dataclass
from typing import Any

# Try to import Pydantic
try:
    from pydantic import BaseModel, Field, ValidationError, field_validator

    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    BaseModel = object
    Field = None
    ValidationError = Exception

    def field_validator(*args, **kwargs):
        return lambda f: f


# =============================================================================
# Simple Field Helper
# =============================================================================


def field(
    default: Any = ...,
    description: str = "",
    min_length: int | None = None,
    max_length: int | None = None,
    gt: float | None = None,
    ge: float | None = None,
    lt: float | None = None,
    le: float | None = None,
    pattern: str | None = None,
    examples: list[Any] | None = None,
) -> Any:
    """
    Simple field definition helper.

    Args:
        default: Default value (use ... for required fields)
        description: Human-readable description
        min_length: Minimum string length
        max_length: Maximum string length
        gt: Greater than (for numbers)
        ge: Greater than or equal (for numbers)
        lt: Less than (for numbers)
        le: Less than or equal (for numbers)
        pattern: Regex pattern for validation
        examples: Example values for documentation

    Example:
        class MyRequest(RequestModel):
            name: str = field(description="User name", min_length=1)
            age: int = field(default=0, description="User age", ge=0)
            email: str = field(description="Email", pattern=r".*@.*")
    """
    if not PYDANTIC_AVAILABLE:
        return default if default is not ... else None

    return Field(
        default=default,
        description=description,
        min_length=min_length,
        max_length=max_length,
        gt=gt,
        ge=ge,
        lt=lt,
        le=le,
        pattern=pattern,
        examples=examples or [],
    )


# =============================================================================
# Validation Error Response
# =============================================================================


@dataclass
class ValidationErrorDetail:
    """Single validation error."""

    field: str
    message: str
    value: Any = None


@dataclass
class ValidationResult:
    """Result of validation."""

    valid: bool
    data: Any = None
    errors: list[ValidationErrorDetail] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON response."""
        if self.valid:
            return {"valid": True, "data": self.data}
        return {
            "valid": False,
            "errors": [
                {"field": e.field, "message": e.message, "value": e.value}
                for e in (self.errors or [])
            ],
        }


# =============================================================================
# Request Model Base Class
# =============================================================================

if PYDANTIC_AVAILABLE:

    class RequestModel(BaseModel):
        """
        Base class for request validation models.

        Example:
            class CreateUserRequest(RequestModel):
                name: str = field(description="User name", min_length=1)
                email: str = field(description="Email address")
                age: int = field(default=0, ge=0)

            # In handler:
            data, error = CreateUserRequest.validate_request(request_body)
            if error:
                return error  # Returns formatted error response
        """

        class Config:
            # Allow extra fields to be ignored
            extra = "ignore"
            # Use enum values instead of names
            use_enum_values = True

        @classmethod
        def validate_request(cls, body: dict[str, Any]) -> tuple:
            """
            Validate request body and return (data, error).

            Returns:
                (validated_data, None) if valid
                (None, error_dict) if invalid
            """
            try:
                data = cls(**body)
                return data, None
            except ValidationError as e:
                errors = []
                for error in e.errors():
                    field_name = ".".join(str(loc) for loc in error["loc"])
                    errors.append(
                        {"field": field_name, "message": error["msg"], "type": error["type"]}
                    )
                return None, {"success": False, "error": "Validation failed", "details": errors}

        @classmethod
        def get_schema(cls) -> dict[str, Any]:
            """Get JSON schema for documentation."""
            return cls.model_json_schema()

        def to_dict(self) -> dict[str, Any]:
            """Convert to dictionary."""
            return self.model_dump()

else:
    # Fallback when Pydantic is not available
    class RequestModel:
        """Fallback RequestModel when Pydantic is not installed."""

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        @classmethod
        def validate_request(cls, body: dict[str, Any]) -> tuple:
            """Basic validation without Pydantic."""
            try:
                data = cls(**body)
                return data, None
            except Exception as e:
                return None, {"success": False, "error": f"Validation failed: {e!s}", "details": []}

        def to_dict(self) -> dict[str, Any]:
            return self.__dict__.copy()


# =============================================================================
# Pre-built Request Models for Common Operations
# =============================================================================

if PYDANTIC_AVAILABLE:

    class TM1ConnectionParams(RequestModel):
        """TM1 connection parameters."""

        connection_type: str = field(
            default="v12", description="Connection type: v12, v12_azure_ad, v12_paas, token, onprem"
        )

        # v12 basic auth
        base_url: str | None = field(default=None, description="TM1 REST API base URL")
        user: str | None = field(default=None, description="Username")
        password: str | None = field(default=None, description="Password")

        # v12 Azure AD
        tenant_id: str | None = field(default=None, description="Azure AD tenant ID")
        client_id: str | None = field(default=None, description="Azure AD client ID")
        client_secret: str | None = field(default=None, description="Azure AD client secret")

        # v12 PAaaS
        api_key: str | None = field(default=None, description="IBM API key")

        # Token
        access_token: str | None = field(default=None, description="Pre-acquired access token")

        # Legacy onprem
        address: str | None = field(default=None, description="Server address (legacy)")
        port: int | None = field(default=None, description="Server port (legacy)")

        # Common
        ssl: bool = field(default=True, description="Use SSL")
        instance: str | None = field(default=None, description="TM1 instance name")
        database: str | None = field(default=None, description="TM1 database name")

    class FetchRequest(TM1ConnectionParams):
        """Request for fetching cell values."""

        cube: str = field(description="Cube name")
        element1: str = field(description="First element coordinates (comma-separated)")
        element2: str = field(description="Second element coordinates (comma-separated)")

    class UpdateRequest(TM1ConnectionParams):
        """Request for updating a cell value."""

        cube: str = field(description="Cube name")
        target_element: str = field(description="Target element coordinates (comma-separated)")
        value: float = field(description="Value to write")

    class CalculateRequest(TM1ConnectionParams):
        """Request for fetch + add + update operation."""

        cube: str = field(description="Cube name")
        element1: str = field(description="First element coordinates")
        element2: str = field(description="Second element coordinates")
        target_element: str = field(description="Target element for the sum")


# =============================================================================
# Validation Decorator for Handlers
# =============================================================================


def validate(model_class: type[RequestModel]):
    """
    Decorator to automatically validate request body.

    Example:
        class MyHandler(SimpleHandler):
            @validate(FetchRequest)
            async def post(self, data: FetchRequest):
                # data is already validated
                result = fetch_data(data.cube, data.element1, data.element2)
                return self.success(result)
    """

    def decorator(func):
        import functools

        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            body = self.get_json_body() if hasattr(self, "get_json_body") else {}
            data, error = model_class.validate_request(body)
            if error:
                self.set_status(400)
                self.write(error)
                return None
            return await func(self, data, *args, **kwargs)

        return wrapper

    return decorator


# =============================================================================
# Helper Functions
# =============================================================================


def validate_required(body: dict[str, Any], *fields: str) -> dict[str, Any] | None:
    """
    Simple validation for required fields (no Pydantic needed).

    Args:
        body: Request body dict
        fields: Required field names

    Returns:
        None if valid, error dict if invalid

    Example:
        error = validate_required(body, "cube", "element1", "element2")
        if error:
            return self.error(error["message"])
    """
    missing = []
    for field_name in fields:
        value = body.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field_name)

    if missing:
        return {
            "success": False,
            "error": f"Missing required fields: {', '.join(missing)}",
            "missing_fields": missing,
        }
    return None


def validate_types(body: dict[str, Any], **field_types) -> dict[str, Any] | None:
    """
    Simple type validation (no Pydantic needed).

    Args:
        body: Request body dict
        field_types: Field names with expected types

    Returns:
        None if valid, error dict if invalid

    Example:
        error = validate_types(body, cube=str, port=int, ssl=bool)
        if error:
            return self.error(error["message"])
    """
    errors = []
    for field_name, expected_type in field_types.items():
        if field_name in body:
            value = body[field_name]
            if not isinstance(value, expected_type):
                errors.append(
                    {
                        "field": field_name,
                        "message": f"Expected {expected_type.__name__}, got {type(value).__name__}",
                        "value": value,
                    }
                )

    if errors:
        return {"success": False, "error": "Type validation failed", "details": errors}
    return None
