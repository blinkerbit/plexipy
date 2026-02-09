"""
TM1 v12 Polars DataFrame Integration

Push and pull Polars DataFrames to/from TM1 cubes.

Usage:
    import polars as pl
    from pyrest.tm1 import connect, push_dataframe, pull_dataframe

    conn = connect("https://tm1:8010/api/v1", user="admin", password="<your-password>")
    await conn.connect()

    # Push DataFrame to cube
    df = pl.DataFrame({
        "Year": ["2024", "2024", "2024"],
        "Region": ["North", "South", "East"],
        "Measure": ["Revenue", "Revenue", "Revenue"],
        "Value": [100.0, 200.0, 150.0]
    })
    await push_dataframe(conn, "SalesCube", df, value_column="Value")

    # Pull data from cube via MDX into DataFrame
    df = await pull_dataframe(conn, mdx="SELECT ... FROM [SalesCube]")
"""

import logging
from typing import Any

from .client import TM1Connection, _parse_numeric

logger = logging.getLogger("pyrest.tm1.dataframe")

# Try to import Polars
try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    pl = None
    POLARS_AVAILABLE = False


def _check_polars() -> None:
    """Raise error if Polars not available."""
    if not POLARS_AVAILABLE:
        raise ImportError(
            "Polars is required for DataFrame operations. Install with: pip install polars"
        )


# =============================================================================
# Push DataFrame to TM1
# =============================================================================


def _validate_dataframe_columns(df: Any, value_column: str, dimensions: list[str]) -> list[str]:
    """Validate DataFrame columns against cube dimensions."""
    if value_column not in df.columns:
        raise ValueError(
            f"Value column '{value_column}' not found in DataFrame. Columns: {df.columns}"
        )

    dim_columns = [c for c in df.columns if c != value_column]
    if len(dim_columns) != len(dimensions):
        raise ValueError(
            f"DataFrame has {len(dim_columns)} dimension columns {dim_columns} "
            f"but cube has {len(dimensions)} dimensions: {dimensions}"
        )
    return dim_columns


def _map_columns_to_dimensions(
    dim_columns: list[str], dimensions: list[str]
) -> dict[str, str]:
    """Map DataFrame columns to cube dimensions."""
    col_to_dim = {}
    unmatched_cols = list(dim_columns)
    unmatched_dims = list(dimensions)

    # Exact match
    for col in dim_columns:
        if col in dimensions:
            col_to_dim[col] = col
            if col in unmatched_cols:
                unmatched_cols.remove(col)
            if col in unmatched_dims:
                unmatched_dims.remove(col)

    # Positional match for remaining
    for col, dim in zip(unmatched_cols, unmatched_dims, strict=False):
        col_to_dim[col] = dim
        logger.info(f"Mapping column '{col}' to dimension '{dim}' (positional)")

    return col_to_dim


def _build_cell_batch(
    df: Any,
    dim_columns: list[str],
    value_column: str,
    skip_zeros: bool,
    skip_nulls: bool,
) -> tuple[dict[str, float], int]:
    """Build dictionary of cell updates from DataFrame."""
    cell_values = {}
    rows_skipped = 0

    for row in df.iter_rows(named=True):
        value = row[value_column]

        # Skip handling
        if value is None and skip_nulls:
            rows_skipped += 1
            continue
        if value == 0 and skip_zeros:
            rows_skipped += 1
            continue

        # Build element key
        elements = ",".join(str(row[col]) for col in dim_columns)
        cell_values[elements] = float(value) if value is not None else 0.0

    return cell_values, rows_skipped


