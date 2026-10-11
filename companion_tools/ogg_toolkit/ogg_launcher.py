"""Bundled CTR OGG toolkit entrypoint (no external BAT/PS1 in the ZIP)."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def run():
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    script = resources / "CTR_Music_Toolkit_GUI.ps1"
    if sys.platform != "win32" or not script.is_file():
        return 2
    command = [
        "powershell.exe", "-NoLogo", "-NoProfile", "-Sta",
        "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
        "-File", str(script)
    ]
    try:
        return subprocess.run(command, cwd=str(resources), check=False).returncode
    except OSError:
        return 3


if __name__ == "__main__":
    raise SystemExit(run())
