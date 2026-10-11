"""Check every official game-install file before enabling PLAY.

The game's original disc file is user-supplied and never distributed by Forge.
Personal mods, save files and user configurations are intentionally optional.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

# Fallback for v2.1.0 installations made before the installer wrote
# an explicit package manifest. These are exactly the files in its ZIP.
RELEASE_210 = (
    "ctr-native.exe",
    "LICENSE.txt",
    "README_FIRST.txt",
    "THIRD_PARTY_NOTICES.txt",
    "assets/UI_NATIVE/blankbuttons.png",
    "assets/UI_NATIVE/cnk_turbo_gauge.png",
    "assets/UI_NATIVE/control_glyphs.png",
    "assets/UI_NATIVE/finalbuttons.png",
)
DISC_IMAGE = "assets/ctr-u.bin"


def _safe_package_paths(items):
    """Accept only relative, bounded file paths from the official install list."""
    if not isinstance(items, list) or len(items) > 20000:
        return None
    output, seen = [], set()
    for item in items:
        if isinstance(item, dict):
            item = item.get("path")
        if not isinstance(item, str) or not (1 <= len(item) <= 260):
            return None
        if "\\" in item or item.startswith("/") or ":" in item:
            return None
        segments = item.split("/")
        if any(p in ("", ".", "..") for p in segments):
            return None
        identity = item.casefold()
        if identity in seen:
            return None
        seen.add(identity)
        output.append(item)
    if "ctr-native.exe" not in seen:
        return None
    return output


def required_game_files(game_path):
    """Return the complete official package list plus the original CTR disc.

    2.1.0 predates installer manifests; later verified game ZIPs save their
    own file list in forge_release_state.json. No automatic file searches.
    """
    if not isinstance(game_path, (str, os.PathLike)) or not os.fspath(game_path):
        return ("ctr-native.exe", DISC_IMAGE), ""
    root = Path(game_path)
    marker = root / "forge_release_state.json"
    paths = ["ctr-native.exe"]
    if marker.is_file():
        try:
            if marker.stat().st_size > 2_000_000:
                raise ValueError("Oversized game release manifest")
            data = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Invalid game release manifest")
            manifest = data.get("package_files")
            if manifest is not None:
                checked = _safe_package_paths(manifest)
                if checked is None:
                    raise ValueError("Invalid package file list")
                paths = checked
            elif data.get("version") == "2.1.0":
                paths = list(RELEASE_210)
        except (OSError, UnicodeError, ValueError, TypeError):
            return tuple(paths + [DISC_IMAGE]), "forge_release_state.json is unreadable or damaged"
    elif marker.exists():
        return tuple(paths + [DISC_IMAGE]), "forge_release_state.json cannot be read"
    paths = list(dict.fromkeys([*paths, DISC_IMAGE]))
    return tuple(paths), ""


def missing_game_files(game_path):
    """Check all official files without scanning personal mods or user data."""
    if not isinstance(game_path, (str, os.PathLike)) or not os.fspath(game_path):
        return ["ctr-native.exe", DISC_IMAGE]
    root = Path(game_path)
    required, manifest_error = required_game_files(root)
    if manifest_error:
        return [manifest_error]
    missing = []
    for name in required:
        path = root.joinpath(*name.split("/"))
        try:
            if not path.is_file():
                missing.append(name)
            elif name == DISC_IMAGE and path.stat().st_size < 2352:
                missing.append(name + " (empty/incomplete)")
            elif name != DISC_IMAGE and path.stat().st_size == 0:
                missing.append(name + " (empty)")
        except OSError:
            missing.append(name + " (unreadable)")
    return missing


def launch_issue(game_path):
    if not isinstance(game_path, (str, os.PathLike)) or not os.fspath(game_path):
        return "Select your game installation folder in Launcher Settings."
    root = Path(game_path)
    if not root.is_dir():
        return "The selected game folder does not exist. Check Settings."
    missing = missing_game_files(root)
    if not missing:
        return ""
    names = ", ".join(missing[:5])
    if len(missing) > 5:
        names += " and " + str(len(missing) - 5) + " more"
    issue = "Missing required game files: " + names
    if any(name.startswith(DISC_IMAGE) for name in missing):
        issue += ". Supply your own legally obtained raw NTSC-U disc image (MODE2/2352) at assets/ctr-u.bin."
    return issue


def repair_local_files(game_path):
    """Create only root mods/; report other missing official files accurately."""
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
        created = not mods.is_dir()
        mods.mkdir(exist_ok=True)
    except OSError as exc:
        return {"ok": False, "detail": "Could not prepare game mods folder: " + str(exc)}
    missing = missing_game_files(root)
    explanation = ("Root mods folder created." if created else "Root mods folder ready.")
    if missing:
        detail = explanation + " " + launch_issue(root) + " Repair did not replace these files."
    else:
        detail = explanation + " All official required files were found."
    return {
        "ok": True, "detail": detail, "created_mods": created,
        "missing_disc": any(item.startswith(DISC_IMAGE) for item in missing),
        "missing_required": missing, "ready": not missing,
    }
