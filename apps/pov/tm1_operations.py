"""
TM1 Operations for POV App

Uses the central pyrest.tm1 async client.
All operations are fully async - no thread pool needed.
"""

from dataclasses import dataclass
from typing import Any

# Import the central TM1 async client
try:
    from pyrest.tm1 import TM1Connection, TM1Error
    from pyrest.tm1 import connect as tm1_connect

    TM1_AVAILABLE = True
except ImportError:
    TM1_AVAILABLE = False
    tm1_connect = None
    TM1Connection = None
    TM1Error = Exception


@dataclass
class ElementData:
    """Data for a single element/cell."""

    coordinates: str
    value: float


@dataclass
class POVResult:
    """Result of a POV operation."""

    element1: ElementData
    element2: ElementData
    sum_value: float
    target: ElementData | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "element1": {"coordinates": self.element1.coordinates, "value": self.element1.value},
            "element2": {"coordinates": self.element2.coordinates, "value": self.element2.value},
            "sum": self.sum_value,
        }
        if self.target:
            result["target"] = {
                "coordinates": self.target.coordinates,
                "written": self.sum_value,
                "confirmed": self.target.value,
            }
        return result


def _build_connection(params: dict) -> TM1Connection:
    """Create a TM1Connection from params dict."""
    return tm1_connect(
        base_url=params.get("base_url", ""),
        user=params.get("user", ""),
        password=params.get("password", ""),
        access_token=params.get("access_token", ""),
        ssl_verify=params.get("verify", False),
    )


async def test_connection(params: dict) -> str:
    """Test TM1 connection and return server name."""
    async with _build_connection(params) as conn:
        return await conn.get_server_name()


async def fetch_data(params: dict, cube: str, element1: str, element2: str) -> POVResult:
    """Fetch two values from a cube."""
    async with _build_connection(params) as conn:
        values = await conn.get_values(cube, [element1, element2])
        v1, v2 = values[0], values[1]

        return POVResult(
            element1=ElementData(coordinates=element1, value=v1),
            element2=ElementData(coordinates=element2, value=v2),
            sum_value=v1 + v2,
        )


async def update_target(params: dict, cube: str, target_element: str, value: float) -> ElementData:
    """Update a cell and return confirmed value."""
    async with _build_connection(params) as conn:
        await conn.update_value(cube, target_element, value)

        # Read back to confirm
        confirmed = await conn.get_value(cube, target_element)

        return ElementData(coordinates=target_element, value=confirmed)


async def execute_pov(
    params: dict, cube: str, element1: str, element2: str, target_element: str
) -> POVResult:
    """Full POV: fetch, add, update, confirm."""
    async with _build_connection(params) as conn:
        # Fetch
        values = await conn.get_values(cube, [element1, element2])
        v1, v2 = values[0], values[1]
        total = v1 + v2

        # Update
        await conn.update_value(cube, target_element, total)

        # Confirm
        confirmed = await conn.get_value(cube, target_element)

        return POVResult(
            element1=ElementData(coordinates=element1, value=v1),
            element2=ElementData(coordinates=element2, value=v2),
            sum_value=total,
            target=ElementData(coordinates=target_element, value=confirmed),
        )
