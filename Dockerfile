# PyRest Framework Dockerfile
# Multi-stage build for optimized image size

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.11-slim as runtime

# Labels
LABEL maintainer="PyRest Team"
LABEL description="PyRest - Tornado-based REST API Framework"
LABEL version="1.0.0"

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYREST_HOST=0.0.0.0 \
    PYREST_PORT=8000

# Create non-root user
RUN groupadd --gid 1000 pyrest && \
    useradd --uid 1000 --gid pyrest --shell /bin/bash --create-home pyrest

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --chown=pyrest:pyrest pyrest/ ./pyrest/
COPY --chown=pyrest:pyrest apps/ ./apps/
COPY --chown=pyrest:pyrest main.py .
COPY --chown=pyrest:pyrest config.json .
COPY --chown=pyrest:pyrest auth_config.json .
COPY --chown=pyrest:pyrest setup_pip.sh ./setup_pip.sh

# Create directories for nginx config and logs, make setup_pip.sh executable
RUN mkdir -p /app/nginx /app/logs && \
    chmod +x /app/setup_pip.sh && \
    chown -R pyrest:pyrest /app

# Switch to non-root user
USER pyrest

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/pyrest/health')" || exit 1

# Default command
CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8000"]
