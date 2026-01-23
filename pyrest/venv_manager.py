"""
Virtual Environment Manager for PyRest framework.
Handles automatic creation and management of virtual environments for isolated apps.

Designed for Linux Docker containers.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("pyrest.venv_manager")


class VenvManager:
    """
    Manages virtual environments for isolated apps.
    Auto-creates venv and installs dependencies when requirements.txt is present.
    
    Designed for Linux Docker containers - uses Linux-style paths (bin/python, bin/pip).
    Uses uv for fast package installation if available.
    """
    
    def __init__(self):
        self._setup_pip_script = Path(__file__).parent.parent / "setup_pip.sh"
        self._uv_available = self._check_uv_available()
    
    def _check_uv_available(self) -> bool:
        """Check if uv is available for package installation."""
        try:
            result = subprocess.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                logger.info(f"=" * 60)
                logger.info(f"UV DETECTED: {version}")
                logger.info(f"Using uv for fast venv creation and package installation")
                logger.info(f"=" * 60)
                return True
        except FileNotFoundError:
            logger.info("uv command not found in PATH")
        except Exception as e:
            logger.warning(f"uv check failed: {e}")
        logger.info("uv not available, will use pip for package management")
        return False
    
    def _run_setup_pip_script(self) -> None:
        """Run setup_pip.sh script if it exists to configure pip proxy etc."""
        if not self._setup_pip_script.exists():
            return
        try:
            # Try to source the script and get environment variables
            if os.access(self._setup_pip_script, os.X_OK):
                result = subprocess.run(
                    ["bash", "-c", f"source {self._setup_pip_script} && env"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if "=" in line and not line.startswith("#"):
                            key, value = line.split("=", 1)
                            os.environ[key] = value
            else:
                # Fallback: parse the script manually
                try:
                    with open(self._setup_pip_script, "r") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            if line.startswith("export "):
                                line = line[7:].strip()
                            if "=" in line:
                                key, value = line.split("=", 1)
                                value = value.strip().strip('"').strip("'")
                                os.environ[key.strip()] = value
                except Exception as e:
                    logger.warning(f"Failed to parse setup_pip.sh: {e}")
        except Exception as e:
            logger.warning(f"Failed to run setup_pip.sh: {e}")
    
    def get_venv_path(self, app_path: Path, venv_name: str = ".venv") -> Path:
        """
        Get the virtual environment path for an app.
        
        Creates venvs inside the app folder (e.g., apps/tm1data/.venv).
        """
        # Resolve to absolute path first
        app_path = app_path.resolve()
        app_name = app_path.name
        
        # Create venv in the app folder
        venv_path = app_path / venv_name
        
        logger.info(
            f"Venv location for app '{app_name}': {venv_path} "
            f"(in app folder: {app_path})"
        )
        return venv_path
    
    def get_python_executable(self, venv_path: Path) -> Path:
        """Get the Python executable path within a virtual environment (Linux: bin/python)."""
        return venv_path / "bin" / "python"
    
    def get_pip_executable(self, venv_path: Path) -> Path:
        """Get the pip executable path within a virtual environment (Linux: bin/pip)."""
        return venv_path / "bin" / "pip"
    
    def venv_exists(self, venv_path: Path) -> bool:
        """
        Check if a virtual environment exists and is valid.
        Validates that the venv directory exists and Python executable exists.
        """
        if not venv_path.exists():
            return False
        
        python_exe = self.get_python_executable(venv_path)
        if not python_exe.exists():
            logger.warning(
                f"Venv directory exists at {venv_path} but Python executable "
                f"not found at {python_exe}. Venv may be from a different platform."
            )
            return False
        
        # Check if it's executable (Linux)
        if not os.access(python_exe, os.X_OK):
            logger.warning(f"Python executable at {python_exe} is not executable")
            return False
        
        return True
    
    def has_requirements(self, app_path: Path) -> bool:
        """Check if an app has a requirements.txt file."""
        return (app_path / "requirements.txt").exists()
    
    def create_venv(self, venv_path: Path) -> Tuple[bool, str]:
        """
        Create a new virtual environment.
        Uses uv if available for faster creation.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            tool = "uv" if self._uv_available else "venv"
            logger.info(f"=" * 60)
            logger.info(f"CREATING VENV: {venv_path}")
            logger.info(f"Using: {tool}")
            logger.info(f"Python: {sys.executable}")
            logger.info(f"=" * 60)
            
            self._run_setup_pip_script()
            
            if self._uv_available:
                # Use uv venv for faster creation
                result = subprocess.run(
                    ["uv", "venv", str(venv_path), "--python", sys.executable],
                    capture_output=True,
                    text=True
                )
            else:
                # Fall back to standard venv
                result = subprocess.run(
                    [sys.executable, "-m", "venv", str(venv_path)],
                    capture_output=True,
                    text=True
                )
            
            if result.stdout:
                logger.info(f"venv creation stdout:\n{result.stdout}")
            if result.stderr:
                logger.info(f"venv creation stderr:\n{result.stderr}")
            
            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error creating venv"
                logger.error(f"Failed to create venv (exit code {result.returncode}): {error_msg}")
                return False, error_msg
            
            logger.info(f"Virtual environment created successfully at {venv_path}")
            return True, "Virtual environment created successfully"
            
        except Exception as e:
            error_msg = f"Exception creating venv: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def install_requirements(self, venv_path: Path, requirements_file: Path) -> Tuple[bool, str]:
        """
        Install requirements from a requirements.txt file into a virtual environment.
        Uses uv if available (faster), falls back to pip.
        
        Returns:
            Tuple of (success, message)
        """
        # Resolve venv_path to absolute to ensure consistency
        venv_path = venv_path.resolve()
        
        if not requirements_file.exists():
            return False, f"Requirements file not found: {requirements_file}"
        
        # When using uv, we don't need pip - uv handles everything
        if not self._uv_available:
            pip_exe = self.get_pip_executable(venv_path)
            pip_exe = pip_exe.resolve()
            if not pip_exe.exists():
                return False, f"pip not found at {pip_exe} (venv: {venv_path})"
        
        installer = "uv" if self._uv_available else "pip"
        logger.info(f"=" * 60)
        logger.info(f"INSTALLING REQUIREMENTS: {requirements_file.name}")
        logger.info(f"Installer: {installer}")
        logger.info(f"Venv: {venv_path}")
        logger.info(f"=" * 60)
        
        # Log requirements.txt contents
        try:
            with open(requirements_file, 'r') as f:
                req_contents = f.read()
            logger.info(f"Requirements file contents:\n{req_contents}")
        except Exception as e:
            logger.warning(f"Could not read requirements file: {e}")
        
        self._run_setup_pip_script()
        try:
            if self._uv_available:
                # Use uv for fast installation
                logger.info(f"Installing packages using uv...")
                result = subprocess.run(
                    ["uv", "pip", "install", "--python", str(self.get_python_executable(venv_path)),
                     "-r", str(requirements_file)],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
            else:
                # Fall back to pip
                # Upgrade pip first
                logger.info("Upgrading pip...")
                pip_upgrade = subprocess.run(
                    [str(pip_exe), "install", "--upgrade", "pip"],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if pip_upgrade.returncode != 0:
                    logger.warning(f"pip upgrade failed: {pip_upgrade.stderr}")
                else:
                    logger.info(f"pip upgrade output:\n{pip_upgrade.stdout}")
                
                # Install requirements
                logger.info(f"Installing packages using pip...")
                result = subprocess.run(
                    [str(pip_exe), "install", "-r", str(requirements_file)],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
            
            # Always log output for visibility
            if result.stdout:
                logger.info(f"{installer} install stdout:\n{result.stdout}")
            if result.stderr:
                logger.info(f"{installer} install stderr:\n{result.stderr}")
            
            if result.returncode != 0:
                error_msg = result.stderr or f"Unknown error installing requirements with {installer}"
                logger.error(f"Failed to install requirements (exit code {result.returncode})")
                return False, error_msg
            
            logger.info(f"Requirements installation completed successfully using {installer}")
            logger.info(f"Venv ready: {venv_path}")
            
            return True, "Requirements installed successfully"
            
        except subprocess.TimeoutExpired:
            error_msg = "Timeout installing requirements"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Exception installing requirements: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def ensure_venv(self, app_path: Path, venv_name: str = ".venv") -> Tuple[bool, Path, str]:
        """
        Ensure a virtual environment exists for an app with requirements.txt.
        Creates the venv inside the app folder and installs requirements.
        
        Args:
            app_path: Path to the app directory
            venv_name: Name of the venv directory (default: .venv)
            
        Returns:
            Tuple of (success, venv_path, message)
        """
        venv_path = self.get_venv_path(app_path, venv_name)
        requirements_file = app_path / "requirements.txt"
        
        # Check if requirements.txt exists
        if not requirements_file.exists():
            return True, venv_path, "No requirements.txt found, using parent environment"
        
        # Resolve venv_path to absolute for consistent checking
        venv_path = venv_path.resolve()
        logger.info(f"Ensuring venv at: {venv_path} (inside app folder: {app_path})")
        
        if not self.venv_exists(venv_path):
            # If venv directory exists but is invalid, remove and recreate
            if venv_path.exists():
                logger.warning(
                    f"Existing venv at {venv_path} is invalid. Removing and recreating..."
                )
                try:
                    import shutil
                    shutil.rmtree(venv_path)
                    logger.info(f"Removed invalid venv at {venv_path}")
                except Exception as e:
                    logger.error(f"Failed to remove invalid venv: {e}")
                    return False, venv_path, f"Failed to remove invalid venv: {e}"
            
            success, message = self.create_venv(venv_path)
            if not success:
                return False, venv_path, message
        else:
            logger.info(f"Venv already valid at {venv_path}")
        
        # Install/update requirements
        success, message = self.install_requirements(venv_path, requirements_file)
        if not success:
            return False, venv_path, message
        
        return True, venv_path, "Virtual environment ready"
    
    def get_app_python(self, app_path: Path, venv_name: str = ".venv") -> Path:
        """
        Get the Python executable for an app.
        Returns the venv Python if it exists, otherwise the current Python.
        
        Args:
            app_path: Path to the app directory
            venv_name: Name of the venv directory
            
        Returns:
            Path to the Python executable
        """
        venv_path = self.get_venv_path(app_path, venv_name)
        python_exe = self.get_python_executable(venv_path)
        
        if python_exe.exists():
            return python_exe
        
        return Path(sys.executable)
    
    def run_in_venv(
        self, 
        app_path: Path, 
        command: list, 
        venv_name: str = ".venv",
        env: Optional[dict] = None,
        cwd: Optional[Path] = None
    ) -> subprocess.Popen:
        """
        Run a command using the app's virtual environment.
        
        Args:
            app_path: Path to the app directory
            command: Command to run (will use venv's Python)
            venv_name: Name of the venv directory
            env: Additional environment variables
            cwd: Working directory (defaults to app_path)
            
        Returns:
            subprocess.Popen object
        """
        python_exe = self.get_app_python(app_path, venv_name)
        
        # Build environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        
        # Set VIRTUAL_ENV environment variable
        venv_path = self.get_venv_path(app_path, venv_name)
        if venv_path.exists():
            run_env["VIRTUAL_ENV"] = str(venv_path)
            # Prepend venv bin to PATH (Linux)
            run_env["PATH"] = f"{venv_path / 'bin'}:{run_env.get('PATH', '')}"
        
        # Build command with Python executable
        full_command = [str(python_exe)] + command
        
        logger.info(f"Running command in venv: {' '.join(full_command)}")
        
        return subprocess.Popen(
            full_command,
            cwd=str(cwd or app_path),
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )


# Singleton instance
_venv_manager: Optional[VenvManager] = None


def get_venv_manager() -> VenvManager:
    """Get the singleton VenvManager instance."""
    global _venv_manager
    if _venv_manager is None:
        _venv_manager = VenvManager()
    return _venv_manager
