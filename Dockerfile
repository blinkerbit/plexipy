# PyRest Framework Dockerfile
# Single-stage build using Alpine Python with Nginx
#
# Air-gapped / Internal PyPI Proxy Support:
#   Build with: docker build --build-arg PIP_INDEX_URL=https://pypi.internal.company.com/simple/ ...
#   Or set at runtime via environment variables in docker-compose.yml

# =============================================================================
# Single Stage: Alpine Python with Nginx
# =============================================================================
FROM python:3.14-alpine

# Build arguments for internal PyPI proxy (air-gapped environments)
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""

# Labels (single instruction = single layer)
LABEL maintainer="PyRest Team" \
    description="PyRest - Tornado-based REST API Framework with Nginx" \
    version="1.0.0"

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYREST_HOST=0.0.0.0 \
    PYREST_PORT=8000 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

# Install runtime-only system dependencies and create non-root user
# Build tools (gcc, musl-dev, etc.) are installed separately below and removed after use
RUN apk add --no-cache \
    nginx \
    bash \
    && mkdir -p /run/nginx \
    && addgroup -g 1000 pyrest \
    && adduser -u 1000 -G pyrest -s /bin/bash -D pyrest

WORKDIR /app

# Install build deps, Python packages (production only), then strip build deps
# Uses .build-deps virtual package so apk del removes them cleanly (~150 MB saved)
# Only production deps are installed -- pytest/ruff/dev tools stay out of the image
COPY requirements.txt pyproject.toml ./
# hadolint ignore=DL3013,DL3018
RUN apk add --no-cache --virtual .build-deps \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev \
    && pip install --no-cache-dir uv \
    && uv pip install --system --no-cache \
    'tornado>=6.4' 'pydantic>=2.0.0' 'PyJWT>=2.8.0' \
    && apk del --no-network .build-deps

# Copy application code (executables get 755, config/data get 755)
COPY --chown=root:root --chmod=755 pyrest/ ./pyrest/
COPY --chown=root:root --chmod=755 apps/ ./apps/
COPY --chown=root:root --chmod=755 scripts/ ./scripts/
COPY --chown=root:root --chmod=755 main.py .
COPY --chown=root:root --chmod=755 setup_pip.sh .
COPY --chown=root:root --chmod=644 config.json auth_config.json pyproject.toml ./

# Copy nginx configuration
COPY --chown=root:root --chmod=644 nginx/docker-nginx.conf /etc/nginx/nginx.conf

# Create directories, fix Windows line endings, set permissions -- single layer
# No redundant chmod/chown since COPY --chown/--chmod already handled app files
RUN mkdir -p /app/nginx /app/logs /var/log/nginx /etc/nginx/conf.d \
    && sed -i 's/\r$//' /app/setup_pip.sh /app/scripts/*.sh \
    && chown -R pyrest:pyrest /app/nginx /app/logs \
    && chown -R pyrest:pyrest /var/log/nginx /run/nginx /var/lib/nginx \
    && touch /run/nginx/nginx.pid \
    && chown pyrest:pyrest /run/nginx/nginx.pid

# Switch to non-root user before all runtime instructions
USER pyrest

# Expose ports (nginx on 8080/8443, pyrest on 8000)
EXPOSE 8080 8443 8000

# Health check - verify both nginx and pyrest are responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:8080/nginx-health && \
    wget -q --spider http://localhost:8000/pyrest/health || exit 1

# Use custom entrypoint that starts both nginx and pyrest
CMD ["/app/scripts/entrypoint-unified.sh"]
