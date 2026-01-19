"""
Hello World example app for PyRest framework.

This is an EMBEDDED app - it runs within the main PyRest process
because it does NOT have a requirements.txt file.

URL prefix: /pyrest/hello (based on the app name in config.json)

Endpoints:
- GET /pyrest/hello/ - Hello world message
- GET /pyrest/hello/name/{name} - Personalized greeting
- GET /pyrest/hello/protected - Protected endpoint (requires auth)
"""

from pyrest.handlers import BaseHandler
from pyrest.auth import authenticated
from pyrest.decorators import RestHandler


class HelloHandler(BaseHandler):
    """Simple hello endpoint."""
    
    async def get(self):
        """Return a hello message."""
        greeting = self.app_config.get("settings", {}).get("greeting", "Hello")
        self.success(data={
            "message": f"{greeting}, World!",
            "app_type": "embedded"
        })


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


class HelloProtectedHandler(BaseHandler):
    """Example of a protected endpoint requiring authentication."""
    
    @authenticated
    async def get(self):
        """Return a personalized hello for authenticated users."""
        user = self.current_user
        name = user.get("name") or user.get("sub", "User")
        self.success(data={
            "message": f"Hello, {name}! You are authenticated.",
            "user": user
        })


def get_handlers():
    """
    Return the list of handlers for this app.
    
    Each tuple is (path, handler_class) or (path, handler_class, init_kwargs)
    Paths are relative to the app prefix (e.g., "/" becomes "/pyrest/hello/")
    """
    return [
        (r"/", HelloHandler),
        (r"/name/(?P<name>[^/]+)", HelloNameHandler),
        (r"/protected", HelloProtectedHandler),
    ]
