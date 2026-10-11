"""Safe, explicit game launch checks and non-destructive local repairs.

The user-selected game directory is authoritative. No disc images or personal
mods are searched for, copied, replaced or downloaded by these operations.
"""
from __future__ import annotations

import os
from pathlib import Path


def launch_issue(game_path):
    """Return a user-readable blocker, or empty string if launch can proceed."""
    if not isinstance(game_path, (str, os.PathLike)) or not os.fspath(game_path):
        return "Select your game installation folder in Launcher Settings."
    root = Path(game_path)
    if not root.is_dir():
        return "The selected game folder does not exist. Check Settings."
    if not (root / "ctr-native.exe").is_file():
        return "ctr-native.exe is missing from the selected game folder."
    image = root / "assets" / "ctr-u.bin"
    if not image.is_file():
        return ("Missing original CTR disc data: assets/ctr-u.bin. "
                "Add your own legally obtained raw NTSC-U disc image "
                "(MODE2/2352) to the selected game's assets folder.")
    try:
        if image.stat().st_size < 2352:
            return "assets/ctr-u.bin is empty or too small to contain valid disc data."
    except OSError:
        return "Could not read assets/ctr-u.bin from the selected game folder."
    return ""


def repair_local_files(game_path):
    """Repair root mods/ only; inspect executable and original data without touching them."""
    if not isinstance(game_path, (str, os.PathLike)) or not os.fspath(game_path):
        return {"ok": False, "detail": "Select the game folder in Settings."}
    root = Path(game_path)
    if not root.is_dir():
        return {"ok": False, "detail": "Selected game folder does not exist."}
    if not (root / "ctr-native.exe").is_file():
        return {"ok": False, "detail": "ctr-native.exe missing. Install or update the game first."}
    mods = root / "mods"
    try:
        if mods.exists() and not mods.is_dir():
            return {"ok": False, "detail": "A file named mods blocks the mod folder."}
        missing = not mods.is_dir()
        mods.mkdir(exist_ok=True)
    except OSError as exc:
        return {"ok": False, "detail": "Could not prepare game mods folder: " + str(exc)}
    if (root / "assets" / "ctr-u.bin").is_file():
        return {"ok": True, "detail": "Game executable and original disc present; "
                + ("created root mods folder." if missing else "root mods folder ready."),
                "created_mods": missing, "missing_disc": False}
    return {"ok": True, "detail": ("Root mods folder created. " if missing else
                                 "Root mods folder ready. ")
            + "Original disc data assets/ctr-u.bin is missing; Repair cannot provide it.",
            "created_mods": missing, "missing_disc": True}
