"""
Tests for the virtual environment manager module.
"""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.venv_manager import VenvManager, get_venv_manager


class TestVenvManager:
    """Tests for VenvManager class."""
    
    @pytest.fixture
    def venv_manager(self):
        """Create VenvManager instance."""
        return VenvManager()
    
    def test_get_venv_path(self, venv_manager, temp_dir: Path):
        """Should return correct venv path."""
        app_path = temp_dir / "myapp"
        
        venv_path = venv_manager.get_venv_path(app_path)
        
        assert venv_path == app_path / ".venv"
    
    def test_get_venv_path_custom(self, venv_manager, temp_dir: Path):
        """Should return custom venv path."""
        app_path = temp_dir / "myapp"
        
        venv_path = venv_manager.get_venv_path(app_path, "custom_venv")
        
        assert venv_path == app_path / "custom_venv"
    
    def test_get_python_executable_windows(self, temp_dir: Path):
        """Should return correct Python path on Windows."""
        manager = VenvManager()
        manager.is_windows = True
        
        venv_path = temp_dir / ".venv"
        python_exe = manager.get_python_executable(venv_path)
        
        assert python_exe == venv_path / "Scripts" / "python.exe"
    
    def test_get_python_executable_unix(self, temp_dir: Path):
        """Should return correct Python path on Unix."""
        manager = VenvManager()
        manager.is_windows = False
        
        venv_path = temp_dir / ".venv"
        python_exe = manager.get_python_executable(venv_path)
        
        assert python_exe == venv_path / "bin" / "python"
    
    def test_get_pip_executable(self, venv_manager, temp_dir: Path):
        """Should return correct pip path."""
        venv_path = temp_dir / ".venv"
        pip_exe = venv_manager.get_pip_executable(venv_path)
        
        if venv_manager.is_windows:
            assert pip_exe == venv_path / "Scripts" / "pip.exe"
        else:
            assert pip_exe == venv_path / "bin" / "pip"
    
    def test_venv_exists_false(self, venv_manager, temp_dir: Path):
        """Should return False for nonexistent venv."""
        venv_path = temp_dir / ".venv"
        
        assert venv_manager.venv_exists(venv_path) is False
    
    def test_has_requirements_true(self, venv_manager, temp_dir: Path):
        """Should detect requirements.txt."""
        app_path = temp_dir / "app"
        app_path.mkdir()
        (app_path / "requirements.txt").write_text("tornado>=6.4")
        
        assert venv_manager.has_requirements(app_path) is True
    
    def test_has_requirements_false(self, venv_manager, temp_dir: Path):
        """Should return False without requirements.txt."""
        app_path = temp_dir / "app"
        app_path.mkdir()
        
        assert venv_manager.has_requirements(app_path) is False
    
    def test_create_venv(self, venv_manager, temp_dir: Path):
        """Should create virtual environment."""
        venv_path = temp_dir / "test_venv"
        
        success, message = venv_manager.create_venv(venv_path)
        
        assert success is True
        assert venv_path.exists()
        assert venv_manager.get_python_executable(venv_path).exists()
    
    def test_create_venv_failure(self, venv_manager, temp_dir: Path):
        """Should handle venv creation failure."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "Error creating venv"
            
            venv_path = temp_dir / "failed_venv"
            success, message = venv_manager.create_venv(venv_path)
            
            assert success is False
            assert "Error" in message
    
    def test_install_requirements(self, venv_manager, temp_dir: Path):
        """Should install requirements into venv."""
        # Create a real venv first
        venv_path = temp_dir / "venv_for_install"
        venv_manager.create_venv(venv_path)
        
        # Create requirements file with just pip (already installed)
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("pip")
        
        success, message = venv_manager.install_requirements(venv_path, req_file)
        
        assert success is True
    
    def test_install_requirements_no_pip(self, venv_manager, temp_dir: Path):
        """Should fail if pip not found."""
        venv_path = temp_dir / "no_pip_venv"
        venv_path.mkdir()
        
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("somepackage")
        
        success, message = venv_manager.install_requirements(venv_path, req_file)
        
        assert success is False
        assert "pip not found" in message
    
    def test_ensure_venv_no_requirements(self, venv_manager, temp_dir: Path):
        """Should skip venv creation if no requirements.txt."""
        app_path = temp_dir / "no_reqs_app"
        app_path.mkdir()
        
        success, venv_path, message = venv_manager.ensure_venv(app_path)
        
        assert success is True
        assert "No requirements.txt" in message
    
    def test_ensure_venv_with_requirements(self, venv_manager, temp_dir: Path):
        """Should create venv and install requirements."""
        app_path = temp_dir / "app_with_reqs"
        app_path.mkdir()
        
        # Create requirements.txt
        (app_path / "requirements.txt").write_text("pip")
        
        success, venv_path, message = venv_manager.ensure_venv(app_path)
        
        assert success is True
        assert venv_path.exists()
        assert "ready" in message.lower()
    
    def test_get_app_python_with_venv(self, venv_manager, temp_dir: Path):
        """Should return venv Python if exists."""
        app_path = temp_dir / "app"
        app_path.mkdir()
        
        # Create venv
        venv_path = app_path / ".venv"
        venv_manager.create_venv(venv_path)
        
        python_exe = venv_manager.get_app_python(app_path)
        
        assert ".venv" in str(python_exe)
    
    def test_get_app_python_without_venv(self, venv_manager, temp_dir: Path):
        """Should return system Python if no venv."""
        app_path = temp_dir / "app_no_venv"
        app_path.mkdir()
        
        python_exe = venv_manager.get_app_python(app_path)
        
        assert python_exe == Path(sys.executable)


class TestGetVenvManager:
    """Tests for get_venv_manager singleton."""
    
    def test_singleton(self):
        """Should return same instance."""
        # Reset singleton
        import pyrest.venv_manager as vm
        vm._venv_manager = None
        
        manager1 = get_venv_manager()
        manager2 = get_venv_manager()
        
        assert manager1 is manager2
