"""
POV (Point of View) App - TM1 Cube Value Operations

Connects to TM1 (On-Premise, Cloud, or v12 with Azure AD), fetches values 
from two elements, adds them, and updates a third element with the result.

Supported Connection Types:
- onprem: Traditional TM1 on-premise with basic/CAM auth
- cloud: IBM Planning Analytics Cloud with API key
- azure_ad: TM1 v12 Cloud with Azure AD authentication

Endpoints:
- GET  /pyrest/pov/              - API info
- GET  /pyrest/pov/ui            - Web UI
- POST /pyrest/pov/connect       - Test TM1 connection
- POST /pyrest/pov/fetch         - Fetch values from two elements
- POST /pyrest/pov/update        - Update element with sum
- POST /pyrest/pov/calculate     - One-call: fetch, add, update (REST API)
"""

import json
import tornado.web
from concurrent.futures import ThreadPoolExecutor
from functools import partial

# Thread pool for async TM1 operations (TM1py is blocking)
TM1_EXECUTOR = ThreadPoolExecutor(max_workers=16)

# Try to import TM1py
try:
    from TM1py import TM1Service
    TM1_AVAILABLE = True
except ImportError:
    TM1_AVAILABLE = False
    TM1Service = None

# Try to import MSAL for Azure AD token acquisition
try:
    from msal import ConfidentialClientApplication
    MSAL_AVAILABLE = True
except ImportError:
    MSAL_AVAILABLE = False
    ConfidentialClientApplication = None


class POVBaseHandler(tornado.web.RequestHandler):
    """Base handler with common utilities."""
    
    def initialize(self, app_config=None, **kwargs):
        self.app_config = app_config or {}
    
    def set_default_headers(self):
        self.set_header("Content-Type", "application/json")
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")
    
    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()
    
    def get_json_body(self):
        try:
            return json.loads(self.request.body) if self.request.body else {}
        except json.JSONDecodeError:
            return {}
    
    def success(self, data=None, message="Success"):
        self.write({"success": True, "message": message, "data": data or {}})
    
    def error(self, message, status=400):
        self.set_status(status)
        self.write({"success": False, "error": message})
    
    def _acquire_azure_ad_token(self, tenant_id: str, client_id: str, client_secret: str, 
                                  scope: str = None) -> str:
        """
        Acquire an access token from Azure AD using client credentials flow.
        
        Args:
            tenant_id: Azure AD tenant ID
            client_id: Azure AD application (client) ID
            client_secret: Azure AD application client secret
            scope: OAuth2 scope (defaults to TM1 API scope)
            
        Returns:
            Access token string
            
        Raises:
            Exception if token acquisition fails
        """
        if not MSAL_AVAILABLE:
            raise ImportError("MSAL library not available. Install with: pip install msal")
        
        # Default scope for TM1/Planning Analytics
        if not scope:
            scope = f"{client_id}/.default"
        
        # Create MSAL confidential client
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        
        app = ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret
        )
        
        # Acquire token using client credentials
        result = app.acquire_token_for_client(scopes=[scope])
        
        if "access_token" in result:
            return result["access_token"]
        else:
            error = result.get("error", "Unknown error")
            error_desc = result.get("error_description", "No description")
            raise Exception(f"Token acquisition failed: {error} - {error_desc}")
    
    def _build_tm1_params(self, body: dict) -> dict:
        """Build TM1Service parameters from request body."""
        connection_type = body.get('connection_type', 'onprem')
        
        if connection_type == 'azure_ad':
            # TM1 v12 Cloud with Azure AD authentication
            base_url = body.get('base_url', '')
            tenant_id = body.get('tenant_id', '')
            client_id = body.get('client_id', '')
            client_secret = body.get('client_secret', '')
            scope = body.get('scope', '')  # Optional custom scope
            
            if not all([base_url, tenant_id, client_id, client_secret]):
                raise ValueError("Azure AD connection requires: base_url, tenant_id, client_id, client_secret")
            
            # Acquire access token from Azure AD
            access_token = self._acquire_azure_ad_token(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
                scope=scope or None
            )
            
            # Use token with TM1Service
            return {
                'base_url': base_url,
                'access_token': access_token,
                'ssl': True
            }
            
        elif connection_type == 'cloud':
            # IBM Planning Analytics Cloud with API key
            base_url = body.get('base_url', '')
            ipm_url = body.get('ipm_url', '')
            tenant = body.get('tenant', '')
            api_key = body.get('api_key', '')
            
            if base_url:
                return {'base_url': base_url, 'api_key': api_key, 'ssl': True}
            else:
                return {'ipm_url': ipm_url, 'tenant': tenant, 'api_key': api_key, 'ssl': True}
        else:
            # On-Premise connection (default)
            params = {
                'address': body.get('address', 'localhost'),
                'port': int(body.get('port', 8001)),
                'user': body.get('user', 'admin'),
                'password': body.get('password', ''),
                'ssl': body.get('ssl', False)
            }
            namespace = body.get('namespace', '')
            if namespace:
                params['namespace'] = namespace
            return params
    
    async def run_tm1_async(self, func, *args, **kwargs):
        """
        Run a blocking TM1 operation asynchronously in a thread pool.
        
        Usage:
            result = await self.run_tm1_async(some_blocking_func, arg1, arg2)
        """
        loop = tornado.ioloop.IOLoop.current()
        return await loop.run_in_executor(TM1_EXECUTOR, partial(func, *args, **kwargs))
    
    def _parse_value(self, value):
        """Parse TM1 value to numeric."""
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0


