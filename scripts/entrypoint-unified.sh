#!/bin/bash
# entrypoint-unified.sh
# Unified entrypoint for PyRest Docker container with embedded Nginx
# Starts nginx, isolated apps, and the main PyRest server
#
# Air-gapped / Internal PyPI Proxy Support:
#   Set these environment variables in docker-compose.yml:
#   - PIP_INDEX_URL: https://pypi.internal.company.com/simple/
#   - PIP_TRUSTED_HOST: pypi.internal.company.com
#   (uv automatically uses PIP_INDEX_URL - no separate config needed)

set -e

APPS_FOLDER="${PYREST_APPS_FOLDER:-/app/apps}"
BASE_PORT="${PYREST_ISOLATED_BASE_PORT:-8001}"
BASE_PATH="${PYREST_BASE_PATH:-/pyrest}"
RUNNER_SCRIPT="/app/pyrest/templates/isolated_app.py"

# PyPI proxy settings (for air-gapped environments)
# Both pip and uv respect these env vars automatically:
#   - PIP_INDEX_URL
#   - PIP_TRUSTED_HOST

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║   ██████╗ ██╗   ██╗██████╗ ███████╗███████╗████████╗     ║"
echo "║   ██╔══██╗╚██╗ ██╔╝██╔══██╗██╔════╝██╔════╝╚══██╔══╝     ║"
echo "║   ██████╔╝ ╚████╔╝ ██████╔╝█████╗  ███████╗   ██║        ║"
echo "║   ██╔═══╝   ╚██╔╝  ██╔══██╗██╔══╝  ╚════██║   ██║        ║"
echo "║   ██║        ██║   ██║  ██║███████╗███████║   ██║        ║"
echo "║   ╚═╝        ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝   ╚═╝        ║"
echo "║                                                           ║"
echo "║   Tornado-based REST API Framework                        ║"
echo "║   Version 1.0.0 (Alpine + Nginx Unified)                  ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Trap signals for graceful shutdown
cleanup() {
    echo ""
    echo "Shutting down..."
    # Stop nginx
    if [[ -f /run/nginx/nginx.pid ]]; then
        nginx -s quit 2>/dev/null || true
    fi
    # Kill background processes
    jobs -p | xargs -r kill 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT SIGQUIT

# Function to setup and start an isolated app
start_isolated_app() {
    local app_dir="$1"
    local port="$2"
    local app_name=$(basename "$app_dir")
    local requirements_file="$app_dir/requirements.txt"
    local venv_path="$app_dir/.venv"
    local python_exe="$venv_path/bin/python"
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Setting up isolated app: $app_name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Create venv if needed
    if [[ ! -f "$python_exe" ]]; then
        echo "Creating venv at: $venv_path"
        
        # Remove existing invalid venv
        [[ -d "$venv_path" ]] && rm -rf "$venv_path"
        
        # Create venv using uv if available
        if command -v uv &> /dev/null; then
            uv venv "$venv_path" --python python3
        else
            python3 -m venv "$venv_path"
        fi
        
        if [[ ! -f "$python_exe" ]]; then
            echo "ERROR: Failed to create venv for $app_name" >&2
            return 1
        fi
    fi
    
    # Install requirements (supports internal PyPI proxy for air-gapped environments)
    # Both pip and uv respect PIP_INDEX_URL and PIP_TRUSTED_HOST env vars
    echo "Installing requirements..."
    
    if [[ -n "$PIP_INDEX_URL" ]]; then
        echo "  Using PyPI index: $PIP_INDEX_URL"
    fi
    
    if command -v uv &> /dev/null; then
        uv pip install --python "$python_exe" -r "$requirements_file" 2>&1 | tail -5
    else
        "$venv_path/bin/pip" install -q -r "$requirements_file"
    fi
    
    # Start the app in background with nohup to prevent SIGHUP termination
    echo "Starting $app_name on port $port..."
    
    # Create log directory
    mkdir -p /app/logs
    
    PYREST_APP_NAME="$app_name" \
    PYREST_APP_PATH="$app_dir" \
    PYREST_APP_PORT="$port" \
    PYREST_BASE_PATH="$BASE_PATH" \
    VIRTUAL_ENV="$venv_path" \
    PATH="$venv_path/bin:$PATH" \
    nohup "$python_exe" "$RUNNER_SCRIPT" >> "/app/logs/${app_name}.log" 2>&1 &
    
    local app_pid=$!
    echo "✓ $app_name started (PID: $app_pid) on port $port"
    echo "  Log: /app/logs/${app_name}.log"
    return 0
}

# =============================================================================
# Start Nginx
# =============================================================================
echo "============================================================"
echo "Starting Nginx"
echo "============================================================"

# Ensure nginx conf.d directory exists
mkdir -p /etc/nginx/conf.d

# Copy generated nginx config if it exists
if [[ -f "/app/nginx/pyrest_generated.conf" ]]; then
    # Copy and fix upstream addresses for unified container mode
    # Replace 'server pyrest:' with 'server 127.0.0.1:' since nginx and pyrest are on same host
    sed 's/server pyrest:/server 127.0.0.1:/g' /app/nginx/pyrest_generated.conf > /etc/nginx/conf.d/pyrest.conf
    echo "✓ Loaded PyRest nginx configuration (unified mode)"
else
    echo "  No pyrest_generated.conf found (will be generated on first run)"
    # Create a minimal fallback config
    cat > /etc/nginx/conf.d/pyrest.conf << 'EOF'
# Fallback config - PyRest will generate full config on startup
upstream pyrest_main {
    server 127.0.0.1:8000;
    keepalive 64;
}

server {
    listen 8080 default_server;
    listen [::]:8080 default_server;
    server_name _;

    location /nginx-health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    location /pyrest/ {
        proxy_pass http://pyrest_main;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = / {
        return 301 /pyrest/;
    }
}
EOF
    echo "✓ Created fallback nginx configuration"
fi

# Start nginx in background
nginx -g "daemon off;" &
NGINX_PID=$!
echo "✓ Nginx started (PID: $NGINX_PID)"

# Give nginx a moment to start
sleep 1

# Verify nginx is running
if ! kill -0 $NGINX_PID 2>/dev/null; then
    echo "ERROR: Nginx failed to start!" >&2
    cat /var/log/nginx/error.log 2>/dev/null || true
    exit 1
fi

# =============================================================================
# Start Isolated Apps
# =============================================================================
echo ""
echo "============================================================"
echo "Starting Isolated Apps"
echo "============================================================"

current_port=$BASE_PORT
isolated_count=0

if [[ -d "$APPS_FOLDER" ]]; then
    # Sort apps alphabetically to ensure consistent port assignment with Python
    for app_dir in $(find "$APPS_FOLDER" -mindepth 1 -maxdepth 1 -type d | sort); do
        [[ -d "$app_dir" ]] || continue
        
        requirements_file="$app_dir/requirements.txt"
        
        # Only process apps with requirements.txt (isolated apps)
        if [[ -f "$requirements_file" ]]; then
            start_isolated_app "$app_dir" "$current_port"
            current_port=$((current_port + 1))
            isolated_count=$((isolated_count + 1))
        fi
    done
fi

if [[ $isolated_count -eq 0 ]]; then
    echo "No isolated apps found"
else
    echo ""
    echo "Started $isolated_count isolated app(s)"
    
    # Give isolated apps a moment to start
    sleep 2
    
    # Verify background processes are running
    echo ""
    echo "Verifying isolated apps..."
    ps aux | grep "[p]ython.*isolated_app" || echo "  (no processes found yet)"
    echo ""
fi

# =============================================================================
# Start Main PyRest Server
# =============================================================================
echo ""
echo "============================================================"
echo "Starting Main PyRest Server"
echo "============================================================"

# Start the main PyRest server in foreground
# --no-isolated: shell script already started isolated apps
python3 /app/main.py --no-isolated &
PYREST_PID=$!

echo "✓ PyRest started (PID: $PYREST_PID)"

# Wait for PyRest to generate the nginx config and reload nginx
echo ""
echo "Waiting for PyRest to generate nginx configuration..."
sleep 5

if [[ -f "/app/nginx/pyrest_generated.conf" ]]; then
    echo "Reloading nginx with updated configuration..."
    # Copy and fix upstream addresses for unified container mode
    sed 's/server pyrest:/server 127.0.0.1:/g' /app/nginx/pyrest_generated.conf > /etc/nginx/conf.d/pyrest.conf
    nginx -s reload
    echo "✓ Nginx reloaded with PyRest configuration"
fi

echo ""
echo "============================================================"
echo "All services started successfully!"
echo "============================================================"
echo ""
echo "  Nginx:     http://localhost:8080"
echo "  PyRest:    http://localhost:8000"
echo ""

# Wait for any process to exit
wait -n || true

# If we get here, something exited - shutdown gracefully
cleanup
