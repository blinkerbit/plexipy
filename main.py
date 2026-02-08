#!/usr/bin/env python3
"""
PyRest Framework - Main Entry Point

A Tornado-based REST API framework with support for:
- Embedded apps (running in main process)
- Isolated apps (running in separate processes with own venv)
- Azure AD authentication
- Automatic nginx configuration generation

Usage:
    python main.py                    # Start with default settings
    python main.py --port 8080        # Custom port
    python main.py --debug            # Debug mode
    python main.py --no-isolated      # Skip isolated app setup
    python main.py --no-nginx         # Skip nginx config generation
"""

import argparse
import sys
from pathlib import Path

# Add the project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pyrest.server import run_server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PyRest - A Tornado-based REST API Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                     Start server with default config
  python main.py --port 8080         Start on port 8080
  python main.py --debug             Enable debug mode
  python main.py --no-isolated       Don't setup isolated apps

App Types:
  - Embedded apps: No requirements.txt, run in main process
  - Isolated apps: Have requirements.txt, run in separate venv/process

URL Structure:
  All endpoints are served under /pyrest/<app_name>/...

  Framework:
    /pyrest/              API info
    /pyrest/health        Health check
    /pyrest/apps          List all apps
    /pyrest/status        System status
    /pyrest/auth/...      Authentication endpoints

  Apps:
    /pyrest/<app_name>/   App endpoints
""",
    )

    parser.add_argument(
        "--host", type=str, default=None, help="Host to bind to (default: from config or 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="Port to listen on (default: from config or 8000)"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument(
        "--no-isolated",
        action="store_true",
        dest="no_isolated",
        help="Skip setting up isolated apps (useful for development)",
    )
    parser.add_argument(
        "--no-nginx",
        action="store_true",
        dest="no_nginx",
        help="Skip generating nginx configuration",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to configuration file (default: config.json)",
    )

    args = parser.parse_args()

    # Print startup banner
    sys.stdout.write("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   ██████╗ ██╗   ██╗██████╗ ███████╗███████╗████████╗     ║
║   ██╔══██╗╚██╗ ██╔╝██╔══██╗██╔════╝██╔════╝╚══██╔══╝     ║
║   ██████╔╝ ╚████╔╝ ██████╔╝█████╗  ███████╗   ██║        ║
║   ██╔═══╝   ╚██╔╝  ██╔══██╗██╔══╝  ╚════██║   ██║        ║
║   ██║        ██║   ██║  ██║███████╗███████║   ██║        ║
║   ╚═╝        ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝   ╚═╝        ║
║                                                           ║
║   Tornado-based REST API Framework                        ║
║   Version 1.0.0                                           ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
""")

    run_server(
        host=args.host,
        port=args.port,
        debug=args.debug,
        setup_isolated=not args.no_isolated,
        generate_nginx=not args.no_nginx,
    )


if __name__ == "__main__":
    main()
