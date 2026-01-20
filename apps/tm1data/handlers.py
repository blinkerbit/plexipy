"""
TM1 Data API - Multi-instance TM1 connector for PyRest framework.

This is an ISOLATED app - it runs as a separate process with its own
virtual environment because it HAS a requirements.txt file.

Supports multiple TM1 instances - both TM1 Cloud (IBM Planning Analytics) 
and TM1 On-Premise connections configured via config.json.

URL prefix: /pyrest/tm1data (based on the app name in config.json)

Endpoints:
- GET  /pyrest/tm1data/                     - API info and configured instances
- GET  /pyrest/tm1data/instances            - List all configured TM1 instances
- GET  /pyrest/tm1data/instance/{name}/cubes          - List cubes for instance
- GET  /pyrest/tm1data/instance/{name}/cube/{cube}/dimensions - Get cube dimensions
- POST /pyrest/tm1data/instance/{name}/query          - Execute MDX query
- GET  /pyrest/tm1data/instance/{name}/status         - Check connection status
- POST /pyrest/tm1data/instance/{name}/reconnect      - Force reconnection
"""

import os
import json
import time
from typing import Dict, Any, Optional, List

# Import TM1 utilities from pyrest.utils
try:
    from pyrest.utils.tm1 import TM1ConnectionManager, TM1InstanceConfig, is_tm1_available
    from pyrest.utils.logging import setup_app_logging, get_app_logger, AppLogger
    TM1_AVAILABLE = is_tm1_available()
except ImportError:
    # Fallback when pyrest is not in path (isolated execution)
    TM1_AVAILABLE = False
    TM1ConnectionManager = None
    TM1InstanceConfig = None
    
    # Try direct TM1py import
    try:
        from TM1py import TM1Service
        TM1_AVAILABLE = True
    except ImportError:
        pass

# Import base handler and authentication
try:
    from pyrest.handlers import BaseHandler
    from pyrest.auth import authenticated
except ImportError:
    # Fallback for isolated execution
    import tornado.web
    
    class BaseHandler(tornado.web.RequestHandler):
        def initialize(self, app_config=None, **kwargs):
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
            return await func(self, *args, **kwargs)
        return wrapper

# App-specific logger
_app_logger: Optional[AppLogger] = None


def _get_logger() -> Optional[AppLogger]:
    """Get or create the app logger."""
    global _app_logger
    if _app_logger is None:
        try:
            _app_logger = setup_app_logging(
                app_name="tm1data",
                log_dir="logs",
                log_level="INFO",
                console_output=False
            )
        except Exception:
            pass
    return _app_logger


class TM1BaseHandler(BaseHandler):
    """Base handler with TM1 connection manager initialization and logging."""
    
    def initialize(self, app_config=None, **kwargs):
        super().initialize(app_config=app_config, **kwargs)
        self._start_time = time.time()
        
        # Initialize logger
        self.logger = _get_logger()
        
        # Initialize the connection manager with app config
        if app_config and TM1ConnectionManager and not TM1ConnectionManager._initialized:
            app_logger_instance = self.logger.get_logger() if self.logger else None
            TM1ConnectionManager.initialize(app_config, app_logger_instance)
    
    def on_finish(self):
        """Log request completion."""
        if self.logger:
            duration_ms = (time.time() - self._start_time) * 1000
            self.logger.log_request(
                method=self.request.method,
                path=self.request.path,
                status_code=self.get_status(),
                duration_ms=duration_ms,
            )
    
    def get_instance_name(self, instance_name: str = None) -> str:
        """Get the instance name from parameter or query string."""
        if instance_name:
            return instance_name
        if TM1ConnectionManager:
            return self.get_argument("instance", TM1ConnectionManager.get_default_instance())
        return self.get_argument("instance", "default")
    
    def log_tm1_operation(self, operation: str, instance: str, success: bool, 
                          duration_ms: float = None, details: Dict = None):
        """Log a TM1 operation."""
        if self.logger:
            self.logger.log_tm1_operation(operation, instance, success, duration_ms, details)


