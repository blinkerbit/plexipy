#!/bin/bash
# Build Docker images for PyRest

set -e

echo "=========================================="
echo "Building PyRest Docker Images"
echo "=========================================="

# Build main PyRest image
echo ""
echo "Building main PyRest image..."
docker build -t pyrest:latest -f Dockerfile .

echo ""
echo "Build complete!"
echo ""
echo "To run:"
echo "  docker run -p 8000:8000 pyrest:latest"
echo ""
echo "Or use docker-compose:"
echo "  docker-compose up -d"
