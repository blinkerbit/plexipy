"""
Tests for the virtual environment manager module.
Async tests -- methods like create_venv, install_requirements, ensure_venv are now async.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.venv_manager import VenvManager, get_venv_manager

# VenvManager hardcodes Linux paths (bin/python, bin/pip) for Docker production use.
# Tests that create real venvs and check executable paths must be skipped on Windows.
_skip_on_windows = pytest.mark.skipif(
    sys.platform == "win32",
    reason="VenvManager uses Linux-only paths (bin/python); skipped on Windows",
)


class TestVenvManager:
    """Tests for VenvManager class."""

    @pytest.fixture
    def venv_manager(self):
        return VenvManager()

    def test_get_venv_path(self, venv_manager, temp_dir: Path):
        """Should return correct venv path."""
        app_path = temp_dir / "myapp"
        venv_path = venv_manager.get_venv_path(app_path)
        assert venv_path == (app_path / ".venv").resolve()

    def test_get_venv_path_custom(self, venv_manager, temp_dir: Path):
        """Should return custom venv path."""
        app_path = temp_dir / "myapp"
        venv_path = venv_manager.get_venv_path(app_path, "custom_venv")
        assert venv_path == (app_path / "custom_venv").resolve()

    def test_get_python_executable_unix(self, temp_dir: Path):
        """Should return correct Python path (bin/python on Linux)."""
        manager = VenvManager()
        venv_path = temp_dir / ".venv"
        python_exe = manager.get_python_executable(venv_path)
        assert python_exe == venv_path / "bin" / "python"

    def test_get_pip_executable(self, venv_manager, temp_dir: Path):
        """Should return correct pip path."""
        venv_path = temp_dir / ".venv"
        pip_exe = venv_manager.get_pip_executable(venv_path)
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

    @_skip_on_windows
    @pytest.mark.asyncio
    async def test_create_venv(self, venv_manager, temp_dir: Path):
        """Should create virtual environment (async)."""
        venv_path = temp_dir / "test_venv"
        success, _message = await venv_manager.create_venv(venv_path)
        assert success is True
        assert venv_path.exists()
        assert venv_manager.get_python_executable(venv_path).exists()

    @_skip_on_windows
    @pytest.mark.asyncio
    async def test_install_requirements(self, venv_manager, temp_dir: Path):
        """Should install requirements into venv (async)."""
        venv_path = temp_dir / "venv_for_install"
        await venv_manager.create_venv(venv_path)

        req_file = temp_dir / "requirements.txt"
        req_file.write_text("pip")

        success, _message = await venv_manager.install_requirements(venv_path, req_file)
        assert success is True

    @_skip_on_windows
    @pytest.mark.asyncio
    async def test_install_requirements_no_pip(self, venv_manager, temp_dir: Path):
        """Should fail if pip not found (async)."""
        venv_path = temp_dir / "no_pip_venv"
        venv_path.mkdir()

        req_file = temp_dir / "requirements.txt"
        req_file.write_text("somepackage")

        success, message = await venv_manager.install_requirements(venv_path, req_file)
        assert success is False
        assert "pip not found" in message

    @pytest.mark.asyncio
    async def test_ensure_venv_no_requirements(self, venv_manager, temp_dir: Path):
        """Should skip venv creation if no requirements.txt (async)."""
        app_path = temp_dir / "no_reqs_app"
        app_path.mkdir()

        success, _venv_path, message = await venv_manager.ensure_venv(app_path)
        assert success is True
        assert "No requirements.txt" in message

    @_skip_on_windows
    @pytest.mark.asyncio
    async def test_ensure_venv_with_requirements(self, venv_manager, temp_dir: Path):
        """Should create venv and install requirements (async)."""
        app_path = temp_dir / "app_with_reqs"
        app_path.mkdir()
        (app_path / "requirements.txt").write_text("pip")

        success, venv_path, message = await venv_manager.ensure_venv(app_path)
        assert success is True
        assert venv_path.exists()
        assert "ready" in message.lower()

    @pytest.mark.asyncio
    async def test_remove_venv(self, venv_manager, temp_dir: Path):
        """Should remove venv directory (async)."""
        venv_path = temp_dir / "removable_venv"
        await venv_manager.create_venv(venv_path)
        assert venv_path.exists()

        ok, _msg = await venv_manager.remove_venv(venv_path)
        assert ok is True
        assert not venv_path.exists()

    @pytest.mark.asyncio
    async def test_remove_venv_nonexistent(self, venv_manager, temp_dir: Path):
        """Should succeed when removing nonexistent venv."""
        venv_path = temp_dir / "does_not_exist"
        ok, _msg = await venv_manager.remove_venv(venv_path)
        assert ok is True

    def test_get_app_python_with_venv(self, venv_manager, temp_dir: Path):
        """Should return venv Python if exists (sync check)."""
        app_path = temp_dir / "app"
        app_path.mkdir()
        # Create a fake venv structure
        venv_bin = app_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        fake_python = venv_bin / "python"
        fake_python.touch()
        fake_python.chmod(0o755)

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
        import pyrest.venv_manager as vm

        vm._venv_manager = None

        manager1 = get_venv_manager()
        manager2 = get_venv_manager()
        assert manager1 is manager2
