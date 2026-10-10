"""Safe, independent self-updates for the Windows Crash Forge Launcher.

Launcher releases live in CarisaDemon/Crash-Forge-Launcher, NEVER the game's
Crash-Forge-Racing repository. On frozen Windows builds, updates are downloaded
and verified in the background. Applying waits until the GUI has CLOSED; the
separate bundled updater performs a rollback-capable file replacement.

Source/development launches never modify their own code automatically.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "CarisaDemon/Crash-Forge-Launcher"
RELEASES_URL = "https://github.com/" + REPOSITORY + "/releases"
RELEASES_API = "https://api.github.com/repos/" + REPOSITORY + "/releases?per_page=20"
ZIP_NAME = "Crash-Forge-Launcher-Windows.zip"
UPDATER_EXE = "ForgeLauncherUpdater.exe"
APP_EXE = "CrashForgeLauncher.exe"
MAX_ZIP_BYTES = 400 * 1024 * 1024
MAX_EXTRACTED_BYTES = 950 * 1024 * 1024
MAX_FILES = 16000
SHA = re.compile(r"^[a-f0-9]{64}$", re.I)
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$", re.I)
_ALLOWED_ROOT = frozenset({
    APP_EXE.lower(), UPDATER_EXE.lower(), "launcher_version.txt",
    "launcher_changelog.txt", "forge_online_config.json",
    "assets", "_internal",
})
_PROTECTED = frozenset({
    "launcher_settings.json", "installed_mods.json", "community_catalog.json",
    "checkpoint_launcher.txt", "public_hub", "forge hub uploads",
    ".git", "backups", "user_data", "cache",
})
_FORBIDDEN_SUFFIXES = frozenset({
    ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".wsf", ".hta", ".msi", ".msp",
    ".lnk", ".reg", ".scr", ".com", ".pif",
})
# Explicitly protect community/user assets and screenshots. The updater
# may replace only launcher-owned branding resources; never assets/mods/.
_OFFICIAL_ASSETS = frozenset({
    "assets/fondo.png",
    "assets/icons/cfr_icon.png",
    "assets/icons/cfr_icon.ico",
    "assets/art/kart_sketch_icon.png",
})
_HEADER = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "CrashForgeLauncher/0.3.29",
    "X-GitHub-Api-Version": "2022-11-28",
}


class LauncherUpdateError(ValueError):
    pass


def parse_version(version):
    found = VERSION.fullmatch(str(version or "").strip())
    return tuple(map(int, found.groups())) if found else None


def state_root():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        str(Path.home()), "AppData", "Local")
    return Path(base) / "CrashForgeLauncher" / "updates"


def is_portable_build():
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def read_local_version(app_dir):
    path = Path(app_dir) / "launcher_version.txt"
    try:
        value = path.read_text(encoding="utf-8-sig").strip()
        return value if parse_version(value) else "0.0.0"
    except OSError:
        return "0.0.0"


def _open_json(url, timeout=14):
    if url != RELEASES_API:
        raise LauncherUpdateError("Unexpected release metadata endpoint")
    req = urllib.request.Request(url, headers=_HEADER)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as reply:
            u = urllib.parse.urlsplit(reply.geturl())
            if u.scheme != "https" or u.hostname != "api.github.com":
                raise LauncherUpdateError("GitHub API redirected outside its host")
            if int(reply.headers.get("Content-Length", "0") or "0") > 800000:
                raise LauncherUpdateError("GitHub metadata exceeded the limit")
            raw = reply.read(800001)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        if error.code in (403, 429):
            raise LauncherUpdateError("GitHub update checks are rate limited") from error
        raise LauncherUpdateError(f"GitHub API error HTTP {error.code}") from error
    except (TimeoutError, OSError) as error:
        raise LauncherUpdateError("Unable to check launcher releases: " + str(error)) from error
    if len(raw) > 800000:
        raise LauncherUpdateError("GitHub metadata exceeded the limit")
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise LauncherUpdateError("Invalid GitHub release metadata") from error


def _trusted_asset(asset):
    if not isinstance(asset, dict):
        return None
    name = str(asset.get("name") or "")
    url = str(asset.get("browser_download_url") or "")
    parts = urllib.parse.urlsplit(url)
    if (not name or "/" in name or "\\" in name or
            parts.scheme != "https" or parts.hostname != "github.com" or
            parts.username or parts.password or parts.port not in (None, 443) or
            not parts.path.startswith(f"/{REPOSITORY}/releases/download/")):
        return None
    size = asset.get("size", 0)
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        return None
    digest = str(asset.get("digest") or "")
    digest = digest[7:] if digest.startswith("sha256:") else ""
    if not SHA.fullmatch(digest):
        digest = ""
    return {"name": name, "url": url, "size": size, "sha256": digest.lower()}


def parse_release(raw):
    if not isinstance(raw, dict) or raw.get("draft") or raw.get("prerelease"):
        return None
    tag = str(raw.get("tag_name") or "")
    version = parse_version(tag)
    url = str(raw.get("html_url") or "")
    parts = urllib.parse.urlsplit(url)
    if (version is None or parts.scheme != "https" or
            parts.hostname != "github.com" or
            not parts.path.startswith(f"/{REPOSITORY}/releases/tag/")):
        return None
    assets = raw.get("assets") or []
    if not isinstance(assets, list):
        return None
    items = [x for x in (_trusted_asset(a) for a in assets[:100]) if x]
    package = next((x for x in items if x["name"] == ZIP_NAME
                    and x["size"] <= MAX_ZIP_BYTES), None)
    if not package:
        return None
    sha_file = None
    if not package["sha256"]:
        sha_file = next((x for x in items
                         if x["name"].lower() in (
                             (ZIP_NAME + ".sha256").lower(), "sha256sums.txt")
                         and x["size"] <= 128000), None)
    return {
        "version": ".".join(map(str, version)),
        "tag": tag,
        "url": url,
        "published_at": str(raw.get("published_at") or "")[:35],
        "description": str(raw.get("body") or "")[:900],
        "asset": package,
        "sha_asset": sha_file,
        "verified": bool(package["sha256"] or sha_file),
    }


def fetch_latest():
    releases = _open_json(RELEASES_API)
    if not releases:
        return None
    if not isinstance(releases, list):
        raise LauncherUpdateError("GitHub Releases response is not a list")
    parsed = [parse_release(x) for x in releases[:20]]
    candidates = [x for x in parsed if x and x["verified"]]
    return max(candidates,
               key=lambda x: parse_version(x["version"])) if candidates else None


def newer_release(release, installed):
    if not release:
        return False
    a, b = parse_version(release.get("version")), parse_version(installed)
    return a is not None and b is not None and a > b


def _read_download(url, size_limit, timeout=30):
    source = urllib.parse.urlsplit(url)
    if (source.scheme != "https" or source.hostname != "github.com" or
            not source.path.startswith(f"/{REPOSITORY}/releases/download/")):
        raise LauncherUpdateError("This file does not come from the launcher repository")
    req = urllib.request.Request(url, headers={"User-Agent": _HEADER["User-Agent"]})
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except (TimeoutError, OSError) as exc:
        raise LauncherUpdateError("Could not download launcher release asset") from exc
    final = urllib.parse.urlsplit(response.geturl())
    if final.scheme != "https" or final.hostname not in (
        "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"
    ):
        response.close()
        raise LauncherUpdateError("The release asset redirected outside GitHub")
    if int(response.headers.get("Content-Length", 0) or 0) > size_limit:
        response.close()
        raise LauncherUpdateError("Release asset exceeds size limit")
    return response


def expected_digest(release):
    pkg = release["asset"]
    if SHA.fullmatch(pkg.get("sha256") or ""):
        return pkg["sha256"].lower()
    sidecar = release.get("sha_asset")
    if not sidecar:
        raise LauncherUpdateError("Launcher ZIP has no SHA-256 checksum")
    with _read_download(sidecar["url"], 128000) as response:
        data = response.read(128001)
    if len(data) > 128000:
        raise LauncherUpdateError("Checksum file is too large")
    for line in data.decode("utf-8-sig", "replace").splitlines():
        match = re.fullmatch(r"\s*([a-fA-F0-9]{64})(?:\s+\*?([^\r\n]+))?\s*", line)
        if match:
            filename = (match.group(2) or "").strip()
            is_dedicated = (sidecar["name"].lower() ==
                            (pkg["name"] + ".sha256").lower())
            if filename == pkg["name"] or (is_dedicated and not filename):
                return match.group(1).lower()
    raise LauncherUpdateError("Checksum file does not match the official Launcher ZIP")


def _safe_member(name, is_dir):
    if (not name or name.startswith("/") or "\\" in name or "\0" in name
            or len(name) > 280 or re.match(r"^[A-Za-z]:", name)):
        raise LauncherUpdateError("Unsafe launcher ZIP path")
    parts = name.rstrip("/").split("/")
    if not parts or any(x in ("", ".", "..") for x in parts):
        raise LauncherUpdateError("Unsafe archive directory")
    first = parts[0].lower()
    if first in _PROTECTED or first not in _ALLOWED_ROOT:
        raise LauncherUpdateError("Launcher archive includes non-distributable content: " + first)
    if (first not in ("assets", "_internal") and len(parts) != 1):
        raise LauncherUpdateError("Unexpected release folder layout")
    if first == "assets":
        canonical = "/".join(parts).lower()
        if is_dir:
            if not any(asset.startswith(canonical + "/") for asset in _OFFICIAL_ASSETS):
                raise LauncherUpdateError("Release contains an unknown assets directory")
        elif canonical not in _OFFICIAL_ASSETS:
            raise LauncherUpdateError("Release would overwrite personal game/mod assets: " + name)
    if not is_dir and Path(name).suffix.lower() in _FORBIDDEN_SUFFIXES:
        raise LauncherUpdateError("Launcher ZIP includes a forbidden script/file")
    if not is_dir and name.lower() == "forge_online_config.json":
        # The public feed config is deployable but local user changes remain
        # protected by the apply helper; it never overwrites it.
        pass
    return "/".join(parts)


def inspect_package(zf, expected_version):
    if not isinstance(zf, zipfile.ZipFile):
        raise LauncherUpdateError("Invalid ZIP object")
    entries = zf.infolist()
    if not entries or len(entries) > MAX_FILES:
        raise LauncherUpdateError("Launcher ZIP is empty or has too many files")
    files, total, seen = [], 0, set()
    for entry in entries:
        name = _safe_member(entry.filename, entry.is_dir())
        mode = entry.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise LauncherUpdateError("ZIP symlinks are not supported")
        if entry.is_dir():
            continue
        case = name.lower()
        if case in seen:
            raise LauncherUpdateError("Duplicate launcher archive filename")
        seen.add(case)
        total += entry.file_size
        if total > MAX_EXTRACTED_BYTES:
            raise LauncherUpdateError("Launcher ZIP expands beyond 950 MiB")
        files.append((entry, name))
    required = {APP_EXE.lower(), UPDATER_EXE.lower(), "launcher_version.txt"}
    if not required.issubset(seen):
        raise LauncherUpdateError("Release missing launcher EXE, updater or version marker")
    embedded_version = zf.read("launcher_version.txt").decode("utf-8-sig").strip()
    if embedded_version != expected_version:
        raise LauncherUpdateError("Release tag and launcher_version.txt disagree")
    return files


def _inside(parent, candidate):
    try:
        root = os.path.normcase(os.path.realpath(parent))
        child = os.path.normcase(os.path.realpath(candidate))
        return os.path.commonpath((root, child)) == root
    except ValueError:
        return False



def _installed_receipt_file(root=None):
    root = Path(root) if root is not None else state_root()
    return root / "installed_release.json"


def read_installed_release(app_dir, root=None):
    """Read the trusted updater's local receipt for this exact EXE installation."""
    path = _installed_receipt_file(root)
    try:
        if not path.is_file() or path.stat().st_size > 8192:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema") != 1 or
                data.get("repository") != REPOSITORY or
                data.get("app_dir") != str(Path(app_dir).resolve()) or
                data.get("version") != read_local_version(app_dir) or
                not SHA.fullmatch(str(data.get("zip_sha256") or ""))):
            return None
        return data
    except (OSError, ValueError, TypeError):
        return None


