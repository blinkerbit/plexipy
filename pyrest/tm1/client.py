"""
TM1 v12 Async REST Client

Pure async HTTP client for TM1 v12 REST API.
No TM1py dependency - uses tornado.httpclient for fully non-blocking I/O.

Usage:
    from pyrest.tm1 import TM1Connection

    # Connect
    conn = TM1Connection(base_url="https://tm1server/api/v1", user="admin", password="<your-password>")
    await conn.connect()

    # Read values
    values = await conn.get_values("SalesCube", ["elem1,elem2", "elem3,elem4"])

    # Write values
    await conn.update_values("SalesCube", {"elem1,elem2": 100, "elem3,elem4": 200})

    # Close
    await conn.close()
"""

import base64
import contextlib
import json
import logging
import ssl
from typing import Any
from urllib.parse import quote

import tornado.escape
import tornado.httpclient

logger = logging.getLogger("pyrest.tm1.client")


class TM1Error(Exception):
    """TM1 REST API error."""

    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class TM1Connection:
    """
    Async TM1 v12 REST API client.

    Provides a simple, non-blocking interface to TM1 v12 REST API.

    Args:
        base_url: TM1 REST API base URL (e.g., https://tm1server:8010/api/v1)
        user: Username for basic auth
        password: Password for basic auth
        access_token: Pre-acquired access token (for Azure AD)
        ssl_verify: Whether to verify SSL certificates
        timeout: Request timeout in seconds

    Usage:
        conn = TM1Connection(base_url="https://tm1:8010/api/v1", user="admin", password="<your-password>")
        await conn.connect()

        values = await conn.get_values("MyCube", ["elem1", "elem2"])
        await conn.update_values("MyCube", {"elem1": 100})

        await conn.close()
    """

    def __init__(
        self,
        base_url: str,
        user: str = "",
        password: str = "",
        access_token: str = "",
        ssl_verify: bool = True,
        timeout: float = 30.0,
        session_context: str = "PyRest",
    ):
        # Normalize base_url - remove trailing slash
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self.access_token = access_token
        self.ssl_verify = ssl_verify
        self.timeout = timeout
        self.session_context = session_context

        # Session state
        self._session_id: str | None = None
        self._server_name: str | None = None
        self._connected = False

        # HTTP client
        self._http_client = tornado.httpclient.AsyncHTTPClient()

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def connect(self) -> str:
        """
        Establish connection to TM1 server.

        Returns:
            Server name string

        Raises:
            TM1Error: If connection fails
        """
        data = await self._get("/Configuration/ProductVersion")
        self._server_name = data.get("value", "TM1 Server")
        self._connected = True
        logger.info(f"Connected to TM1: {self._server_name}")
        return self._server_name

    async def close(self) -> None:
        """Close the TM1 connection and end session."""
        if self._connected:
            with contextlib.suppress(Exception):
                await self._post("/ActiveSession/tm1.Close", body={})
            self._connected = False
            self._session_id = None
            logger.info("TM1 connection closed")

    @property
    def connected(self) -> bool:
        """Whether currently connected."""
        return self._connected

    @property
    def server_name(self) -> str | None:
        """Connected server name."""
        return self._server_name

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.close()

    # =========================================================================
    # Cell Operations
    # =========================================================================

    async def get_value(self, cube: str, elements: str) -> float:
        """
        Get a single cell value from a cube.

        Args:
            cube: Cube name
            elements: Comma-separated element names (in dimension order)

        Returns:
            Numeric cell value

        Example:
            value = await conn.get_value("SalesCube", "2024,North,Revenue")
        """
        values = await self.get_values(cube, [elements])
        return values[0]

    async def get_values(self, cube: str, element_list: list[str]) -> list[float]:
        """
        Get multiple cell values from a cube.

        Args:
            cube: Cube name
            element_list: List of comma-separated element coordinates

        Returns:
            List of numeric values in same order as element_list

        Example:
            values = await conn.get_values("SalesCube", [
                "2024,North,Revenue",
                "2024,South,Revenue",
                "2024,East,Revenue"
            ])
            # values = [100.0, 200.0, 150.0]
        """
        if not element_list:
            return []

        # Get cube dimensions for building MDX
        dimensions = await self.get_cube_dimensions(cube)

        # Build MDX to fetch all values in one request
        member_refs = []
        for elem_str in element_list:
            parts = [e.strip() for e in elem_str.split(",")]
            if len(parts) != len(dimensions):
                raise TM1Error(
                    f"Element '{elem_str}' has {len(parts)} parts but cube '{cube}' "
                    f"has {len(dimensions)} dimensions: {dimensions}"
                )
            member = ",".join(
                f"[{dim}].[{elem}]" for dim, elem in zip(dimensions, parts, strict=False)
            )
            member_refs.append(f"({member})")

        mdx = f"SELECT {{{','.join(member_refs)}}} ON COLUMNS FROM [{cube}]"

        # Execute MDX
        result = await self.execute_mdx(cube, mdx)

        # Extract numeric values
        values = []
        for cell in result:
            raw = cell.get("Value")
            values.append(_parse_numeric(raw))

        # Pad with 0.0 if fewer cells returned
        while len(values) < len(element_list):
            values.append(0.0)

        return values

    async def update_value(self, cube: str, elements: str, value: float) -> None:
        """
        Update a single cell in a cube.

        Args:
            cube: Cube name
            elements: Comma-separated element names
            value: Value to write

        Example:
            await conn.update_value("SalesCube", "2024,North,Revenue", 12345.67)
        """
        await self.update_values(cube, {elements: value})

    async def update_values(self, cube: str, cell_values: dict[str, float]) -> None:
        """
        Update multiple cells in a cube.

        Args:
            cube: Cube name
            cell_values: Dict mapping element coordinates to values
                Key: comma-separated element names
                Value: numeric value to write

        Example:
            await conn.update_values("SalesCube", {
                "2024,North,Revenue": 100,
                "2024,South,Revenue": 200,
                "2024,East,Revenue": 150
            })
        """
        if not cell_values:
            return

        # Get cube dimensions
        dimensions = await self.get_cube_dimensions(cube)

        # Build cellset for PATCH request
        cells = []
        for elem_str, value in cell_values.items():
            parts = [e.strip() for e in elem_str.split(",")]
            if len(parts) != len(dimensions):
                raise TM1Error(
                    f"Element '{elem_str}' has {len(parts)} parts but cube '{cube}' "
                    f"has {len(dimensions)} dimensions: {dimensions}"
                )

            # Build element tuple for each dimension
            element_refs = []
            for dim, elem in zip(dimensions, parts, strict=False):
                element_refs.append({"Name": dim, "Element": {"Name": elem}})

            cells.append({"Tuple": element_refs, "Value": float(value)})

        # Use write-back endpoint
        body = {"Cells": cells}
        url = f"/Cubes('{_quote(cube)}')/tm1.Update"
        await self._post(url, body=body)

        logger.info(f"Updated {len(cells)} cell(s) in cube '{cube}'")

    # =========================================================================
    # MDX Execution
    # =========================================================================

    async def execute_mdx(self, cube: str, mdx: str) -> list[dict[str, Any]]:
        """
        Execute an MDX query and return cell values.

        Args:
            cube: Cube name (for context)
            mdx: MDX query string

        Returns:
            List of cell value dicts, each with 'Value' key

        Example:
            cells = await conn.execute_mdx("SalesCube",
                "SELECT {[Year].[2024]} ON COLUMNS FROM [SalesCube]"
            )
        """
        body = {"MDX": mdx}
        result = await self._post("/ExecuteMDX?$expand=Cells($select=Value)", body=body)
        return result.get("Cells", [])

    async def execute_mdx_raw(self, mdx: str) -> dict[str, Any]:
        """
        Execute an MDX query and return full response.

        Args:
            mdx: MDX query string

        Returns:
            Full MDX response dict
        """
        body = {"MDX": mdx}
        return await self._post("/ExecuteMDX?$expand=Axes,Cells", body=body)

    async def execute_mdx_values(self, mdx: str) -> list[float]:
        """
        Execute MDX and return just numeric values.

        Args:
            mdx: MDX query string

        Returns:
            List of numeric values

        Example:
            values = await conn.execute_mdx_values(
                "SELECT {[Year].[2024]} ON COLUMNS FROM [SalesCube]"
            )
        """
        body = {"MDX": mdx}
        result = await self._post("/ExecuteMDX?$expand=Cells($select=Value)", body=body)
        cells = result.get("Cells", [])
        return [_parse_numeric(c.get("Value")) for c in cells]

    # =========================================================================
    # Metadata
    # =========================================================================

    async def get_cubes(self) -> list[str]:
        """Get list of all cube names."""
        data = await self._get("/Cubes?$select=Name")
        return [c["Name"] for c in data.get("value", [])]

    async def get_cube_dimensions(self, cube: str) -> list[str]:
        """
        Get dimension names for a cube (in order).

        Args:
            cube: Cube name

        Returns:
            List of dimension names in cube order
        """
        url = f"/Cubes('{_quote(cube)}')/Dimensions?$select=Name"
        data = await self._get(url)
        return [d["Name"] for d in data.get("value", [])]

    async def get_dimension_elements(
        self, dimension: str, hierarchy: str | None = None
    ) -> list[str]:
        """
        Get element names from a dimension.

        Args:
            dimension: Dimension name
            hierarchy: Hierarchy name (defaults to dimension name)

        Returns:
            List of element names
        """
        hier = hierarchy or dimension
        url = f"/Dimensions('{_quote(dimension)}')/Hierarchies('{_quote(hier)}')/Elements?$select=Name"
        data = await self._get(url)
        return [e["Name"] for e in data.get("value", [])]

    async def get_server_name(self) -> str:
        """Get TM1 server name."""
        data = await self._get("/Configuration/ServerName")
        return data.get("value", "Unknown")

    # =========================================================================
    # HTTP Methods (Internal)
    # =========================================================================

    def _build_headers(self) -> dict[str, str]:
        """Build request headers."""
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json;odata.metadata=none",
        }

        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        elif self.user:
            credentials = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"

        if self.session_context:
            headers["TM1-SessionContext"] = self.session_context

        return headers

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        """Build SSL context."""
        if not self.ssl_verify:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return None

    async def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
    ) -> dict[str, Any]:
        """Make HTTP request to TM1 REST API."""
        url = f"{self.base_url}{path}"
        headers = self._build_headers()
        ssl_context = self._build_ssl_context()

        request_body = json.dumps(body).encode("utf-8") if body is not None else None

        try:
            request = tornado.httpclient.HTTPRequest(
                url=url,
                method=method,
                headers=headers,
                body=request_body,
                request_timeout=self.timeout,
                ssl_options=ssl_context,
                validate_cert=self.ssl_verify,
            )

            response = await self._http_client.fetch(request, raise_error=False)

            # Handle session cookie
            if "Set-Cookie" in (response.headers or {}):
                for cookie in response.headers.get_list("Set-Cookie"):
                    if "TM1SessionId" in cookie:
                        self._session_id = cookie.split("TM1SessionId=")[1].split(";")[0]

            # Check for errors
            if response.code >= 400:
                error_body = (
                    response.body.decode("utf-8", errors="replace") if response.body else ""
                )
                error_msg = _extract_error_message(error_body, response.code)
                raise TM1Error(error_msg, status_code=response.code, response_body=error_body)

            # Parse response
            if response.body:
                return json.loads(response.body.decode("utf-8"))
            return {}

        except TM1Error:
            raise
        except Exception as e:
            raise TM1Error(f"Request failed: {e!s}") from e

    async def _get(self, path: str) -> dict[str, Any]:
        """HTTP GET."""
        return await self._request("GET", path)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """HTTP POST."""
        return await self._request("POST", path, body)

    async def _patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """HTTP PATCH."""
        return await self._request("PATCH", path, body)

    async def _delete(self, path: str) -> dict[str, Any]:
        """HTTP DELETE."""
        return await self._request("DELETE", path)


