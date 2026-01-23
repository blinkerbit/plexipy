"""
TM1 MDX Query Tool for PyRest framework.

This is an ISOLATED app - it runs in its own process with TM1py installed
because it has a requirements.txt file.

URL prefix: /pyrest/tm1query

Endpoints:
- GET  /pyrest/tm1query/           - Query tool UI
- GET  /pyrest/tm1query/instances  - List configured TM1 instances
- POST /pyrest/tm1query/connect    - Test connection to a TM1 instance
- POST /pyrest/tm1query/mdx        - Execute MDX query
- GET  /pyrest/tm1query/cubes      - List cubes (for a connected instance)
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import tornado.web
import tornado.ioloop

logger = logging.getLogger("tm1query")

# Thread pool for async TM1 operations (TM1py is blocking)
TM1_EXECUTOR = ThreadPoolExecutor(max_workers=16)

# TM1py import
try:
    from TM1py import TM1Service
    from TM1py.Exceptions import TM1pyException
    TM1_AVAILABLE = True
except ImportError:
    TM1_AVAILABLE = False
    TM1Service = None
    TM1pyException = Exception


class TM1QueryBaseHandler(tornado.web.RequestHandler):
    """Base handler for TM1 Query app."""
    
    # Store active connections per session
    _connections: Dict[str, TM1Service] = {}
    
    def initialize(self, app_config: Optional[Dict[str, Any]] = None, **kwargs):
        """Initialize handler with app configuration."""
        self.app_config = app_config or {}
        self.settings_config = self.app_config.get("settings", {})
        self.tm1_instances = self.app_config.get("tm1_instances", {})
    
    def set_default_headers(self):
        """Set default headers including CORS."""
        self.set_header("Content-Type", "application/json")
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")
    
    def options(self, *args, **kwargs):
        """Handle preflight CORS requests."""
        self.set_status(204)
        self.finish()
    
    def get_json_body(self) -> Dict[str, Any]:
        """Parse JSON request body."""
        try:
            return json.loads(self.request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    
    def success(self, data: Any = None, message: str = "Success"):
        """Send success response."""
        response = {"success": True, "message": message}
        if data is not None:
            response["data"] = data
        self.write(response)
    
    def error(self, message: str, status_code: int = 400):
        """Send error response."""
        self.set_status(status_code)
        self.write({"success": False, "error": message})
    
    async def run_tm1_async(self, func, *args, **kwargs):
        """
        Run a blocking TM1 operation asynchronously in a thread pool.
        
        Usage:
            result = await self.run_tm1_async(some_blocking_func, arg1, arg2)
        """
        loop = tornado.ioloop.IOLoop.current()
        return await loop.run_in_executor(TM1_EXECUTOR, partial(func, *args, **kwargs))
    
    def _resolve_env(self, value: Any) -> Any:
        """Resolve environment variables in config values."""
        if not isinstance(value, str):
            return value
        if value.startswith("${") and "}" in value:
            start = value.find("${")
            end = value.find("}")
            env_expr = value[start + 2:end]
            if ":-" in env_expr:
                var_name, default = env_expr.split(":-", 1)
                result = os.environ.get(var_name.strip(), default)
            else:
                result = os.environ.get(env_expr.strip(), "")
            return value[:start] + result + value[end + 1:]
        return value
    
    def _build_connection_params(self, instance_config: Dict[str, Any]) -> Dict[str, Any]:
        """Build TM1Service connection parameters from config."""
        conn_type = self._resolve_env(instance_config.get("connection_type", "onprem"))
        
        if conn_type.lower() in ("cloud", "paas"):
            # Cloud connection
            region = self._resolve_env(instance_config.get("cloud_region", ""))
            tenant = self._resolve_env(instance_config.get("cloud_tenant", ""))
            return {
                "base_url": f"https://{region}.planninganalytics.ibmcloud.com/tm1/api/{tenant}/v1",
                "ipm_url": f"https://{region}.planninganalytics.ibmcloud.com",
                "api_key": self._resolve_env(instance_config.get("cloud_api_key", "")),
                "tenant": tenant,
                "ssl": True,
            }
        else:
            # On-premise connection
            params = {
                "address": self._resolve_env(instance_config.get("server", "localhost")),
                "port": int(self._resolve_env(instance_config.get("port", 8010))),
                "ssl": self._resolve_env(instance_config.get("ssl", True)),
                "user": self._resolve_env(instance_config.get("user", "")),
                "password": self._resolve_env(instance_config.get("password", "")),
            }
            # Handle boolean ssl
            if isinstance(params["ssl"], str):
                params["ssl"] = params["ssl"].lower() in ("true", "1", "yes")
            return params


class TM1QueryUIHandler(TM1QueryBaseHandler):
    """Serve the MDX Query UI."""
    
    def set_default_headers(self):
        """Set HTML content type."""
        self.set_header("Content-Type", "text/html")
    
    async def get(self):
        """Serve the query tool HTML page."""
        html_path = Path(__file__).parent / "static" / "index.html"
        if html_path.exists():
            self.write(html_path.read_text(encoding="utf-8"))
        else:
            # Inline HTML fallback
            self.write(self._get_inline_html())
    
    def _get_inline_html(self) -> str:
        """Return inline HTML if static file not found."""
        return """<!DOCTYPE html>
