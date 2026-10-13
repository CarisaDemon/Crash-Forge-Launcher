"""Local, read-only support report. No network, game launch or user file writes."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import json
import shutil

CATEGORY_NAMES = ("racers", "karts", "wheels", "tracks", "music", "vanilla_racer_masks")

def _folders(folder):
    """Return a bounded count. Missing or inaccessible folders are reported safely."""
    try:
        if not folder.is_dir():
            return 0
        total = 0
        for entry in folder.iterdir():
            if entry.is_dir():
                total += 1
            if total >= 10000:
                break
        return total
    except OSError:
        return None

def _safe_member(value):
    if not isinstance(value, str) or not value or len(value) > 260:
        return False
    if value.startswith(("/", "\\")) or "\\" in value or ":" in value:
        return False
    return all(piece not in ("", ".", "..") for piece in value.split("/"))

def inspect(game_dir):
    """Rows: (check name, OK/CHECK, explanation). Never alters the installation."""
    root = Path(game_dir) if isinstance(game_dir, str) and game_dir.strip() else None
    results = []
    def add(name, ok, description):
        results.append((name, "OK" if ok else "CHECK", str(description)))

    if root is None or not root.is_dir():
        add("Game location", False, "Choose an existing game folder in Launcher Settings.")
        return results

    add("Game location", True, str(root))
    exe = root / "ctr-native.exe"
    add("Game executable", exe.is_file(), "ctr-native.exe present" if exe.is_file()
        else "ctr-native.exe not found")

    disc = root / "assets" / "ctr-u.bin"
    try:
        disc_ok = disc.is_file() and disc.stat().st_size >= 2352
    except OSError:
        disc_ok = False
    add("Original game disc", disc_ok,
        "Present (not hash-verified)" if disc_ok else "assets/ctr-u.bin missing or incomplete")

    manifest = root / "forge_release_state.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Manifest must be a JSON object")
            names = data.get("package_files")
            if not isinstance(names, list) or not (1 <= len(names) <= 20000):
                raise ValueError("Invalid or absent package file list")
            if not all(_safe_member(p) for p in names):
                raise ValueError("Unsafe package file path")
            missing = [p for p in names if not (root / PurePosixPath(p)).is_file()]
            version = str(data.get("version") or "unknown")[:40]
            add("Official package files", not missing,
                f"v{version}: all {len(names)} files present (not hash-verified)"
                if not missing else f"v{version}: {len(missing)} file(s) missing: "
                + ", ".join(missing[:3]))
        except (OSError, ValueError, TypeError) as exc:
            add("Official package files", False, f"Could not verify file list: {exc}")
    else:
        add("Official package files", False,
            "No release manifest found; may be an older or development build.")

    standard_mods = _folders(root / "mods")
    add("Web mod packages", standard_mods is not None,
        f"{standard_mods} package folder(s)" if standard_mods is not None
        else "Mod folder inaccessible")
    legacy = root / "assets" / "mods"
    counts = [_folders(legacy / category) for category in CATEGORY_NAMES]
    add("Legacy mods", all(x is not None for x in counts),
        f"{sum(x for x in counts if x is not None)} legacy mod folder(s)")
    try:
        free_gb = shutil.disk_usage(root).free / (1024 ** 3)
        add("Free disk space", free_gb >= 1.0, f"{free_gb:.1f} GB available")
    except OSError:
        add("Free disk space", False, "Could not read available disk space")

    try:
        latest = sorted((p for p in root.glob("*.log") if p.is_file()),
                        key=lambda p: p.stat().st_mtime, reverse=True)[:3]
        add("Game log", bool(latest),
            ", ".join(p.name for p in latest) if latest else "No log written yet")
    except OSError:
        add("Game log", False, "Log folder could not be inspected")
    return results

def format_report(rows):
    return "CRASH FORGE: RACING - GAME HEALTH CHECK\n" + "\n".join(
        f"[{status}] {name}: {detail}" for name, status, detail in rows
    ) + "\n"
