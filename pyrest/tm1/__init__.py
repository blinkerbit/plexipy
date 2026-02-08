"""
PyRest TM1 Module - Async TM1 v12 REST API Client

A simple, fully async client for TM1 v12 REST API.
No TM1py dependency. Uses native async HTTP for non-blocking operations.

=== QUICK START ===

    from pyrest.tm1 import connect

    # Connect to TM1
    async with connect("https://tm1:8010/api/v1", user="admin", password="<your-password>") as conn:

        # Get values
        values = await conn.get_values("SalesCube", [
            "2024,North,Revenue",
            "2024,South,Revenue"
        ])

        # Update values
        await conn.update_values("SalesCube", {
            "2024,North,Revenue": 100,
            "2024,South,Revenue": 200
        })

=== GET SINGLE VALUE ===

    value = await conn.get_value("SalesCube", "2024,North,Revenue")

=== EXECUTE MDX ===

    values = await conn.execute_mdx_values(
        "SELECT {[Year].[2024]} ON COLUMNS FROM [SalesCube]"
    )

=== PUSH POLARS DATAFRAME ===

    import polars as pl
    from pyrest.tm1 import connect, push_dataframe

    df = pl.DataFrame({
        "Year": ["2024", "2024"],
        "Region": ["North", "South"],
        "Measure": ["Revenue", "Revenue"],
        "Value": [100.0, 200.0]
    })

    async with connect(...) as conn:
        count = await push_dataframe(conn, "SalesCube", df)

=== PULL DATA INTO DATAFRAME ===

    from pyrest.tm1 import connect, pull_dataframe

    async with connect(...) as conn:
        df = await pull_dataframe(conn, mdx="SELECT ... FROM [SalesCube]")
        logger.debug(f"DataFrame:\n{df}")

=== WITH ACCESS TOKEN (Azure AD) ===

    async with connect("https://tm1:8010/api/v1", access_token="eyJ...") as conn:
        values = await conn.get_values("Cube", ["elem1"])
"""

import logging

# Core client
from .client import (
    TM1Connection,
    TM1Error,
    connect,
)

# DataFrame operations (import functions, Polars is optional)
from .dataframe import (
    POLARS_AVAILABLE,
    cube_to_dataframe,
    pull_dataframe,
    push_dataframe,
)

logger = logging.getLogger(__name__)

__all__ = [
    "POLARS_AVAILABLE",
    # Connection
    "TM1Connection",
    "TM1Error",
    "connect",
    "cube_to_dataframe",
    "pull_dataframe",
    # DataFrame
    "push_dataframe",
]