<html><head><title>TM1 MDX Query</title></head>
<body><h1>TM1 MDX Query Tool</h1>
<p>Static files not found. Please check app deployment.</p></body></html>"""


class TM1InstancesHandler(TM1QueryBaseHandler):
    """List configured TM1 instances."""
    
    async def get(self):
        """Return list of configured TM1 instances."""
        if not TM1_AVAILABLE:
            self.error("TM1py is not installed", 500)
            return
        
        instances = []
        for name, config in self.tm1_instances.items():
            conn_type = self._resolve_env(config.get("connection_type", "onprem"))
            instance_info = {
                "name": name,
                "description": config.get("description", ""),
                "connection_type": conn_type,
            }
            if conn_type.lower() in ("cloud", "paas"):
                instance_info["cloud_region"] = self._resolve_env(config.get("cloud_region", ""))
            else:
                instance_info["server"] = self._resolve_env(config.get("server", "localhost"))
                instance_info["port"] = int(self._resolve_env(config.get("port", 8010)))
            instances.append(instance_info)
        
        self.success(data={"instances": instances, "tm1py_available": TM1_AVAILABLE})


class TM1ConnectHandler(TM1QueryBaseHandler):
    """Test connection to a TM1 instance."""
    
    async def post(self):
        """Test connection with provided or configured credentials."""
        if not TM1_AVAILABLE:
            self.error("TM1py is not installed", 500)
            return
        
        body = self.get_json_body()
        instance_name = body.get("instance", "default")
        
        # Check if using custom connection params or configured instance
        if body.get("custom"):
            params = {
                "address": body.get("server", "localhost"),
                "port": int(body.get("port", 8010)),
                "ssl": body.get("ssl", True),
                "user": body.get("user", ""),
                "password": body.get("password", ""),
            }
        else:
            # Use configured instance
            if instance_name not in self.tm1_instances:
                self.error(f"Instance '{instance_name}' not configured", 404)
                return
            params = self._build_connection_params(self.tm1_instances[instance_name])
        
        def _connect_sync(tm1_params):
            """Blocking TM1 connection test."""
            with TM1Service(**tm1_params) as tm1:
                return tm1.server.get_server_name()
        
        try:
            server_name = await self.run_tm1_async(_connect_sync, params)
            self.success(data={
                "connected": True,
                "server_name": server_name,
                "instance": instance_name
            }, message=f"Connected to {server_name}")
        except Exception as e:
            self.error(f"Connection failed: {str(e)}", 400)


class TM1MDXHandler(TM1QueryBaseHandler):
    """Execute MDX queries."""
    
    async def post(self):
        """Execute an MDX query and return results."""
        if not TM1_AVAILABLE:
            self.error("TM1py is not installed", 500)
            return
        
        body = self.get_json_body()
        mdx = body.get("mdx", "").strip()
        instance_name = body.get("instance", "default")
        max_rows = body.get("max_rows", self.settings_config.get("max_rows", 10000))
        
        if not mdx:
            self.error("MDX query is required", 400)
            return
        
        # Build connection params
        if body.get("custom"):
            params = {
                "address": body.get("server", "localhost"),
                "port": int(body.get("port", 8010)),
                "ssl": body.get("ssl", True),
                "user": body.get("user", ""),
                "password": body.get("password", ""),
            }
        else:
            if instance_name not in self.tm1_instances:
                self.error(f"Instance '{instance_name}' not configured", 404)
                return
            params = self._build_connection_params(self.tm1_instances[instance_name])
        
        def _execute_mdx_sync(tm1_params, mdx_query, limit):
            """Blocking MDX execution."""
            with TM1Service(**tm1_params) as tm1:
                cellset = tm1.cubes.cells.execute_mdx(mdx_query)
                
                rows = []
                row_count = 0
                
                for cell_key, cell_value in cellset.items():
                    if row_count >= limit:
                        break
                    
                    row = {
                        "coordinates": list(cell_key) if isinstance(cell_key, tuple) else [cell_key],
                        "value": cell_value
                    }
                    rows.append(row)
                    row_count += 1
                
                return rows, row_count >= limit
        
        try:
            rows, truncated = await self.run_tm1_async(_execute_mdx_sync, params, mdx, max_rows)
            
            self.success(data={
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
                "max_rows": max_rows
            }, message=f"Query returned {len(rows)} rows")
                
        except TM1pyException as e:
            self.error(f"TM1 Error: {str(e)}", 400)
        except Exception as e:
            logger.exception("MDX execution error")
            self.error(f"Query failed: {str(e)}", 500)


class TM1CubesHandler(TM1QueryBaseHandler):
    """List cubes from a TM1 instance."""
    
    async def get(self):
        """Get list of cubes."""
        if not TM1_AVAILABLE:
            self.error("TM1py is not installed", 500)
            return
        
        instance_name = self.get_argument("instance", "default")
        
        if instance_name not in self.tm1_instances:
            self.error(f"Instance '{instance_name}' not configured", 404)
            return
        
        params = self._build_connection_params(self.tm1_instances[instance_name])
        
        def _get_cubes_sync(tm1_params):
            """Blocking cube list operation."""
            with TM1Service(**tm1_params) as tm1:
                return tm1.cubes.get_all_names()
        
        try:
            cubes = await self.run_tm1_async(_get_cubes_sync, params)
            self.success(data={"cubes": cubes, "count": len(cubes)})
        except Exception as e:
            self.error(f"Failed to get cubes: {str(e)}", 400)


def get_handlers():
    """Return the list of handlers for this app."""
    return [
        (r"/", TM1QueryUIHandler),
        (r"/instances", TM1InstancesHandler),
        (r"/connect", TM1ConnectHandler),
        (r"/mdx", TM1MDXHandler),
        (r"/cubes", TM1CubesHandler),
    ]
