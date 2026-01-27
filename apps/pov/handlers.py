"""
POV (Point of View) App - HTTP Handlers

Connects to TM1 v12 (primary target) or legacy TM1 versions, fetches values 
from two elements, adds them, and updates a third element with the result.

TM1 v12 Connection Types (Primary Target):
- v12: TM1 v12 with basic authentication (RECOMMENDED)
- v12_azure_ad: TM1 v12 with Azure AD OAuth2 authentication
- v12_paas: IBM Planning Analytics as a Service (TM1 v12)

Legacy Connection Types (Backward Compatibility):
- token: Pre-acquired access token
- azure_ad: Legacy Azure AD using MSAL
- cloud: Legacy IBM Planning Analytics Cloud
- onprem: Legacy TM1 on-premise (pre-v12)

Endpoints:
- GET  /pyrest/pov/              - API info
- GET  /pyrest/pov/ui            - Web UI
- GET  /pyrest/pov/token-ui      - Token manager UI
- POST /pyrest/pov/token         - Acquire Azure AD token
- POST /pyrest/pov/connect       - Test TM1 connection
- POST /pyrest/pov/fetch         - Fetch values from two elements
- POST /pyrest/pov/update        - Update element with value
- POST /pyrest/pov/calculate     - One-call: fetch, add, update (REST API)
"""

import json
import os
import tornado.web
import tornado.ioloop
from concurrent.futures import ThreadPoolExecutor
from functools import partial

# Import TM1 operations
from . import tm1_operations as tm1_ops

# Thread pool for async TM1 operations (TM1py is blocking)
TM1_EXECUTOR = ThreadPoolExecutor(max_workers=16)

# Try to import MSAL for Azure AD token acquisition
try:
    from msal import ConfidentialClientApplication
    MSAL_AVAILABLE = True
except ImportError:
    MSAL_AVAILABLE = False
    ConfidentialClientApplication = None


# =============================================================================
# Base Handler
# =============================================================================

class POVBaseHandler(tornado.web.RequestHandler):
    """Base handler with connection building and common utilities."""
    
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
    
    async def run_async(self, func, *args, **kwargs):
        """Run a blocking function asynchronously in the thread pool."""
        loop = tornado.ioloop.IOLoop.current()
        return await loop.run_in_executor(TM1_EXECUTOR, partial(func, *args, **kwargs))
    
    def build_tm1_params(self, body: dict) -> dict:
        """
        Build TM1Service parameters from request body.
        
        Supports TM1 v12 connection types as the primary target:
        - v12: TM1 v12 with basic authentication
        - v12_azure_ad: TM1 v12 with Azure AD OAuth2 authentication
        - v12_paas: IBM Planning Analytics as a Service (TM1 v12)
        
        Also supports legacy connection types for backward compatibility.
        """
        connection_type = body.get('connection_type', 'v12')
        
        # TM1 v12 with basic authentication
        if connection_type == 'v12':
            base_url = body.get('base_url', '')
            if not base_url:
                raise ValueError("TM1 v12 connection requires: base_url")
            
            params = {
                'base_url': base_url,
                'user': body.get('user', ''),
                'password': body.get('password', ''),
                'ssl': body.get('ssl', True),
            }
            if body.get('instance'):
                params['instance'] = body.get('instance')
            if body.get('database'):
                params['database'] = body.get('database')
            if not body.get('verify_ssl_cert', True):
                params['verify'] = False
            return params
        
        # TM1 v12 with Azure AD
        elif connection_type == 'v12_azure_ad':
            base_url = body.get('base_url', '')
            tenant_id = body.get('tenant_id', '')
            client_id = body.get('client_id', '')
            client_secret = body.get('client_secret', '')
            
            if not all([base_url, tenant_id, client_id, client_secret]):
                raise ValueError("TM1 v12 Azure AD requires: base_url, tenant_id, client_id, client_secret")
            
            params = {
                'base_url': base_url,
                'tenant': tenant_id,
                'client_id': client_id,
                'client_secret': client_secret,
                'ssl': True,
            }
            if body.get('auth_url'):
                params['auth_url'] = body.get('auth_url')
            if body.get('instance'):
                params['instance'] = body.get('instance')
            if body.get('database'):
                params['database'] = body.get('database')
            if not body.get('verify_ssl_cert', True):
                params['verify'] = False
            return params
        
        # TM1 v12 PAaaS
        elif connection_type == 'v12_paas':
            base_url = body.get('base_url', '')
            api_key = body.get('api_key', '')
            
            if not base_url or not api_key:
                raise ValueError("TM1 v12 PAaaS requires: base_url, api_key")
            
            params = {
                'base_url': base_url,
                'api_key': api_key,
                'ssl': True,
            }
            if body.get('iam_url'):
                params['iam_url'] = body.get('iam_url')
            if body.get('tenant'):
                params['tenant'] = body.get('tenant')
            if body.get('instance'):
                params['instance'] = body.get('instance')
            if body.get('database'):
                params['database'] = body.get('database')
            return params
        
        # Pre-acquired access token
        elif connection_type == 'token':
            base_url = body.get('base_url', '')
            access_token = body.get('access_token', '')
            if not base_url:
                raise ValueError("Token connection requires: base_url")
            if not access_token:
                raise ValueError("Token connection requires: access_token")
            return {'base_url': base_url, 'access_token': access_token, 'ssl': True}
        
        # Legacy Azure AD using MSAL
        elif connection_type == 'azure_ad':
            base_url = body.get('base_url', '')
            tenant_id = body.get('tenant_id', '')
            client_id = body.get('client_id', '')
            client_secret = body.get('client_secret', '')
            scope = body.get('scope', '')
            
            if not all([base_url, tenant_id, client_id, client_secret]):
                raise ValueError("Azure AD requires: base_url, tenant_id, client_id, client_secret")
            
            access_token = self._acquire_azure_ad_token(tenant_id, client_id, client_secret, scope or None)
            return {'base_url': base_url, 'access_token': access_token, 'ssl': True}
        
        # Legacy IBM Cloud
        elif connection_type == 'cloud':
            base_url = body.get('base_url', '')
            ipm_url = body.get('ipm_url', '')
            tenant = body.get('tenant', '')
            api_key = body.get('api_key', '')
            
            if base_url:
                return {'base_url': base_url, 'api_key': api_key, 'ssl': True}
            else:
                return {'ipm_url': ipm_url, 'tenant': tenant, 'api_key': api_key, 'ssl': True}
        
        # Legacy On-Premise
        else:
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
    
    def _acquire_azure_ad_token(self, tenant_id: str, client_id: str, client_secret: str, scope: str = None) -> str:
        """Acquire access token from Azure AD using MSAL."""
        if not MSAL_AVAILABLE:
            raise ImportError("MSAL library not available. Install with: pip install msal")
        
        if not scope:
            scope = f"{client_id}/.default"
        
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = ConfidentialClientApplication(client_id, authority=authority, client_credential=client_secret)
        result = app.acquire_token_for_client(scopes=[scope])
        
        if "access_token" in result:
            return result["access_token"]
        else:
            error = result.get("error", "Unknown error")
            error_desc = result.get("error_description", "No description")
            raise Exception(f"Token acquisition failed: {error} - {error_desc}")


