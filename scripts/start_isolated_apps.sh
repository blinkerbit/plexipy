#!/bin/bash
# start_isolated_apps.sh
# Starts isolated PyRest apps that have requirements.txt
# Each app gets its own venv inside the app folder

set -e

APPS_FOLDER="${PYREST_APPS_FOLDER:-/app/apps}"
BASE_PORT="${PYREST_ISOLATED_BASE_PORT:-8001}"
BASE_PATH="${PYREST_BASE_PATH:-/pyrest}"
RUNNER_SCRIPT="/app/pyrest/templates/isolated_app.py"

echo "============================================================"
echo "Starting Isolated Apps"
echo "Apps folder: $APPS_FOLDER"
echo "Base port: $BASE_PORT"
echo "============================================================"

# Check if apps folder exists
if [ ! -d "$APPS_FOLDER" ]; then
    echo "Apps folder not found: $APPS_FOLDER"
    exit 0
fi

# Track current port
current_port=$BASE_PORT

# Iterate through each app folder
for app_dir in "$APPS_FOLDER"/*/; do
    # Skip if not a directory
    [ -d "$app_dir" ] || continue
    
    app_name=$(basename "$app_dir")
    requirements_file="$app_dir/requirements.txt"
    venv_path="$app_dir/.venv"
    python_exe="$venv_path/bin/python"
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Processing app: $app_name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Skip if no requirements.txt (not an isolated app)
    if [ ! -f "$requirements_file" ]; then
        echo "No requirements.txt found - skipping (embedded app)"
        continue
    fi
    
    echo "Found requirements.txt - this is an isolated app"
    
    # Create venv if it doesn't exist or is invalid
    if [ ! -f "$python_exe" ]; then
        echo "Creating venv at: $venv_path"
        
        # Remove existing invalid venv
        if [ -d "$venv_path" ]; then
            echo "Removing invalid venv..."
            rm -rf "$venv_path"
        fi
        
        # Create venv using uv if available, otherwise use python -m venv
        if command -v uv &> /dev/null; then
            echo "Using uv to create venv..."
            uv venv "$venv_path" --python python3
        else
            echo "Using python -m venv..."
            python3 -m venv "$venv_path"
        fi
        
        if [ ! -f "$python_exe" ]; then
            echo "ERROR: Failed to create venv - python not found at $python_exe"
            continue
        fi
        
        echo "Venv created successfully"
    else
        echo "Venv already exists at: $venv_path"
    fi
    
    # Install requirements
    echo "Installing requirements from: $requirements_file"
    
    if command -v uv &> /dev/null; then
        echo "Using uv to install packages..."
        uv pip install --python "$python_exe" -r "$requirements_file"
    else
        echo "Using pip to install packages..."
        "$venv_path/bin/pip" install -r "$requirements_file"
    fi
    
    echo "Requirements installed"
    
    # Start the isolated app
    echo "Starting $app_name on port $current_port..."
    
    # Export environment variables for the app
    export PYREST_APP_NAME="$app_name"
    export PYREST_APP_PATH="$app_dir"
    export PYREST_APP_PORT="$current_port"
    export PYREST_BASE_PATH="$BASE_PATH"
    export VIRTUAL_ENV="$venv_path"
    export PATH="$venv_path/bin:$PATH"
    
    # Start the app in background
    "$python_exe" "$RUNNER_SCRIPT" &
    app_pid=$!
    
    echo "Started $app_name (PID: $app_pid) on port $current_port"
    
    # Increment port for next app
    current_port=$((current_port + 1))
done

echo ""
echo "============================================================"
echo "All isolated apps started"
echo "============================================================"

# Keep script running to maintain background processes
wait
