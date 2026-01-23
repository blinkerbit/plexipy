# PyRest Framework Dockerfile
# Multi-stage build for optimized image size

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.11-slim-buster as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install uv inside venv for fast package management (used for isolated apps too)
RUN pip install --no-cache-dir uv

# Install Python dependencies using uv
COPY requirements.txt .
RUN uv pip install --no-cache -r requirements.txt

# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.11-slim-buster as runtime

# Labels
LABEL maintainer="PyRest Team"
LABEL description="PyRest - Tornado-based REST API Framework"
LABEL version="1.0.0"

# Copy virtual environment from builder (includes uv)
COPY --from=builder /opt/venv /opt/venv

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYREST_HOST=0.0.0.0 \
    PYREST_PORT=8000 \
    PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd --gid 1000 pyrest && \
    useradd --uid 1000 --gid pyrest --shell /bin/bash --create-home pyrest

WORKDIR /app
# Copy application code
COPY --chown=pyrest:pyrest pyrest/ ./pyrest/
COPY --chown=pyrest:pyrest apps/ ./apps/
COPY --chown=pyrest:pyrest scripts/ ./scripts/
COPY --chown=pyrest:pyrest main.py .
COPY --chown=pyrest:pyrest config.json .
COPY --chown=pyrest:pyrest auth_config.json .
COPY --chown=pyrest:pyrest setup_pip.sh ./setup_pip.sh

# Create directories for nginx config and logs, convert scripts to Unix line endings, make executable
RUN mkdir -p /app/nginx /app/logs && \
    sed -i 's/\r$//' /app/setup_pip.sh /app/scripts/*.sh && \
    chmod +x /app/setup_pip.sh && \
    chmod +x /app/scripts/*.sh && \
    chown -R pyrest:pyrest /app

# Switch to non-root user
USER pyrest

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/pyrest/health')" || exit 1

# Default command - uses entrypoint script to start isolated apps first, then main server
CMD ["/app/scripts/entrypoint.sh"]