# =============================================================================
# Factory Functions
# =============================================================================


def connect(
    base_url: str,
    user: str = "",
    password: str = "",
    access_token: str = "",
    ssl_verify: bool = True,
    timeout: float = 30.0,
) -> TM1Connection:
    """
    Create a TM1 connection (does NOT connect yet - use await conn.connect() or async with).

    Args:
        base_url: TM1 REST API base URL
        user: Username
        password: Password
        access_token: Pre-acquired access token
        ssl_verify: Verify SSL certificates
        timeout: Request timeout in seconds

    Returns:
        TM1Connection instance (not yet connected)

    Example:
        conn = connect("https://tm1:8010/api/v1", user="admin", password="<your-password>")
        await conn.connect()
        values = await conn.get_values("Cube", ["elem1,elem2"])
        await conn.close()

    Example (context manager):
        async with connect("https://tm1:8010/api/v1", user="admin", password="<your-password>") as conn:
            values = await conn.get_values("Cube", ["elem1,elem2"])
    """
    return TM1Connection(
        base_url=base_url,
        user=user,
        password=password,
        access_token=access_token,
        ssl_verify=ssl_verify,
        timeout=timeout,
    )


# =============================================================================
# Helpers
# =============================================================================


def _quote(s: str) -> str:
    """URL-encode a string for OData paths."""
    return quote(s, safe="")


def _parse_numeric(value: Any) -> float:
    """Parse TM1 cell value to float."""
    if value is None:
        return 0.0
    if isinstance(value, dict) and "Value" in value:
        value = value["Value"]
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _extract_error_message(body: str, status_code: int) -> str:
    """Extract error message from TM1 REST API error response."""
    try:
        data = json.loads(body)
        error = data.get("error", {})
        message = error.get("message", {})
        if isinstance(message, dict):
            return message.get("value", f"TM1 error (HTTP {status_code})")
        return str(message) or f"TM1 error (HTTP {status_code})"
    except (json.JSONDecodeError, AttributeError):
        return f"TM1 error (HTTP {status_code}): {body[:200]}"
