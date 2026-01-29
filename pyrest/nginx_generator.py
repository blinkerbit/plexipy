"""
Nginx Configuration Generator for PyRest framework.
Generates nginx configuration for routing to embedded and isolated apps.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from .config import get_config
from .app_loader import AppConfig

logger = logging.getLogger("pyrest.nginx_generator")


class NginxGenerator:
    """
    Generates nginx configuration files for PyRest apps.
    """
    
    def __init__(self, output_dir: str = "nginx", docker_mode: bool = None):
        self.config = get_config()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Detect Docker mode if not explicitly set
        if docker_mode is None:
            # Check for Docker environment indicators
            docker_mode = (
                os.path.exists("/.dockerenv") or  # Inside Docker container
                os.environ.get("DOCKER_MODE", "").lower() == "true" or
                os.environ.get("PYREST_DOCKER", "").lower() == "true"
            )
        
        self.docker_mode = docker_mode
        self.main_service_name = os.environ.get("PYREST_MAIN_SERVICE", "pyrest")
        self.isolated_service_prefix = os.environ.get("PYREST_ISOLATED_SERVICE_PREFIX", "")
    
    def generate_upstream_config(
        self,
        main_port: int,
        isolated_apps: List[AppConfig]
    ) -> str:
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
        
        lines.extend([
            f"    server {main_server};",
            "    keepalive 64;",
            "}",
            ""
        ])
        
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
                
                lines.extend([
                    f"# Isolated app: {app.name}",
                    f"upstream pyrest_{app.name} {{",
                    f"    server {isolated_server};",
                    f"    keepalive 32;",
                    "}",
                    ""
                ])
        
        return "\n".join(lines)
    
    def generate_location_config(
        self,
        base_path: str,
        embedded_apps: List[AppConfig],
        isolated_apps: List[AppConfig]
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
            ""
        ]
        
        # Add locations for isolated apps first (more specific routes)
        for app in isolated_apps:
            if app.port:
                prefix = app.prefix.rstrip("/")
                lines.extend([
                    f"# Isolated app: {app.name}",
                    f"location {base_path}{prefix}/ {{",
                    f"    proxy_pass http://pyrest_{app.name};",
                    "}",
                    ""
                ])
        
        # Add catch-all location for main server (embedded apps)
        lines.extend([
            "# Main PyRest server (embedded apps + framework endpoints)",
            f"location {base_path}/ {{",
            "    proxy_pass http://pyrest_main;",
            "}",
            ""
        ])
        
        return "\n".join(lines)
    
    def generate_full_config(
        self,
        main_port: int,
        embedded_apps: List[AppConfig],
        isolated_apps: List[AppConfig],
        server_name: str = "localhost",
        listen_port: int = 80
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
            ""
        ]
        
        # Upstreams
        lines.append(self.generate_upstream_config(main_port, isolated_apps))
        
        # Server block
        # Use default_server to make this the default server block
        lines.extend([
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
            ""
        ])
        
        # Add locations for isolated apps first (more specific routes)
        # Sort by prefix length (longest first) to ensure most specific matches first
        sorted_isolated = sorted(
            [app for app in isolated_apps if app.port],
            key=lambda a: len(a.prefix),
            reverse=True
        )
        
        for app in sorted_isolated:
            prefix = app.prefix.rstrip("/")
            full_path = f"{base_path}{prefix}"
            # Use regex to match both /pyrest/app and /pyrest/app/...
            # This ensures requests work with or without trailing slash
            # Important: When using regex location, we need to pass the full URI
            # Using $request_uri preserves the original request path
            lines.extend([
                f"    # Isolated app: {app.name}",
                f"    location ~ ^{full_path}(/.*)?$ {{",
                f"        proxy_pass http://pyrest_{app.name}$request_uri;",
                "    }",
                ""
            ])
        
        # Add catch-all location for main server (embedded apps + framework endpoints)
        # This must come after isolated app locations
        lines.extend([
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
            ""
        ])
        
        return "\n".join(lines)
    
    def generate_complete_nginx_conf(
        self,
        main_port: int,
        embedded_apps: List[AppConfig],
        isolated_apps: List[AppConfig],
        server_name: str = "localhost",
        listen_port: int = 80
    ) -> str:
        """Generate complete nginx.conf with http block (for Docker)."""
        server_config = self.generate_full_config(
            main_port=main_port,
            embedded_apps=embedded_apps,
            isolated_apps=isolated_apps,
            server_name=server_name,
            listen_port=listen_port
        )
        
        lines = [
            "# Complete Nginx Configuration for PyRest",
            f"# Generated: {datetime.now().isoformat()}",
            f"# Docker mode: {self.docker_mode}",
            "#",
            "# This is a complete nginx.conf file suitable for Docker deployments.",
            "#",
            ""
        ]
        
        # Nginx main configuration
        lines.extend([
            "user nginx;",
            "worker_processes auto;",
            "error_log /var/log/nginx/error.log warn;",
            "pid /var/run/nginx.pid;",
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
            "                    '\"$http_user_agent\" \"$http_x_forwarded_for\"';",
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
            "    add_header X-Frame-Options \"SAMEORIGIN\" always;",
            "    add_header X-Content-Type-Options \"nosniff\" always;",
            "    add_header X-XSS-Protection \"1; mode=block\" always;",
            "",
            ""
        ])
        
        # Add the server configuration (upstreams and server block)
        lines.append(server_config)
        
        # Close http block
        lines.extend([
            "    # Include additional configuration",
            "    include /etc/nginx/conf.d/*.conf;",
            "}"
        ])
        
        return "\n".join(lines)
    
    def generate_and_save(
        self,
        embedded_apps: List[AppConfig],
        isolated_apps: List[AppConfig],
        filename: str = "pyrest_generated.conf",
        complete_config: bool = None
    ) -> Path:
        """
        Generate nginx config and save to file.
        
        Args:
            embedded_apps: List of embedded app configs
            isolated_apps: List of isolated app configs
            filename: Output filename (if ends with 'nginx.conf', generates complete config)
            complete_config: If True, generate complete nginx.conf. If None, auto-detect based on filename or docker_mode.
        """
        main_port = self.config.port
        
        # Auto-detect if we should generate complete config
        if complete_config is None:
            # Generate complete config only if filename is nginx.conf or default.conf
            # (These are used to replace the entire nginx.conf in Docker)
            # For other filenames (like pyrest_generated.conf), generate server block
            # that can be included in existing nginx.conf
            complete_config = (
                filename.endswith("nginx.conf") or 
                filename == "default.conf"
            )
        
        if complete_config:
            config_content = self.generate_complete_nginx_conf(
                main_port=main_port,
                embedded_apps=embedded_apps,
                isolated_apps=isolated_apps
            )
        else:
            config_content = self.generate_full_config(
                main_port=main_port,
                embedded_apps=embedded_apps,
                isolated_apps=isolated_apps
            )
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = self.output_dir / filename
        
        # Resolve to absolute path to avoid any path resolution issues
        output_path = output_path.resolve()
        
        # Check if output_path exists as a directory (shouldn't happen, but handle it)
        if output_path.exists():
            if output_path.is_dir():
                logger.warning(f"Output path {output_path} exists as a directory. Removing it.")
                try:
                    shutil.rmtree(output_path)
                except Exception as e:
                    logger.error(f"Failed to remove directory {output_path}: {e}")
                    # Use a different filename as fallback
                    output_path = (self.output_dir / f"{filename}.new").resolve()
            elif output_path.is_file():
                # File exists, we'll overwrite it (which is fine)
                logger.debug(f"Overwriting existing nginx config file: {output_path}")
        
        # Double-check right before opening (in case something changed)
        if output_path.exists() and output_path.is_dir():
            logger.error(f"Output path {output_path} is still a directory. Using fallback filename.")
            output_path = (self.output_dir / f"{filename}.new").resolve()
            # Remove fallback if it's also a directory
            if output_path.exists() and output_path.is_dir():
                try:
                    shutil.rmtree(output_path)
                except Exception:
                    pass
        
        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(output_path, "w") as f:
                f.write(config_content)
            logger.info(f"Generated nginx configuration: {output_path}")
            return output_path
        except (IsADirectoryError, OSError) as e:
            # If we still get a directory error, try a different filename
            logger.error(f"Failed to write nginx configuration to {output_path}: {e}")
            fallback_path = (self.output_dir / f"{filename}.{int(datetime.now().timestamp())}").resolve()
            try:
                with open(fallback_path, "w") as f:
                    f.write(config_content)
                logger.warning(f"Used fallback path for nginx configuration: {fallback_path}")
                return fallback_path
            except Exception as e2:
                logger.error(f"Failed to write to fallback path {fallback_path}: {e2}")
                raise
        except Exception as e:
            logger.error(f"Failed to write nginx configuration to {output_path}: {e}")
            raise
    
    def generate_app_summary(
        self,
        embedded_apps: List[AppConfig],
        isolated_apps: List[AppConfig]
    ) -> str:
        """Generate a summary of app routing for reference."""
        base_path = self.config.base_path
        main_port = self.config.port
        
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
        
        lines.extend([
            "",
            "## Isolated Apps"
        ])
        
        for app in isolated_apps:
            prefix = app.prefix.rstrip("/")
            lines.append(f"  - {app.name}: {base_path}{prefix}/ (port {app.port})")
        
        if not isolated_apps:
            lines.append("  (none)")
        
        return "\n".join(lines)


# Singleton instance
_nginx_generator: Optional[NginxGenerator] = None


def get_nginx_generator(docker_mode: bool = None) -> NginxGenerator:
    """
    Get the singleton NginxGenerator instance.
    
    Args:
        docker_mode: Force Docker mode detection. If None, auto-detects.
    """
    global _nginx_generator
    if _nginx_generator is None:
        _nginx_generator = NginxGenerator(docker_mode=docker_mode)
    return _nginx_generator
