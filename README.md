# PyRest Framework

A modular, Tornado-based REST API framework designed to replace TM1 TurboIntegrator with a modern, extensible Python solution. Supports both embedded and isolated apps with automatic virtual environment management and Azure AD authentication.

## Features

- **Modular App Architecture**: Drop apps into the `apps/` folder and they're automatically discovered
- **Embedded Apps**: Simple apps run within the main process (no `requirements.txt`)
- **Isolated Apps**: Apps with dependencies run in separate processes with their own virtual environment
- **Azure AD Authentication**: Centralized OAuth 2.0 authentication for all apps
- **JWT Support**: Token-based authentication with automatic validation
- **Automatic Venv Management**: Framework creates and manages virtual environments for isolated apps
- **Nginx Config Generation**: Automatically generates nginx reverse proxy configuration
- **Simple Decorators**: Easy-to-use decorators for defining REST endpoints

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Nginx (Port 80/443)                       │
│                 Reverse Proxy for all /pyrest/* routes           │
└─────────────────────────────────────────────────────────────────┘
                                    │
                ┌───────────────────┴───────────────────┐
                │                                       │
                ▼                                       ▼
┌─────────────────────────────┐       ┌─────────────────────────────┐
│   Main PyRest (Port 8000)   │       │  Isolated Apps (Port 8001+) │
│                             │       │                             │
│  • Framework endpoints      │       │  • Own virtual environment  │
│  • Auth endpoints           │       │  • Own dependencies         │
│  • Embedded apps            │       │  • Separate process         │
└─────────────────────────────┘       └─────────────────────────────┘
```

## URL Structure

All endpoints are served under `/pyrest/`:

```
/pyrest/                    - API info
/pyrest/health              - Health check
/pyrest/apps                - List all apps
/pyrest/status              - System status (embedded + isolated apps)
/pyrest/admin               - Admin Dashboard UI
/pyrest/auth/login          - JWT login
/pyrest/auth/azure/login    - Azure AD OAuth login
/pyrest/<app_name>/...      - App-specific endpoints
```

## Admin Dashboard

PyRest includes a built-in admin dashboard for monitoring and managing the framework.

**Access**: `http://localhost:8000/pyrest/admin`

### Features

- **Dashboard**: View system stats, app counts, and quick links
- **Applications**: See all embedded and isolated apps, start/stop/restart isolated apps
- **Settings**: View and modify framework configuration
- **Authentication**: View Azure AD configuration status
- **Logs**: View recent log entries

### Admin API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pyrest/admin/api/status` | GET | Full system status |
| `/pyrest/admin/api/config` | GET/PUT | Framework configuration |
| `/pyrest/admin/api/auth-config` | GET | Auth configuration (masked) |
| `/pyrest/admin/api/apps` | GET | List all apps |
| `/pyrest/admin/api/apps/{name}` | GET | App details |
| `/pyrest/admin/api/apps/{name}/start` | POST | Start isolated app |
| `/pyrest/admin/api/apps/{name}/stop` | POST | Stop isolated app |
| `/pyrest/admin/api/apps/{name}/restart` | POST | Restart isolated app |

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repository-url>
cd pyrest

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Copy and edit the configuration files:

```bash
# Edit main config
# config.json - Framework settings

# Edit auth config for Azure AD
# auth_config.json - Azure AD credentials
```

### 3. Run the Server

```bash
python main.py
```

The server will start at `http://localhost:8000/pyrest`

## Creating Apps

### Embedded App (No Dependencies)

Create a folder in `apps/` without a `requirements.txt`:

```
apps/
  └── myapp/
      ├── config.json
      └── handlers.py
```

**config.json:**
```json
{
  "name": "myapp",
  "version": "1.0.0",
  "description": "My embedded app",
  "enabled": true
}
```

**handlers.py:**
```python
from pyrest.handlers import BaseHandler
from pyrest.auth import authenticated

class HelloHandler(BaseHandler):
    async def get(self):
        self.success(data={"message": "Hello from embedded app!"})

class ProtectedHandler(BaseHandler):
    @authenticated
    async def get(self):
        self.success(data={"user": self.current_user})

def get_handlers():
    return [
        (r"/", HelloHandler),
        (r"/protected", ProtectedHandler),
    ]
```

Your app will be available at `http://localhost:8000/pyrest/myapp/`

### Isolated App (With Dependencies)

Create a folder in `apps/` WITH a `requirements.txt`:

```
apps/
  └── tm1app/
      ├── config.json
      ├── requirements.txt    # <-- Triggers isolated mode
      └── handlers.py
```

**config.json:**
```json
{
  "name": "tm1app",
  "version": "1.0.0",
  "description": "TM1 API app",
  "enabled": true,
  "port": 8001
}
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
3. Spawn the app as a separate process on the specified port
4. Generate nginx config to route `/pyrest/tm1app/*` to port 8001

## Authentication

### Azure AD Setup

1. Go to Azure Portal > Azure Active Directory > App registrations
2. Create a new registration
3. Add redirect URI: `http://localhost:8000/pyrest/auth/azure/callback`
4. Create a client secret
5. Update `auth_config.json`:

```json
{
  "provider": "azure_ad",
  "tenant_id": "your-tenant-id",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "redirect_uri": "http://localhost:8000/pyrest/auth/azure/callback",
  "scopes": ["openid", "profile", "email"]
}
```

### Using Authentication in Handlers

```python
from pyrest.handlers import BaseHandler
from pyrest.auth import authenticated, require_roles

class MyHandler(BaseHandler):
    @authenticated
    async def get(self):
        user = self.current_user
        self.success(data={"user": user})
    
    @authenticated
    @require_roles("admin")
    async def post(self):
        # Only admins can access
        ...
```

## API Endpoints

### Framework Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pyrest/` | GET | API information |
| `/pyrest/health` | GET | Health check |
| `/pyrest/apps` | GET | List all apps |
| `/pyrest/status` | GET | System status |

### Authentication Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pyrest/auth/register` | POST | Register new user |
| `/pyrest/auth/login` | POST | JWT login |
| `/pyrest/auth/refresh` | POST | Refresh token |
| `/pyrest/auth/me` | GET | Get current user |
| `/pyrest/auth/azure/login` | GET | Start Azure AD flow |
| `/pyrest/auth/azure/callback` | GET | Azure AD callback |

## Nginx Setup

The framework automatically generates nginx configuration at `nginx/pyrest_generated.conf`:

```bash
# Copy to nginx
sudo cp nginx/pyrest_generated.conf /etc/nginx/sites-available/pyrest.conf

# Enable
sudo ln -s /etc/nginx/sites-available/pyrest.conf /etc/nginx/sites-enabled/

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

## Command Line Options

```bash
python main.py --help

Options:
  --host HOST           Host to bind to (default: 0.0.0.0)
  --port PORT           Port to listen on (default: 8000)
  --debug               Enable debug mode
  --no-isolated         Skip isolated app setup
  --no-nginx            Skip nginx config generation
  --config FILE         Path to config file
```

## Project Structure

```
pyrest/
├── main.py                     # Entry point
├── config.json                 # Framework configuration
├── auth_config.json            # Azure AD configuration
├── requirements.txt            # Framework dependencies
├── pyrest/                     # Core framework
│   ├── __init__.py
│   ├── config.py               # Configuration management
│   ├── auth.py                 # Authentication (JWT + Azure AD)
│   ├── handlers.py             # Base handlers
│   ├── decorators.py           # Routing decorators
│   ├── app_loader.py           # App discovery
│   ├── venv_manager.py         # Virtual environment management
│   ├── process_manager.py      # Isolated app process management
│   ├── nginx_generator.py      # Nginx config generation
│   ├── server.py               # Tornado server
│   └── templates/
│       └── isolated_app.py     # Isolated app runner template
├── apps/                       # Your apps go here
│   ├── hello/                  # Embedded app example
│   └── tm1data/                # Isolated app example
└── nginx/
    └── pyrest_generated.conf   # Auto-generated nginx config
```

## TM1py Integration

For apps that need TM1 connectivity, create an isolated app with `TM1py` in requirements.txt. See `apps/tm1data/` for an example.

```python
from TM1py import TM1Service

# Connect to TM1
tm1 = TM1Service(
    address="localhost",
    port=8010,
    ssl=True,
    user="admin",
    password="password"
)

# Use TM1 API
cubes = tm1.cubes.get_all_names()
```

## Docker Deployment

### Quick Start with Docker

```bash
# Build the image
docker build -t pyrest:latest .

# Run the container
docker run -p 8000:8000 pyrest:latest

# Access the API
curl http://localhost:8000/pyrest/health
```

### Docker Compose (Recommended)

```bash
# Start all services (PyRest + Nginx)
docker-compose up -d

# View logs
docker-compose logs -f pyrest

# Stop all services
docker-compose down
```

### Development with Docker

```bash
# Use development compose file (hot reload, debug mode)
docker-compose -f docker-compose.dev.yml up -d
```

### Docker Files

| File | Description |
|------|-------------|
| `Dockerfile` | Main PyRest image (multi-stage build) |
| `Dockerfile.isolated` | Base image for isolated apps |
| `docker-compose.yml` | Production setup with nginx |
| `docker-compose.dev.yml` | Development setup with hot reload |
| `.dockerignore` | Files excluded from Docker build |
| `nginx/docker-nginx.conf` | Nginx config for Docker |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYREST_HOST` | 0.0.0.0 | Host to bind to |
| `PYREST_PORT` | 8000 | Port to listen on |
| `PYREST_DEBUG` | false | Enable debug mode |

### Building Isolated App Images

```bash
# Build an isolated app image
docker build \
  --build-arg APP_NAME=tm1data \
  --build-arg APP_PORT=8001 \
  -t pyrest-tm1data:latest \
  -f Dockerfile.isolated .

# Run it
docker run -p 8001:8001 pyrest-tm1data:latest
```

## License

MIT License
