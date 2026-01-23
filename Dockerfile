# PyRest Framework Dockerfile
# Multi-stage build for optimized image size
#
# Air-gapped / Internal PyPI Proxy Support:
#   Build with: docker build --build-arg PIP_INDEX_URL=https://pypi.internal.company.com/simple/ ...
#   Or set at runtime via environment variables in docker-compose.yml

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.11-slim-bookworm as builder

# Build arguments for internal PyPI proxy (air-gapped environments)
# Only PIP_INDEX_URL needed - uv automatically respects this variable
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""

# Set pip/uv environment for build stage (uv uses PIP_INDEX_URL automatically)
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install uv inside venv for fast package management (used for isolated apps too)
# Uses PIP_INDEX_URL if set
RUN pip install --no-cache-dir uv

# Install Python dependencies using uv
# Uses UV_INDEX_URL if set
COPY requirements.txt .
RUN uv pip install --no-cache -r requirements.txt

# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.11-slim-bookworm as runtime

# Build arguments for internal PyPI proxy (air-gapped environments)
# These can be set at build time or overridden at runtime via environment
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""

# Labels
LABEL maintainer="PyRest Team"
LABEL description="PyRest - Tornado-based REST API Framework"
LABEL version="1.0.0"

# Copy virtual environment from builder (includes uv)
COPY --from=builder /opt/venv /opt/venv

# Environment variables
# PIP_INDEX_URL and PIP_TRUSTED_HOST set from build args (can be overridden at runtime)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYREST_HOST=0.0.0.0 \
    PYREST_PORT=8000 \
    PATH="/opt/venv/bin:$PATH" \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

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
