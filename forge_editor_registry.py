"""Bundled Windows editor selection, independent of the CTR game folder.

All three tools are shipped in the launcher onedir distribution under
_internal/editor_tools. Never search the user's game for old .bat editors.
"""
from __future__ import annotations
from pathlib import Path
import os

EDITORS = {
    "ogg": "CrashForgeOGGToolkit.exe",
    "cseq": "CrashForgeCSEQToolkit.exe",
    "model": "CrashForgeModelImporter.exe",
}

def editor_executable(tool, launcher_dir, *, override="", runtime_dir=None):
    if tool not in EDITORS:
        raise ValueError("Unknown Crash Forge editor: " + str(tool))
    name = EDITORS[tool]
    base = Path(launcher_dir)
    # The release ZIP is extracted with EXE at root and editors in _internal.
    candidates = [
        base / "_internal" / "editor_tools" / name,
        base / "editor_tools" / name,
    ]
    if runtime_dir:
        candidates.append(Path(runtime_dir) / "editor_tools" / name)
    # Developer override comes after the shipped EXE: never replace an
    # installed bundled editor with a stale legacy .bat or external Python.
    if override:
        path = Path(str(override).strip().strip('"'))
        if path.suffix.casefold() == ".exe":
            candidates.append(path)
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.suffix.casefold() == ".exe":
                return str(candidate.resolve())
        except (OSError, ValueError):
            continue
    return None