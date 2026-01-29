# PyRest Framework Dockerfile
# Single-stage build using Alpine Python with Nginx
#
# Air-gapped / Internal PyPI Proxy Support:
#   Build with: docker build --build-arg PIP_INDEX_URL=https://pypi.internal.company.com/simple/ ...
#   Or set at runtime via environment variables in docker-compose.yml

# =============================================================================
# Single Stage: Alpine Python with Nginx
# =============================================================================
FROM python:3.11-alpine

# Build arguments for internal PyPI proxy (air-gapped environments)
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""

# Labels
LABEL maintainer="PyRest Team"
LABEL description="PyRest - Tornado-based REST API Framework with Nginx"
LABEL version="1.0.0"

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYREST_HOST=0.0.0.0 \
    PYREST_PORT=8000 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

# Install system dependencies including nginx and build tools
RUN apk add --no-cache \
    nginx \
    bash \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev \
    && mkdir -p /run/nginx \
    && rm -rf /var/cache/apk/*

# Create non-root user
RUN addgroup -g 1000 pyrest && \
    adduser -u 1000 -G pyrest -s /bin/bash -D pyrest

WORKDIR /app

# Install uv for fast package management
RUN pip install --no-cache-dir uv

# Copy and install Python dependencies
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application code
COPY --chown=pyrest:pyrest pyrest/ ./pyrest/
COPY --chown=pyrest:pyrest apps/ ./apps/
COPY --chown=pyrest:pyrest scripts/ ./scripts/
COPY --chown=pyrest:pyrest main.py .
COPY --chown=pyrest:pyrest config.json .
COPY --chown=pyrest:pyrest auth_config.json .
COPY --chown=pyrest:pyrest setup_pip.sh ./setup_pip.sh

# Copy nginx configuration
COPY --chown=pyrest:pyrest nginx/docker-nginx.conf /etc/nginx/nginx.conf

# Create directories for nginx config, logs, and PID
# Set proper permissions for nginx to run
RUN mkdir -p /app/nginx /app/logs /var/log/nginx /run/nginx /etc/nginx/conf.d && \
    sed -i 's/\r$//' /app/setup_pip.sh /app/scripts/*.sh && \
    chmod +x /app/setup_pip.sh && \
    chmod +x /app/scripts/*.sh && \
    chown -R pyrest:pyrest /app && \
    chown -R pyrest:pyrest /var/log/nginx && \
    chown -R pyrest:pyrest /run/nginx && \
    chown -R pyrest:pyrest /var/lib/nginx && \
    chown -R pyrest:pyrest /etc/nginx && \
    touch /run/nginx/nginx.pid && \
    chown pyrest:pyrest /run/nginx/nginx.pid

# Expose ports (nginx on 80/443, pyrest on 8000)
EXPOSE 80 443 8000

# Health check - check nginx and pyrest
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost/nginx-health && \
    wget -q --spider http://localhost:8000/pyrest/health || exit 1

# Use custom entrypoint that starts both nginx and pyrest
CMD ["/app/scripts/entrypoint-unified.sh"]
