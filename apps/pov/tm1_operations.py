"""
TM1 Operations Module for POV App

Clean, reusable functions for TM1 cube operations.
All blocking TM1 operations are contained here for easy testing and maintenance.
"""

from typing import Tuple, Dict, Any, Optional
from dataclasses import dataclass

# Try to import TM1py
try:
    from TM1py import TM1Service
    TM1_AVAILABLE = True
except ImportError:
    TM1_AVAILABLE = False
    TM1Service = None


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
    target: Optional[ElementData] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        result = {
            "element1": {"coordinates": self.element1.coordinates, "value": self.element1.value},
            "element2": {"coordinates": self.element2.coordinates, "value": self.element2.value},
            "sum": self.sum_value
        }
        if self.target:
            result["target"] = {
                "coordinates": self.target.coordinates,
                "written": self.sum_value,
                "confirmed": self.target.value
            }
        return result


def parse_value(value: Any) -> float:
    """
    Parse TM1 cell value to numeric.
    
    Handles:
    - None -> 0.0
    - int/float -> float
    - str (numeric) -> float
    - str (non-numeric) -> 0.0
    - dict with 'Value' key -> extract and parse
    """
    if value is None:
        return 0.0
    
    # Handle dict with 'Value' key (some TM1py responses)
    if isinstance(value, dict) and 'Value' in value:
        value = value['Value']
        if value is None:
            return 0.0
    
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def fetch_element(tm1: 'TM1Service', cube: str, element: str) -> float:
    """
    Fetch a single element value from a cube.
    
    Args:
        tm1: TM1Service connection
        cube: Cube name
        element: Element coordinates (comma-separated for multi-dim)
        
    Returns:
        Numeric value of the cell
    """
    raw_value = tm1.cubes.cells.get_value(cube, element.strip())
    return parse_value(raw_value)


def fetch_elements(tm1: 'TM1Service', cube: str, element1: str, element2: str) -> Tuple[float, float]:
    """
    Fetch values from two elements in a cube.
    
    Args:
        tm1: TM1Service connection
        cube: Cube name
        element1: First element coordinates
        element2: Second element coordinates
        
    Returns:
        Tuple of (value1, value2) as floats
    """
    value1 = fetch_element(tm1, cube, element1)
    value2 = fetch_element(tm1, cube, element2)
    return value1, value2


def calculate_sum(value1: float, value2: float) -> float:
    """
    Add two values.
    
    Args:
        value1: First value
        value2: Second value
        
    Returns:
        Sum of the values
    """
    return value1 + value2


def update_element(tm1: 'TM1Service', cube: str, element: str, value: float) -> float:
    """
    Update a cell with a value and return confirmed value.
    
    Args:
        tm1: TM1Service connection
        cube: Cube name
        element: Target element coordinates
        value: Value to write
        
    Returns:
        Confirmed value after write
    """
    # Parse element to tuple for write_value
    element_tuple = tuple(e.strip() for e in element.split(','))
    
    # Write the value
    tm1.cubes.cells.write_value(
        value=float(value),
        cube_name=cube,
        element_tuple=element_tuple
    )
    
    # Read back to confirm
    confirmed = tm1.cubes.cells.get_value(cube, element.strip())
    return parse_value(confirmed)


def fetch_data(tm1_params: Dict[str, Any], cube: str, element1: str, element2: str) -> POVResult:
    """
    Fetch data from two elements.
    
    Args:
        tm1_params: TM1Service connection parameters
        cube: Cube name
        element1: First element coordinates
        element2: Second element coordinates
        
    Returns:
        POVResult with fetched values and calculated sum
    """
    with TM1Service(**tm1_params) as tm1:
        v1, v2 = fetch_elements(tm1, cube, element1, element2)
        
        return POVResult(
            element1=ElementData(coordinates=element1, value=v1),
            element2=ElementData(coordinates=element2, value=v2),
            sum_value=calculate_sum(v1, v2)
        )


def update_target(tm1_params: Dict[str, Any], cube: str, target_element: str, value: float) -> ElementData:
    """
    Update target element with a value.
    
    Args:
        tm1_params: TM1Service connection parameters
        cube: Cube name
        target_element: Target element coordinates
        value: Value to write
        
    Returns:
        ElementData with confirmed value
    """
    with TM1Service(**tm1_params) as tm1:
        confirmed = update_element(tm1, cube, target_element, value)
        
        return ElementData(
            coordinates=target_element,
            value=confirmed
        )


def execute_pov(tm1_params: Dict[str, Any], cube: str, element1: str, element2: str, target_element: str) -> POVResult:
    """
    Execute full POV operation: fetch, add, update.
    
    Args:
        tm1_params: TM1Service connection parameters
        cube: Cube name
        element1: First source element
        element2: Second source element
        target_element: Target element for sum
        
    Returns:
        POVResult with all data including confirmed target
    """
    with TM1Service(**tm1_params) as tm1:
        # Fetch source values
        v1, v2 = fetch_elements(tm1, cube, element1, element2)
        
        # Calculate sum
        total = calculate_sum(v1, v2)
        
        # Update target
        confirmed = update_element(tm1, cube, target_element, total)
        
        return POVResult(
            element1=ElementData(coordinates=element1, value=v1),
            element2=ElementData(coordinates=element2, value=v2),
            sum_value=total,
            target=ElementData(coordinates=target_element, value=confirmed)
        )


def test_connection(tm1_params: Dict[str, Any]) -> str:
    """
    Test TM1 connection and return server name.
    
    Args:
        tm1_params: TM1Service connection parameters
        
    Returns:
        Server name string
    """
    with TM1Service(**tm1_params) as tm1:
        return tm1.server.get_server_name()