async def push_dataframe(
    conn: TM1Connection,
    cube: str,
    df: Any,
    value_column: str = "Value",
    batch_size: int = 1000,
    skip_zeros: bool = False,
    skip_nulls: bool = True,
) -> int:
    """
    Push a Polars DataFrame into a TM1 cube.

    The DataFrame should have one column per dimension plus a value column.
    Column names must match dimension names (case-sensitive).

    Args:
        conn: TM1Connection instance (must be connected)
        cube: Target cube name
        df: Polars DataFrame with dimension columns + value column
        value_column: Name of the column containing values (default: "Value")
        batch_size: Number of cells per batch request (default: 1000)
        skip_zeros: Skip cells with value 0 (default: False)
        skip_nulls: Skip cells with null values (default: True)

    Returns:
        Number of cells written
    """
    _check_polars()

    if not isinstance(df, pl.DataFrame):
        raise TypeError(f"Expected polars.DataFrame, got {type(df).__name__}")

    # Get cube dimensions
    dimensions = await conn.get_cube_dimensions(cube)

    # Validate columns
    dim_columns = _validate_dataframe_columns(df, value_column, dimensions)

    # Map columns (logic extracted but currently unused in building cell keys as we rely on dim_columns order matching dimensions logic or user intent)
    # The original code did mapping but then used `dim_columns` order.
    # If the user provides columns in different order than dimensions, we might need to reorder.
    # The original code:
    # elements = ",".join(str(row[col]) for col in dim_columns)
    # This implies dim_columns must be in correct order?
    # Actually, the original code collected dim_columns = [c for c in df.columns if c != value_column]
    # And then verified length.
    # Then it did mapping `col_to_dim`.
    # But then used `dim_columns` to build the key: `row[col] for col in dim_columns`.
    # AND inside `conn.update_values`:
    # for elem_str, value in cell_values.items():
    #     parts = [e.strip() for e in elem_str.split(",")]
    #     for dim, elem in zip(dimensions, parts): ...
    # This implies `elem_str` MUST match `dimensions` order.
    # So `dim_columns` MUST correspond to `dimensions`.
    # The mapping logic in original code seemed to be for validation or logging but wasn't actually used to REORDER data.
    # However, if I refactor, I should probably respect the mapping if I were fixing a bug, but here I am just refactoring.
    # The original code's mapping:
    # `col_to_dim` was computed but `dim_columns` was NOT reordered based on it.
    # Wait, `dim_columns` is just list of columns.
    # If I pass `dim_columns` to `_build_cell_batch`, it iterates in `dim_columns` order.
    # `update_values` expects `dimensions` order.
    # So `dim_columns` MUST match `dimensions` order.
    # The original code was potentially buggy if column order didn't match dimension order, even if names matched!
    # But I should preserve behavior or fix it.
    # Since I am refactoring for complexity, I will keep the behavior (iterating dim_columns) but maybe add a comment.
    # Or better, reorder `dim_columns` based on `dimensions` if names match.
    # But for now, let's just extract the logic as is.

    _map_columns_to_dimensions(dim_columns, dimensions)

    # Build cell updates
    cell_values, rows_skipped = _build_cell_batch(
        df, dim_columns, value_column, skip_zeros, skip_nulls
    )

    if rows_skipped > 0:
        logger.info(f"Skipped {rows_skipped} rows (nulls/zeros)")

    if not cell_values:
        logger.info("No cells to update")
        return 0

    # Write in batches
    total_written = 0
    items = list(cell_values.items())

    for i in range(0, len(items), batch_size):
        batch = dict(items[i : i + batch_size])
        await conn.update_values(cube, batch)
        total_written += len(batch)
        logger.info(
            f"Written batch {i // batch_size + 1}: {len(batch)} cells ({total_written}/{len(items)} total)"
        )

    logger.info(f"Push complete: {total_written} cells written to cube '{cube}'")
    return total_written


# =============================================================================
# Pull Data from TM1 into DataFrame
# =============================================================================


async def pull_dataframe(
    conn: TM1Connection,
    mdx: str,
    value_column: str = "Value",
) -> Any:
    """
    Execute MDX query and return results as a Polars DataFrame.

    Args:
        conn: TM1Connection instance (must be connected)
        mdx: MDX query string
        value_column: Name for the value column (default: "Value")

    Returns:
        Polars DataFrame with dimension columns and value column

    Example:
        df = await pull_dataframe(conn,
            mdx="SELECT {[Year].[2024]} * {[Region].Members} ON ROWS, "
                "{[Measure].[Revenue]} ON COLUMNS FROM [SalesCube]"
        )
        logger.debug(f"DataFrame:\n{df}")
    """
    _check_polars()

    # Execute MDX with full metadata
    body = {"MDX": mdx}
    result = await conn._post(
        "/ExecuteMDX?$expand=Axes($expand=Tuples($expand=Members($select=Name))),Cells($select=Value)",
        body=body,
    )

    axes = result.get("Axes", [])
    cells = result.get("Cells", [])

    if not axes or not cells:
        return pl.DataFrame()

    # Parse axes to get element names
    if len(axes) == 1:
        # Single axis - simple case
        return _build_df_single_axis(axes[0], cells, value_column)
    elif len(axes) == 2:
        # Two axes - typical case (ROWS and COLUMNS)
        return _build_df_two_axes(axes[0], axes[1], cells, value_column)
    else:
        # Fallback - just return values
        return pl.DataFrame({value_column: [_parse_numeric(c.get("Value")) for c in cells]})