def update_required(release, installed, app_dir=None, root=None):
    """Detect new versions OR a changed verified package on the same version.

    A fresh/manual installation has no signed-package receipt and is offered
    one verified refresh. The helper writes that receipt on successful apply,
    so identical ZIPs never trigger an update loop.
    """
    if not release or not release.get("verified"):
        return False
    latest, local = parse_version(release.get("version")), parse_version(installed)
    if latest is None or local is None or latest < local:
        return False
    if latest > local:
        return True
    if app_dir is None:
        return False
    package = release.get("asset") or {}
    digest = str(package.get("sha256") or "").lower()
    if not SHA.fullmatch(digest):
        return False
    receipt = read_installed_release(app_dir, root=root)
    return receipt is None or receipt["zip_sha256"].lower() != digest


def pending_update_required(pending, app_dir, root=None):
    """A fully staged, hashed ZIP can replace an older BUILD of the same vX.Y.Z."""
    if not pending or not isinstance(pending, dict):
        return False
    current = read_local_version(app_dir)
    latest, installed = parse_version(pending.get("version")), parse_version(current)
    if latest is None or installed is None or latest < installed:
        return False
    if latest > installed:
        return True
    digest = str(pending.get("zip_sha256") or "").lower()
    if not SHA.fullmatch(digest):
        return False
    receipt = read_installed_release(app_dir, root=root)
    return receipt is None or receipt["zip_sha256"].lower() != digest