class TM1InfoHandler(TM1BaseHandler):
    """TM1 API information endpoint."""
    
    async def get(self):
        """Return API information and configured instances."""
        if not TM1ConnectionManager:
            self.success(data={
                "name": "TM1 Data API",
                "version": "2.0.0",
                "tm1py_available": TM1_AVAILABLE,
                "error": "TM1ConnectionManager not available"
            })
            return
        
        instances = TM1ConnectionManager.get_all_instances()
        instances_info = [inst.to_dict() for inst in instances.values()]
        
        self.success(data={
            "name": "TM1 Data API",
            "version": "2.0.0",
            "tm1py_available": TM1_AVAILABLE,
            "app_type": "isolated",
            "default_instance": TM1ConnectionManager.get_default_instance(),
            "instances": instances_info,
            "instance_count": len(instances),
            "endpoints": [
                "GET  /instances - List all configured TM1 instances",
                "GET  /instance/{name}/cubes - List cubes for instance",
                "GET  /instance/{name}/cube/{cube}/dimensions - Get cube dimensions",
                "POST /instance/{name}/query - Execute MDX query",
                "GET  /instance/{name}/status - Check connection status",
                "POST /instance/{name}/reconnect - Force reconnection"
            ]
        })


class TM1InstancesHandler(TM1BaseHandler):
    """List all configured TM1 instances."""
    
    async def get(self):
        """Return list of all configured TM1 instances."""
        if not TM1ConnectionManager:
            self.error("TM1ConnectionManager not available", 503)
            return
        
        instances = TM1ConnectionManager.get_all_instances()
        instances_info = []
        
        for name, inst in instances.items():
            info = inst.to_dict()
            info["connected"] = TM1ConnectionManager.is_connected(name)
            instances_info.append(info)
        
        self.success(data={
            "instances": instances_info,
            "count": len(instances_info),
            "default_instance": TM1ConnectionManager.get_default_instance()
        })


class TM1InstanceCubesHandler(TM1BaseHandler):
    """List TM1 cubes for a specific instance."""
    
    @authenticated
    async def get(self, instance_name: str):
        """Return list of TM1 cubes for the specified instance."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        if not TM1ConnectionManager:
            self.error("TM1ConnectionManager not available", 503)
            return
        
        # Validate instance exists
        if not TM1ConnectionManager.has_instance(instance_name):
            self.error(f"TM1 instance '{instance_name}' not found", 404)
            return
        
        start_time = time.time()
        try:
            tm1 = TM1ConnectionManager.get_connection(instance_name)
            if not tm1:
                self.error(f"Could not connect to TM1 instance '{instance_name}'", 503)
                self.log_tm1_operation("get_cubes", instance_name, False)
                return
            
            cubes = tm1.cubes.get_all_names()
            duration_ms = (time.time() - start_time) * 1000
            
            self.log_tm1_operation("get_cubes", instance_name, True, duration_ms, 
                                   {"cube_count": len(cubes)})
            
            self.success(data={
                "instance": instance_name,
                "cubes": cubes,
                "count": len(cubes)
            })
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.log_tm1_operation("get_cubes", instance_name, False, duration_ms,
                                   {"error": str(e)})
            self.error(f"TM1 error on instance '{instance_name}': {str(e)}", 500)


class TM1InstanceCubeDimensionsHandler(TM1BaseHandler):
    """Get dimensions for a specific cube on a specific instance."""
    
    @authenticated
    async def get(self, instance_name: str, cube_name: str):
        """Return dimensions of a cube for the specified instance."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        if not TM1ConnectionManager:
            self.error("TM1ConnectionManager not available", 503)
            return
        
        # Validate instance exists
        if not TM1ConnectionManager.has_instance(instance_name):
            self.error(f"TM1 instance '{instance_name}' not found", 404)
            return
        
        start_time = time.time()
        try:
            tm1 = TM1ConnectionManager.get_connection(instance_name)
            if not tm1:
                self.error(f"Could not connect to TM1 instance '{instance_name}'", 503)
                return
            
            cube = tm1.cubes.get(cube_name)
            duration_ms = (time.time() - start_time) * 1000
            
            self.log_tm1_operation("get_cube_dimensions", instance_name, True, duration_ms,
                                   {"cube": cube_name})
            
            self.success(data={
                "instance": instance_name,
                "cube": cube_name,
                "dimensions": cube.dimensions
            })
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.log_tm1_operation("get_cube_dimensions", instance_name, False, duration_ms,
                                   {"cube": cube_name, "error": str(e)})
            self.error(f"TM1 error on instance '{instance_name}': {str(e)}", 500)


