#!/bin/bash
# Lint both Python code and Dockerfile
# Usage: ./scripts/lint-all.sh

set -e

echo "=========================================="
echo "Running all linting checks"
echo "=========================================="
echo ""

# Check Python linting
if command -v ruff &> /dev/null; then
    echo "1. Linting Python code with ruff..."
    ruff check pyrest/ apps/ main.py
    echo "✓ Python linting passed!"
    echo ""
else
    echo "⚠ ruff not found, skipping Python linting"
    echo "  Install with: pip install ruff"
    echo ""
fi

# Check Dockerfile linting
if command -v docker &> /dev/null; then
    echo "2. Linting Dockerfile with hadolint..."
    ./scripts/lint-dockerfile.sh
    echo ""
else
    echo "⚠ Docker not found, skipping Dockerfile linting"
    echo ""
fi

echo "=========================================="
echo "All linting checks completed!"
echo "=========================================="
