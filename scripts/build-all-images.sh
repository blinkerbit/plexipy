#!/bin/bash
# build-all-images.sh
# Build Docker images for ALL isolated PyRest apps.
#
# Usage:
#   ./scripts/build-all-images.sh [REGISTRY] [TAG]
#
# Examples:
#   ./scripts/build-all-images.sh                                    # Local only
#   ./scripts/build-all-images.sh myregistry.azurecr.io              # With ACR registry
#   ./scripts/build-all-images.sh myregistry.azurecr.io v1.2.0       # With tag
#   ./scripts/build-all-images.sh myregistry.azurecr.io latest --push  # Build and push
#
# Air-gapped environments:
#   PIP_INDEX_URL=https://pypi.internal.company.com/simple/ \
#   PIP_TRUSTED_HOST=pypi.internal.company.com \
#   ./scripts/build-all-images.sh myregistry.azurecr.io

set -euo pipefail

REGISTRY="${1:-}"
TAG="${2:-latest}"
PUSH="${3:-}"

# Resolve project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APPS_DIR="$PROJECT_ROOT/apps"

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  PyRest - Build All Isolated App Images                  ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

if [ -n "$REGISTRY" ]; then
    echo "Registry: $REGISTRY"
fi
echo "Tag:      $TAG"
echo ""

# Also build the main framework image
echo "============================================================"
echo "Building main framework image..."
echo "============================================================"

if [ -n "$REGISTRY" ]; then
    MAIN_IMAGE="$REGISTRY/pyrest-main:$TAG"
else
    MAIN_IMAGE="pyrest-main:$TAG"
fi

MAIN_BUILD_ARGS=""
if [ -n "${PIP_INDEX_URL:-}" ]; then
    MAIN_BUILD_ARGS="$MAIN_BUILD_ARGS --build-arg PIP_INDEX_URL=$PIP_INDEX_URL"
fi
if [ -n "${PIP_TRUSTED_HOST:-}" ]; then
    MAIN_BUILD_ARGS="$MAIN_BUILD_ARGS --build-arg PIP_TRUSTED_HOST=$PIP_TRUSTED_HOST"
fi

docker build \
    -f "$PROJECT_ROOT/Dockerfile" \
    $MAIN_BUILD_ARGS \
    -t "$MAIN_IMAGE" \
    "$PROJECT_ROOT"

echo "Built: $MAIN_IMAGE"
BUILT_IMAGES=("$MAIN_IMAGE")

# Discover and build isolated apps
ISOLATED_COUNT=0
FAILED_COUNT=0
FAILED_APPS=""

for app_dir in "$APPS_DIR"/*/; do
    [ -d "$app_dir" ] || continue

    app_name=$(basename "$app_dir")

    # Skip non-isolated apps (no requirements.txt) and __pycache__
    [ -f "$app_dir/requirements.txt" ] || continue
    [ "$app_name" != "__pycache__" ] || continue

    echo ""
    echo "============================================================"
    echo "Building: $app_name"
    echo "============================================================"

    if "$SCRIPT_DIR/build-app-image.sh" "$app_name" "$REGISTRY" "$TAG"; then
        ISOLATED_COUNT=$((ISOLATED_COUNT + 1))
        if [ -n "$REGISTRY" ]; then
            BUILT_IMAGES+=("$REGISTRY/pyrest-$app_name:$TAG")
        else
            BUILT_IMAGES+=("pyrest-$app_name:$TAG")
        fi
    else
        FAILED_COUNT=$((FAILED_COUNT + 1))
        FAILED_APPS="$FAILED_APPS $app_name"
        echo "WARNING: Failed to build $app_name"
    fi
done

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  Build Summary                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "  Main framework: 1"
echo "  Isolated apps:  $ISOLATED_COUNT"
echo "  Failed:         $FAILED_COUNT"

if [ $FAILED_COUNT -gt 0 ]; then
    echo "  Failed apps:   $FAILED_APPS"
fi

echo ""
echo "  Images built:"
for img in "${BUILT_IMAGES[@]}"; do
    echo "    - $img"
done

# Push if requested
if [ "$PUSH" = "--push" ] && [ -n "$REGISTRY" ]; then
    echo ""
    echo "Pushing images to $REGISTRY ..."
    for img in "${BUILT_IMAGES[@]}"; do
        echo "  Pushing $img ..."
        docker push "$img"
    done
    echo "All images pushed."
fi

echo ""