class POVInfoHandler(POVBaseHandler):
    """API info endpoint."""
    
    async def get(self):
        self.success(data={
            "app": "POV - Point of View",
            "description": "Fetch two values, add them, update a third element",
            "tm1py_available": TM1_AVAILABLE,
            "msal_available": MSAL_AVAILABLE,
            "endpoints": {
                "GET /ui": "Web interface",
                "POST /connect": "Test TM1 connection",
                "POST /fetch": "Fetch values from two elements",
                "POST /update": "Update element with value",
                "POST /calculate": "One-call: fetch + add + update"
            },
            "connection_types": {
                "onprem": {
                    "description": "Traditional TM1 on-premise",
                    "fields": ["address", "port", "user", "password", "ssl", "namespace"]
                },
                "cloud": {
                    "description": "IBM Planning Analytics Cloud (API key auth)",
                    "fields": ["base_url", "api_key"],
                    "alt_fields": ["ipm_url", "tenant", "api_key"]
                },
                "azure_ad": {
                    "description": "TM1 v12 Cloud with Azure AD (OAuth2 client credentials)",
                    "auth_flow": "Uses MSAL to acquire access token with client credentials",
                    "fields": ["base_url", "tenant_id", "client_id", "client_secret"],
                    "optional_fields": ["scope"],
                    "note": "Access token is acquired automatically using client_id, client_secret, and tenant_id"
                }
            }
        })


class POVUIHandler(tornado.web.RequestHandler):
    """Serve the POV UI."""
    
    def initialize(self, app_config=None, **kwargs):
        self.app_config = app_config or {}
    
    async def get(self):
        import os
        app_path = os.environ.get('PYREST_APP_PATH', os.path.dirname(__file__))
        html_path = os.path.join(app_path, 'static', 'index.html')
        
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                self.set_header('Content-Type', 'text/html')
                self.write(f.read())
        except FileNotFoundError:
            self.set_status(404)
            self.write({'error': 'UI not found', 'path': html_path})


