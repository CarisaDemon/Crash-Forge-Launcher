"""Read-only GitHub Releases discovery + opt-in, SHA-256 verified Windows game updates.

Never downloads automatically. The GUI schedules metadata checks, and only
explicit user confirmation can run install_game_release(). A release ZIP
must contain ctr-native.exe at archive root, exclude private mods/saves,
and have a SHA256SUMS.txt, <zip>.sha256, or GitHub asset SHA-256 digest.
Only the official pinned repository is accepted.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

REPOSITORY = "CarisaDemon/Crash-Forge-Racing"
RELEASES_URL = "https://github.com/" + REPOSITORY + "/releases"
LATEST_API_URL = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest"
RELEASE_LIST_API_URL = "https://api.github.com/repos/" + REPOSITORY + "/releases?per_page=30"
CHECK_CHOICES = (
    "On launch",
    "Every 6 hours",
    "Every 12 hours",
    "Daily",
    "Weekly",
    "Manual only",
)
CHECK_SECONDS = {
    "On launch": 0,
    "Every 6 hours": 6 * 3600,
    "Every 12 hours": 12 * 3600,
    "Daily": 24 * 3600,
    "Weekly": 7 * 24 * 3600,
    "Manual only": None,
}
MAX_METADATA = 1024 * 1024
MAX_CHECKSUM = 128 * 1024
MAX_DOWNLOAD = 2 * 1024 * 1024 * 1024
MAX_UNPACKED = 8 * 1024 * 1024 * 1024
MAX_FILES = 20000
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-._+].*)?$", re.I)
GAME_PACKAGE = re.compile(
    r"^(?:crash[-_ ]?forge[-_ ]?racing|cfr)"
    r"[-_ .a-z0-9]*?(?:windows|win32|win64|win-x86|win-x64)"
    r"[-_ .a-z0-9]*\.zip$", re.I,
)
_ALLOWED_GAME_EXTENSIONS = {
    ".exe", ".dll", ".pak", ".bin", ".dat", ".wad", ".ogg", ".wav", ".cseq",
    ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".dds", ".webp", ".gif",
    ".obj", ".mtl", ".gltf", ".glb", ".ttf", ".otf", ".json", ".txt",
    ".cfg", ".ini", ".xml", ".glsl", ".vert", ".frag", ".shd",
}
_BLOCKED_PATH_COMPONENTS = {
    "mods", "saves", "save", "savedata", "profiles", "ghosts", "userdata",
    ".git", ".forge_game_backups", ".forge_mod_backups",
}
_HEADER = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "CrashForgeLauncher/0.3.27",
    "X-GitHub-Api-Version": "2022-11-28",
}


class ReleaseError(ValueError):
    pass


def check_due(frequency, last_check, now=None, startup=False):
    if frequency not in CHECK_SECONDS:
        frequency = "Daily"
    if frequency == "Manual only":
        return False
    if frequency == "On launch":
        return bool(startup)
    interval = CHECK_SECONDS[frequency]
    current = time.time() if now is None else float(now)
    try:
        last = float(last_check)
    except (TypeError, ValueError, OverflowError):
        last = 0
    return not last or current - last >= interval or last > current + 120


def parse_version(tag):
    found = VERSION.fullmatch(str(tag or "").strip())
    return tuple(map(int, found.groups())) if found else None


def compare_versions(local, online):
    """-1: remote newer; 0: same; 1: local newer; None: unknown."""
    a, b = parse_version(local), parse_version(online)
    if a is None or b is None:
        return None
    return -1 if a < b else 1 if a > b else 0


def _read_json(url, max_bytes=MAX_METADATA, timeout=12):
    req = urllib.request.Request(url, headers=_HEADER)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != "api.github.com":
                raise ReleaseError("GitHub API redirected outside its trusted host.")
            if int(response.headers.get("Content-Length", 0) or 0) > max_bytes:
                raise ReleaseError("GitHub response exceeded size limit.")
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code in (403, 429):
            raise ReleaseError("GitHub rate limit reached. Try again later.") from exc
        raise ReleaseError("GitHub returned HTTP " + str(exc.code)) from exc
    except (OSError, TimeoutError) as exc:
        raise ReleaseError("Cannot connect to GitHub Releases: " + str(exc)) from exc
    if len(raw) > max_bytes:
        raise ReleaseError("GitHub response exceeded size limit.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ReleaseError("Invalid JSON from GitHub Releases.") from exc
    return data


def _trusted_asset(asset):
    if not isinstance(asset, dict):
        return None
    name = str(asset.get("name") or "").strip()
    url = str(asset.get("browser_download_url") or "")
    parsed = urllib.parse.urlsplit(url)
    prefix = "/" + REPOSITORY + "/releases/download/"
    if (parsed.scheme != "https" or parsed.hostname != "github.com"
        or parsed.username or parsed.password or parsed.port not in (None, 443)
        or not parsed.path.startswith(prefix) or not name or "/" in name
        or "\\" in name):
        return None
    size = asset.get("size", 0)
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return None
    digest = str(asset.get("digest") or "")
    checksum = digest[7:].lower() if digest.startswith("sha256:") else ""
    if not SHA256.fullmatch(checksum):
        checksum = ""
    return {"name": name, "url": url, "size": size, "sha256": checksum}


def parse_release(data, *, allow_prerelease=False):
    # Experimental game releases are public when marked prerelease, but must
    # still have the same verified Windows package and user-confirmed install.
    if (not isinstance(data, dict) or data.get("draft") or
            (data.get("prerelease") and not allow_prerelease)):
        return None
    tag = str(data.get("tag_name") or "").strip()
    url = str(data.get("html_url") or "")
    parsed = urllib.parse.urlsplit(url)
    if (not tag or parsed.scheme != "https" or parsed.hostname != "github.com"
        or not parsed.path.startswith("/" + REPOSITORY + "/releases/tag/")
        or not parse_version(tag)):
        raise ReleaseError("Release tag or source URL is not an official game version.")
    raw_assets = data.get("assets") or []
    assets = [_trusted_asset(x) for x in raw_assets[:100]] if isinstance(raw_assets, list) else []
    assets = [x for x in assets if x]
    windows = [
        a for a in assets if GAME_PACKAGE.fullmatch(a["name"])
        and 0 < a["size"] <= MAX_DOWNLOAD
    ]
    windows.sort(key=lambda a: (a["name"].lower().startswith("cfr"), a["name"].lower()))
    package = windows[0] if windows else None
    checksum_file = None
    if package and not package["sha256"]:
        checks = [package["name"] + ".sha256", "SHA256SUMS.txt", "SHA256SUMS"]
        checksum_file = next((a for n in checks for a in assets
                              if a["name"].lower() == n.lower()
                              and 0 < a["size"] <= MAX_CHECKSUM), None)
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "name": str(data.get("name") or tag)[:130],
        "url": url,
        "published_at": str(data.get("published_at") or "")[:35],
        "notes": str(data.get("body") or "")[:1400],
        "asset": package,
        "checksum_asset": checksum_file,
        "verified_package": bool(package and (package["sha256"] or checksum_file)),
    }


def fetch_latest_release(*, allow_prerelease=False):
    """Find official Windows game releases only, independently of launcher.

    Experimental published builds are opt-in and can be selected by the GUI
    without ever auto-downloading or switching launcher versions.
    """
    entries = _read_json(RELEASE_LIST_API_URL)
    if entries is None:
        return None
    if not isinstance(entries, list):
        raise ReleaseError("Invalid GitHub Releases listing.")
    releases_found = []
    for item in entries[:30]:
        if (not isinstance(item, dict) or item.get("draft") or
                (item.get("prerelease") and not allow_prerelease)):
            continue
        try:
            candidate = parse_release(item, allow_prerelease=allow_prerelease)
        except ReleaseError:
            continue
        if candidate:
            releases_found.append(candidate)
    if not releases_found:
        return None
    with_game_zip = [item for item in releases_found if item["asset"]]
    pool = with_game_zip or releases_found
    return max(pool, key=lambda item: parse_version(item["version"]) or (0, 0, 0))


def _open_trusted_download(url, timeout=35):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or not parsed.path.startswith(
            "/" + REPOSITORY + "/releases/download/"):
        raise ReleaseError("This download is not from the official Releases repository.")
    request = urllib.request.Request(url, headers={"User-Agent": _HEADER["User-Agent"]})
    response = urllib.request.urlopen(request, timeout=timeout)
    final = urllib.parse.urlsplit(response.geturl())
    # GitHub asset downloads are redirected to GitHub's asset CDN.
    if (final.scheme != "https" or final.hostname not in (
        "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"
    )):
        response.close()
        raise ReleaseError("GitHub release asset redirected to an untrusted host.")
    return response


def _expected_digest(release):
    asset = release.get("asset") if isinstance(release, dict) else None
    if not asset:
        raise ReleaseError("This GitHub release has no official Windows game ZIP.")
    if SHA256.fullmatch(asset.get("sha256") or ""):
        return asset["sha256"].lower()
    checksum = release.get("checksum_asset")
    if not checksum:
        raise ReleaseError("This release lacks the mandatory SHA-256 checksum.")
    try:
        with _open_trusted_download(checksum["url"]) as r:
            data = r.read(MAX_CHECKSUM + 1)
    except (OSError, TimeoutError) as exc:
        raise ReleaseError("Could not retrieve the release checksum.") from exc
    if len(data) > MAX_CHECKSUM:
        raise ReleaseError("Release checksum file is too large.")
    contents = data.decode("utf-8-sig", "replace").splitlines()
    for line in contents:
        match = re.match(r"^\s*([0-9a-fA-F]{64})(?:\s+\*?(.+?))?\s*$", line)
        if match:
            name = (match.group(2) or "").strip()
            if name == asset["name"] or (
                name == "" and checksum["name"].lower() ==
                (asset["name"] + ".sha256").lower()
            ):
                return match.group(1).lower()
    raise ReleaseError("Checksum file does not mention the official Windows ZIP.")


def game_installed_version(game_path):
    if not game_path:
        return None
    marker = os.path.join(game_path, "forge_release_state.json")
    try:
        with open(marker, encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict) and parse_version(state.get("version")):
            return str(state["version"])
    except (OSError, ValueError, TypeError):
        pass
    return None


def _game_running():
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ctr-native.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=6, check=False)
        if result.returncode:
            # Fail closed when Windows cannot verify process state.
            raise ReleaseError("Cannot verify whether the game is running; close it first.")
        return "ctr-native.exe" in result.stdout.lower()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseError("Could not verify the game's process state.") from exc


def _collect_zip_files(archive):
    infos = archive.infolist()
    if not infos or len(infos) > MAX_FILES:
        raise ReleaseError("Game archive is empty or has too many files.")
    items, seen, unpacked = [], set(), 0
    for info in infos:
        raw = info.filename
        if ("\\" in raw or raw.startswith("/") or "\x00" in raw
            or re.match(r"^[a-zA-Z]:", raw) or len(raw) > 260):
            raise ReleaseError("Game package includes an unsafe path.")
        segments = raw.rstrip("/").split("/")
        if not segments or any(part in ("", ".", "..") for part in segments):
            raise ReleaseError("Game package includes an unsafe directory.")
        lower_parts = [part.casefold() for part in segments]
        if any(part in _BLOCKED_PATH_COMPONENTS for part in lower_parts):
            raise ReleaseError("Release ZIP includes user mods or saves; cannot overwrite personal content.")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ReleaseError("Game package contains an unsafe symbolic link.")
        if info.is_dir():
            continue
        relative = "/".join(segments)
        case = relative.casefold()
        if case == "forge_release_state.json":
            raise ReleaseError("The release cannot override the installer's version marker.")
        if case in seen:
            raise ReleaseError("Duplicate game file path (case insensitive).")
        seen.add(case)
        suffix = Path(relative).suffix.lower()
        if suffix not in _ALLOWED_GAME_EXTENSIONS or (
            suffix == ".exe" and relative.lower() != "ctr-native.exe"
        ):
            raise ReleaseError("Game release contains unsupported executable or file: " + relative)
        if info.file_size > MAX_UNPACKED:
            raise ReleaseError("Game file exceeds limit.")
        unpacked += info.file_size
        if unpacked > MAX_UNPACKED:
            raise ReleaseError("Game package expands beyond safety limit.")
        items.append((info, relative))
    if "ctr-native.exe" not in seen:
        raise ReleaseError("Official game ZIP must contain ctr-native.exe at archive root.")
    return items


def _inside(base, path):
    root = os.path.normcase(os.path.realpath(base))
    candidate = os.path.normcase(os.path.realpath(path))
    try:
        return os.path.commonpath((root, candidate)) == root
    except ValueError:
        return False


def install_game_release(release, game_path, progress=None):
    """Verified, user-authorized release install with backups and rollback.

    Only replace files explicitly in the ZIP, preserve user-created folders.
    The caller MUST obtain explicit confirmation before invoking this function.
    """
    # Never accept an empty install directory. This check must happen before
    # release checksum retrieval or the game-running/process check.
    if not isinstance(game_path, (str, os.PathLike)) or not os.fspath(game_path):
        raise ReleaseError(
            "Choose a game installation folder in Launcher Settings before installing.")
    if not isinstance(release, dict) or not release.get("verified_package"):
        raise ReleaseError("Only a Windows release with SHA-256 may be installed.")
    if not parse_version(release.get("version")):
        raise ReleaseError("Release has no valid version.")
    if _game_running():
        raise ReleaseError("Close Crash Forge: Racing before installing an update.")
    expected = _expected_digest(release)
    asset = release["asset"]
    target_root = os.path.abspath(os.path.normpath(str(game_path)))
    parent = os.path.dirname(target_root)
    if not os.path.isdir(parent):
        raise ReleaseError("Select an existing parent folder in Settings first.")
    if not os.path.isdir(target_root):
        # Installation starts only after the download and ZIP are verified.
        missing_target = True
    else:
        missing_target = False
    with tempfile.TemporaryDirectory(prefix=".cfr-game-staging-", dir=parent) as work:
        zip_path = os.path.join(work, "release.zip")
        size = 0
        digest = hashlib.sha256()
        started = time.monotonic()
        try:
            with _open_trusted_download(asset["url"]) as r, open(zip_path, "wb") as output:
                total = int(r.headers.get("Content-Length", 0) or 0)
                if total > MAX_DOWNLOAD:
                    raise ReleaseError("Official Windows ZIP exceeds 2 GiB.")
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_DOWNLOAD:
                        raise ReleaseError("Download exceeds 2 GiB.")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        speed = size / max(.01, time.monotonic() - started)
                        progress("download", size, total or int(asset["size"]), speed)
        except (OSError, TimeoutError) as exc:
            raise ReleaseError("Official ZIP download failed: " + str(exc)) from exc
        if digest.hexdigest() != expected:
            raise ReleaseError("SHA-256 mismatch. The game was NOT modified.")
        staged = os.path.join(work, "payload")
        os.makedirs(staged)
        with zipfile.ZipFile(zip_path, "r") as z:
            entries = _collect_zip_files(z)
            for idx, (info, relative) in enumerate(entries):
                destination = os.path.join(staged, *relative.split("/"))
                if not _inside(staged, destination):
                    raise ReleaseError("Release path escapes its staging folder.")
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with z.open(info, "r") as source, open(destination, "wb") as output:
                    shutil.copyfileobj(source, output, length=256 * 1024)
                if progress and idx % 20 == 0:
                    progress("extract", idx + 1, len(entries), 0)
        if _game_running():
            raise ReleaseError("Close the game before applying this verified package.")
        if missing_target:
            os.makedirs(target_root, exist_ok=False)
        if not _inside(parent, target_root):
            raise ReleaseError("Installation directory resolves outside selected location.")
        backup_root = os.path.join(target_root, ".forge_game_backups")
        transaction_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:7]
        backup = os.path.join(backup_root, transaction_id)
        os.makedirs(backup, exist_ok=False)
        changed = []
        try:
            marker_relative = "forge_release_state.json"
            existing = [(relative, os.path.join(staged, *relative.split("/")))
                        for _, relative in entries]
            marker = os.path.join(staged, marker_relative)
            with open(marker, "w", encoding="utf-8") as f:
                json.dump({"version": release["version"], "tag": release["tag"],
                           "release_url": release["url"], "archive_sha256": expected,
                           "installed_at": int(time.time())}, f, indent=2)
            existing.append((marker_relative, marker))
            for index, (relative, source) in enumerate(existing):
                destination = os.path.join(target_root, *relative.split("/"))
                if not _inside(target_root, destination):
                    raise ReleaseError("Unsafe existing game path or directory link.")
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                old_present = os.path.lexists(destination)
                old_backup = os.path.join(backup, *relative.split("/"))
                if old_present:
                    if os.path.isdir(destination):
                        raise ReleaseError("A game file collides with an existing directory.")
                    os.makedirs(os.path.dirname(old_backup), exist_ok=True)
                    os.replace(destination, old_backup)
                changed.append((destination, old_backup if old_present else None))
                os.replace(source, destination)
                if progress and index % 10 == 0:
                    progress("install", index + 1, len(existing), 0)
        except Exception as exc:
            problems = []
            for destination, old_backup in reversed(changed):
                try:
                    if os.path.isfile(destination):
                        os.remove(destination)
                    if old_backup is not None and os.path.exists(old_backup):
                        os.makedirs(os.path.dirname(destination), exist_ok=True)
                        os.replace(old_backup, destination)
                except OSError as rollback_exc:
                    problems.append(str(rollback_exc))
            if problems:
                raise ReleaseError("Install failed and rollback needs manual repair: " +
                                   "; ".join(problems[:2])) from exc
            raise ReleaseError("Game update failed; original files restored: " + str(exc)) from exc
        if progress:
            progress("installed", len(entries), len(entries), 0)
    return {"version": release["version"], "files": len(entries), "backup": backup}