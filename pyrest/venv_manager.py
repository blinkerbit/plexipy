"""
Virtual Environment Manager for PyRest framework.
Fully async -- uses asyncio.create_subprocess_exec for all subprocess operations.

Designed for Linux Docker containers (Python 3.14+).
"""

import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

DEFAULT_VENV_NAME = ".venv"

logger = logging.getLogger("pyrest.venv_manager")


async def _run_cmd(
    *args: str,
    timeout: float = 300,
) -> tuple[int, str, str]:
    """
    Run a command asynchronously and return (returncode, stdout, stderr).
    All subprocess operations go through this single helper.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(timeout):
            stdout_bytes, stderr_bytes = await proc.communicate()
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", f"Command timed out after {timeout}s: {' '.join(args)}"

    return (
        proc.returncode or 0,
        (stdout_bytes or b"").decode(errors="replace"),
        (stderr_bytes or b"").decode(errors="replace"),
    )


class VenvManager:
    """
    Manages virtual environments for isolated apps.
    All heavy operations (create, install, remove) are async.

    Designed for Linux Docker containers -- uses Linux-style paths (bin/python).
    Uses uv for fast package installation if available.
    """

    def __init__(self) -> None:
        self._setup_pip_script = Path(__file__).parent.parent / "setup_pip.sh"
        # uv check is done once at init (sync, very fast)
        self._uv_available = self._check_uv_available()

    # ------------------------------------------------------------------
    # Init-time helpers (sync -- only called once)
    # ------------------------------------------------------------------

    def _check_uv_available(self) -> bool:
        """Check if uv is available for package installation (sync, init-time)."""
        import subprocess as _sp

        try:
            result = _sp.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                logger.info("=" * 60)
                logger.info(f"UV DETECTED: {version}")
                logger.info("Using uv for fast venv creation and package installation")
                logger.info("=" * 60)
                return True
        except FileNotFoundError:
            logger.info("uv command not found in PATH")
        except Exception as e:
            logger.warning(f"uv check failed: {e}")
        logger.info("uv not available, will use pip for package management")
        return False

    # ------------------------------------------------------------------
    # Pure functions (no I/O)
    # ------------------------------------------------------------------

    @staticmethod
    def get_venv_path(app_path: Path, venv_name: str = DEFAULT_VENV_NAME) -> Path:
        """Get the virtual environment path for an app (inside app folder)."""
        return app_path.resolve() / venv_name

    @staticmethod
    def get_python_executable(venv_path: Path) -> Path:
        """Get the Python executable path within a venv (Linux: bin/python)."""
        return venv_path / "bin" / "python"

    @staticmethod
    def get_pip_executable(venv_path: Path) -> Path:
        """Get the pip executable path within a venv (Linux: bin/pip)."""
        return venv_path / "bin" / "pip"

    @staticmethod
    def venv_exists(venv_path: Path) -> bool:
        """Check if a virtual environment exists and is valid."""
        if not venv_path.exists():
            return False
        python_exe = venv_path / "bin" / "python"
        if not python_exe.exists():
            logger.warning(f"Venv at {venv_path} missing Python executable at {python_exe}")
            return False
        if not os.access(python_exe, os.X_OK):
            logger.warning(f"Python at {python_exe} is not executable")
            return False
        return True

    @staticmethod
    def has_requirements(app_path: Path) -> bool:
        """Check if an app has a requirements.txt file."""
        return (app_path / "requirements.txt").exists()

    def get_app_python(self, app_path: Path, venv_name: str = DEFAULT_VENV_NAME) -> Path:
        """Return venv Python if it exists, else system Python."""
        venv_path = self.get_venv_path(app_path, venv_name)
        python_exe = self.get_python_executable(venv_path)
        return python_exe if python_exe.exists() else Path(sys.executable)

    # ------------------------------------------------------------------
    # Async operations
    # ------------------------------------------------------------------

    def _parse_env_line(self, line: str) -> tuple[str, str] | None:
        """Helper to parse a KEY=VALUE line."""
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        
        if line.startswith("export "):
            line = line[7:].strip()
            
        if "=" in line:
            key, value = line.split("=", 1)
            return key.strip(), value.strip().strip('"').strip("'")
        return None

    def _apply_env_vars(self, lines: list[str]) -> None:
        """Helper to parse and apply env vars from lines."""
        for line in lines:
            kv = self._parse_env_line(line)
            if kv:
                os.environ[kv[0]] = kv[1]

    async def _load_pip_env(self) -> None:
        """Async: source setup_pip.sh to load proxy env vars."""
        if not self._setup_pip_script.exists():
            return
            
        try:
            if os.access(self._setup_pip_script, os.X_OK):
                # Script is executable, try running it
                rc, stdout, _ = await _run_cmd(
                    "bash",
                    "-c",
                    f"source {self._setup_pip_script} && env",
                    timeout=10,
                )
                if rc == 0:
                    self._apply_env_vars(stdout.splitlines())
            else:
                # Script is not executable, parse manually
                content = await asyncio.to_thread(self._setup_pip_script.read_text)
                self._apply_env_vars(content.splitlines())
                        
        except Exception as e:
            logger.warning(f"Failed to load pip env from setup_pip.sh: {e}")

    async def create_venv(self, venv_path: Path) -> tuple[bool, str]:
        """
        Async: create a new virtual environment.
        Uses uv if available for faster creation.
        """
        try:
            tool = "uv" if self._uv_available else "venv"
            logger.info("=" * 60)
            logger.info(f"CREATING VENV: {venv_path}")
            logger.info(f"Using: {tool}  |  Python: {sys.executable}")
            logger.info("=" * 60)

            await self._load_pip_env()

            if self._uv_available:
                rc, stdout, stderr = await _run_cmd(
                    "uv",
                    "venv",
                    str(venv_path),
                    "--python",
                    sys.executable,
                    timeout=60,
                )
            else:
                rc, stdout, stderr = await _run_cmd(
                    sys.executable,
                    "-m",
                    "venv",
                    str(venv_path),
                    timeout=60,
                )

            if stdout:
                logger.info(f"venv creation stdout:\n{stdout}")
            if stderr:
                logger.info(f"venv creation stderr:\n{stderr}")

            if rc != 0:
                error_msg = stderr or "Unknown error creating venv"
                logger.error(f"Failed to create venv (exit code {rc}): {error_msg}")
                return False, error_msg

            logger.info(f"Virtual environment created at {venv_path}")
            return True, "Virtual environment created successfully"

        except Exception as e:
            error_msg = f"Exception creating venv: {e}"
            logger.exception(error_msg)
            return False, error_msg

    async def _install_with_uv(
        self, venv_path: Path, requirements_file: Path
    ) -> tuple[int, str, str]:
        """Install requirements using uv."""
        logger.info("Installing packages using uv...")
        return await _run_cmd(
            "uv",
            "pip",
            "install",
            "--python",
            str(self.get_python_executable(venv_path)),
            "-r",
            str(requirements_file),
            timeout=300,
        )

    async def _install_with_pip(
        self, venv_path: Path, requirements_file: Path
    ) -> tuple[int, str, str]:
        """Install requirements using pip."""
        pip_exe = self.get_pip_executable(venv_path)
        logger.info("Upgrading pip...")
        
        # Upgrade pip first
        up_rc, up_out, up_err = await _run_cmd(
            str(pip_exe),
            "install",
            "--upgrade",
            "pip",
            timeout=60,
        )
        if up_rc != 0:
            logger.warning(f"pip upgrade failed: {up_err}")
        else:
            logger.info(f"pip upgraded: {up_out.strip()}")

        logger.info("Installing packages using pip...")
        return await _run_cmd(
            str(pip_exe),
            "install",
            "-r",
            str(requirements_file),
            timeout=300,
        )

    async def install_requirements(
        self, venv_path: Path, requirements_file: Path
    ) -> tuple[bool, str]:
        """
        Async: install requirements from requirements.txt into a venv.
        Uses uv if available (faster), falls back to pip.
        """
        venv_path = venv_path.resolve()

        if not requirements_file.exists():
            return False, f"Requirements file not found: {requirements_file}"

        pip_exe = self.get_pip_executable(venv_path)
        if not self._uv_available and not pip_exe.exists():
            return False, f"pip not found at {pip_exe} (venv: {venv_path})"

        installer = "uv" if self._uv_available else "pip"
        logger.info("=" * 60)
        logger.info(f"INSTALLING REQUIREMENTS: {requirements_file.name}")
        logger.info(f"Installer: {installer}  |  Venv: {venv_path}")
        logger.info("=" * 60)

        # Log requirements (async file read)
        try:
            content = await asyncio.to_thread(requirements_file.read_text)
            logger.info(f"Requirements:\n{content}")
        except Exception as e:
            logger.warning(f"Could not read requirements file: {e}")

        await self._load_pip_env()

        try:
            if self._uv_available:
                rc, stdout, stderr = await self._install_with_uv(venv_path, requirements_file)
            else:
                rc, stdout, stderr = await self._install_with_pip(venv_path, requirements_file)

            if stdout:
                logger.info(f"{installer} install stdout:\n{stdout}")
            if stderr:
                logger.info(f"{installer} install stderr:\n{stderr}")

            if rc != 0:
                error_msg = stderr or f"Unknown error installing with {installer}"
                logger.error(f"Failed to install requirements (exit code {rc})")
                return False, error_msg

            logger.info(f"Requirements installed successfully using {installer}")
            return True, "Requirements installed successfully"

        except Exception as e:
            error_msg = f"Exception installing requirements: {e}"
            logger.exception(error_msg)
            return False, error_msg

    async def remove_venv(self, venv_path: Path) -> tuple[bool, str]:
        """Async: remove a virtual environment directory."""
        if not venv_path.exists():
            return True, "Venv does not exist"
        try:
            await asyncio.to_thread(shutil.rmtree, str(venv_path))
            logger.info(f"Removed venv at {venv_path}")
            return True, "Venv removed"
        except Exception as e:
            error_msg = f"Failed to remove venv: {e}"
            logger.exception(error_msg)
            return False, error_msg

    async def ensure_venv(self, app_path: Path, venv_name: str = DEFAULT_VENV_NAME) -> tuple[bool, Path, str]:
        """
        Async: ensure a virtual environment exists and has deps installed.

        Args:
            app_path: Path to the app directory
            venv_name: Name of the venv directory (default: .venv)

        Returns:
            Tuple of (success, venv_path, message)
        """
        venv_path = self.get_venv_path(app_path, venv_name).resolve()
        requirements_file = app_path / "requirements.txt"

        if not requirements_file.exists():
            return True, venv_path, "No requirements.txt found, using parent environment"

        logger.info(f"Ensuring venv at: {venv_path}")

        if not self.venv_exists(venv_path):
            # Invalid venv -- remove and recreate
            if venv_path.exists():
                logger.warning(f"Invalid venv at {venv_path}, removing...")
                ok, msg = await self.remove_venv(venv_path)
                if not ok:
                    return False, venv_path, msg

            ok, msg = await self.create_venv(venv_path)
            if not ok:
                return False, venv_path, msg
        else:
            logger.info(f"Venv already valid at {venv_path}")

        # Install/update requirements
        ok, msg = await self.install_requirements(venv_path, requirements_file)
        if not ok:
            return False, venv_path, msg

        return True, venv_path, "Virtual environment ready"

    async def run_in_venv(
        self,
        app_path: Path,
        command: list[str],
        venv_name: str = DEFAULT_VENV_NAME,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> asyncio.subprocess.Process:
        """
        Async: run a command using the app's virtual environment.

        Returns:
            asyncio.subprocess.Process
        """
        python_exe = self.get_app_python(app_path, venv_name)

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        venv_path = self.get_venv_path(app_path, venv_name)
        if venv_path.exists():
            run_env["VIRTUAL_ENV"] = str(venv_path)
            run_env["PATH"] = f"{venv_path / 'bin'}:{run_env.get('PATH', '')}"

        full_command = [str(python_exe), *command]
        logger.info(f"Running in venv: {' '.join(full_command)}")

        return await asyncio.create_subprocess_exec(
            *full_command,
            cwd=str(cwd or app_path),
            env=run_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )


# Singleton
_venv_manager: VenvManager | None = None


def get_venv_manager() -> VenvManager:
    """Get the singleton VenvManager instance."""
    global _venv_manager
    if _venv_manager is None:
        _venv_manager = VenvManager()
    return _venv_manager
