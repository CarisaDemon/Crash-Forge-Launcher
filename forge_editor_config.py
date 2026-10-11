"""Shared, portable Crash Forge game location resolution for bundled editors.

The launcher is the sole writer of game_install_path. Independent editor EXEs
read that setting, so standalone opening works without installed Python or
machine-specific paths. Env overrides are accepted ONLY for valid game roots.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def valid_game_root(value):
    if not value:
        return None
    try:
        text = str(value).strip().strip('"')
        if not text:
            return None
        path = Path(os.path.expandvars(text)).expanduser()
        if path.suffix.casefold() == ".exe":
            path = path.parent
        path = path.resolve()
        if path.is_dir() and (
            (path / "ctr-native.exe").is_file() or
            (path / "ctr_native.exe").is_file()
        ):
            return path
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def launcher_settings_candidates(*, executable=None, source_file=None, environment=None):
    env = environment if environment is not None else os.environ
    paths = []
    hint = env.get("CFR_LAUNCHER_SETTINGS", "").strip().strip('"')
    if hint:
        paths.append(Path(hint))
    paths_from = []
    if executable is None:
        executable = sys.executable
    if executable:
        paths_from.append(Path(executable).resolve().parent)
    if source_file is not None:
        paths_from.append(Path(source_file).resolve().parent)
    # When an editor is in <launcher>/_internal/editor_tools/, walking up
    # reaches the real launcher_settings.json (and never a C:\-specific path).
    for root in paths_from:
        paths.extend(parent / "launcher_settings.json" for parent in
                     (root, *list(root.parents)[:3]))
    unique = []
    seen = set()
    for path in paths:
        normalized = os.path.normcase(str(path))
        if normalized not in seen:
            seen.add(normalized)
            unique.append(path)
    return unique


def find_game_installation(*, executable=None, source_file=None, environment=None):
    env = environment if environment is not None else os.environ
    preferred = valid_game_root(env.get("CFR_GAME_PATH", ""))
    if preferred is not None:
        return preferred
    for settings in launcher_settings_candidates(
        executable=executable, source_file=source_file, environment=env
    ):
        try:
            if not settings.is_file() or settings.stat().st_size > 65536:
                continue
            obj = json.loads(settings.read_text(encoding="utf-8-sig"))
            if not isinstance(obj, dict):
                continue
            candidate = valid_game_root(obj.get("game_install_path", ""))
            if candidate is not None:
                return candidate
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
    return None