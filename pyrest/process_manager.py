"""
Process Manager for PyRest framework.
Handles spawning and managing isolated app processes.
"""

import os
import sys
import signal
import subprocess
import logging
import atexit
from pathlib import Path
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
import threading
import time

from .config import get_config
from .venv_manager import get_venv_manager

logger = logging.getLogger("pyrest.process_manager")


@dataclass
class AppProcess:
    """Represents a running isolated app process."""
    name: str
    port: int
    process: subprocess.Popen
    app_path: Path
    venv_path: Optional[Path] = None
    started_at: float = field(default_factory=time.time)
    
    @property
    def is_running(self) -> bool:
        """Check if the process is still running."""
        return self.process.poll() is None
    
    @property
    def pid(self) -> Optional[int]:
        """Get the process ID."""
        return self.process.pid if self.process else None
    
    @property
    def return_code(self) -> Optional[int]:
        """Get the return code if process has exited."""
        return self.process.poll()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "port": self.port,
            "pid": self.pid,
            "is_running": self.is_running,
            "app_path": str(self.app_path),
            "venv_path": str(self.venv_path) if self.venv_path else None,
            "started_at": self.started_at,
            "return_code": self.return_code
        }


class ProcessManager:
    """
    Manages isolated app processes.
    Spawns apps as subprocesses and tracks their status.
    """
    
    def __init__(self):
        self.config = get_config()
        self.venv_manager = get_venv_manager()
        self._processes: Dict[str, AppProcess] = {}
        self._next_port = self.config.isolated_app_base_port
        self._port_lock = threading.Lock()
        
        # Register cleanup on exit
        atexit.register(self.shutdown_all)
    
    def get_next_port(self) -> int:
        """Get the next available port for an isolated app."""
        with self._port_lock:
            port = self._next_port
            self._next_port += 1
            return port
    
    def assign_port(self, app_name: str, preferred_port: Optional[int] = None) -> int:
        """
        Assign a port to an app.
        
        Args:
            app_name: Name of the app
            preferred_port: Preferred port number (if available)
            
        Returns:
            Assigned port number
        """
        if preferred_port is not None:
            # Check if port is already in use by another app
            for name, proc in self._processes.items():
                if proc.port == preferred_port and name != app_name:
                    logger.warning(
                        f"Port {preferred_port} already assigned to {name}, "
                        f"auto-assigning for {app_name}"
                    )
                    return self.get_next_port()
            return preferred_port
        
        return self.get_next_port()
    
    def spawn_app(
        self,
        app_name: str,
        app_path: Path,
        port: int,
        venv_path: Optional[Path] = None
    ) -> Optional[AppProcess]:
        """
        Spawn an isolated app as a subprocess.
        
        Args:
            app_name: Name of the app
            app_path: Path to the app directory
            port: Port number to run the app on
            venv_path: Path to the virtual environment (optional)
            
        Returns:
            AppProcess object if successful, None otherwise
        """
        # Check if app is already running
        if app_name in self._processes:
            existing = self._processes[app_name]
            if existing.is_running:
                logger.warning(f"App {app_name} is already running on port {existing.port}")
                return existing
            else:
                # Clean up dead process
                del self._processes[app_name]
        
        # Get the isolated app runner script path
        runner_script = Path(__file__).parent / "templates" / "isolated_app.py"
        
        if not runner_script.exists():
            logger.error(f"Isolated app runner not found at {runner_script}")
            return None
        
        # Determine Python executable
        if venv_path and venv_path.exists():
            python_exe = self.venv_manager.get_python_executable(venv_path)
        else:
            python_exe = Path(sys.executable)
        
        # Build environment variables
        env = os.environ.copy()
        env["PYREST_APP_NAME"] = app_name
        env["PYREST_APP_PATH"] = str(app_path)
        env["PYREST_APP_PORT"] = str(port)
        env["PYREST_MAIN_PORT"] = str(self.config.port)
        env["PYREST_BASE_PATH"] = self.config.base_path
        env["PYREST_AUTH_CONFIG"] = str(Path(self.config.auth_config_file).absolute())
        
        if venv_path:
            env["VIRTUAL_ENV"] = str(venv_path)
        
        try:
            logger.info(f"Spawning isolated app '{app_name}' on port {port}")
            logger.debug(f"Python: {python_exe}, Script: {runner_script}")
            
            # Spawn the process
            process = subprocess.Popen(
                [str(python_exe), str(runner_script)],
                cwd=str(app_path),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Don't create new console window on Windows
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            
            # Wait briefly to check if process started successfully
            time.sleep(0.5)
            
            if process.poll() is not None:
                # Process already exited
                stdout, stderr = process.communicate()
                logger.error(
                    f"App {app_name} failed to start. "
                    f"Exit code: {process.returncode}. "
                    f"Stderr: {stderr.decode() if stderr else 'N/A'}"
                )
                return None
            
            # Create and store AppProcess
            app_process = AppProcess(
                name=app_name,
                port=port,
                process=process,
                app_path=app_path,
                venv_path=venv_path
            )
            
            self._processes[app_name] = app_process
            logger.info(f"App '{app_name}' started successfully on port {port} (PID: {process.pid})")
            
            return app_process
            
        except Exception as e:
            logger.error(f"Failed to spawn app {app_name}: {e}")
            return None
    
    def stop_app(self, app_name: str, timeout: float = 5.0) -> bool:
        """
        Stop a running app.
        
        Args:
            app_name: Name of the app to stop
            timeout: Timeout in seconds before force killing
            
        Returns:
            True if stopped successfully
        """
        if app_name not in self._processes:
            logger.warning(f"App {app_name} is not running")
            return False
        
        app_process = self._processes[app_name]
        
        if not app_process.is_running:
            del self._processes[app_name]
            return True
        
        try:
            logger.info(f"Stopping app {app_name} (PID: {app_process.pid})")
            
            # Try graceful shutdown first
            app_process.process.terminate()
            
            try:
                app_process.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning(f"App {app_name} didn't stop gracefully, force killing")
                app_process.process.kill()
                app_process.process.wait()
            
            del self._processes[app_name]
            logger.info(f"App {app_name} stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping app {app_name}: {e}")
            return False
    
    def shutdown_all(self):
        """Shutdown all running app processes."""
        logger.info("Shutting down all isolated apps...")
        
        for app_name in list(self._processes.keys()):
            self.stop_app(app_name)
        
        logger.info("All isolated apps stopped")
    
    def get_running_apps(self) -> List[AppProcess]:
        """Get list of all running app processes."""
        # Clean up any dead processes
        dead_apps = [
            name for name, proc in self._processes.items() 
            if not proc.is_running
        ]
        for name in dead_apps:
            logger.info(f"Cleaning up dead process for app {name}")
            del self._processes[name]
        
        return list(self._processes.values())
    
    def get_app_status(self, app_name: str) -> Optional[Dict[str, Any]]:
        """Get the status of a specific app."""
        if app_name not in self._processes:
            return None
        
        return self._processes[app_name].to_dict()
    
    def get_all_status(self) -> List[Dict[str, Any]]:
        """Get status of all managed apps."""
        return [proc.to_dict() for proc in self.get_running_apps()]


# Singleton instance
_process_manager: Optional[ProcessManager] = None


def get_process_manager() -> ProcessManager:
    """Get the singleton ProcessManager instance."""
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager()
    return _process_manager
