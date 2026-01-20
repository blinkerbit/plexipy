# PyRest Framework

A modular, Tornado-based REST API framework designed for building TM1-integrated and general-purpose Python APIs. Supports multiple TM1 instances (Cloud and On-Premise), Azure AD authentication with role-based access control, and automatic app isolation with virtual environment management.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
  - [Framework Configuration](#framework-configuration)
  - [App Configuration](#app-configuration)
  - [Environment Variables](#environment-variable-resolution)
- [Authentication](#authentication)
  - [Azure AD Setup](#azure-ad-setup)
  - [Authentication Decorators](#authentication-decorators)
  - [Role-Based Access Control](#role-based-access-control)
- [Logging](#logging)
  - [App-Specific Logging](#app-specific-logging)
  - [Log Configuration](#log-configuration)
  - [Structured Logging](#structured-logging)
- [TM1 Integration](#tm1-integration)
  - [Multi-Instance Configuration](#multi-instance-configuration)
  - [Using TM1 Connections](#using-tm1-connections)
- [Utils Package](#utils-package)
- [Creating Apps](#creating-apps)
- [API Reference](#api-reference)
- [Docker Deployment](#docker-deployment)

---

## Features

- **Modular App Architecture**: Drop apps into the `apps/` folder for automatic discovery
- **Embedded Apps**: Simple apps run within the main process (no `requirements.txt`)
- **Isolated Apps**: Apps with dependencies run in separate processes with their own virtual environment
- **Multi-TM1 Support**: Connect to multiple TM1 instances (Cloud and On-Premise) simultaneously
- **Azure AD Authentication**: OAuth 2.0 with role-based access control
- **App-Specific Logging**: Separate log files per app with smart formatting and rotation
- **Environment Variable Resolution**: Use `${VAR:-default}` syntax in config files
- **Automatic Venv Management**: Creates and manages virtual environments for isolated apps
- **Nginx Config Generation**: Automatically generates reverse proxy configuration

---

## Architecture

```
+------------------------------------------------------------------+
|                        Nginx (Port 80/443)                        |
|                 Reverse Proxy for all /pyrest/* routes            |
+------------------------------------------------------------------+
                                    |
                +-------------------+-------------------+
                |                                       |
                v                                       v
+-----------------------------+       +-----------------------------+
|   Main PyRest (Port 8000)   |       |  Isolated Apps (Port 8001+) |
|                             |       |                             |
|  - Framework endpoints      |       |  - Own virtual environment  |
|  - Auth endpoints           |       |  - Own dependencies         |
|  - Embedded apps            |       |  - Separate process         |
|  - Admin dashboard          |       |  - App-specific logging     |
+-----------------------------+       +-----------------------------+
```

---

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd pyrest

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate
# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the server
python main.py
```

The server starts at `http://localhost:8000/pyrest`

### Pip Proxy Configuration

To configure pip proxy settings (e.g., for corporate networks), edit `setup_pip.sh` in the project root. This script is run automatically before any venv or pip operations.

Example `setup_pip.sh`:

```bash
#!/bin/bash
# Uncomment and modify as needed:
# export PIP_INDEX_URL="https://your-proxy.com/simple"
# export PIP_TRUSTED_HOST="your-proxy.com"
# export HTTP_PROXY="http://proxy.example.com:8080"
# export HTTPS_PROXY="http://proxy.example.com:8080"
```

The file is empty by default; add your proxy or pip configuration as needed. On Unix, ensure it is executable: `chmod +x setup_pip.sh`.

---

## Configuration

### Framework Configuration

The main framework configuration is in `config.json`:

```json
{
  "host": "0.0.0.0",
  "port": 8000,
  "debug": true,
  "base_path": "/pyrest",
  "apps_folder": "apps",
  "env_file": ".env",
  "auth_config_file": "auth_config.json",
  "jwt_secret": "your-secret-key-change-in-production",
  "jwt_expiry_hours": 24,
  "cors_enabled": true,
  "cors_origins": ["*"],
  "log_level": "INFO",
  "isolated_app_base_port": 8001
}
```

### App Configuration

Each app has its own `config.json` with the following structure:

```json
{
  "name": "myapp",
  "version": "1.0.0",
  "description": "My application description",
  "enabled": true,
  "auth_required": true,
  "port": 8001,
  "venv_path": ".venv",
  "settings": {
    "custom_setting": "value",
    "log_level": "INFO",
    "log_dir": "logs"
  },
  "os_vars": {
    "MY_VAR": "value",
    "API_KEY": ""
  },
  "tm1_instances": {
    "production": { ... },
    "development": { ... }
  }
}
```

#### Configuration Sections

| Section | Description |
|---------|-------------|
| `name` | App identifier (used in URL path) |
| `enabled` | Whether the app is active |
| `auth_required` | Require authentication for all endpoints |
| `port` | Port for isolated apps (auto-assigned if not specified) |
| `settings` | Custom app settings accessible in handlers |
| `os_vars` | Environment variables to set for the app |
| `tm1_instances` | TM1 connection configurations (see [TM1 Integration](#tm1-integration)) |

#### os_vars Section

The `os_vars` section sets environment variables for the app:

```json
{
  "os_vars": {
    "DATABASE_URL": "postgresql://localhost/mydb",
    "API_KEY": "",
    "DEBUG_MODE": "false"
  }
}
```

Environment variables are set in two formats:
1. **Prefixed**: `<app_name>.<VAR_NAME>` (e.g., `myapp.DATABASE_URL`)
2. **Direct**: `VAR_NAME` for isolated apps (e.g., `DATABASE_URL`)

### Environment Variable Resolution

Config values can reference environment variables using `${VAR:-default}` syntax:

```json
{
  "settings": {
    "api_url": "${API_URL:-https://api.example.com}",
    "timeout": "${TIMEOUT:-30}"
  },
  "os_vars": {
    "DB_HOST": "${DATABASE_HOST:-localhost}",
    "DB_PORT": "${DATABASE_PORT:-5432}"
  }
}
```

**Syntax:**
- `${VAR}` - Use environment variable, empty string if not set
- `${VAR:-default}` - Use environment variable, or `default` if not set

---

## Authentication

### Azure AD Setup

1. **Create App Registration** in Azure Portal:
   - Go to Azure Active Directory > App registrations
   - Click "New registration"
   - Set redirect URI: `http://localhost:8000/pyrest/auth/azure/callback`

2. **Create Client Secret**:
   - Go to Certificates & secrets
   - Create a new client secret

3. **Configure App Roles** (for role-based access):
   - Go to App roles
   - Create roles (e.g., "Admin", "Reader", "TM1.ReadWrite")

4. **Update auth_config.json**:

```json
{
  "provider": "azure_ad",
  "tenant_id": "your-tenant-id",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "redirect_uri": "http://localhost:8000/pyrest/auth/azure/callback",
  "scopes": ["openid", "profile", "email", "User.Read"]
}
```

Or use environment variables:
```bash
export AZURE_AD_TENANT_ID="your-tenant-id"
export AZURE_AD_CLIENT_ID="your-client-id"
export AZURE_AD_CLIENT_SECRET="your-client-secret"
```

### Authentication Decorators

PyRest provides several authentication decorators:

#### Basic Authentication (JWT)

```python
from pyrest.handlers import BaseHandler
from pyrest.auth import authenticated

class MyHandler(BaseHandler):
    @authenticated
    async def get(self):
        user = self._current_user
        self.success(data={"user": user})
```

#### Azure AD Authentication

```python
from pyrest.handlers import BaseHandler
from pyrest.auth import azure_ad_authenticated

class MyHandler(BaseHandler):
    @azure_ad_authenticated
    async def get(self):
        user = self._current_user      # Dict with user info
        roles = self._azure_roles      # List[str] of Azure AD roles
        self.success(data={
            "user": user["email"],
            "roles": roles
        })
```

### Role-Based Access Control

#### Using require_azure_roles

```python
from pyrest.handlers import BaseHandler
from pyrest.auth import azure_ad_authenticated, require_azure_roles

class AdminHandler(BaseHandler):
    @azure_ad_authenticated
    @require_azure_roles(["Admin", "SuperUser"])
    async def get(self):
        # Only users with "Admin" OR "SuperUser" role can access
        self.success(data={"message": "Admin access granted"})

class DataHandler(BaseHandler):
    @azure_ad_authenticated
    @require_azure_roles(["TM1.ReadWrite", "DataManager"])
    async def post(self):
        # Requires TM1.ReadWrite or DataManager role
        self.success(data={"message": "Data updated"})
```

#### Using azure_ad_protected (Combined Decorator)

```python
from pyrest.handlers import BaseHandler
from pyrest.auth import azure_ad_protected

# Authentication only (no role check)
class PublicHandler(BaseHandler):
    @azure_ad_protected()
    async def get(self):
        self.success(data={"message": "Authenticated user"})

# Authentication + role check
class AdminHandler(BaseHandler):
    @azure_ad_protected(["Admin", "SuperUser"])
    async def get(self):
        self.success(data={"message": "Admin access"})
```

#### Available Decorators

| Decorator | Description |
|-----------|-------------|
| `@authenticated` | Requires valid JWT token |
| `@azure_ad_authenticated` | Requires valid Azure AD token, extracts user info and roles |
| `@require_roles(roles: List[str])` | Checks JWT token roles (use after `@authenticated`) |
| `@require_azure_roles(roles: List[str])` | Checks Azure AD roles (use after `@azure_ad_authenticated`) |
| `@azure_ad_protected(roles: List[str] = None)` | Combined Azure AD auth + optional role check |

#### Handler Attributes After Authentication

After Azure AD authentication, handlers have access to:

```python
self._current_user    # Dict with user details
self._azure_roles     # List[str] of Azure AD app roles
self._azure_token     # Raw Azure AD token
```

**User Info Structure:**
```python
{
    "oid": "user-object-id",
    "sub": "subject-id",
    "name": "John Doe",
    "email": "john@company.com",
    "given_name": "John",
    "family_name": "Doe",
    "roles": ["Admin", "Reader"],
    "groups": ["group-id-1", "group-id-2"],
    "tenant_id": "tenant-id",
    "app_id": "app-id"
}
```

---

## Logging

### App-Specific Logging

Each app gets its own log files with automatic rotation:

```
logs/
  myapp.log           # All logs for myapp
  myapp.error.log     # Error-only logs for myapp
  tm1data.log         # All logs for tm1data
  tm1data.error.log   # Error-only logs for tm1data
```

### Log Configuration

Configure logging in your app's `config.json`:

```json
{
  "settings": {
    "log_level": "INFO",
    "log_dir": "logs"
  }
}
```

**Log Levels:** `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

### Using the Logger in Handlers

```python
from pyrest.utils import get_app_logger, setup_app_logging

# Setup logging (usually done automatically)
logger = setup_app_logging(
    app_name="myapp",
    log_dir="logs",
    log_level="INFO"
)

# In your handler
class MyHandler(BaseHandler):
    async def get(self):
        logger = get_app_logger("myapp")
        logger.info("Processing request")
        logger.error("Something went wrong", exc_info=True)
```

### Structured Logging

The logger provides structured logging methods:

```python
# Log HTTP requests
logger.log_request(
    method="GET",
    path="/api/data",
    status_code=200,
    duration_ms=45.2,
    user="john@company.com"
)

# Log TM1 operations
logger.log_tm1_operation(
    operation="get_cubes",
    instance="production",
    success=True,
    duration_ms=120.5,
    details={"cube_count": 15}
)
```

### Log Format

Default log format:
```
2026-01-20 10:30:45 | INFO     | pyrest.app.myapp | Processing request
2026-01-20 10:30:46 | ERROR    | pyrest.app.myapp | [handlers.py:125] | Connection failed
```

JSON format (for log aggregation):
```json
{
  "timestamp": "2026-01-20T10:30:45.123Z",
  "level": "INFO",
  "logger": "pyrest.app.myapp",
  "message": "Processing request",
  "app": "myapp",
  "location": {"file": "handlers.py", "line": 45, "function": "get"}
}
```

---

## TM1 Integration

### Multi-Instance Configuration

Configure multiple TM1 instances in your app's `config.json`:

```json
{
  "name": "tm1data",
  "settings": {
    "default_instance": "production",
    "session_context": "PyRest TM1 App"
  },
  "os_vars": {
    "TM1_DEFAULT_INSTANCE": "production"
  },
  "tm1_instances": {
    "production": {
      "description": "Production TM1 Server",
      "connection_type": "onprem",
      "server": "${TM1_PROD_SERVER:-prod-tm1.company.com}",
      "port": "${TM1_PROD_PORT:-8010}",
      "ssl": true,
      "user": "${TM1_PROD_USER:-}",
      "password": "${TM1_PROD_PASSWORD:-}",
      "namespace": "",
      "integrated_login": false
    },
    "development": {
      "description": "Development TM1 Server",
      "connection_type": "onprem",
      "server": "localhost",
      "port": "8010",
      "ssl": true,
      "user": "admin",
      "password": "${TM1_DEV_PASSWORD:-}"
    },
    "cloud": {
      "description": "IBM Planning Analytics Cloud",
      "connection_type": "cloud",
      "cloud_region": "${TM1_CLOUD_REGION:-us-east}",
      "cloud_tenant": "${TM1_CLOUD_TENANT:-}",
      "cloud_api_key": "${TM1_CLOUD_API_KEY:-}",
      "instance": "MyTM1Instance"
    }
  }
}
```

#### On-Premise Connection Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `connection_type` | Must be `"onprem"` | `"onprem"` |
| `server` | TM1 server hostname or IP | `"localhost"` |
| `port` | TM1 HTTP port | `8010` |
| `ssl` | Use SSL/HTTPS | `true` |
| `user` | TM1 username | `""` |
| `password` | TM1 password | `""` |
| `namespace` | CAM namespace (for CAM auth) | `""` |
| `gateway` | CAM gateway URL | `""` |
| `integrated_login` | Use Windows auth | `false` |
| `cam_passport` | CAM passport token | `""` |

#### Cloud Connection Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `connection_type` | Must be `"cloud"` or `"paas"` | - |
| `cloud_region` | IBM Cloud region (us-east, eu-de, etc.) | `""` |
| `cloud_tenant` | Tenant ID | `""` |
| `cloud_api_key` | IBM Cloud API key | `""` |
| `instance` | TM1 instance name in cloud | `""` |

### Using TM1 Connections

```python
from pyrest.utils import TM1ConnectionManager

class TM1Handler(BaseHandler):
    def initialize(self, app_config=None, **kwargs):
        super().initialize(app_config=app_config, **kwargs)
        # Initialize with app config
        if app_config:
            TM1ConnectionManager.initialize(app_config)
    
    async def get(self, instance_name: str):
        # Get connection to specific instance
        tm1 = TM1ConnectionManager.get_connection(instance_name)
        if not tm1:
            self.error(f"Could not connect to {instance_name}", 503)
            return
        
        cubes = tm1.cubes.get_all_names()
        self.success(data={"cubes": cubes})
```

#### TM1ConnectionManager Methods

| Method | Description |
|--------|-------------|
| `initialize(app_config)` | Initialize with app configuration |
| `get_connection(instance_name)` | Get or create TM1 connection |
| `get_instance_config(instance_name)` | Get instance configuration |
| `get_all_instances()` | Get all configured instances |
| `list_instance_names()` | Get list of instance names |
| `has_instance(name)` | Check if instance exists |
| `is_connected(name)` | Check if connected to instance |
| `close_connection(name)` | Close specific connection |
| `close_all_connections()` | Close all connections |
| `reset_connection(name)` | Reset and allow reconnection |

---

## Utils Package

The `pyrest.utils` package provides shared utilities for all apps:

### Available Imports

```python
from pyrest.utils import (
    # TM1 utilities
    TM1ConnectionManager,
    TM1InstanceConfig,
    
    # Logging utilities
    AppLogger,
    setup_app_logging,
    get_app_logger,
)
```

### TM1 Utilities

```python
from pyrest.utils import TM1ConnectionManager, TM1InstanceConfig

# Initialize (usually done in handler.initialize)
TM1ConnectionManager.initialize(app_config)

# Get connection
tm1 = TM1ConnectionManager.get_connection("production")

# List instances
instances = TM1ConnectionManager.list_instance_names()

# Check connection status
status = TM1ConnectionManager.get_connection_status("production")
```

### Logging Utilities

```python
from pyrest.utils import setup_app_logging, get_app_logger

# Setup logging for an app
logger = setup_app_logging(
    app_name="myapp",
    log_dir="logs",
    log_level="INFO",
    use_json=False,        # Set True for JSON output
    console_output=False   # Set True to also log to console
)

# Get existing logger
logger = get_app_logger("myapp")

# Use the logger
logger.info("Operation completed")
logger.error("Operation failed", exc_info=True)
logger.log_tm1_operation("get_cubes", "production", True, 45.2)
```

---

## Creating Apps

### Embedded App (No Dependencies)

Create a folder in `apps/` without a `requirements.txt`:

```
apps/
  myapp/
    config.json
    handlers.py
```

**config.json:**
```json
{
  "name": "myapp",
  "version": "1.0.0",
  "description": "My embedded app",
  "enabled": true,
  "settings": {
    "log_level": "INFO"
  }
}
```

**handlers.py:**
```python
from pyrest.handlers import BaseHandler
from pyrest.auth import azure_ad_protected

class HelloHandler(BaseHandler):
    async def get(self):
        self.success(data={"message": "Hello!"})

class ProtectedHandler(BaseHandler):
    @azure_ad_protected(["Reader", "Admin"])
    async def get(self):
        self.success(data={
            "user": self._current_user["email"],
            "roles": self._azure_roles
        })

def get_handlers():
    return [
        (r"/", HelloHandler),
        (r"/protected", ProtectedHandler),
    ]
```

### Isolated App (With Dependencies)

Create a folder in `apps/` WITH a `requirements.txt`:

```
apps/
  tm1app/
    config.json
    requirements.txt
    handlers.py
```

**requirements.txt:**
```
tornado>=6.4
PyJWT>=2.8.0
TM1py>=2.0.0
```

The framework will:
1. Create a virtual environment at `apps/tm1app/.venv/`
2. Install the dependencies
3. Spawn the app as a separate process
4. Generate nginx config for routing

---

## API Reference

### Framework Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pyrest/` | GET | API information |
| `/pyrest/health` | GET | Health check |
| `/pyrest/apps` | GET | List all apps |
| `/pyrest/status` | GET | System status |
| `/pyrest/admin` | GET | Admin dashboard |

### Authentication Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pyrest/auth/login` | POST | JWT login |
| `/pyrest/auth/refresh` | POST | Refresh token |
| `/pyrest/auth/me` | GET | Current user info |
| `/pyrest/auth/azure/login` | GET | Start Azure AD flow |
| `/pyrest/auth/azure/callback` | GET | Azure AD callback |

### TM1 Data App Endpoints (Example)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pyrest/tm1data/` | GET | API info and instances |
| `/pyrest/tm1data/instances` | GET | List TM1 instances |
| `/pyrest/tm1data/instance/{name}/cubes` | GET | List cubes |
| `/pyrest/tm1data/instance/{name}/status` | GET | Connection status |
| `/pyrest/tm1data/instance/{name}/query` | POST | Execute MDX query |

---

## Docker Deployment

The image includes `setup_pip.sh`; it is run before venv and pip operations. Edit it before building if you need pip proxy configuration.

### Quick Start

```bash
# Build and run
docker build -t pyrest:latest .
docker run -p 8000:8000 pyrest:latest

# With Docker Compose
docker-compose up -d
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYREST_HOST` | 0.0.0.0 | Host to bind to |
| `PYREST_PORT` | 8000 | Port to listen on |
| `PYREST_DEBUG` | false | Enable debug mode |
| `AZURE_AD_TENANT_ID` | - | Azure AD tenant ID |
| `AZURE_AD_CLIENT_ID` | - | Azure AD client ID |
| `AZURE_AD_CLIENT_SECRET` | - | Azure AD client secret |

---

## Project Structure

```
pyrest/
  main.py                       # Entry point
  config.json                   # Framework configuration
  auth_config.json              # Azure AD configuration
  requirements.txt              # Framework dependencies
  pyrest/                       # Core framework
    __init__.py
    config.py                   # Configuration management
    auth.py                     # Authentication (JWT + Azure AD)
    handlers.py                 # Base handlers
    decorators.py               # Routing decorators
    app_loader.py               # App discovery and loading
    venv_manager.py             # Virtual environment management
    process_manager.py          # Isolated app process management
    nginx_generator.py          # Nginx config generation
    server.py                   # Tornado server
    utils/                      # Shared utilities
      __init__.py
      tm1.py                    # TM1 connection management
      logging.py                # App-specific logging
    admin/                      # Admin dashboard
    templates/                  # App templates
  apps/                         # Your apps go here
    hello/                      # Embedded app example
    tm1data/                    # Isolated app with TM1
  logs/                         # Log files (auto-created)
  nginx/                        # Nginx configuration
```

---

## License

MIT License
