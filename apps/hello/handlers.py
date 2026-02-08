"""
Hello World example app for PyRest framework.

This is an EMBEDDED app - it runs within the main PyRest process
because it does NOT have a requirements.txt file.

URL prefix: /pyrest/hello (based on the app name in config.json)

Endpoints:
- GET  /pyrest/hello/                     - Hello world message
- GET  /pyrest/hello/name/{name}          - Personalized greeting (path parameter)
- GET  /pyrest/hello/query                - Example of reading URL query parameters
- POST /pyrest/hello/body                 - Example of reading request body parameters
- POST /pyrest/hello/mixed                - Example combining query params and body params
- GET  /pyrest/hello/protected            - Protected endpoint (requires auth)
- *    /pyrest/hello/args/{id}?key=val    - Unified load_args() example (RECOMMENDED)
"""

import json

from pyrest.auth import authenticated
from pyrest.handlers import BaseHandler


class HelloHandler(BaseHandler):
    """Simple hello endpoint."""

    async def get(self):
        """Return a hello message."""
        greeting = self.app_config.get("settings", {}).get("greeting", "Hello")
        self.success(data={"message": f"{greeting}, World!", "app_type": "embedded"})


class HelloNameHandler(BaseHandler):
    """Hello with name parameter."""

    async def get(self, name: str):
        """Return a personalized hello message."""
        greeting = self.app_config.get("settings", {}).get("greeting", "Hello")
        max_length = self.app_config.get("settings", {}).get("max_name_length", 100)

        if len(name) > max_length:
            self.error(f"Name too long (max {max_length} characters)", 400)
            return

        self.success(data={"message": f"{greeting}, {name}!"})


class HelloQueryParamsHandler(BaseHandler):
    """Example of reading URL query parameters."""

    async def get(self):
        """
        Example of reading query parameters from URL.

        Usage:
            GET /pyrest/hello/query?name=John&age=30&city=NewYork
        """
        # Get query parameters using get_argument (Tornado method)
        name = self.get_argument("name", default="World")
        age = self.get_argument("age", default=None)
        city = self.get_argument("city", default=None)

        # Get all query arguments as a dict
        all_params = {}
        for key in self.request.arguments:
            # get_arguments returns a list (for multi-value params)
            values = self.get_arguments(key)
            all_params[key] = values[0] if len(values) == 1 else values

        # Build response
        message = f"Hello, {name}!"
        if age:
            message += f" You are {age} years old."
        if city:
            message += f" From {city}."

        self.success(
            data={
                "message": message,
                "query_params": all_params,
                "name": name,
                "age": age,
                "city": city,
            }
        )


class HelloBodyParamsHandler(BaseHandler):
    """Example of reading parameters from request body (JSON)."""

    async def post(self):
        """
        Example of reading parameters from request body (JSON).

        Usage:
            POST /pyrest/hello/body
            Content-Type: application/json
            Body: {"name": "John", "age": 30, "city": "New York"}
        """
        try:
            # Parse JSON body
            body_data = json.loads(self.request.body.decode("utf-8"))

            # Extract parameters
            name = body_data.get("name", "World")
            age = body_data.get("age")
            city = body_data.get("city")
            email = body_data.get("email")

            # Build response
            message = f"Hello, {name}!"
            if age:
                message += f" You are {age} years old."
            if city:
                message += f" From {city}."

            self.success(
                data={
                    "message": message,
                    "received_data": body_data,
                    "name": name,
                    "age": age,
                    "city": city,
                    "email": email,
                }
            )
        except json.JSONDecodeError:
            self.error("Invalid JSON in request body", 400)
        except Exception as e:
            self.error(f"Error processing request: {e!s}", 500)

    async def put(self):
        """
        Example of reading parameters from request body (JSON) via PUT.

        Usage:
            PUT /pyrest/hello/body
            Content-Type: application/json
            Body: {"name": "Jane", "age": 25}
        """
        await self.post()  # Reuse POST logic