# =============================================================================
# UI Handlers
# =============================================================================

class POVUIHandler(tornado.web.RequestHandler):
    """Serve the POV UI."""
    
    def initialize(self, app_config=None, **kwargs):
        self.app_config = app_config or {}
    
    async def get(self):
        app_path = os.environ.get('PYREST_APP_PATH', os.path.dirname(__file__))
        html_path = os.path.join(app_path, 'static', 'index.html')
        
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                self.set_header('Content-Type', 'text/html')
                self.write(f.read())
        except FileNotFoundError:
            self.set_status(404)
            self.write({'error': 'UI not found', 'path': html_path})


class POVTokenUIHandler(tornado.web.RequestHandler):
    """Serve the Token Manager UI."""
    
    def initialize(self, app_config=None, **kwargs):
        self.app_config = app_config or {}
    
    async def get(self):
        app_path = os.environ.get('PYREST_APP_PATH', os.path.dirname(__file__))
        html_path = os.path.join(app_path, 'static', 'token.html')
        
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                self.set_header('Content-Type', 'text/html')
                self.write(f.read())
        except FileNotFoundError:
            self.set_status(404)
            self.write({'error': 'Token UI not found', 'path': html_path})


# =============================================================================
# API Handlers
# =============================================================================

class POVInfoHandler(POVBaseHandler):
    """API info endpoint."""
    
    async def get(self):
        self.success(data={
            "app": "POV - Point of View",
            "description": "Fetch two values, add them, update a third element",
            "tm1_version": "12 (primary target)",
            "tm1py_available": tm1_ops.TM1_AVAILABLE,
            "msal_available": MSAL_AVAILABLE,
            "endpoints": {
                "GET /ui": "Web interface",
                "GET /token-ui": "Azure AD Token Manager UI",
                "POST /token": "Acquire Azure AD access token",
                "POST /connect": "Test TM1 connection",
                "POST /fetch": "Fetch values from two elements",
                "POST /update": "Update element with value",
                "POST /calculate": "One-call: fetch + add + update"
            },
            "connection_types": {
                "v12": {"description": "TM1 v12 basic auth (RECOMMENDED)", "fields": ["base_url", "user", "password"]},
                "v12_azure_ad": {"description": "TM1 v12 Azure AD", "fields": ["base_url", "tenant_id", "client_id", "client_secret"]},
                "v12_paas": {"description": "TM1 v12 PAaaS", "fields": ["base_url", "api_key"]},
                "token": {"description": "Pre-acquired token", "fields": ["base_url", "access_token"]},
                "azure_ad": {"description": "Legacy Azure AD", "fields": ["base_url", "tenant_id", "client_id", "client_secret"]},
                "cloud": {"description": "Legacy IBM Cloud", "fields": ["base_url", "api_key"]},
                "onprem": {"description": "Legacy On-Premise", "fields": ["address", "port", "user", "password"]}
            }
        })