def save_installed_release(version, digest, app_dir, root=None):
    """Persist the verified ZIP hash only after the helper completes install."""
    if not parse_version(version) or not SHA.fullmatch(str(digest or "")):
        raise LauncherUpdateError("Cannot save unverified launcher release receipt")
    root = Path(root) if root is not None else state_root()
    root.mkdir(parents=True, exist_ok=True)
    path = _installed_receipt_file(root)
    record = {
        "schema": 1, "repository": REPOSITORY, "version": version,
        "zip_sha256": digest.lower(), "app_dir": str(Path(app_dir).resolve()),
        "installed_at": int(time.time()),
    }
    tmp = root / "installed_release.json.tmp"
    try:
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return record


def _status_file(root):
    return root / "pending.json"


def pending_update(root=None):
    root = Path(root) if root is not None else state_root()
    try:
        data = json.loads(_status_file(root).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not parse_version(data.get("version")):
            return None
        if data.get("repository") != REPOSITORY:
            return None
        stage = root / "stage" / data["version"]
        payload = stage / "payload"
        manifest = stage / "manifest.json"
        if not payload.is_dir() or not manifest.is_file():
            return None
        if manifest.stat().st_size > 409600:
            return None
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return None
        digest = str(metadata.get("zip_sha256") or "").lower()
        if (metadata.get("schema") != 1 or
                metadata.get("repository") != REPOSITORY or
                metadata.get("version") != data["version"] or
                not SHA.fullmatch(digest)):
            return None
        return {"version": data["version"], "payload": str(payload),
                "manifest": str(manifest), "zip_sha256": digest,
                "release_url": data.get("release_url", "")}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def stage_release(release, current_version, progress=None, root=None,
                  app_dir=None):
    """Download, hash and safely extract update to LOCALAPPDATA (no installation writes)."""
    if not update_required(release, current_version, app_dir=app_dir, root=root):
        return None
    if not release.get("verified") or not release.get("asset"):
        raise LauncherUpdateError("Launcher release has no verified ZIP")
    expected = expected_digest(release)
    root = Path(root) if root is not None else state_root()
    stage = root / "stage" / release["version"]
    # Never let remote release names decide any other directory names.
    if not parse_version(release["version"]):
        raise LauncherUpdateError("Invalid launcher update version")
    root.mkdir(parents=True, exist_ok=True)
    existing = pending_update(root)
    if (existing and existing["version"] == release["version"]
            and existing.get("zip_sha256") == expected):
        return existing
    temp = Path(tempfile.mkdtemp(prefix="dl-", dir=str(root)))
    archive = temp / "launcher.zip"
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with _read_download(release["asset"]["url"], MAX_ZIP_BYTES) as response, \
             archive.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0) or 0)
            while True:
                block = response.read(256 * 1024)
                if not block:
                    break
                downloaded += len(block)
                if downloaded > MAX_ZIP_BYTES:
                    raise LauncherUpdateError("Launcher ZIP exceeds 400 MiB")
                digest.update(block)
                output.write(block)
                if progress:
                    progress("download", downloaded, total or release["asset"]["size"])
        if digest.hexdigest() != expected:
            raise LauncherUpdateError("Launcher update checksum mismatch; no files changed")
        payload = temp / "payload"
        payload.mkdir()
        hashes = []
        with zipfile.ZipFile(archive, "r") as zf:
            members = inspect_package(zf, release["version"])
            for index, (info, name) in enumerate(members):
                target = payload.joinpath(*name.split("/"))
                if not _inside(payload, target):
                    raise LauncherUpdateError("Launcher ZIP path escapes staging directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                check = hashlib.sha256()
                with zf.open(info) as source, target.open("wb") as output:
                    while True:
                        piece = source.read(256 * 1024)
                        if not piece:
                            break
                        check.update(piece)
                        output.write(piece)
                hashes.append({"path": name, "bytes": info.file_size,
                               "sha256": check.hexdigest()})
                if progress and (index % 20 == 0 or index == len(members)-1):
                    progress("extract", index + 1, len(members))
        (temp / "manifest.json").write_text(json.dumps({
            "schema": 1, "repository": REPOSITORY,
            "version": release["version"], "zip_sha256": expected,
            "files": hashes
        }, indent=2), encoding="utf-8")
        # Atomic staging: only complete, verified releases become pending.
        if stage.exists():
            shutil.rmtree(stage)
        stage.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp, stage)
        temp = None
        new_pending = {
            "repository": REPOSITORY, "version": release["version"],
            "release_url": release["url"],
            "staged_at": int(time.time()),
        }
        pending_tmp = root / "pending.json.tmp"
        pending_tmp.write_text(json.dumps(new_pending, indent=2), encoding="utf-8")
        os.replace(pending_tmp, _status_file(root))
        return pending_update(root)
    except (zipfile.BadZipFile, OSError) as exc:
        raise LauncherUpdateError("Update download or ZIP extraction failed: " + str(exc)) from exc
    finally:
        if temp and temp.is_dir():
            shutil.rmtree(temp, ignore_errors=True)