class HelloMixedParamsHandler(BaseHandler):
    """Example combining URL query parameters and request body parameters."""

    async def post(self):
        """
        Example combining query parameters and body parameters.

        Usage:
            POST /pyrest/hello/mixed?source=web&version=1.0
            Content-Type: application/json
            Body: {"name": "John", "age": 30}
        """
        try:
            # Read query parameters from URL
            source = self.get_argument("source", default="unknown")
            version = self.get_argument("version", default=None)

            # Read body parameters (JSON)
            body_data = {}
            if self.request.body:
                body_data = json.loads(self.request.body.decode("utf-8"))

            name = body_data.get("name", "World")
            age = body_data.get("age")

            # Combine both sources
            self.success(
                data={
                    "message": f"Hello, {name}!",
                    "query_params": {"source": source, "version": version},
                    "body_params": body_data,
                    "combined": {"name": name, "age": age, "source": source, "version": version},
                }
            )
        except json.JSONDecodeError:
            self.error("Invalid JSON in request body", 400)
        except Exception as e:
            self.error(f"Error processing request: {e!s}", 500)


class HelloProtectedHandler(BaseHandler):
    """Example of a protected endpoint requiring authentication."""

    @authenticated
    async def get(self):
        """Return a personalized hello for authenticated users."""
        user = self.current_user
        name = user.get("name") or user.get("sub", "User")
        self.success(data={"message": f"Hello, {name}! You are authenticated.", "user": user})


class HelloArgsHandler(BaseHandler):
    """
    RECOMMENDED: Unified load_args() example.

    This is the simplest way to access all request parameters.
    Use load_args() to get path params, query params, and body in one call.
    """

    async def get(self, **path_kwargs):
        """
        Example using load_args() - the easy way to read parameters.

        Usage:
            GET /pyrest/hello/args/123?name=John&limit=10

        Returns:
            args['path']  = {'id': '123'}
            args['query'] = {'name': 'John', 'limit': '10'}
            args['body']  = {}
        """
        args = self.load_args()

        self.success(
            data={
                "message": "Use load_args() for easy parameter access",
                "args": args,
                "example": {
                    "path_id": args["path"].get("id"),
                    "query_name": args["query"].get("name", "default"),
                    "query_limit": args["query"].get("limit", "100"),
                },
            }
        )

    async def post(self, **path_kwargs):
        """
        Example using load_args() with POST body.

        Usage:
            POST /pyrest/hello/args/456?source=api
            Content-Type: application/json
            Body: {"cube": "Sales", "view": "Default"}

        Returns:
            args['path']  = {'id': '456'}
            args['query'] = {'source': 'api'}
            args['body']  = {'cube': 'Sales', 'view': 'Default'}
        """
        args = self.load_args()

        # Easy access to all parameters
        item_id = args["path"].get("id")
        source = args["query"].get("source", "unknown")
        cube = args["body"].get("cube")
        view = args["body"].get("view")

        self.success(
            data={
                "message": f"Processing item {item_id} from {source}",
                "args": args,
                "parsed": {"id": item_id, "source": source, "cube": cube, "view": view},
            }
        )


def get_handlers():
    """
    Return the list of handlers for this app.

    Each tuple is (path, handler_class) or (path, handler_class, init_kwargs)
    Paths are relative to the app prefix (e.g., "/" becomes "/pyrest/hello/")
    """
    return [
        (r"/", HelloHandler),
        (r"/name/(?P<name>[^/]+)", HelloNameHandler),
        (r"/query", HelloQueryParamsHandler),
        (r"/body", HelloBodyParamsHandler),
        (r"/mixed", HelloMixedParamsHandler),
        (r"/protected", HelloProtectedHandler),
        # RECOMMENDED: Use load_args() for easy parameter access
        (r"/args/(?P<id>[^/]+)", HelloArgsHandler),
        (r"/args", HelloArgsHandler),  # Also works without path param
    ]