class POVTokenHandler(POVBaseHandler):
    """Acquire Azure AD access token."""
    
    async def post(self):
        if not MSAL_AVAILABLE:
            return self.error("MSAL library not available", 500)
        
        body = self.get_json_body()
        tenant_id = body.get('tenant_id', '').strip()
        client_id = body.get('client_id', '').strip()
        client_secret = body.get('client_secret', '').strip()
        scope = body.get('scope', '').strip()
        
        if not tenant_id or not client_id or not client_secret:
            return self.error("Required: tenant_id, client_id, client_secret")
        
        try:
            token = await self.run_async(
                self._acquire_azure_ad_token, tenant_id, client_id, client_secret, scope or None
            )
            self.success(data={"access_token": token, "expires_in": 3600}, message="Token acquired")
        except Exception as e:
            self.error(f"Token acquisition failed: {str(e)}")


class POVConnectHandler(POVBaseHandler):
    """Test TM1 connection."""
    
    async def post(self):
        if not tm1_ops.TM1_AVAILABLE:
            return self.error("TM1py not installed", 500)
        
        body = self.get_json_body()
        
        try:
            params = self.build_tm1_params(body)
        except ValueError as e:
            return self.error(str(e))
        
        try:
            server_name = await self.run_async(tm1_ops.test_connection, params)
            self.success(
                data={"server_name": server_name, "connected": True, "connection_type": body.get('connection_type', 'v12')},
                message=f"Connected to {server_name}"
            )
        except Exception as e:
            self.error(f"Connection failed: {str(e)}")


class POVFetchHandler(POVBaseHandler):
    """Fetch values from two elements."""
    
    async def post(self):
        if not tm1_ops.TM1_AVAILABLE:
            return self.error("TM1py not installed", 500)
        
        body = self.get_json_body()
        cube = body.get('cube')
        element1 = body.get('element1', '')
        element2 = body.get('element2', '')
        
        # Validate
        if not cube:
            return self.error("cube is required")
        if not element1 or not element2:
            return self.error("element1 and element2 are required")
        
        try:
            params = self.build_tm1_params(body)
        except ValueError as e:
            return self.error(str(e))
        
        # Execute: fetch_data -> return result
        try:
            result = await self.run_async(tm1_ops.fetch_data, params, cube, element1, element2)
            self.success(data=result.to_dict())
        except Exception as e:
            self.error(f"Fetch failed: {str(e)}")


class POVUpdateHandler(POVBaseHandler):
    """Update element with a value."""
    
    async def post(self):
        if not tm1_ops.TM1_AVAILABLE:
            return self.error("TM1py not installed", 500)
        
        body = self.get_json_body()
        cube = body.get('cube')
        target_element = body.get('target_element', '')
        value = body.get('value')
        
        # Validate
        if not cube:
            return self.error("cube is required")
        if not target_element:
            return self.error("target_element is required")
        if value is None:
            return self.error("value is required")
        
        try:
            params = self.build_tm1_params(body)
        except ValueError as e:
            return self.error(str(e))
        
        # Execute: update_target -> return confirmed
        try:
            result = await self.run_async(tm1_ops.update_target, params, cube, target_element, float(value))
            self.success(
                data={"target_element": target_element, "written_value": float(value), "confirmed_value": result.value},
                message="Cell updated successfully"
            )
        except Exception as e:
            self.error(f"Update failed: {str(e)}")


class POVCalculateHandler(POVBaseHandler):
    """One-call: fetch, add, update."""
    
    async def post(self):
        if not tm1_ops.TM1_AVAILABLE:
            return self.error("TM1py not installed", 500)
        
        body = self.get_json_body()
        cube = body.get('cube')
        element1 = body.get('element1', '')
        element2 = body.get('element2', '')
        target_element = body.get('target_element', '')
        
        # Validate
        if not cube:
            return self.error("cube is required")
        if not element1 or not element2:
            return self.error("element1 and element2 are required")
        if not target_element:
            return self.error("target_element is required")
        
        try:
            params = self.build_tm1_params(body)
        except ValueError as e:
            return self.error(str(e))
        
        # Execute: fetch -> sum -> update -> return all
        try:
            result = await self.run_async(tm1_ops.execute_pov, params, cube, element1, element2, target_element)
            self.success(
                data=result.to_dict(),
                message=f"Calculated {result.element1.value} + {result.element2.value} = {result.sum_value}"
            )
        except Exception as e:
            self.error(f"Calculate failed: {str(e)}")


# =============================================================================
# Handler Registration
# =============================================================================

def get_handlers():
    """Return the list of handlers for this app."""
    return [
        (r"/", POVInfoHandler),
        (r"/ui", POVUIHandler),
        (r"/token-ui", POVTokenUIHandler),
        (r"/token", POVTokenHandler),
        (r"/connect", POVConnectHandler),
        (r"/fetch", POVFetchHandler),
        (r"/update", POVUpdateHandler),
        (r"/calculate", POVCalculateHandler),
    ]
