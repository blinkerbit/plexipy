# PyRest Simple Guide

A quick guide for TM1 developers to create REST APIs without deep Python knowledge.

## Quick Start

### 1. Create a Simple Handler

```python
from pyrest.simple_handler import SimpleHandler

class HelloHandler(SimpleHandler):
    async def get(self):
        self.ok({"message": "Hello World!"})
```

### 2. Accept Input Data

```python
class GreetHandler(SimpleHandler):
    async def post(self):
        # Get JSON body
        data = self.get_json_body()
        name = data.get("name", "Guest")
        
        self.ok({"greeting": f"Hello, {name}!"})
```

### 3. Validate Required Fields

```python
class FetchHandler(SimpleHandler):
    async def post(self):
        # Validate required fields automatically
        data = self.get_data(required=["cube", "element1", "element2"])
        if not data:
            return  # Error already sent to client
        
        # Use the data
        cube = data["cube"]
        element1 = data["element1"]
        
        self.ok({"cube": cube, "element": element1})
```

### 4. Use Pydantic for Better Validation

```python
from pyrest.simple_handler import SimpleHandler
from pyrest.validation import RequestModel, field

# Define your input structure
class FetchInput(RequestModel):
    cube: str = field(description="Cube name")
    element1: str = field(description="First element")
    element2: str = field(description="Second element")

class FetchHandler(SimpleHandler):
    async def post(self):
        # Validate with Pydantic model
        data = self.get_data(model=FetchInput)
        if not data:
            return  # Validation error sent automatically
        
        # Access validated data with autocomplete!
        self.ok({
            "cube": data.cube,
            "element1": data.element1,
            "element2": data.element2
        })
```

## Response Methods

```python
class MyHandler(SimpleHandler):
    async def post(self):
        # Success response
        self.ok({"value": 123})
        self.ok({"items": [1,2,3]}, message="Found 3 items")
        
        # Error responses
        self.error("Something went wrong")
        self.error("Invalid cube name", status=400)
        self.not_found("Cube not found")
        self.unauthorized("Please login")
        self.server_error("Database connection failed")
```

## Running Async Operations

For operations that might take time (TM1, database, file I/O):

```python
class SlowHandler(SimpleHandler):
    async def post(self):
        data = self.get_data(required=["cube"])
        if not data:
            return
        
        # Run blocking operation asynchronously
        result = await self.run_async(slow_function, data["cube"])
        self.ok(result)
```

With automatic error handling:

```python
class SafeHandler(SimpleHandler):
    async def post(self):
        data = self.get_data(required=["cube"])
        if not data:
            return
        
        # Automatically catches errors and sends error response
        result = await self.try_async(
            risky_function,
            data["cube"],
            error_message="Failed to process cube"
        )
        
        if result is None:
            return  # Error already sent
        
        self.ok(result)
```

## Complete Example

```python
"""
My TM1 App - handlers.py
"""
from pyrest.simple_handler import SimpleHandler
from pyrest.validation import RequestModel, field
from typing import Optional

# Define input models
class ConnectInput(RequestModel):
    base_url: str = field(description="TM1 server URL")
    user: str = field(description="Username")
    password: str = field(description="Password")

class QueryInput(ConnectInput):
    cube: str = field(description="Cube name")
    mdx: str = field(description="MDX query")
    max_rows: int = field(default=1000, description="Max rows", ge=1, le=10000)

# Handlers
class InfoHandler(SimpleHandler):
    async def get(self):
        self.ok({
            "app": "My TM1 App",
            "version": "1.0.0"
        })

class QueryHandler(SimpleHandler):
    async def post(self):
        # Validate input
        data = self.get_data(model=QueryInput)
        if not data:
            return
        
        # Run query
        result = await self.try_async(
            run_mdx_query,
            data.base_url, data.user, data.password,
            data.cube, data.mdx, data.max_rows,
            error_message="Query failed"
        )
        
        if result is None:
            return
        
        self.ok(result)

# Register handlers
def get_handlers():
    return [
        (r"/", InfoHandler),
        (r"/query", QueryHandler),
    ]
```

## Validation Field Options

```python
from pyrest.validation import RequestModel, field

class MyInput(RequestModel):
    # Required string
    name: str = field(description="User name")
    
    # Optional with default
    age: int = field(default=0, description="Age")
    
    # String length validation
    code: str = field(min_length=3, max_length=10, description="Code")
    
    # Number range validation
    quantity: int = field(ge=0, le=100, description="0-100")
    price: float = field(gt=0, description="Must be positive")
    
    # Pattern validation (regex)
    email: str = field(pattern=r".*@.*\..*", description="Email")
```

## Error Messages

When validation fails, clients receive clear error messages:

```json
{
  "success": false,
  "error": "Validation failed",
  "details": [
    {
      "field": "cube",
      "message": "Field required",
      "type": "missing"
    },
    {
      "field": "max_rows",
      "message": "Input should be greater than or equal to 1",
      "type": "greater_than_equal"
    }
  ]
}
```

## File Structure

```
apps/
└── myapp/
    ├── __init__.py      # Empty file
    ├── config.json      # App configuration
    ├── handlers.py      # Your handlers
    ├── requirements.txt # Dependencies (optional)
    └── static/          # Static files (optional)
        └── index.html
```

## config.json

```json
{
  "name": "myapp",
  "version": "1.0.0",
  "description": "My TM1 App",
  "enabled": true
}
```

## Tips for Non-Python Developers

1. **Indentation matters** - Use 4 spaces (not tabs)
2. **Colons end statements** - `async def get(self):`
3. **`self`** - Always the first parameter in class methods
4. **`await`** - Required before `self.run_async()` and `self.try_async()`
5. **`return`** - Use `return` after error responses to stop execution
6. **Type hints** - `name: str` means name should be a string (helps with autocomplete)

## Common Patterns

### Check if something exists
```python
if not data:
    return  # Stop here
```

### Get value with default
```python
value = data.get("key", "default_value")
```

### Format string
```python
message = f"Hello, {name}!"  # f-string
```

### List/dict access
```python
first_item = items[0]
value = my_dict["key"]
```