class POVConnectHandler(POVBaseHandler):
    """Test TM1 connection."""
    
    async def post(self):
        if not TM1_AVAILABLE:
            return self.error("TM1py not installed", 500)
        
        body = self.get_json_body()
        
        try:
            params = self._build_tm1_params(body)
        except ValueError as e:
            return self.error(str(e))
        except Exception as e:
            return self.error(f"Invalid connection parameters: {str(e)}")
        
        def _connect_sync(tm1_params):
            """Blocking TM1 connection test."""
            with TM1Service(**tm1_params) as tm1:
                return tm1.server.get_server_name()
        
        try:
            server_name = await self.run_tm1_async(_connect_sync, params)
            connection_type = body.get('connection_type', 'onprem')
            
            self.success(
                data={
                    "server_name": server_name,
                    "connected": True,
                    "connection_type": connection_type
                },
                message=f"Connected to {server_name}"
            )
        except Exception as e:
            self.error(f"Connection failed: {str(e)}")


class POVFetchHandler(POVBaseHandler):
    """Fetch values from two elements in a cube."""
    
    async def post(self):
        """
        Fetch numeric values from two cell coordinates.
        
        Request body:
        {
            "connection_type": "onprem" | "cloud",
            // Connection fields...
            "cube": "CubeName",
            "element1": "Year,Region,Measure1",  // Comma-separated elements
            "element2": "Year,Region,Measure2"   // Comma-separated elements
        }
        """
        if not TM1_AVAILABLE:
            return self.error("TM1py not installed", 500)
        
        body = self.get_json_body()
        
        cube = body.get('cube')
        element1 = body.get('element1', '')
        element2 = body.get('element2', '')
        
        if not cube:
            return self.error("cube is required")
        if not element1 or not element2:
            return self.error("element1 and element2 are required")
        
        try:
            params = self._build_tm1_params(body)
        except (ValueError, Exception) as e:
            return self.error(str(e))
        
        def _fetch_sync(tm1_params, cube_name, elem1, elem2):
            """Blocking TM1 fetch operation."""
            with TM1Service(**tm1_params) as tm1:
                value1 = tm1.cubes.cells.get_value(cube_name, elem1)
                value2 = tm1.cubes.cells.get_value(cube_name, elem2)
                return value1, value2
        
        try:
            value1, value2 = await self.run_tm1_async(_fetch_sync, params, cube, element1, element2)
            
            v1 = self._parse_value(value1)
            v2 = self._parse_value(value2)
            
            self.success(data={
                "element1": {"coordinates": element1, "value": v1},
                "element2": {"coordinates": element2, "value": v2},
                "sum": v1 + v2
            })
        except Exception as e:
            self.error(f"Fetch failed: {str(e)}")


class POVUpdateHandler(POVBaseHandler):
    """Update an element with a value."""
    
    async def post(self):
        """
        Update a cell with a numeric value.
        
        Request body:
        {
            "connection_type": "onprem" | "cloud",
            // Connection fields...
            "cube": "CubeName",
            "target_element": "Year,Region,Measure3",  // Comma-separated
            "value": 12345.67
        }
        """
        if not TM1_AVAILABLE:
            return self.error("TM1py not installed", 500)
        
        body = self.get_json_body()
        
        cube = body.get('cube')
        target_element = body.get('target_element', '')
        value = body.get('value')
        
        if not cube:
            return self.error("cube is required")
        if not target_element:
            return self.error("target_element is required")
        if value is None:
            return self.error("value is required")
        
        try:
            params = self._build_tm1_params(body)
        except (ValueError, Exception) as e:
            return self.error(str(e))
        
        def _update_sync(tm1_params, cube_name, target_elem, write_value):
            """Blocking TM1 update operation."""
            with TM1Service(**tm1_params) as tm1:
                elements = [e.strip() for e in target_elem.split(',')]
                cellset = {tuple(elements): float(write_value)}
                tm1.cubes.cells.write_values(cube_name, cellset)
                return tm1.cubes.cells.get_value(cube_name, target_elem)
        
        try:
            new_value = await self.run_tm1_async(_update_sync, params, cube, target_element, value)
            
            self.success(
                data={
                    "target_element": target_element,
                    "written_value": float(value),
                    "confirmed_value": self._parse_value(new_value)
                },
                message="Cell updated successfully"
            )
        except Exception as e:
            self.error(f"Update failed: {str(e)}")


