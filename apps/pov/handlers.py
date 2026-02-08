"""
POV (Point of View) App - TM1 Cube Value Operations

A simple app that:
1. Fetches two values from a TM1 cube
2. Adds them together
3. Updates a third cell with the result

Endpoints:
- GET  /pyrest/pov/          - API info
- GET  /pyrest/pov/ui        - Web UI
- POST /pyrest/pov/connect   - Test TM1 connection
- POST /pyrest/pov/fetch     - Fetch values
- POST /pyrest/pov/update    - Update cell
- POST /pyrest/pov/calculate - Fetch + Add + Update
"""

import os

from pyrest.simple_handler import SimpleHandler
from pyrest.validation import PYDANTIC_AVAILABLE, RequestModel, field

# Import async TM1 operations
from . import tm1_operations as tm1_ops

# =============================================================================
# Request Models
# =============================================================================

if PYDANTIC_AVAILABLE:

    class ConnectionInput(RequestModel):
        connection_type: str = field(default="v12", description="v12, v12_azure_ad, token, onprem")
        base_url: str | None = field(default=None, description="TM1 REST API URL")
        user: str | None = field(default=None, description="Username")
        password: str | None = field(default=None, description="Password")
        access_token: str | None = field(default=None, description="Pre-acquired token")
        address: str | None = field(default=None, description="Server address (legacy)")
        port: int | None = field(default=None, description="Server port (legacy)")
        ssl: bool = field(default=True, description="Use SSL")

    class FetchInput(ConnectionInput):
        cube: str = field(description="Cube name")
        element1: str = field(description="First element (comma-separated for multi-dim)")
        element2: str = field(description="Second element")

    class UpdateInput(ConnectionInput):
        cube: str = field(description="Cube name")
        target_element: str = field(description="Target element")
        value: float = field(description="Value to write")

    class CalculateInput(ConnectionInput):
        cube: str = field(description="Cube name")
        element1: str = field(description="First element")
        element2: str = field(description="Second element")
        target_element: str = field(description="Target element for sum")


# =============================================================================
# Connection Builder
# =============================================================================


def build_tm1_params(data) -> dict:
    """Build TM1 connection parameters from request data."""

    def get(k, d=None):
        return getattr(data, k, None) if hasattr(data, k) else data.get(k, d)

    conn_type = get("connection_type", "v12")

    if conn_type == "v12":
        if not get("base_url"):
            raise ValueError("base_url is required")
        return {
            "base_url": get("base_url"),
            "user": get("user", ""),
            "password": get("password", ""),
            "ssl": get("ssl", True),
        }

    elif conn_type == "v12_azure_ad":
        required = ["base_url", "tenant_id", "client_id", "client_secret"]
        missing = [f for f in required if not get(f)]
        if missing:
            raise ValueError(f"Missing: {', '.join(missing)}")
        return {
            "base_url": get("base_url"),
            "tenant": get("tenant_id"),
            "client_id": get("client_id"),
            "client_secret": get("client_secret"),
            "ssl": True,
        }

    elif conn_type == "token":
        if not get("base_url") or not get("access_token"):
            raise ValueError("base_url and access_token required")
        return {"base_url": get("base_url"), "access_token": get("access_token"), "ssl": True}

    else:  # onprem
        return {
            "address": get("address", "localhost"),
            "port": int(get("port", 8001)),
            "user": get("user", "admin"),
            "password": get("password", ""),
            "ssl": get("ssl", False),
        }


# =============================================================================
# Handlers
# =============================================================================


class POVInfoHandler(SimpleHandler):
    async def get(self):
        self.ok(
            {
                "app": "POV - Point of View",
                "tm1py_available": tm1_ops.TM1_AVAILABLE,
                "endpoints": {
                    "GET /ui": "Web interface",
                    "POST /connect": "Test connection",
                    "POST /fetch": "Fetch two values",
                    "POST /update": "Update a cell",
                    "POST /calculate": "Fetch + Add + Update",
                },
            }
        )


class POVUIHandler(SimpleHandler):
    async def get(self):
        app_path = os.environ.get("PYREST_APP_PATH", os.path.dirname(__file__))
        html_path = os.path.join(app_path, "static", "index.html")
        try:
            with open(html_path, encoding="utf-8") as f:
                self.set_header("Content-Type", "text/html")
                self.write(f.read())
        except FileNotFoundError:
            self.not_found("UI not found")