class TM1InstanceQueryHandler(TM1BaseHandler):
    """Execute MDX queries on a specific instance."""
    
    @authenticated
    async def post(self, instance_name: str):
        """Execute an MDX query on the specified instance."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        if not TM1ConnectionManager:
            self.error("TM1ConnectionManager not available", 503)
            return
        
        # Validate instance exists
        if not TM1ConnectionManager.has_instance(instance_name):
            self.error(f"TM1 instance '{instance_name}' not found", 404)
            return
        
        body = self.get_json_body()
        mdx = body.get("mdx")
        
        if not mdx:
            self.error("MDX query is required", 400)
            return
        
        start_time = time.time()
        try:
            tm1 = TM1ConnectionManager.get_connection(instance_name)
            if not tm1:
                self.error(f"Could not connect to TM1 instance '{instance_name}'", 503)
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
            
            duration_ms = (time.time() - start_time) * 1000
            self.log_tm1_operation("execute_mdx", instance_name, True, duration_ms,
                                   {"result_count": len(result)})
            
            self.success(data={
                "instance": instance_name,
                "query": mdx,
                "results": result,
                "count": len(result)
            })
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.log_tm1_operation("execute_mdx", instance_name, False, duration_ms,
                                   {"error": str(e)})
            self.error(f"TM1 query error on instance '{instance_name}': {str(e)}", 500)


class TM1InstanceStatusHandler(TM1BaseHandler):
    """Check TM1 connection status for a specific instance."""
    
    @authenticated
    async def get(self, instance_name: str):
        """Return TM1 connection status for the specified instance."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        if not TM1ConnectionManager:
            self.error("TM1ConnectionManager not available", 503)
            return
        
        # Use the built-in status method
        status = TM1ConnectionManager.get_connection_status(instance_name)
        
        if not status.get("configured"):
            self.error(f"TM1 instance '{instance_name}' not found", 404)
            return
        
        self.success(data=status)


