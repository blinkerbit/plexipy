"""
Tests for the process manager module.
"""

import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.process_manager import ProcessManager, AppProcess, get_process_manager


class TestAppProcess:
    """Tests for AppProcess dataclass."""
    
    def test_is_running_true(self):
        """Should return True for running process."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Still running
        mock_process.pid = 12345
        
        app_process = AppProcess(
            name="testapp",
            port=8001,
            process=mock_process,
            app_path=Path("/test/app")
        )
        
        assert app_process.is_running is True
        assert app_process.pid == 12345
    
    def test_is_running_false(self):
        """Should return False for exited process."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Exited
        
        app_process = AppProcess(
            name="testapp",
            port=8001,
            process=mock_process,
            app_path=Path("/test/app")
        )
        
        assert app_process.is_running is False
        assert app_process.return_code == 0
    
    def test_to_dict(self):
        """Should convert to dictionary."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345
        
        app_process = AppProcess(
            name="testapp",
            port=8001,
            process=mock_process,
            app_path=Path("/test/app"),
            venv_path=Path("/test/app/.venv")
        )
        
        result = app_process.to_dict()
        
        assert result["name"] == "testapp"
        assert result["port"] == 8001
        assert result["pid"] == 12345
        assert result["is_running"] is True
        assert "/test/app" in result["app_path"]


class TestProcessManager:
    """Tests for ProcessManager class."""
    
    @pytest.fixture
    def process_manager(self):
        """Create ProcessManager with mocked config."""
        with patch("pyrest.process_manager.get_config") as mock_config:
            mock_config.return_value.isolated_app_base_port = 8001
            mock_config.return_value.port = 8000
            mock_config.return_value.base_path = "/pyrest"
            mock_config.return_value.auth_config_file = "auth_config.json"
            
            return ProcessManager()
    
    def test_get_next_port(self, process_manager):
        """Should return incrementing ports."""
        port1 = process_manager.get_next_port()
        port2 = process_manager.get_next_port()
        port3 = process_manager.get_next_port()
        
        assert port1 == 8001
        assert port2 == 8002
        assert port3 == 8003
    
    def test_assign_port_preferred(self, process_manager):
        """Should use preferred port if available."""
        port = process_manager.assign_port("testapp", 9000)
        
        assert port == 9000
    
    def test_assign_port_auto(self, process_manager):
        """Should auto-assign if no preferred port."""
        port = process_manager.assign_port("testapp")
        
        assert port == 8001
    
    def test_assign_port_conflict(self, process_manager):
        """Should auto-assign if preferred port in use."""
        # Mock an existing app on port 9000
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        process_manager._processes["existing"] = AppProcess(
            name="existing",
            port=9000,
            process=mock_process,
            app_path=Path("/test")
        )
        
        port = process_manager.assign_port("newapp", 9000)
        
        assert port != 9000
        assert port == 8001
    
    def test_spawn_app(self, process_manager, temp_dir: Path):
        """Should spawn app as subprocess."""
        app_path = temp_dir / "testapp"
        app_path.mkdir()
        
        # Create minimal handlers.py
        (app_path / "handlers.py").write_text("def get_handlers(): return []")
        (app_path / "config.json").write_text('{"name": "testapp"}')
        
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = None
            mock_process.pid = 12345
            mock_popen.return_value = mock_process
            
            result = process_manager.spawn_app(
                app_name="testapp",
                app_path=app_path,
                port=8001
            )
            
            assert result is not None
            assert result.name == "testapp"
            assert result.port == 8001
            assert "testapp" in process_manager._processes
    
    def test_spawn_app_already_running(self, process_manager, temp_dir: Path):
        """Should return existing process if already running."""
        app_path = temp_dir / "testapp"
        
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        
        existing = AppProcess(
            name="testapp",
            port=8001,
            process=mock_process,
            app_path=app_path
        )
        process_manager._processes["testapp"] = existing
        
        result = process_manager.spawn_app(
            app_name="testapp",
            app_path=app_path,
            port=8002
        )
        
        assert result is existing
        assert result.port == 8001  # Original port
    
    def test_spawn_app_failure(self, process_manager, temp_dir: Path):
        """Should return None if spawn fails."""
        app_path = temp_dir / "failapp"
        app_path.mkdir()
        
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = 1  # Exited immediately
            mock_process.communicate.return_value = (b"", b"Error")
            mock_popen.return_value = mock_process
            
            result = process_manager.spawn_app(
                app_name="failapp",
                app_path=app_path,
                port=8001
            )
            
            assert result is None
    
    def test_stop_app(self, process_manager):
        """Should stop running app."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.return_value = 0
        
        process_manager._processes["testapp"] = AppProcess(
            name="testapp",
            port=8001,
            process=mock_process,
            app_path=Path("/test")
        )
        
        result = process_manager.stop_app("testapp")
        
        assert result is True
        mock_process.terminate.assert_called_once()
        assert "testapp" not in process_manager._processes
    
    def test_stop_app_not_running(self, process_manager):
        """Should return False for non-running app."""
        result = process_manager.stop_app("nonexistent")
        
        assert result is False
    
    def test_stop_app_force_kill(self, process_manager):
        """Should force kill if graceful stop fails."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), 0]
        
        process_manager._processes["stubborn"] = AppProcess(
            name="stubborn",
            port=8001,
            process=mock_process,
            app_path=Path("/test")
        )
        
        result = process_manager.stop_app("stubborn", timeout=0.1)
        
        assert result is True
        mock_process.kill.assert_called_once()
    
    def test_get_running_apps(self, process_manager):
        """Should return list of running apps."""
        mock_running = MagicMock()
        mock_running.poll.return_value = None
        
        mock_stopped = MagicMock()
        mock_stopped.poll.return_value = 0
        
        process_manager._processes["running"] = AppProcess(
            name="running", port=8001, process=mock_running, app_path=Path("/test")
        )
        process_manager._processes["stopped"] = AppProcess(
            name="stopped", port=8002, process=mock_stopped, app_path=Path("/test")
        )
        
        running = process_manager.get_running_apps()
        
        assert len(running) == 1
        assert running[0].name == "running"
    
    def test_get_app_status(self, process_manager):
        """Should return status of specific app."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345
        
        process_manager._processes["testapp"] = AppProcess(
            name="testapp",
            port=8001,
            process=mock_process,
            app_path=Path("/test")
        )
        
        status = process_manager.get_app_status("testapp")
        
        assert status is not None
        assert status["name"] == "testapp"
        assert status["is_running"] is True
    
    def test_get_all_status(self, process_manager):
        """Should return status of all apps."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345
        
        process_manager._processes["app1"] = AppProcess(
            name="app1", port=8001, process=mock_process, app_path=Path("/test1")
        )
        process_manager._processes["app2"] = AppProcess(
            name="app2", port=8002, process=mock_process, app_path=Path("/test2")
        )
        
        statuses = process_manager.get_all_status()
        
        assert len(statuses) == 2
    
    def test_shutdown_all(self, process_manager):
        """Should stop all running apps."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.return_value = 0
        
        process_manager._processes["app1"] = AppProcess(
            name="app1", port=8001, process=mock_process, app_path=Path("/test1")
        )
        process_manager._processes["app2"] = AppProcess(
            name="app2", port=8002, process=mock_process, app_path=Path("/test2")
        )
        
        process_manager.shutdown_all()
        
        assert len(process_manager._processes) == 0


class TestGetProcessManager:
    """Tests for get_process_manager singleton."""
    
    def test_singleton(self):
        """Should return same instance."""
        import pyrest.process_manager as pm
        pm._process_manager = None
        
        with patch("pyrest.process_manager.get_config") as mock_config:
            mock_config.return_value.isolated_app_base_port = 8001
            mock_config.return_value.port = 8000
            mock_config.return_value.base_path = "/pyrest"
            mock_config.return_value.auth_config_file = "auth_config.json"
            
            manager1 = get_process_manager()
            manager2 = get_process_manager()
            
            assert manager1 is manager2
