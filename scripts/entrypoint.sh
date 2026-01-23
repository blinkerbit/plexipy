#!/bin/bash
# entrypoint.sh
# Main entrypoint for PyRest Docker container
# Starts isolated apps first, then the main PyRest server

set -e

APPS_FOLDER="${PYREST_APPS_FOLDER:-/app/apps}"
BASE_PORT="${PYREST_ISOLATED_BASE_PORT:-8001}"
BASE_PATH="${PYREST_BASE_PATH:-/pyrest}"
RUNNER_SCRIPT="/app/pyrest/templates/isolated_app.py"

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
echo "║   Version 1.0.0                                           ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

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
    if [ ! -f "$python_exe" ]; then
        echo "Creating venv at: $venv_path"
        
        # Remove existing invalid venv
        [ -d "$venv_path" ] && rm -rf "$venv_path"
        
        # Create venv using uv if available
        if command -v uv &> /dev/null; then
            uv venv "$venv_path" --python python3
        else
            python3 -m venv "$venv_path"
        fi
        
        if [ ! -f "$python_exe" ]; then
            echo "ERROR: Failed to create venv for $app_name"
            return 1
        fi
    fi
    
    # Install requirements
    echo "Installing requirements..."
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
}

# Start isolated apps first
echo "============================================================"
echo "Starting Isolated Apps"
echo "============================================================"

current_port=$BASE_PORT
isolated_count=0

if [ -d "$APPS_FOLDER" ]; then
    for app_dir in "$APPS_FOLDER"/*/; do
        [ -d "$app_dir" ] || continue
        
        requirements_file="$app_dir/requirements.txt"
        
        # Only process apps with requirements.txt (isolated apps)
        if [ -f "$requirements_file" ]; then
            start_isolated_app "$app_dir" "$current_port"
            current_port=$((current_port + 1))
            isolated_count=$((isolated_count + 1))
        fi
    done
fi

if [ $isolated_count -eq 0 ]; then
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

echo ""
echo "============================================================"
echo "Starting Main PyRest Server"
echo "============================================================"

# Start the main PyRest server (foreground)
# --no-isolated: shell script already started isolated apps
exec python3 /app/main.py --no-isolated
