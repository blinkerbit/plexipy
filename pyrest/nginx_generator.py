"""
Nginx Configuration Generator for PyRest framework.
Generates nginx configuration for routing to embedded and isolated apps.
"""

import asyncio
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from .app_loader import AppConfig
from .config import get_config

logger = logging.getLogger("pyrest.nginx_generator")


class NginxGenerator:
    """
    Generates nginx configuration files for PyRest apps.
    """

    def __init__(self, output_dir: str = "nginx", docker_mode: bool | None = None):
        self.config = get_config()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Detect Docker mode if not explicitly set
        if docker_mode is None:
            # Check for Docker environment indicators
            docker_mode = (
                Path("/.dockerenv").exists()  # Inside Docker container
                or os.environ.get("DOCKER_MODE", "").lower() == "true"
                or os.environ.get("PYREST_DOCKER", "").lower() == "true"
            )

        self.docker_mode = docker_mode
        self.main_service_name = os.environ.get("PYREST_MAIN_SERVICE", "pyrest")
        self.isolated_service_prefix = os.environ.get("PYREST_ISOLATED_SERVICE_PREFIX", "")

    def generate_upstream_config(self, main_port: int, isolated_apps: list[AppConfig]) -> str:
        """Generate nginx upstream blocks."""
        lines = [
            "# PyRest Upstream Configuration",
            f"# Generated: {datetime.now().isoformat()}",
            f"# Docker mode: {self.docker_mode}",
            "",
            "# Main PyRest server",
            "upstream pyrest_main {",
        ]

        # Use service name in Docker, localhost otherwise
        if self.docker_mode:
            main_server = f"{self.main_service_name}:{main_port}"
        else:
            main_server = f"127.0.0.1:{main_port}"

        lines.extend([f"    server {main_server};", "    keepalive 64;", "}", ""])

        # Add upstream for each isolated app
        for app in isolated_apps:
            if app.port:
                # In Docker, isolated apps might be in separate containers
                # Use service name if prefix is set, otherwise assume same container
                if self.docker_mode and self.isolated_service_prefix:
                    isolated_server = f"{self.isolated_service_prefix}{app.name}:{app.port}"
                elif self.docker_mode:
                    # Same container, use service name or localhost
                    isolated_server = f"{self.main_service_name}:{app.port}"
                else:
                    isolated_server = f"127.0.0.1:{app.port}"

                lines.extend(
                    [
                        f"# Isolated app: {app.name}",
                        f"upstream pyrest_{app.name} {{",
                        f"    server {isolated_server};",
                        "    keepalive 32;",
                        "}",
                        "",
                    ]
                )

        return "\n".join(lines)

    def generate_location_config(
        self, base_path: str, embedded_apps: list[AppConfig], isolated_apps: list[AppConfig]
    ) -> str:
        """Generate nginx location blocks for routing."""
        lines = [
            "# PyRest Location Configuration",
            f"# Generated: {datetime.now().isoformat()}",
            "",
            "# Proxy settings",
            "proxy_http_version 1.1;",
            "proxy_set_header Host $host;",
            "proxy_set_header X-Real-IP $remote_addr;",
            "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            "proxy_set_header X-Forwarded-Proto $scheme;",
            "proxy_set_header Upgrade $http_upgrade;",
            'proxy_set_header Connection "upgrade";',
            "proxy_connect_timeout 60s;",
            "proxy_send_timeout 60s;",
            "proxy_read_timeout 60s;",
            "proxy_buffering off;",
            "",
        ]

        # Add locations for isolated apps first (more specific routes)
        for app in isolated_apps:
            if app.port:
                prefix = app.prefix.rstrip("/")
                lines.extend(
                    [
                        f"# Isolated app: {app.name}",
                        f"location {base_path}{prefix}/ {{",
                        f"    proxy_pass http://pyrest_{app.name};",
                        "}",
                        "",
                    ]
                )

        # Add catch-all location for main server (embedded apps)
        lines.extend(
            [
                "# Main PyRest server (embedded apps + framework endpoints)",
                f"location {base_path}/ {{",
                "    proxy_pass http://pyrest_main;",
                "}",
                "",
            ]
        )

        return "\n".join(lines)

    def generate_full_config(
        self,
        main_port: int,
        embedded_apps: list[AppConfig],
        isolated_apps: list[AppConfig],
        server_name: str = "localhost",
        listen_port: int = 8080,
    ) -> str:
        """Generate complete nginx server configuration."""
        base_path = self.config.base_path

        lines = [
            "# PyRest Nginx Configuration",
            f"# Generated: {datetime.now().isoformat()}",
            "#",
            "# This file is auto-generated by PyRest.",
            "# Include this file in your nginx.conf or copy to sites-available.",
            "#",
            "# Installation:",
            "#   1. Copy to /etc/nginx/sites-available/pyrest.conf",
            "#   2. ln -s /etc/nginx/sites-available/pyrest.conf /etc/nginx/sites-enabled/",
            "#   3. nginx -t && systemctl reload nginx",
            "",
            "",
        ]

        # Upstreams
        lines.append(self.generate_upstream_config(main_port, isolated_apps))

        # Server block
        # Use default_server to make this the default server block
        lines.extend(
            [
                "",
                "server {",
                f"    listen {listen_port} default_server;",
                f"    listen [::]:{listen_port} default_server;",
                f"    server_name {server_name};",
                "",
                "    # Logging",
                "    access_log /var/log/nginx/pyrest_access.log;",
                "    error_log /var/log/nginx/pyrest_error.log;",
                "",
                "    # Security headers",
                '    add_header X-Frame-Options "SAMEORIGIN" always;',
                '    add_header X-Content-Type-Options "nosniff" always;',
                '    add_header X-XSS-Protection "1; mode=block" always;',
                "",
                "    # Proxy settings",
                "    proxy_http_version 1.1;",
                "    proxy_set_header Host $host;",
                "    proxy_set_header X-Real-IP $remote_addr;",
                "    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                "    proxy_set_header X-Forwarded-Proto $scheme;",
                "    proxy_set_header X-Forwarded-Host $host;",
                "    proxy_set_header X-Forwarded-Port $server_port;",
                "    proxy_set_header Upgrade $http_upgrade;",
                '    proxy_set_header Connection "upgrade";',
                "    proxy_connect_timeout 60s;",
                "    proxy_send_timeout 60s;",
                "    proxy_read_timeout 60s;",
                "    proxy_buffering off;",
                "",
            ]
        )

        # Add locations for isolated apps first (more specific routes)
        # Sort by prefix length (longest first) to ensure most specific matches first
        sorted_isolated = sorted(
            [app for app in isolated_apps if app.port], key=lambda a: len(a.prefix), reverse=True
        )

        for app in sorted_isolated:
            prefix = app.prefix.rstrip("/")
            full_path = f"{base_path}{prefix}"
            # Use regex to match both /pyrest/app and /pyrest/app/...
            # This ensures requests work with or without trailing slash
            # Important: When using regex location, we need to pass the full URI
            # Using $request_uri preserves the original request path
            lines.extend(
                [
                    f"    # Isolated app: {app.name}",
                    f"    location ~ ^{full_path}(/.*)?$ {{",
                    f"        proxy_pass http://pyrest_{app.name}$request_uri;",
                    "    }",
                    "",
                ]
            )

        # Add catch-all location for main server (embedded apps + framework endpoints)
        # This must come after isolated app locations
        lines.extend(
            [
                "    # Main PyRest server (embedded apps + framework endpoints)",
                f"    location {base_path}/ {{",
                "        proxy_pass http://pyrest_main;",
                "    }",
                "",
                "    # Root redirect to PyRest",
                "    location = / {",
                f"        return 301 {base_path}/;",
                "    }",
                "",
                "    # Health check endpoint",
                "    location /nginx-health {",
                "        access_log off;",
                '        return 200 "healthy\\n";',
                "        add_header Content-Type text/plain;",
                "    }",
                "",
                "    # Static files (if needed)",
                "    location /static/ {",
                "        alias /static/;",
                "        expires 30d;",
                '        add_header Cache-Control "public, immutable";',
                "    }",
                "}",
                "",
            ]
        )

        return "\n".join(lines)

    def generate_complete_nginx_conf(
        self,
        main_port: int,
        embedded_apps: list[AppConfig],
        isolated_apps: list[AppConfig],
        server_name: str = "localhost",
        listen_port: int = 8080,
    ) -> str:
        """Generate complete nginx.conf with http block (for Docker)."""
        server_config = self.generate_full_config(
            main_port=main_port,
            embedded_apps=embedded_apps,
            isolated_apps=isolated_apps,
            server_name=server_name,
            listen_port=listen_port,
        )

        lines = [
            "# Complete Nginx Configuration for PyRest",
            f"# Generated: {datetime.now().isoformat()}",
            f"# Docker mode: {self.docker_mode}",
            "#",
            "# This is a complete nginx.conf file suitable for Docker deployments.",
            "#",
            "",
        ]

        # Nginx main configuration
        lines.extend(
            [
                "# user nginx;",
                "worker_processes auto;",
                "error_log /var/log/nginx/error.log warn;",
                "pid /run/nginx/nginx.pid;",
                "",
                "events {",
                "    worker_connections 1024;",
                "    use epoll;",
                "    multi_accept on;",
                "}",
                "",
                "http {",
                "    include /etc/nginx/mime.types;",
                "    default_type application/octet-stream;",
                "",
                "    # Logging format",
                "    log_format main '$remote_addr - $remote_user [$time_local] \"$request\" '",
                "                    '$status $body_bytes_sent \"$http_referer\" '",
                '                    \'"$http_user_agent" "$http_x_forwarded_for"\';',
                "",
                "    access_log /var/log/nginx/access.log main;",
                "",
                "    # Performance settings",
                "    sendfile on;",
                "    tcp_nopush on;",
                "    tcp_nodelay on;",
                "    keepalive_timeout 65;",
                "    types_hash_max_size 2048;",
                "",
                "    # Gzip compression",
                "    gzip on;",
                "    gzip_vary on;",
                "    gzip_proxied any;",
                "    gzip_comp_level 6;",
                "    gzip_types text/plain text/css text/xml application/json application/javascript ",
                "               application/xml application/xml+rss text/javascript application/x-javascript;",
                "",
                "    # Security headers",
                '    add_header X-Frame-Options "SAMEORIGIN" always;',
                '    add_header X-Content-Type-Options "nosniff" always;',
                '    add_header X-XSS-Protection "1; mode=block" always;',
                "",
                "",
            ]
        )

        # Add the server configuration (upstreams and server block)
        lines.append(server_config)

        # Close http block
        lines.extend(
            ["    # Include additional configuration", "    include /etc/nginx/conf.d/*.conf;", "}"]
        )

        return "\n".join(lines)

    async def generate_and_save(
        self,
        embedded_apps: list[AppConfig],
        isolated_apps: list[AppConfig],
        filename: str = "pyrest_generated.conf",
        complete_config: bool | None = None,
    ) -> Path:
        """
        Async: generate nginx config and write to file.

        File I/O is offloaded to a thread so it never blocks the event loop.
        """
        main_port = self.config.port

        if complete_config is None:
            complete_config = filename.endswith("nginx.conf") or filename == "default.conf"

        # Pure string generation (CPU-only, fast)
        if complete_config:
            config_content = self.generate_complete_nginx_conf(
                main_port=main_port,
                embedded_apps=embedded_apps,
                isolated_apps=isolated_apps,
            )
        else:
            config_content = self.generate_full_config(
                main_port=main_port,
                embedded_apps=embedded_apps,
                isolated_apps=isolated_apps,
            )

        # Async file write helper
        def _write_sync() -> Path:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = (self.output_dir / filename).resolve()

            if output_path.exists() and output_path.is_dir():
                logger.warning(f"Output {output_path} is a directory, removing.")
                try:
                    shutil.rmtree(output_path)
                except Exception as e:
                    logger.exception(f"Failed to remove dir {output_path}: {e}")
                    output_path = (self.output_dir / f"{filename}.new").resolve()

            output_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                output_path.write_text(config_content)
                logger.info(f"Generated nginx configuration: {output_path}")
                return output_path
            except (IsADirectoryError, OSError) as e:
                logger.exception(f"Failed to write nginx config to {output_path}: {e}")
                fallback = (
                    self.output_dir / f"{filename}.{int(datetime.now().timestamp())}"
                ).resolve()
                fallback.write_text(config_content)
                logger.warning(f"Used fallback path: {fallback}")
                return fallback

        return await asyncio.to_thread(_write_sync)

    def generate_app_summary(
        self, embedded_apps: list[AppConfig], isolated_apps: list[AppConfig]
    ) -> str:
        """Generate a summary of app routing for reference."""
        base_path = self.config.base_path

        lines = [
            "# PyRest App Routing Summary",
            f"# Generated: {datetime.now().isoformat()}",
            "",
            "## Framework Endpoints",
            f"  GET  {base_path}/           - API info",
            f"  GET  {base_path}/health     - Health check",
            f"  GET  {base_path}/apps       - List apps",
            f"  POST {base_path}/auth/login - JWT login",
            f"  GET  {base_path}/auth/azure/login - Azure AD login",
            "",
            "## Embedded Apps (port {main_port})",
        ]

        for app in embedded_apps:
            prefix = app.prefix.rstrip("/")
            lines.append(f"  - {app.name}: {base_path}{prefix}/")

        if not embedded_apps:
            lines.append("  (none)")

        lines.extend(["", "## Isolated Apps"])

        for app in isolated_apps:
            prefix = app.prefix.rstrip("/")
            lines.append(f"  - {app.name}: {base_path}{prefix}/ (port {app.port})")

        if not isolated_apps:
            lines.append("  (none)")

        return "\n".join(lines)


# Singleton
_nginx_generator: NginxGenerator | None = None


def get_nginx_generator(docker_mode: bool | None = None) -> NginxGenerator:
    """Get the singleton NginxGenerator instance."""
    global _nginx_generator
    if _nginx_generator is None:
        _nginx_generator = NginxGenerator(docker_mode=docker_mode)
    return _nginx_generator