def portable_target_for_source(source_dir, root=None):
    """Choose a separate EXE installation; never overwrite the .bat sources.

    Existing neighboring public portable installs take priority, otherwise a
    private LOCALAPPDATA app folder becomes the safe first-time destination.
    """
    source = Path(source_dir).resolve()
    neighboring = source.parent / "Crash Forge Launcher App"
    if ((neighboring / APP_EXE).is_file()
            and (neighboring / UPDATER_EXE).is_file()):
        return neighboring.resolve()
    root = Path(root) if root is not None else state_root()
    return (root.parent / "app").resolve()


def launch_update_after_exit(app_dir, current_pid, root=None,
                             source_migration=False, source_dir=None):

    """Apply the verified ZIP on exit, then restart the updated Windows EXE.

    The one-time .bat migration never touches its Python/source directory.
    It runs the SHA-256 verified NEW updater from staging in LOCALAPPDATA,
    allowing v0.3.28 source users to gain restart support during migration.
    """
    if not is_portable_build() and not source_migration:
        return False
    root = Path(root) if root is not None else state_root()
    pending = pending_update(root)
    if not pending_update_required(pending, app_dir, root=root):
        return False
    app_dir = Path(app_dir).resolve()
    staging = Path(pending["payload"]).resolve()
    trusted_updater = staging / UPDATER_EXE
    if not trusted_updater.is_file():
        raise LauncherUpdateError("Verified release has no independent updater EXE.")
    # Existing portable builds use their installed trusted helper; the new
    # staged helper is needed for .bat -> .exe migration and self-restart.
    installed_updater = app_dir / UPDATER_EXE
    bootstrapping = not (app_dir / APP_EXE).is_file()
    current_same_version = (
        parse_version(read_local_version(app_dir)) ==
        parse_version(pending["version"]))
    if source_migration or current_same_version:
        # The older installed helper may reject same-version updates.
        # Verify the new helper's manifest hash before executing it.
        try:
            stage_meta = json.loads(Path(pending["manifest"]).read_text(encoding="utf-8"))
            updater_meta = next(
                row for row in stage_meta["files"]
                if row.get("path", "").lower() == UPDATER_EXE.lower())
            actual_hash = hashlib.sha256(trusted_updater.read_bytes()).hexdigest()
            if updater_meta["sha256"].lower() != actual_hash or (
                    updater_meta["bytes"] != trusted_updater.stat().st_size):
                raise LauncherUpdateError("Staged helper failed checksum verification")
        except (OSError, ValueError, TypeError, KeyError, StopIteration) as error:
            raise LauncherUpdateError("Staged updater EXE is not verified") from error
        updater = trusted_updater
        if source_migration:
            if source_dir is None or not (Path(source_dir) / "launcher.py").is_file():
                raise LauncherUpdateError("Missing developer source directory for EXE migration.")
            source = Path(source_dir).resolve()
            if app_dir == source or _inside(source, app_dir):
                raise LauncherUpdateError("Cannot install EXE into the developer source directory.")
            if bootstrapping and app_dir != (root.parent / "app").resolve():
                raise LauncherUpdateError("Fresh EXE install must use LOCALAPPDATA/CrashForgeLauncher/app.")
    else:
        updater = installed_updater
        if not installed_updater.is_file() or bootstrapping:
            raise LauncherUpdateError("An installed portable updater is required.")
    root.mkdir(parents=True, exist_ok=True)
    copied = root / "apply-launcher-update.exe"
    # Different releases must not corrupt an updater already in flight.
    # The PID-specific name also lets Windows release the copied file later.
    copied = root / ("apply-launcher-update-" + str(int(current_pid)) + ".exe")
    shutil.copy2(updater, copied)
    command = [
        str(copied), "--apply", "--pid", str(int(current_pid)),
        "--app-dir", str(app_dir), "--stage", pending["payload"],
        "--manifest", pending["manifest"], "--state-dir", str(root),
    ]
    if source_migration:
        command.extend(["--source-dir", str(Path(source_dir).resolve())])
        if bootstrapping:
            command.append("--allow-fresh")
    flags = (subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    subprocess.Popen(
        command, close_fds=True, creationflags=flags,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True
