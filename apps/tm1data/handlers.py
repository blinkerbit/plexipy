"""
TM1 Data API - Example isolated app for PyRest framework.

This is an ISOLATED app - it runs as a separate process with its own
virtual environment because it HAS a requirements.txt file.

This demonstrates how to build TM1py-based APIs on PyRest.

URL prefix: /pyrest/tm1data (based on the app name in config.json)

Endpoints:
- GET /pyrest/tm1data/         - API info
- GET /pyrest/tm1data/cubes    - List TM1 cubes
- GET /pyrest/tm1data/cube/{name}/dimensions - Get cube dimensions
- POST /pyrest/tm1data/query   - Execute MDX query
"""

import json
from typing import Dict, Any, Optional

# Note: In isolated apps, we use the IsolatedBaseHandler 
# or import from pyrest if available
try:
    from pyrest.handlers import BaseHandler
    from pyrest.auth import authenticated
except ImportError:
    # Fallback for isolated execution
    import tornado.web
    
    class BaseHandler(tornado.web.RequestHandler):
        def initialize(self, app_config=None):
            self.app_config = app_config or {}
            self._current_user = None
        
        def set_default_headers(self):
            self.set_header("Content-Type", "application/json")
            origin = self.request.headers.get("Origin", "*")
            self.set_header("Access-Control-Allow-Origin", origin)
            self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        
        def options(self, *args, **kwargs):
            self.set_status(204)
            self.finish()
        
        @property
        def current_user(self):
            return self._current_user
        
        def get_json_body(self):
            try:
                return json.loads(self.request.body.decode())
            except:
                return {}
        
        def success(self, data=None, message="Success", status_code=200):
            self.set_status(status_code)
            resp = {"success": True, "message": message}
            if data:
                resp["data"] = data
            self.write(resp)
        
        def error(self, message, status_code=400):
            self.set_status(status_code)
            self.write({"success": False, "error": message})
    
    def authenticated(func):
        import functools
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            auth_header = self.request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                self.set_status(401)
                self.write({"error": "Authorization required"})
                return
            # Basic token validation would go here
            return await func(self, *args, **kwargs)
        return wrapper


# TM1py import (available when running in isolated venv)
try:
    from TM1py import TM1Service
    TM1_AVAILABLE = True
except ImportError:
    TM1_AVAILABLE = False
    TM1Service = None


class TM1Connection:
    """Manages TM1 server connection."""
    
    _instance = None
    
    @classmethod
    def get_connection(cls, config: Dict[str, Any]) -> Optional["TM1Service"]:
        """Get or create TM1 connection."""
        if not TM1_AVAILABLE:
            return None
        
        if cls._instance is None:
            try:
                settings = config.get("settings", {})
                cls._instance = TM1Service(
                    address=settings.get("tm1_server", "localhost"),
                    port=settings.get("tm1_port", 8010),
                    ssl=settings.get("tm1_ssl", True),
                    # Note: In production, get credentials from secure storage
                    user=settings.get("tm1_user", ""),
                    password=settings.get("tm1_password", "")
                )
            except Exception as e:
                print(f"TM1 connection error: {e}")
                return None
        
        return cls._instance


class TM1InfoHandler(BaseHandler):
    """TM1 API information endpoint."""
    
    async def get(self):
        """Return API information."""
        self.success(data={
            "name": "TM1 Data API",
            "version": "1.0.0",
            "tm1py_available": TM1_AVAILABLE,
            "app_type": "isolated",
            "endpoints": [
                "GET /cubes - List all cubes",
                "GET /cube/{name}/dimensions - Get cube dimensions",
                "POST /query - Execute MDX query"
            ]
        })


class TM1CubesHandler(BaseHandler):
    """List TM1 cubes."""
    
    @authenticated
    async def get(self):
        """Return list of TM1 cubes."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        try:
            tm1 = TM1Connection.get_connection(self.app_config)
            if not tm1:
                self.error("TM1 connection not available", 503)
                return
            
            cubes = tm1.cubes.get_all_names()
            self.success(data={"cubes": cubes, "count": len(cubes)})
            
        except Exception as e:
            self.error(f"TM1 error: {str(e)}", 500)


class TM1CubeDimensionsHandler(BaseHandler):
    """Get dimensions for a specific cube."""
    
    @authenticated
    async def get(self, cube_name: str):
        """Return dimensions of a cube."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        try:
            tm1 = TM1Connection.get_connection(self.app_config)
            if not tm1:
                self.error("TM1 connection not available", 503)
                return
            
            cube = tm1.cubes.get(cube_name)
            self.success(data={
                "cube": cube_name,
                "dimensions": cube.dimensions
            })
            
        except Exception as e:
            self.error(f"TM1 error: {str(e)}", 500)


class TM1QueryHandler(BaseHandler):
    """Execute MDX queries."""
    
    @authenticated
    async def post(self):
        """Execute an MDX query and return results."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        body = self.get_json_body()
        mdx = body.get("mdx")
        
        if not mdx:
            self.error("MDX query is required", 400)
            return
        
        try:
            tm1 = TM1Connection.get_connection(self.app_config)
            if not tm1:
                self.error("TM1 connection not available", 503)
                return
            
            # Execute MDX and get cellset
            cellset = tm1.cells.execute_mdx(mdx)
            
            # Convert to simple format
            result = []
            for cell in cellset:
                result.append({
                    "coordinates": cell.get("Ordinal"),
                    "value": cell.get("Value")
                })
            
            self.success(data={
                "query": mdx,
                "results": result,
                "count": len(result)
            })
            
        except Exception as e:
            self.error(f"TM1 query error: {str(e)}", 500)


def get_handlers():
    """Return the list of handlers for this app."""
    return [
        (r"/", TM1InfoHandler),
        (r"/cubes", TM1CubesHandler),
        (r"/cube/(?P<cube_name>[^/]+)/dimensions", TM1CubeDimensionsHandler),
        (r"/query", TM1QueryHandler),
    ]
