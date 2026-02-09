"""
Process Manager for PyRest framework.
Fully async -- uses asyncio for sleep, subprocess wait, and child-PID discovery.

Tornado isolated apps fork multiple worker processes (default 8).
This manager tracks the parent PID and discovers child worker PIDs
via /proc on Linux, killing the entire process group on stop.
"""

import asyncio
import atexit
import contextlib
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_config
from .venv_manager import get_venv_manager

logger = logging.getLogger("pyrest.process_manager")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_child_pids(parent_pid: int) -> list[int]:
    """
    Get all child PIDs of a given parent PID (sync, fast).
    Uses /proc on Linux to discover Tornado worker forks.
    """
    children: list[int] = []
    try:
        proc_path = Path("/proc")
        if not proc_path.exists():
            # Fallback: use ps command (sync, fast)
            result = subprocess.run(
                ["ps", "--ppid", str(parent_pid), "-o", "pid="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    line = line.strip()
                    if line.isdigit():
                        children.append(int(line))
            return children

        # Scan /proc for children (very fast on Linux)
        for entry in proc_path.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat_file = entry / "stat"
                if stat_file.exists():
                    stat_content = stat_file.read_text()
                    close_paren = stat_content.rfind(")")
                    if close_paren > 0:
                        fields = stat_content[close_paren + 2 :].split()
                        if len(fields) >= 2 and int(fields[1]) == parent_pid:
                            children.append(int(entry.name))
            except (PermissionError, FileNotFoundError, ValueError, IndexError):
                continue
    except OSError as e:
        logger.debug("Error scanning child PIDs for %d: %s", parent_pid, e)
    return children


def _pid_alive(pid: int) -> bool:
    """Check if a PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ---------------------------------------------------------------------------
# AppProcess dataclass
# ---------------------------------------------------------------------------


@dataclass
class AppProcess:
    """Represents a running isolated app process (parent + forked workers)."""

    name: str
    port: int
    process: asyncio.subprocess.Process
    app_path: Path
    venv_path: Path | None = None
    started_at: float = field(default_factory=time.time)

    @property
    def is_running(self) -> bool:
        """Whether the app process is still running."""
        return self.process.returncode is None

    @property
    def pid(self) -> int | None:
        """The parent process ID, or None if no process exists."""
        return self.process.pid if self.process else None

    @property
    def child_pids(self) -> list[int]:
        """PIDs of forked Tornado worker processes."""
        if not self.is_running or not self.pid:
            return []
        return _get_child_pids(self.pid)

    @property
    def all_pids(self) -> list[int]:
        """All PIDs (parent + workers) for this app."""
        pids: list[int] = []
        if self.pid:
            pids.append(self.pid)
        pids.extend(self.child_pids)
        return pids

    @property
    def total_processes(self) -> int:
        """Total number of running processes (parent + workers)."""
        return len(self.all_pids)

    @property
    def return_code(self) -> int | None:
        """The process exit code, or None if still running."""
        return self.process.returncode

    def to_dict(self) -> dict[str, Any]:
        """Serialize the app process state to a dictionary."""
        children = self.child_pids
        return {
            "name": self.name,
            "port": self.port,
            "pid": self.pid,
            "child_pids": children,
            "total_processes": 1 + len(children) if self.is_running else 0,
            "is_running": self.is_running,
            "app_path": str(self.app_path),
            "venv_path": str(self.venv_path) if self.venv_path else None,
            "started_at": self.started_at,
            "return_code": self.return_code,
        }


# ---------------------------------------------------------------------------
# ProcessManager (async)
# ---------------------------------------------------------------------------


class ProcessManager:
    """
    Manages isolated app processes.
    spawn_app and stop_app are async to avoid blocking the event loop.
    """

    def __init__(self) -> None:
        self.config = get_config()
        self.venv_manager = get_venv_manager()
        self._processes: dict[str, AppProcess] = {}
        self._next_port: int = self.config.isolated_app_base_port

        # Register sync cleanup on interpreter exit
        atexit.register(self._sync_shutdown_all)

    def get_next_port(self) -> int:
        """Return the next available port and increment the counter."""
        port = self._next_port
        self._next_port += 1
        return port

    def assign_port(self, app_name: str, preferred_port: int | None = None) -> int:
        """Assign a port to an app, using the preferred port if available.

        Args:
            app_name: Name of the app requesting a port.
            preferred_port: Desired port number, or None for auto-assign.

        Returns:
            The assigned port number.
        """
        if preferred_port is not None:
            for name, proc in self._processes.items():
                if proc.port == preferred_port and name != app_name:
                    logger.warning(
                        f"Port {preferred_port} already assigned to {name}, "
                        f"auto-assigning for {app_name}"
                    )
                    return self.get_next_port()
            return preferred_port
        return self.get_next_port()

    # ------------------------------------------------------------------
    # Async: spawn
    # ------------------------------------------------------------------

    async def spawn_app(
        self,
        app_name: str,
        app_path: Path,
        port: int,
        venv_path: Path | None = None,
    ) -> AppProcess | None:
        """
        Async: spawn an isolated app as a subprocess.
        Uses asyncio.sleep instead of time.sleep for the startup check.
        """
        app_path = Path(app_path).resolve()

        # Already running?
        if app_name in self._processes:
            existing = self._processes[app_name]
            if existing.is_running:
                logger.warning(f"App {app_name} already running on port {existing.port}")
                return existing
            del self._processes[app_name]

        # Runner script
        runner_script = (Path(__file__).parent / "templates" / "isolated_app.py").resolve()
        if not runner_script.exists():
            logger.error(f"Isolated app runner not found at {runner_script}")
            return None

        # Python executable
        if not venv_path:
            logger.error(f"No venv_path for isolated app '{app_name}'. Cannot start.")
            return None

        venv_path = Path(venv_path).resolve()
        if not venv_path.exists():
            logger.error(f"Venv path does not exist: {venv_path}")
            return None

        python_exe = self.venv_manager.get_python_executable(venv_path)
        if not python_exe.exists():
            logger.error(f"Python not found at {python_exe}")
            return None

        logger.info(f"Using venv Python for '{app_name}': {python_exe}")

        # Environment
        env = os.environ.copy()
        env.update(
            {
                "PYREST_APP_NAME": app_name,
                "PYREST_APP_PATH": str(app_path),
                "PYREST_APP_PORT": str(port),
                "PYREST_MAIN_PORT": str(self.config.port),
                "PYREST_BASE_PATH": self.config.base_path,
                "PYREST_AUTH_CONFIG": str(Path(self.config.auth_config_file).absolute()),
                "VIRTUAL_ENV": str(venv_path),
            }
        )
        venv_bin = venv_path / "bin"
        if venv_bin.exists():
            env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"

        try:
            logger.info(
                f"Spawning '{app_name}' on port {port} | "
                f"python={python_exe} | runner={runner_script}"
            )

            # Use asyncio.create_subprocess_exec for non-blocking process creation
            # start_new_session=True so we can killpg the whole group later.
            process = await asyncio.create_subprocess_exec(
                str(python_exe),
                str(runner_script),
                cwd=str(app_path),
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )

            # Non-blocking startup check
            await asyncio.sleep(0.5)

            if process.returncode is not None:
                if process.stderr:
                    stderr_content = await process.stderr.read()
                else:
                    stderr_content = b""
                
                logger.error(
                    f"App {app_name} failed to start. "
                    f"Exit code: {process.returncode}. "
                    f"Stderr: {stderr_content.decode(errors='replace') if stderr_content else 'N/A'}"
                )
                return None

            # We don't close stderr in asyncio subprocess manually usually, 
            # but we can consume it if needed or let it buffer (limited size).
            # For now, let's leave it as is.

            app_process = AppProcess(
                name=app_name,
                port=port,
                process=process,
                app_path=app_path,
                venv_path=venv_path,
            )
            self._processes[app_name] = app_process
            logger.info(f"App '{app_name}' started on port {port} (PID: {process.pid})")
            return app_process

        except (OSError, ValueError) as e:
            logger.exception("Failed to spawn app %s: %s", app_name, e)
            return None

    # ------------------------------------------------------------------
    # Async: stop
    # ------------------------------------------------------------------

    async def stop_app(self, app_name: str, timeout: float = 5.0) -> bool:
        """
        Async: stop a running app and ALL its forked worker processes.
        Uses asyncio.to_thread for the blocking process.wait().
        """
        if app_name not in self._processes:
            logger.warning(f"App {app_name} is not running")
            return False

        app_process = self._processes[app_name]
        if not app_process.is_running:
            del self._processes[app_name]
            return True

        try:
            parent_pid = app_process.pid
            children = app_process.child_pids
            logger.info(
                f"Stopping {app_name} (parent PID: {parent_pid}, "
                f"workers: {len(children)}, PIDs: {children})"
            )

            # SIGTERM to entire process group
            try:
                pgid = os.getpgid(parent_pid)
                os.killpg(pgid, signal.SIGTERM)
                logger.info(f"Sent SIGTERM to process group {pgid}")
            except (OSError, ProcessLookupError):
                app_process.process.terminate()

            # Non-blocking wait for parent to exit
            try:
                await asyncio.wait_for(app_process.process.wait(), timeout=timeout)
            except TimeoutError:
                logger.warning(f"App {app_name} didn't stop gracefully, force killing")
                try:
                    pgid = os.getpgid(parent_pid)
                    os.killpg(pgid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    app_process.process.kill()
                with contextlib.suppress(Exception):
                    await app_process.process.wait()

            # Kill straggler workers
            for child_pid in children:
                if _pid_alive(child_pid):
                    logger.warning(f"Killing straggler worker PID {child_pid}")
                    with contextlib.suppress(OSError, ProcessLookupError):
                        os.kill(child_pid, signal.SIGKILL)

            del self._processes[app_name]
            logger.info(f"App {app_name} stopped (all processes terminated)")
            return True

        except OSError as e:
            logger.exception("Error stopping app %s: %s", app_name, e)
            self._processes.pop(app_name, None)
            return False

    # ------------------------------------------------------------------
    # Async: shutdown all
    # ------------------------------------------------------------------

    async def shutdown_all(self) -> None:
        """Async: shutdown all running app processes."""
        logger.info("Shutting down all isolated apps...")
        for app_name in list(self._processes):
            await self.stop_app(app_name)
        logger.info("All isolated apps stopped")

    def _sync_shutdown_all(self) -> None:
        """Sync fallback for atexit (no event loop available)."""
        for app_name in list(self._processes):
            app_process = self._processes.get(app_name)
            if app_process and app_process.is_running:
                try:
                    if hasattr(os, "getpgid"):
                        pgid = os.getpgid(app_process.pid)
                        os.killpg(pgid, signal.SIGTERM)
                    else:
                        app_process.process.terminate()
                except (OSError, ProcessLookupError):
                    app_process.process.terminate()
                try:
                    app_process.process.wait(timeout=3)
                except (subprocess.TimeoutExpired, OSError) as e:
                    logger.debug("Timeout waiting for %s, force killing: %s", app_name, e)
                    app_process.process.kill()
        self._processes.clear()

    # ------------------------------------------------------------------
    # Status queries (sync -- fast, no I/O)
    # ------------------------------------------------------------------

    def get_running_apps(self) -> list[AppProcess]:
        """Return all currently running app processes, pruning dead ones."""
        dead = [n for n, p in self._processes.items() if not p.is_running]
        for name in dead:
            logger.info(f"Cleaning up dead process for app {name}")
            del self._processes[name]
        return list(self._processes.values())

    def get_app_status(self, app_name: str) -> dict[str, Any] | None:
        """Get the status dict for a specific app, or None if not found."""
        if app_name not in self._processes:
            return None
        return self._processes[app_name].to_dict()

    def get_all_status(self) -> list[dict[str, Any]]:
        """Get status dicts for all running app processes."""
        return [p.to_dict() for p in self.get_running_apps()]


# Singleton
_process_manager: ProcessManager | None = None


def get_process_manager() -> ProcessManager:
    """Get the singleton ProcessManager instance."""
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager()
    return _process_manager