class TM1InstanceReconnectHandler(TM1BaseHandler):
    """Force reconnection to a specific TM1 instance."""
    
    @authenticated
    async def post(self, instance_name: str):
        """Reset and reconnect to the specified TM1 instance."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        if not TM1ConnectionManager:
            self.error("TM1ConnectionManager not available", 503)
            return
        
        # Validate instance exists
        if not TM1ConnectionManager.has_instance(instance_name):
            self.error(f"TM1 instance '{instance_name}' not found", 404)
            return
        
        start_time = time.time()
        try:
            # Reset the connection
            TM1ConnectionManager.reset_connection(instance_name)
            
            # Attempt to reconnect
            tm1 = TM1ConnectionManager.get_connection(instance_name)
            
            duration_ms = (time.time() - start_time) * 1000
            
            if tm1:
                server_name = tm1.server.get_server_name()
                self.log_tm1_operation("reconnect", instance_name, True, duration_ms)
                self.success(data={
                    "instance": instance_name,
                    "reconnected": True,
                    "server_name": server_name
                })
            else:
                self.log_tm1_operation("reconnect", instance_name, False, duration_ms)
                self.error(f"Failed to reconnect to TM1 instance '{instance_name}'", 503)
                
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.log_tm1_operation("reconnect", instance_name, False, duration_ms,
                                   {"error": str(e)})
            self.error(f"Reconnection error for instance '{instance_name}': {str(e)}", 500)


# Legacy handlers for backward compatibility (use default instance)
class TM1CubesHandler(TM1BaseHandler):
    """List TM1 cubes (uses default instance)."""
    
    @authenticated
    async def get(self):
        """Return list of TM1 cubes from default instance."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        if not TM1ConnectionManager:
            self.error("TM1ConnectionManager not available", 503)
            return
        
        instance_name = self.get_instance_name()
        
        start_time = time.time()
        try:
            tm1 = TM1ConnectionManager.get_connection(instance_name)
            if not tm1:
                self.error(f"Could not connect to TM1 instance '{instance_name}'", 503)
                return
            
            cubes = tm1.cubes.get_all_names()
            duration_ms = (time.time() - start_time) * 1000
            
            self.log_tm1_operation("get_cubes", instance_name, True, duration_ms,
                                   {"cube_count": len(cubes)})
            
            self.success(data={
                "instance": instance_name,
                "cubes": cubes,
                "count": len(cubes)
            })
            
        except Exception as e:
            self.error(f"TM1 error: {str(e)}", 500)


class TM1QueryHandler(TM1BaseHandler):
    """Execute MDX queries (uses default instance)."""
    
    @authenticated
    async def post(self):
        """Execute an MDX query on default instance."""
        if not TM1_AVAILABLE:
            self.error("TM1py not available", 503)
            return
        
        if not TM1ConnectionManager:
            self.error("TM1ConnectionManager not available", 503)
            return
        
        instance_name = self.get_instance_name()
        body = self.get_json_body()
        mdx = body.get("mdx")
        
        # Allow specifying instance in request body
        if "instance" in body:
            instance_name = body["instance"]
        
        if not mdx:
            self.error("MDX query is required", 400)
            return
        
        start_time = time.time()
        try:
            tm1 = TM1ConnectionManager.get_connection(instance_name)
            if not tm1:
                self.error(f"Could not connect to TM1 instance '{instance_name}'", 503)
                return
            
            cellset = tm1.cells.execute_mdx(mdx)
            
            result = []
            for cell in cellset:
                result.append({
                    "coordinates": cell.get("Ordinal"),
                    "value": cell.get("Value")
                })
            
            duration_ms = (time.time() - start_time) * 1000
            self.log_tm1_operation("execute_mdx", instance_name, True, duration_ms,
                                   {"result_count": len(result)})
            
            self.success(data={
                "instance": instance_name,
                "query": mdx,
                "results": result,
                "count": len(result)
            })
            
        except Exception as e:
            self.error(f"TM1 query error: {str(e)}", 500)


def get_handlers():
    """Return the list of handlers for this app."""
    return [
        # Main info endpoint
        (r"/", TM1InfoHandler),
        
        # List all instances
        (r"/instances", TM1InstancesHandler),
        
        # Instance-specific endpoints
        (r"/instance/(?P<instance_name>[^/]+)/cubes", TM1InstanceCubesHandler),
        (r"/instance/(?P<instance_name>[^/]+)/cube/(?P<cube_name>[^/]+)/dimensions", TM1InstanceCubeDimensionsHandler),
        (r"/instance/(?P<instance_name>[^/]+)/query", TM1InstanceQueryHandler),
        (r"/instance/(?P<instance_name>[^/]+)/status", TM1InstanceStatusHandler),
        (r"/instance/(?P<instance_name>[^/]+)/reconnect", TM1InstanceReconnectHandler),
        
        # Legacy endpoints (use default instance or ?instance= query param)
        (r"/cubes", TM1CubesHandler),
        (r"/query", TM1QueryHandler),
    ]
