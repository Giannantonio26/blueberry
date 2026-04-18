from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_FILE = Path(__file__).with_name("requirements.txt")
CHROMA_SETUP_SCRIPT = Path(__file__).with_name("chroma_setup.py")
LOCAL_TEMP_DIR = PROJECT_ROOT / ".tmp" / "python-setup"


def get_venv_python_path() -> Path:
    """
    Return venv python path.
    Returns a resolved filesystem path value.
    """
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_virtualenv() -> Path:
    """
    Ensure virtualenv.
    Returns a resolved filesystem path value.
    """
    venv_python = get_venv_python_path()
    if venv_python.exists():
        return venv_python

    LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    local_temp_path = str(LOCAL_TEMP_DIR)
    os.environ["TMPDIR"] = local_temp_path
    os.environ["TEMP"] = local_temp_path
    os.environ["TMP"] = local_temp_path
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(VENV_DIR)
    return venv_python


def run_command(command: list[str]) -> None:
    """
    Run command.
    Performs side effects and returns no value.
    """
    LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    environment = build_environment()
    subprocess.check_call(command, cwd=PROJECT_ROOT, env=environment)


def build_environment() -> dict[str, str]:
    """
    Build environment.
    Returns a structured mapping with operation details.
    """
    LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    local_temp_path = str(LOCAL_TEMP_DIR)
    environment["TMPDIR"] = local_temp_path
    environment["TEMP"] = local_temp_path
    environment["TMP"] = local_temp_path
    return environment


def ensure_pip(venv_python: Path) -> None:
    """
    Ensure pip.
    Key behavior: invokes external processes.
    Performs side effects and returns no value.
    """
    pip_check = subprocess.run(
        [str(venv_python), "-m", "pip", "--version"],
        cwd=PROJECT_ROOT,
        env=build_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    if pip_check.returncode != 0:
        run_command(
            [str(venv_python), "-m", "ensurepip", "--upgrade", "--default-pip"]
        )


def main() -> None:
    """
    Run the main entry-point workflow for this module.
    Performs side effects and returns no value.
    """
    parser = argparse.ArgumentParser(
        description="Create the local Python environment and install Blueberry agent dependencies."
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run the Chroma smoke test after installing dependencies.",
    )
    args = parser.parse_args()

    venv_python = ensure_virtualenv()
    ensure_pip(venv_python)

    run_command([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    run_command([str(venv_python), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])
    run_command([str(venv_python), str(CHROMA_SETUP_SCRIPT), "--bootstrap"])

    if args.smoke_test:
        run_command([str(venv_python), str(CHROMA_SETUP_SCRIPT), "--smoke-test"])


if __name__ == "__main__":
    main()
