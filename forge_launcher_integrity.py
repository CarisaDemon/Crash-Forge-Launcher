"""Offline, read-only integrity checks for official Crash Forge Launcher files.

Generated local SHA-256 manifest is installed inside _internal. This module
never downloads or writes anything; the existing verified updater handles repair.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

MANIFEST_PATH = "_internal/forge_integrity.json"
SCHEMA = 1
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ENTRIES = 16000
MAX_UNPACKED = 950 * 1024 * 1024
SHA = re.compile(r"^[a-f0-9]{64}$", re.I)
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
CRITICAL = (
    "CrashForgeLauncher.exe", "ForgeLauncherUpdater.exe", "launcher_version.txt",
    "_internal/_tcl_data/init.tcl", "_internal/_tk_data/tk.tcl",
    "_internal/tcl86t.dll", "_internal/tk86t.dll", "_internal/_tkinter.pyd",
    "_internal/editor_tools/CrashForgeModPackager.exe",
)
USER_FILES = {"forge_online_config.json", "launcher_settings.json",
              "installed_mods.json", "community_catalog.json"}


class IntegrityError(ValueError):
    pass


def _valid_path(name):
    if not isinstance(name, str) or not name or len(name) > 280:
        return False
    if name.startswith("/") or "\\" in name or "\0" in name:
        return False
    parts = name.split("/")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        return False
    top = parts[0].lower()
    if top == "_internal":
        return len(parts) > 1 and name.lower() != MANIFEST_PATH.lower()
    if top == "assets":
        return name.lower() in {
            "assets/fondo.png", "assets/icons/cfr_icon.png",
            "assets/icons/cfr_icon.ico", "assets/art/kart_sketch_icon.png",
        }
    return len(parts) == 1 and top in {
        "crashforgelauncher.exe", "forgelauncherupdater.exe",
        "launcher_version.txt", "launcher_changelog.txt",
    }


def _sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


def _parse(data):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or \
       not VERSION.fullmatch(str(data.get("version", ""))):
        raise IntegrityError("Invalid integrity manifest version")
    records = data.get("files")
    if not isinstance(records, list) or not 8 <= len(records) <= MAX_ENTRIES:
        raise IntegrityError("Invalid integrity manifest file count")
    names = set()
    total = 0
    for item in records:
        if not isinstance(item, dict):
            raise IntegrityError("Invalid file record")
        path, size, digest = item.get("path"), item.get("bytes"), item.get("sha256")
        if not _valid_path(path) or path.lower() in names:
            raise IntegrityError("Invalid or duplicate integrity path")
        if (not isinstance(size, int) or isinstance(size, bool) or size < 0
                or not isinstance(digest, str) or not SHA.fullmatch(digest)):
            raise IntegrityError("Invalid integrity file hash or size")
        names.add(path.lower())
        total += size
        if total > MAX_UNPACKED:
            raise IntegrityError("Integrity file size exceeds allowed limit")
    if not set(x.lower() for x in CRITICAL).issubset(names):
        raise IntegrityError("Integrity manifest lacks critical runtime files")
    return records


def load_manifest(app_dir):
    root = Path(app_dir)
    path = root / MANIFEST_PATH
    if path.is_symlink() or not path.is_file():
        raise IntegrityError("Launcher integrity manifest is unavailable")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise IntegrityError("Launcher integrity manifest is too large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as err:
        raise IntegrityError("Launcher integrity manifest cannot be read") from err
    _parse(data)
    return data


def build_manifest(app_dir, version):
    """Run once after packaging, before ZIP creation; never on end-user PCs."""
    if not VERSION.fullmatch(str(version)):
        raise IntegrityError("Invalid release version")
    root = Path(app_dir)
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise IntegrityError("Symlink in Launcher bundle")
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name.lower() in USER_FILES or name.lower() == MANIFEST_PATH.lower():
            continue
        if not _valid_path(name):
            raise IntegrityError("Unexpected launcher file: " + name)
        records.append({"path": name, "bytes": path.stat().st_size,
                        "sha256": _sha256(path)})
    data = {"schema": SCHEMA, "version": version, "files": records}
    _parse(data)
    target = root / MANIFEST_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=True, separators=(",",":")),
                      encoding="utf-8")
    return data


def audit(app_dir, max_problems=12):
    """Scan launcher-owned files without modifying, removing or downloading."""
    root = Path(app_dir)
    if not (root / MANIFEST_PATH).is_file():
        return {"status": "unavailable", "checked": 0, "problems": [],
                "message": "File verification data unavailable. Reinstall the complete official ZIP."}
    try:
        manifest = load_manifest(root)
    except (IntegrityError, OSError) as err:
        return {"status": "damaged", "checked": 0, "problems": [str(err)],
                "message": str(err)}
    problems = []
    checked = 0
    expected = len(manifest["files"])
    marker = root / "launcher_version.txt"
    if (not marker.is_file() or marker.is_symlink() or
            marker.read_text(encoding="utf-8-sig", errors="replace").strip()
            != manifest["version"]):
        problems.append("launcher_version.txt: wrong release version")
    for item in manifest["files"]:
        name = item["path"]
        path = root.joinpath(*name.split("/"))
        try:
            if path.is_symlink() or not path.is_file():
                reason = "missing"
            elif path.stat().st_size != item["bytes"]:
                reason = "wrong size"
            elif _sha256(path).lower() != item["sha256"].lower():
                reason = "SHA-256 mismatch"
            else:
                checked += 1
                continue
        except OSError:
            reason = "unreadable"
        if len(problems) < max_problems:
            problems.append(name + ": " + reason)
    status = "ok" if not problems else "damaged"
    return {"status": status, "checked": checked, "expected": expected,
            "problems": problems, "version": manifest["version"],
            "message": ("Verified all launcher files." if status == "ok"
                        else "Launcher files missing or modified.")}


def audit_release_zip(archive):
    """Ensure published ZIP matches every manifest record, not just metadata."""
    import zipfile
    with zipfile.ZipFile(archive) as zf:
        try:
            data = json.loads(zf.read(MANIFEST_PATH))
        except (KeyError, ValueError, UnicodeError) as err:
            raise IntegrityError("Release ZIP lacks a valid file manifest") from err
        records = _parse(data)
        names = {item.filename.lower(): item for item in zf.infolist()
                 if not item.is_dir()}
        if MANIFEST_PATH.lower() not in names:
            raise IntegrityError("Missing integrity manifest in ZIP")
        for item in records:
            name = item["path"]
            entry = names.get(name.lower())
            if not entry or entry.file_size != item["bytes"]:
                raise IntegrityError("ZIP release missing or changed: " + name)
            digest = hashlib.sha256()
            with zf.open(entry) as reader:
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != item["sha256"]:
                raise IntegrityError("ZIP integrity check failed: " + name)
        return data["version"], len(records)
