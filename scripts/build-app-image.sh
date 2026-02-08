#!/bin/bash
# build-app-image.sh
# Build a Docker image for a single isolated PyRest app.
#
# Usage:
#   ./scripts/build-app-image.sh <APP_NAME> [REGISTRY] [TAG]
#
# Examples:
#   ./scripts/build-app-image.sh tm1data
#   ./scripts/build-app-image.sh tm1data myregistry.azurecr.io
#   ./scripts/build-app-image.sh pov myregistry.azurecr.io v1.2.0
#
# Air-gapped environments:
#   PIP_INDEX_URL=https://pypi.internal.company.com/simple/ \
#   PIP_TRUSTED_HOST=pypi.internal.company.com \
#   ./scripts/build-app-image.sh tm1data

set -euo pipefail

APP_NAME="${1:?Usage: build-app-image.sh <APP_NAME> [REGISTRY] [TAG]}"
REGISTRY="${2:-}"
TAG="${3:-latest}"

# Resolve project root (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Validate app exists
APP_DIR="$PROJECT_ROOT/apps/$APP_NAME"
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: App directory not found: $APP_DIR"
    echo "Available apps:"
    ls -1 "$PROJECT_ROOT/apps/" 2>/dev/null | grep -v __pycache__ || echo "  (none)"
    exit 1
fi

if [ ! -f "$APP_DIR/requirements.txt" ]; then
    echo "ERROR: $APP_NAME does not have a requirements.txt (not an isolated app)"
    exit 1
fi

# Build image name
if [ -n "$REGISTRY" ]; then
    IMAGE_NAME="$REGISTRY/pyrest-$APP_NAME:$TAG"
else
    IMAGE_NAME="pyrest-$APP_NAME:$TAG"
fi

echo ""
echo "============================================================"
echo "Building: $IMAGE_NAME"
echo "App:      $APP_NAME"
echo "Context:  $PROJECT_ROOT"
echo "============================================================"
echo ""

# Build args for PyPI proxy (if set in environment)
BUILD_ARGS="--build-arg APP_NAME=$APP_NAME"

if [ -n "${PIP_INDEX_URL:-}" ]; then
    BUILD_ARGS="$BUILD_ARGS --build-arg PIP_INDEX_URL=$PIP_INDEX_URL"
    echo "Using PyPI index: $PIP_INDEX_URL"
fi

if [ -n "${PIP_TRUSTED_HOST:-}" ]; then
    BUILD_ARGS="$BUILD_ARGS --build-arg PIP_TRUSTED_HOST=$PIP_TRUSTED_HOST"
fi

# Build
docker build \
    -f "$PROJECT_ROOT/Dockerfile.isolated" \
    $BUILD_ARGS \
    -t "$IMAGE_NAME" \
    "$PROJECT_ROOT"

echo ""
echo "============================================================"
echo "Built successfully: $IMAGE_NAME"
echo "============================================================"
echo ""
echo "Run locally:"
echo "  docker run -p 8001:8001 $IMAGE_NAME"
echo ""
echo "Push to registry:"
echo "  docker push $IMAGE_NAME"
echo ""
