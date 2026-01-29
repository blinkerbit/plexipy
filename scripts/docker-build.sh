#!/bin/bash
# Build Docker image for PyRest
# Single Alpine container with Python + Nginx

set -e

echo "=========================================="
echo "Building PyRest Docker Image"
echo "(Alpine Python + Nginx)"
echo "=========================================="

# Build main PyRest image
echo ""
echo "Building PyRest unified image..."
docker build -t pyrest:latest -f Dockerfile .

echo ""
echo "Build complete!"
echo ""
echo "To run:"
echo "  docker run -p 8000:8000 pyrest:latest"
echo ""
echo "Or use docker-compose:"
echo "  docker-compose up -d"
