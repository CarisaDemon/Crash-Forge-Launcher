"""Authoritative game installation path shared by every Crash Forge editor.

Only the launcher writes the selected game directory. Tools can read it even if
the game EXE is missing, so they show a helpful error instead of guessing a
different installation or asking the creator to select another game folder.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def _selected_root(value):
    """Parse explicit launcher selection without requiring installed game files."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        raw = os.path.expandvars(value.strip().strip('"'))
        root = Path(raw).expanduser()
        if not root.is_absolute():
            return None
        if root.suffix.casefold() == ".exe":
            root = root.parent
        return root.resolve(strict=False)
    except (OSError, ValueError, RuntimeError):
        return None


def valid_game_root(value):
    """A selected install is usable only when it contains the native executable."""
    root = _selected_root(str(value)) if value else None
    try:
        if root is not None and root.is_dir() and any(
                (root / exe).is_file() for exe in ("ctr-native.exe", "ctr_native.exe")):
            return root
    except (OSError, ValueError):
        pass
    return None


def shared_selection_file(*, environment=None):
    """Single per-Windows-user pointer, populated only by the launcher."""
    env = environment if environment is not None else os.environ
    local = env.get("LOCALAPPDATA", "")
    if not local:
        return None
    root = _selected_root(local)
    return root / "CrashForgeRacing" / "launcher_game_selection.json" if root else None


def launcher_settings_candidates(*, executable=None, source_file=None, environment=None):
    env = environment if environment is not None else os.environ
    paths = []
    hint = str(env.get("CFR_LAUNCHER_SETTINGS") or "").strip().strip('"')
    if hint:
        paths.append(Path(hint))
    bases = []
    if executable is None:
        executable = sys.executable
    for arg in (executable, source_file):
        if arg:
            try:
                bases.append(Path(arg).resolve().parent)
            except (OSError, ValueError):
                pass
    for root in bases:
        paths.extend(parent / "launcher_settings.json" for parent in
                     (root, *list(root.parents)[:3]))
    unique, seen = [], set()
    for path in paths:
        norm = os.path.normcase(str(path))
        if norm not in seen:
            seen.add(norm)
            unique.append(path)
    return unique


def _read_settings(path):
    """Return (valid-settings-read, selected-root); blank is authoritative."""
    try:
        if not path.is_file() or path.stat().st_size > 65536:
            return False, None
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict) and isinstance(data.get("game_install_path"), str):
            return True, _selected_root(data["game_install_path"])
    except (OSError, UnicodeError, ValueError, TypeError):
        pass
    return False, None


def save_launcher_selection(settings_file, game_install_path, *, environment=None):
    """Mirror ONLY the launcher-selected path for independently opened EXEs.

    The selected folder is never searched, changed, created, or validated here.
    This is best effort, not a condition for successful launcher Settings save.
    """
    path = shared_selection_file(environment=environment)
    if path is None:
        return False
    try:
        source = Path(settings_file).resolve()
        value = str(game_install_path) if isinstance(game_install_path, str) else ""
        payload = {"schema": 1, "launcher_settings": str(source),
                   "game_install_path": value}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def _read_shared_selection(environment):
    path = shared_selection_file(environment=environment)
    if path is None:
        return False, None
    try:
        if not path.is_file() or path.stat().st_size > 16384:
            return False, None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != 1:
            return False, None
        hint = data.get("launcher_settings")
        if isinstance(hint, str):
            found, directory = _read_settings(Path(hint))
            if found:
                return True, directory
        if isinstance(data.get("game_install_path"), str):
            return True, _selected_root(data["game_install_path"])
    except (OSError, UnicodeError, ValueError, TypeError):
        pass
    return False, None


def selected_game_directory(*, executable=None, source_file=None, environment=None):
    """The exact directory configured in the launcher, regardless of EXE state.

    Explicit settings passed by the currently running launcher take precedence.
    A tool never silently substitutes another local installation or source tree.
    """
    env = environment if environment is not None else os.environ
    hint = str(env.get("CFR_LAUNCHER_SETTINGS") or "").strip().strip('"')
    if hint:
        found, directory = _read_settings(Path(hint))
        if found:
            return directory
    found, directory = _read_shared_selection(env)
    if found:
        return directory
    for settings in launcher_settings_candidates(
            executable=executable, source_file=source_file, environment=env):
        if hint and str(settings) == hint:
            continue
        found, directory = _read_settings(settings)
        if found:
            return directory
    # Compatibility only if the launcher has not written its settings.
    # A stale environment must not override an explicitly selected directory.
    value = env.get("CFR_GAME_PATH")
    if isinstance(value, str) and value.strip():
        return _selected_root(value)
    return None


def find_game_installation(*, executable=None, source_file=None, environment=None):
    """Compatibility API: selected directory only when the game EXE exists."""
    selected = selected_game_directory(
        executable=executable, source_file=source_file, environment=environment)
    return valid_game_root(selected)


def selected_game_explanation(game):
    """Non-modal status suitable for editor windows."""
    if game is None:
        return "No game folder selected in Launcher Settings."
    if valid_game_root(game) is None:
        return "Launcher game folder is missing ctr-native.exe: " + str(game)
    return "Launcher game folder: " + str(game)
