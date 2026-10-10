"""Optional, explicitly requested install of the Windows Model Importer.

Never download at launcher startup. Downloads must be an official release asset
from the same verified Github launcher release, with SHA-256 verification.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import forge_launcher_updates as updates

TOOL_EXE = "CrashForgeModelImporter.exe"
MAX_TOOL_BYTES = 150 * 1024 * 1024
METADATA_NAME = "model_importer.json"


def tools_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "CrashForgeLauncher" / "tools"


def installed_version(root=None):
    root = Path(root) if root is not None else tools_dir()
    exe = root / TOOL_EXE
    manifest = root / METADATA_NAME
    if not exe.is_file() or exe.is_symlink() or not manifest.is_file():
        return None
    try:
        meta = json.loads(manifest.read_text(encoding="utf-8"))
        sha = meta.get("sha256")
        version = meta.get("version")
        if (meta.get("repository") != updates.REPOSITORY
                or not updates.parse_version(version)
                or not isinstance(sha, str) or not updates.SHA.fullmatch(sha)
                or not 2048 <= exe.stat().st_size <= MAX_TOOL_BYTES):
            return None
        digest = hashlib.sha256()
        with exe.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest().lower() != sha.lower():
            return None
        return str(version)
    except (OSError, TypeError, ValueError, KeyError):
        return None


def installed_path(root=None):
    root = Path(root) if root is not None else tools_dir()
    return root / TOOL_EXE if installed_version(root) else None


def find_official_tool(release_data=None):
    """Find latest verified public release that publishes the optional tool."""
    if release_data is None:
        release_data = updates._open_json(updates.RELEASES_API)
    if not isinstance(release_data, list):
        raise updates.LauncherUpdateError("Official GitHub Releases unavailable")
    valid = []
    for entry in release_data[:20]:
        parsed = updates.parse_release(entry)
        if parsed is None or not parsed.get("verified"):
            continue
        if not isinstance(entry.get("assets"), list):
            continue
        items = [item for item in
                 (updates._trusted_asset(asset) for asset in entry["assets"][:100])
                 if item is not None]
        package = next((item for item in items
                        if item["name"] == TOOL_EXE
                        and 2048 <= item["size"] <= MAX_TOOL_BYTES
                        and f"/releases/download/{parsed['tag']}/" in item["url"]), None)
        if package is None:
            continue
        sidecar = next((item for item in items
                        if item["name"] == TOOL_EXE+".sha256"
                        and item["size"] <= 128000
                        and f"/releases/download/{parsed['tag']}/" in item["url"]), None)
        if not package["sha256"] and not sidecar:
            continue
        valid.append({"version": parsed["version"], "tag": parsed["tag"],
                      "asset": package, "sha_asset": sidecar,
                      "repository": updates.REPOSITORY})
    if not valid:
        raise updates.LauncherUpdateError("No verified Model Importer download is published yet")
    return max(valid, key=lambda x: updates.parse_version(x["version"]))


def _asset_digest(release):
    asset = release["asset"]
    digest = asset.get("sha256", "")
    if isinstance(digest, str) and updates.SHA.fullmatch(digest):
        return digest.lower()
    sidecar = release.get("sha_asset")
    if not sidecar:
        raise updates.LauncherUpdateError("Model Importer SHA-256 is missing")
    with updates._read_download(sidecar["url"], 128000) as source:
        raw = source.read(128001)
    if len(raw) > 128000:
        raise updates.LauncherUpdateError("Model Importer checksum exceeds size limit")
    for line in raw.decode("ascii", "replace").splitlines():
        match = re.fullmatch(r"\s*([a-fA-F0-9]{64})\s+\*?([^\r\n]+)\s*", line)
        if match and match.group(2).strip() == TOOL_EXE:
            return match.group(1).lower()
    raise updates.LauncherUpdateError("Official Model Importer checksum is invalid")


def install_tool(release, root=None, progress=None):
    """Verify an official EXE before atomic install; keep a backup of prior EXE."""
    root = Path(root) if root is not None else tools_dir()
    if root.is_symlink():
        raise updates.LauncherUpdateError("Unsafe tool directory")
    version = release.get("version")
    asset = release.get("asset") or {}
    if (release.get("repository") != updates.REPOSITORY
            or not updates.parse_version(version)
            or asset.get("name") != TOOL_EXE
            or not isinstance(asset.get("size"), int)
            or not 2048 <= asset["size"] <= MAX_TOOL_BYTES):
        raise updates.LauncherUpdateError("Invalid official Model Importer metadata")
    expected = _asset_digest(release)
    folder = root.parent
    if root.exists() and not root.is_dir():
        raise updates.LauncherUpdateError("Tool destination is not a directory")
    folder.mkdir(parents=True, exist_ok=True)
    # Keep temporary bytes outside the visible install path until verified.
    with tempfile.TemporaryDirectory(prefix="forge_optional_tool_", dir=folder) as temp:
        newexe = Path(temp) / TOOL_EXE
        digest = hashlib.sha256()
        total = 0
        with updates._read_download(asset["url"], MAX_TOOL_BYTES, timeout=55) as response:
            with newexe.open("wb") as target:
                while True:
                    block = response.read(1024 * 512)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_TOOL_BYTES:
                        raise updates.LauncherUpdateError("Model Importer download is too large")
                    target.write(block)
                    digest.update(block)
                    if progress is not None:
                        progress(total, asset["size"])
        if total != asset["size"] or digest.hexdigest() != expected:
            raise updates.LauncherUpdateError("Model Importer SHA-256/length mismatch")
        # Refuse to execute a non-PE file even if upstream metadata was malformed.
        with newexe.open("rb") as binary:
            if binary.read(2) != b"MZ":
                raise updates.LauncherUpdateError("Model Importer is not a Windows EXE")
        root.mkdir(parents=True, exist_ok=True)
        destination = root / TOOL_EXE
        if destination.is_symlink():
            raise updates.LauncherUpdateError("Unsafe pre-existing tool path")
        old_manifest = root / METADATA_NAME
        oldexe = root / (TOOL_EXE+".previous")
        old_metadata = root / (METADATA_NAME+".previous")
        # No side effects on existing tools until all bytes are authenticated.
        if oldexe.exists():
            oldexe.unlink()
        if old_metadata.exists():
            old_metadata.unlink()
        had_old = destination.exists()
        had_metadata = old_manifest.is_file()
        if had_old:
            os.replace(destination, oldexe)
        if had_metadata:
            os.replace(old_manifest, old_metadata)
        try:
            os.replace(newexe, destination)
            manifest_data = {
                "version": str(version),
                "repository": updates.REPOSITORY,
                "sha256": expected,
            }
            manifest_tmp = Path(temp)/METADATA_NAME
            manifest_tmp.write_text(json.dumps(manifest_data, indent=2)+"\n",
                                    encoding="utf-8")
            os.replace(manifest_tmp, old_manifest)
        except Exception:
            destination.unlink(missing_ok=True)
            if had_old and oldexe.is_file():
                os.replace(oldexe, destination)
            if had_metadata and old_metadata.is_file():
                os.replace(old_metadata, old_manifest)
            raise
        # Retained only as a rollback fallback, not part of the launcher update.
        return destination
