"""Create or update the app's own Python environment. Safe to run every time.

    python setup_env.py

Makes a virtual environment in ~/meeting-live/venv (or $MEETING_LIVE_HOME/venv),
installs requirements.txt, plus requirements-gpu.txt when an NVIDIA GPU is found,
and skips installing when nothing changed since the last run. The last line
printed is the environment's Python, used to start the app:

    <that python> -m app.main
"""

import hashlib
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MEETING_LIVE_HOME") or Path.home() / "meeting-live")
VENV = DATA_DIR / "venv"
PYTHON = VENV / "Scripts" / "python.exe" if os.name == "nt" else VENV / "bin" / "python"
STAMP = VENV / ".installed"


def _see_system_packages():
    """Turn on system packages for an environment made before they were used."""
    cfg = VENV / "pyvenv.cfg"
    text = cfg.read_text(encoding="utf-8")
    if "include-system-site-packages = false" in text:
        cfg.write_text(text.replace("include-system-site-packages = false",
                                    "include-system-site-packages = true"), encoding="utf-8")


def main():
    if sys.version_info < (3, 10):
        sys.exit(f"Python 3.10 or newer is needed, this is {sys.version.split()[0]}.")
    if os.name != "nt":
        sys.exit("meeting-live runs on Windows for now.")

    requirements = [HERE / "requirements.txt"]
    if shutil.which("nvidia-smi"):
        requirements.append(HERE / "requirements-gpu.txt")
    stamp = hashlib.sha256(b"".join(path.read_bytes() for path in requirements)).hexdigest()

    if not PYTHON.exists():
        print(f"Creating environment in {VENV}", flush=True)
        # Seeing the system's packages means anything already installed at a
        # fitting version is reused instead of being downloaded and stored twice.
        venv.create(VENV, with_pip=True, system_site_packages=True)
    else:
        _see_system_packages()
    if not STAMP.exists() or STAMP.read_text() != stamp:
        print("Installing packages (first time takes a few minutes)", flush=True)
        args = [str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "-q"]
        for path in requirements:
            args += ["-r", str(path)]
        subprocess.run(args, check=True)
        STAMP.write_text(stamp)
    else:
        print("Environment is up to date", flush=True)
    print(PYTHON)


if __name__ == "__main__":
    main()
