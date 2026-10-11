"""Bundled OGG Toolkit: no external Python and no visible console."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from forge_editor_config import find_game_installation

def bundled_resources():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

def create_editor_environment():
    env = os.environ.copy()
    game = find_game_installation(source_file=__file__)
    if game is not None:
        env["CFR_GAME_PATH"] = str(game)
    return env

def run():
    resources = bundled_resources()
    script = resources / "CTR_Music_Toolkit_GUI.ps1"
    icon = resources / "forge_assets" / "icons" / "cfr_icon.ico"
    logo = resources / "forge_assets" / "icons" / "cfr_icon.png"
    if sys.platform != "win32" or not all(p.is_file() for p in (script, icon, logo)):
        return 2
    argv = sys.argv[1:]
    if argv == ["--self-test"]:
        return 0
    if argv not in ([], ["--ui-smoke"]):
        return 2
    command = [
        str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
        "-NoLogo", "-NoProfile", "-Sta", "-NonInteractive",
        "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
        "-File", str(script)
    ]
    env = create_editor_environment()
    if argv == ["--ui-smoke"]:
        env["CFR_OGG_SMOKE"] = "1"
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    try:
        result = subprocess.run(
            command, cwd=str(resources), env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
            startupinfo=startup,
            capture_output=bool(argv), text=bool(argv),
            check=False, timeout=45 if argv else None,
        )
        if argv == ["--ui-smoke"]:
            diagnostic_path = env.get("CFR_OGG_SMOKE_OUTPUT")
            if diagnostic_path and result.stdout:
                Path(diagnostic_path).write_text(
                    result.stdout.strip() + "\n", encoding="utf-8"
                )
            elif result.stdout and sys.stdout is not None:
                print(result.stdout, flush=True)
        return result.returncode
    except (OSError, subprocess.TimeoutExpired):
        return 3

if __name__ == "__main__":
    raise SystemExit(run())