#!/bin/bash
# Lint Dockerfile using hadolint
# Usage: ./scripts/lint-dockerfile.sh [Dockerfile path]

set -e

DOCKERFILE="${1:-Dockerfile}"
HADOLINT_IMAGE="hadolint/hadolint:latest"

echo "Linting Dockerfile: $DOCKERFILE"

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed or not in PATH"
    echo "Please install Docker or use hadolint directly"
    exit 1
fi

# Run hadolint via Docker
if [ -f ".hadolint.yaml" ]; then
    echo "Using .hadolint.yaml configuration"
    docker run --rm -i \
        -v "$(pwd)/.hadolint.yaml:/root/.hadolint.yaml" \
        "$HADOLINT_IMAGE" < "$DOCKERFILE"
else
    echo "No .hadolint.yaml found, using default rules"
    docker run --rm -i "$HADOLINT_IMAGE" < "$DOCKERFILE"
fi

echo "✓ Dockerfile linting passed!"