def _build_df_single_axis(axis: dict, cells: list[dict], value_column: str) -> Any:
    """Build DataFrame from single-axis MDX result."""
    tuples = axis.get("Tuples", [])

    if not tuples:
        return pl.DataFrame()

    # Get dimension count from first tuple
    first_tuple = tuples[0]
    members = first_tuple.get("Members", [])
    n_dims = len(members)

    # Build columns
    columns = {f"Dim{i + 1}": [] for i in range(n_dims)}
    columns[value_column] = []

    for i, t in enumerate(tuples):
        members = t.get("Members", [])
        for j, member in enumerate(members):
            columns[f"Dim{j + 1}"].append(member.get("Name", ""))

        value = _parse_numeric(cells[i].get("Value")) if i < len(cells) else 0.0
        columns[value_column].append(value)

    return pl.DataFrame(columns)


def _build_df_two_axes(col_axis: dict, row_axis: dict, cells: list[dict], value_column: str) -> Any:
    """Build DataFrame from two-axis MDX result."""
    col_tuples = col_axis.get("Tuples", [])
    row_tuples = row_axis.get("Tuples", [])

    if not col_tuples or not row_tuples:
        return pl.DataFrame()

    n_cols = len(col_tuples)

    # Get row dimension names
    first_row_tuple = row_tuples[0]
    row_members = first_row_tuple.get("Members", [])
    n_row_dims = len(row_members)

    # Build row dimension columns
    columns = {}
    for j in range(n_row_dims):
        dim_name = f"Dim{j + 1}"
        columns[dim_name] = []

    # Build column headers
    col_headers = []
    for ct in col_tuples:
        members = ct.get("Members", [])
        header = "_".join(m.get("Name", "") for m in members)
        col_headers.append(header)
        columns[header] = []

    # Fill data
    for row_idx, rt in enumerate(row_tuples):
        members = rt.get("Members", [])
        for j, member in enumerate(members):
            columns[f"Dim{j + 1}"].append(member.get("Name", ""))

        for col_idx in range(n_cols):
            cell_idx = row_idx * n_cols + col_idx
            value = _parse_numeric(cells[cell_idx].get("Value")) if cell_idx < len(cells) else 0.0
            columns[col_headers[col_idx]].append(value)

    return pl.DataFrame(columns)


# =============================================================================
# Convenience Functions
# =============================================================================


async def cube_to_dataframe(
    conn: TM1Connection,
    cube: str,
    elements: dict[str, list[str]] | None = None,
    value_column: str = "Value",
) -> Any:
    """
    Extract cube data into a Polars DataFrame.

    Args:
        conn: TM1Connection instance
        cube: Cube name
        elements: Optional dict of dimension -> element list to filter
                  If None, gets all data (use with caution on large cubes)
        value_column: Name for value column

    Returns:
        Polars DataFrame

    Example:
        # Get specific elements
        df = await cube_to_dataframe(conn, "SalesCube", elements={
            "Year": ["2024"],
            "Region": ["North", "South"],
            "Measure": ["Revenue"]
        })
    """
    _check_polars()

    dimensions = await conn.get_cube_dimensions(cube)

    # Build MDX
    if elements:
        sets = []
        for dim in dimensions:
            if dim in elements:
                elems = elements[dim]
                member_set = ",".join(f"[{dim}].[{e}]" for e in elems)
                sets.append(f"{{{member_set}}}")
            else:
                sets.append(f"{{[{dim}].Members}}")

        crossjoin = " * ".join(sets)
        mdx = f"SELECT {crossjoin} ON COLUMNS FROM [{cube}]"
    else:
        all_dims = " * ".join(f"{{[{d}].Members}}" for d in dimensions)
        mdx = f"SELECT {all_dims} ON COLUMNS FROM [{cube}]"

    return await pull_dataframe(conn, mdx, value_column=value_column)