class POVTokenUIHandler(SimpleHandler):
    async def get(self):
        app_path = os.environ.get("PYREST_APP_PATH", os.path.dirname(__file__))
        html_path = os.path.join(app_path, "static", "token.html")
        try:
            with open(html_path, encoding="utf-8") as f:
                self.set_header("Content-Type", "text/html")
                self.write(f.read())
        except FileNotFoundError:
            self.not_found("Token UI not found")


class POVConnectHandler(SimpleHandler):
    async def post(self):
        if not tm1_ops.TM1_AVAILABLE:
            return self.error("TM1 module not available", status=500)

        data = self.get_data(model=ConnectionInput) if PYDANTIC_AVAILABLE else self.get_json_body()
        if data is None:
            return None

        try:
            params = build_tm1_params(data)
        except ValueError as e:
            return self.error(str(e))

        try:
            server_name = await tm1_ops.test_connection(params)
            self.ok({"server_name": server_name, "connected": True})
        except Exception as e:
            self.error(f"Connection failed: {e!s}")


class POVFetchHandler(SimpleHandler):
    async def post(self):
        if not tm1_ops.TM1_AVAILABLE:
            return self.error("TM1 module not available", status=500)

        data = (
            self.get_data(model=FetchInput)
            if PYDANTIC_AVAILABLE
            else self.get_data(required=["cube", "element1", "element2"])
        )
        if data is None:
            return None

        try:
            params = build_tm1_params(data)
        except ValueError as e:
            return self.error(str(e))

        def get(k):
            return getattr(data, k) if hasattr(data, k) else data.get(k)

        try:
            result = await tm1_ops.fetch_data(params, get("cube"), get("element1"), get("element2"))
            self.ok(result.to_dict())
        except Exception as e:
            self.error(f"Fetch failed: {e!s}")


class POVUpdateHandler(SimpleHandler):
    async def post(self):
        if not tm1_ops.TM1_AVAILABLE:
            return self.error("TM1 module not available", status=500)

        data = (
            self.get_data(model=UpdateInput)
            if PYDANTIC_AVAILABLE
            else self.get_data(required=["cube", "target_element", "value"])
        )
        if data is None:
            return None

        try:
            params = build_tm1_params(data)
        except ValueError as e:
            return self.error(str(e))

        def get(k):
            return getattr(data, k) if hasattr(data, k) else data.get(k)

        try:
            result = await tm1_ops.update_target(
                params, get("cube"), get("target_element"), float(get("value"))
            )
            self.ok(
                {
                    "target_element": get("target_element"),
                    "written_value": float(get("value")),
                    "confirmed_value": result.value,
                }
            )
        except Exception as e:
            self.error(f"Update failed: {e!s}")


class POVCalculateHandler(SimpleHandler):
    async def post(self):
        if not tm1_ops.TM1_AVAILABLE:
            return self.error("TM1 module not available", status=500)

        data = (
            self.get_data(model=CalculateInput)
            if PYDANTIC_AVAILABLE
            else self.get_data(required=["cube", "element1", "element2", "target_element"])
        )
        if data is None:
            return None

        try:
            params = build_tm1_params(data)
        except ValueError as e:
            return self.error(str(e))

        def get(k):
            return getattr(data, k) if hasattr(data, k) else data.get(k)

        try:
            result = await tm1_ops.execute_pov(
                params, get("cube"), get("element1"), get("element2"), get("target_element")
            )
            self.ok(
                result.to_dict(),
                message=f"{result.element1.value} + {result.element2.value} = {result.sum_value}",
            )
        except Exception as e:
            self.error(f"Calculate failed: {e!s}")


# =============================================================================
# Handler Registration
# =============================================================================


def get_handlers():
    return [
        (r"/", POVInfoHandler),
        (r"/ui", POVUIHandler),
        (r"/token-ui", POVTokenUIHandler),
        (r"/connect", POVConnectHandler),
        (r"/fetch", POVFetchHandler),
        (r"/update", POVUpdateHandler),
        (r"/calculate", POVCalculateHandler),
    ]
