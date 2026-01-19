"""
Virtual Environment Manager for PyRest framework.
Handles automatic creation and management of virtual environments for isolated apps.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple
import platform

logger = logging.getLogger("pyrest.venv_manager")


class VenvManager:
    """
    Manages virtual environments for isolated apps.
    Auto-creates venv and installs dependencies when requirements.txt is present.
    """
    
    def __init__(self):
        self.is_windows = platform.system() == "Windows"
    
    def get_venv_path(self, app_path: Path, venv_name: str = ".venv") -> Path:
        """Get the virtual environment path for an app."""
        return app_path / venv_name
    
    def get_python_executable(self, venv_path: Path) -> Path:
        """Get the Python executable path within a virtual environment."""
        if self.is_windows:
            return venv_path / "Scripts" / "python.exe"
        else:
            return venv_path / "bin" / "python"
    
    def get_pip_executable(self, venv_path: Path) -> Path:
        """Get the pip executable path within a virtual environment."""
        if self.is_windows:
            return venv_path / "Scripts" / "pip.exe"
        else:
            return venv_path / "bin" / "pip"
    
    def venv_exists(self, venv_path: Path) -> bool:
        """Check if a virtual environment exists and is valid."""
        python_exe = self.get_python_executable(venv_path)
        return venv_path.exists() and python_exe.exists()
    
    def has_requirements(self, app_path: Path) -> bool:
        """Check if an app has a requirements.txt file."""
        return (app_path / "requirements.txt").exists()
    
    def create_venv(self, venv_path: Path) -> Tuple[bool, str]:
        """
        Create a new virtual environment.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            logger.info(f"Creating virtual environment at {venv_path}")
            
            # Use the current Python interpreter to create venv
            result = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error creating venv"
                logger.error(f"Failed to create venv: {error_msg}")
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
        
        Returns:
            Tuple of (success, message)
        """
        pip_exe = self.get_pip_executable(venv_path)
        
        if not pip_exe.exists():
            return False, f"pip not found at {pip_exe}"
        
        if not requirements_file.exists():
            return False, f"Requirements file not found: {requirements_file}"
        
        try:
            logger.info(f"Installing requirements from {requirements_file}")
            
            # Upgrade pip first
            subprocess.run(
                [str(pip_exe), "install", "--upgrade", "pip"],
                capture_output=True,
                text=True
            )
            
            # Install requirements
            result = subprocess.run(
                [str(pip_exe), "install", "-r", str(requirements_file)],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error installing requirements"
                logger.error(f"Failed to install requirements: {error_msg}")
                return False, error_msg
            
            logger.info(f"Requirements installed successfully from {requirements_file}")
            return True, "Requirements installed successfully"
            
        except Exception as e:
            error_msg = f"Exception installing requirements: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def ensure_venv(self, app_path: Path, venv_name: str = ".venv") -> Tuple[bool, Path, str]:
        """
        Ensure a virtual environment exists for an app with requirements.txt.
        Creates the venv if it doesn't exist and installs requirements.
        
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
        
        # Create venv if it doesn't exist
        if not self.venv_exists(venv_path):
            success, message = self.create_venv(venv_path)
            if not success:
                return False, venv_path, message
        else:
            logger.info(f"Virtual environment already exists at {venv_path}")
        
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
            # Prepend venv bin to PATH
            if self.is_windows:
                run_env["PATH"] = f"{venv_path / 'Scripts'};{run_env.get('PATH', '')}"
            else:
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