class POVCalculateHandler(POVBaseHandler):
    """
    One-call REST API: Fetch two values, add them, update third element.
    """
    
    async def post(self):
        """
        Complete operation: fetch, add, update in one call.
        
        Request body:
        {
            "connection_type": "onprem" | "cloud",
            
            // On-Premise fields:
            "address": "tm1server.company.com",
            "port": 8001,
            "user": "admin",
            "password": "secret",
            "ssl": false,
            
            // OR Cloud fields:
            "base_url": "https://region.planning-analytics.cloud.ibm.com/api/tm1/v1",
            "api_key": "your-api-key",
            
            // Operation fields:
            "cube": "SalesCube",
            "element1": "2024,North,Sales",
            "element2": "2024,South,Sales",
            "target_element": "2024,Total,Sales"
        }
        
        Response:
        {
            "success": true,
            "message": "Calculated and updated",
            "data": {
                "element1": {"coordinates": "...", "value": 100},
                "element2": {"coordinates": "...", "value": 200},
                "sum": 300,
                "target": {"coordinates": "...", "written": 300, "confirmed": 300}
            }
        }
        """
        if not TM1_AVAILABLE:
            return self.error("TM1py not installed", 500)
        
        body = self.get_json_body()
        
        cube = body.get('cube')
        element1 = body.get('element1', '')
        element2 = body.get('element2', '')
        target_element = body.get('target_element', '')
        
        if not cube:
            return self.error("cube is required")
        if not element1 or not element2:
            return self.error("element1 and element2 are required")
        if not target_element:
            return self.error("target_element is required")
        
        try:
            params = self._build_tm1_params(body)
        except (ValueError, Exception) as e:
            return self.error(str(e))
        
        def _calculate_sync(tm1_params, cube_name, elem1, elem2, target_elem):
            """Blocking TM1 calculate operation: fetch, add, update, confirm."""
            with TM1Service(**tm1_params) as tm1:
                # Fetch values
                value1 = tm1.cubes.cells.get_value(cube_name, elem1)
                value2 = tm1.cubes.cells.get_value(cube_name, elem2)
                
                # Parse values
                v1 = float(value1) if value1 is not None else 0.0
                v2 = float(value2) if value2 is not None else 0.0
                total = v1 + v2
                
                # Update target
                elements = [e.strip() for e in target_elem.split(',')]
                cellset = {tuple(elements): total}
                tm1.cubes.cells.write_values(cube_name, cellset)
                
                # Confirm
                confirmed = tm1.cubes.cells.get_value(cube_name, target_elem)
                
                return v1, v2, total, confirmed
        
        try:
            v1, v2, total, confirmed = await self.run_tm1_async(
                _calculate_sync, params, cube, element1, element2, target_element
            )
            
            self.success(
                data={
                    "element1": {"coordinates": element1, "value": v1},
                    "element2": {"coordinates": element2, "value": v2},
                    "sum": total,
                    "target": {
                        "coordinates": target_element,
                        "written": total,
                        "confirmed": self._parse_value(confirmed)
                    }
                },
                message=f"Calculated {v1} + {v2} = {total} and updated target"
            )
        except Exception as e:
            self.error(f"Calculate failed: {str(e)}")


def get_handlers():
    """Return the list of handlers for this app."""
    return [
        (r"/", POVInfoHandler),
        (r"/ui", POVUIHandler),
        (r"/connect", POVConnectHandler),
        (r"/fetch", POVFetchHandler),
        (r"/update", POVUpdateHandler),
        (r"/calculate", POVCalculateHandler),
    ]
