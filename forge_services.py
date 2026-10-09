"""Crash Forge online/local data and checked mod installation.

The launcher never invents remote stats. A public HTTPS feed is optional.
Packages must come with SHA-256 and are extracted without executable content.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
import urllib.request
import urllib.parse
import zipfile
import forge_mod_metadata as modmeta
from datetime import datetime

DEFAULT_GAME_PATH = r"C:\Crash Team Racing\Crash Team Racing Compiled Custom Music"
MAX_FEED_BYTES = 1024 * 1024
MAX_MOD_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ZIP_ITEMS = 2000
ALLOWED_MOD_EXT = {
    ".obj", ".mtl", ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".ini",
    ".cfg", ".json", ".txt", ".md", ".wav", ".ogg", ".cseq", ".bin",
    ".dds", ".webp", ".gif", ".xml", ".dat", ".gltf", ".glb",
}
MOD_FOLDERS = {"Character": "racers", "Kart": "karts", "Wheels": "wheels", "Track": "tracks"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class FeedError(ValueError):
    pass


def checked_https_url(url):
    url = str(url or "").strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise FeedError("Only public HTTPS addresses without embedded credentials are accepted.")
    if parsed.port not in (None, 443):
        raise FeedError("Only standard HTTPS port 443 is supported.")
    return url


def config_path(base_dir):
    return os.path.join(base_dir, "forge_online_config.json")


def read_online_config(base_dir):
    path = config_path(base_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            return {key: str(loaded.get(key, "") or "").strip()
                    for key in ("feed_url", "submit_url")}
    except (OSError, ValueError, TypeError):
        pass
    return {"feed_url": "", "submit_url": ""}


def save_online_config(base_dir, config):
    data = {key: str(config.get(key, "") or "").strip()
            for key in ("feed_url", "submit_url")}
    for key in ("feed_url", "submit_url"):
        if data[key]:
            checked_https_url(data[key])
    path = config_path(base_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def fetch_public_feed(url):
    checked_https_url(url)
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "CrashForgeLauncher/0.3"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            checked_https_url(response.geturl())
            if int(response.headers.get("Content-Length", "0") or 0) > MAX_FEED_BYTES:
                raise FeedError("Online catalog is too large.")
            raw = response.read(MAX_FEED_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        raise FeedError("Could not connect to the online catalog: " + str(exc)) from exc
    if len(raw) > MAX_FEED_BYTES:
        raise FeedError("Online catalog is too large.")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise FeedError("The online catalog is not valid JSON.") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise FeedError("Unsupported online catalog format (schema_version must be 1).")
    if not isinstance(data.get("news", []), list) or not isinstance(data.get("mods", []), list):
        raise FeedError("Online news and mods must be lists.")
    return data


def clean_news(feed):
    items = []
    for entry in feed.get("news", [])[:30]:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title", "")).strip()[:90]
        if not title:
            continue
        items.append({
            "category": str(entry.get("category", "NEWS"))[:35],
            "title": title,
            "date": str(entry.get("date", ""))[:20],
            "description": str(entry.get("description", ""))[:500],
            "url": str(entry.get("url", ""))[:500],
        })
    return items


def clean_mods(feed):
    mods = []
    seen = set()
    for item in feed.get("mods", [])[:300]:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("id", "")).strip().lower()
        kind = str(item.get("type", "")).strip()
        compatibility = str(item.get("compatibility", "")).strip().lower()
        if not SLUG_RE.fullmatch(slug) or slug in seen:
            continue
        if kind not in MOD_FOLDERS or compatibility not in ("cfr", "crash-forge-racing"):
            continue
        title = str(item.get("title", "")).strip()[:100]
        author = str(item.get("author", "")).strip()[:75]
        if not title or not author:
            continue
        seen.add(slug)
        download_url = str(item.get("download_url", "")).strip()
        sha256 = str(item.get("sha256", "")).strip().lower()
        try:
            checked_https_url(download_url)
        except FeedError:
            download_url = ""
        if not SHA256_RE.fullmatch(sha256):
            sha256 = ""
        result = {
            "id": slug,
            "title": title,
            "author": author,
            "type": kind,
            "compatibility": "cfr",
            "source": "online",
            "version": str(item.get("version", "1.0"))[:28],
            "description": str(item.get("description", ""))[:600],
            "created_at": str(item.get("created_at", ""))[:50],
            "download_url": download_url,
            "sha256": sha256,
            "page_url": "",
        }
        try:
            result["page_url"] = checked_https_url(item.get("page_url", ""))
        except FeedError:
            pass
        normalized = modmeta.normalize(kind, item)
        # Old feeds may omit subtypes, but explicit invalid metadata is rejected.
        if any(item.get(key) not in (None, "") and normalized.get(key) is None
               for key in modmeta.FIELDS):
            continue
        result.update(normalized)
        # Attribution fields are explicitly curated in the public catalog, not
        # proof of ownership by themselves. Login is checked by the OAuth service.
        login = str(item.get("author_github_login", "")).strip()
        numeric_id = item.get("author_github_id")
        if (re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", login)
                and isinstance(numeric_id, int) and not isinstance(numeric_id, bool)
                and numeric_id > 0):
            result["author_github_login"] = login
            result["author_github_id"] = numeric_id
        for field in ("downloads", "likes"):
            value = item.get(field)
            result[field] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        mods.append(result)
    return mods


def real_game_status(game_path):
    exe = os.path.join(game_path, "ctr-native.exe")
    if not os.path.isfile(exe):
        return {"installed": False, "exe_path": exe, "detail": "No ctr-native.exe found"}
    try:
        size = os.path.getsize(exe)
        modified = datetime.fromtimestamp(os.path.getmtime(exe)).strftime("%Y-%m-%d %H:%M")
        return {"installed": True, "exe_path": exe,
                "detail": "ctr-native.exe | " + modified + " | " + f"{size / 1048576:.1f} MB"}
    except OSError:
        return {"installed": True, "exe_path": exe, "detail": "ctr-native.exe present"}


def real_launcher_changelog(base_dir, limit=5):
    path = os.path.join(base_dir, "LAUNCHER_CHANGELOG.txt")
    version = ""
    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                text = line.strip()
                if text.startswith("v") and re.match(r"^v\d+\.\d+", text):
                    if version:
                        break
                    version = text
                elif version and text.startswith("- "):
                    entries.append(text[2:])
                    if len(entries) >= limit:
                        break
    except OSError:
        pass
    return version, entries


def _verify_archive(z):
    members = z.infolist()
    if not members or len(members) > MAX_ZIP_ITEMS:
        raise FeedError("Archive is empty or contains too many files.")
    size = 0
    for info in members:
        name = info.filename.replace("\\", "/")
        pieces = name.split("/")
        if (name.startswith("/") or len(name) > 240 or
                any(x in ("", ".", "..") for x in pieces if x != pieces[-1]) or
                ".." in pieces or ":" in name or "\x00" in name):
            raise FeedError("The mod ZIP has an unsafe path.")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise FeedError("The mod ZIP contains a symbolic link.")
        if info.is_dir():
            continue
        if not name or not pieces[-1]:
            raise FeedError("The mod ZIP has an invalid entry.")
        if os.path.splitext(name)[1].lower() not in ALLOWED_MOD_EXT:
            raise FeedError("Unsupported file in the mod ZIP: " + pieces[-1])
        size += info.file_size
        if size > MAX_EXTRACTED_BYTES:
            raise FeedError("Mod ZIP exceeds the extracted-size limit.")
    return members


def download_install_mod(mod, game_path, progress=None):
    """Download a verified ZIP and install beneath assets/mods; rollback on failure."""
    kind = mod.get("type", "")
    slug = str(mod.get("id", ""))
    if kind not in MOD_FOLDERS or not SLUG_RE.fullmatch(slug):
        raise FeedError("Invalid mod identity or type.")
    url = checked_https_url(mod.get("download_url", ""))
    sha256 = str(mod.get("sha256", "")).lower()
    if not SHA256_RE.fullmatch(sha256):
        raise FeedError("A SHA-256 checksum is required to install.")
    if not real_game_status(game_path)["installed"]:
        raise FeedError("Select a valid Crash Forge game install before installing mods.")
    dest_parent = os.path.join(game_path, "assets", "mods", MOD_FOLDERS[kind])
    dest = os.path.join(dest_parent, slug)
    os.makedirs(dest_parent, exist_ok=True)
    backup = None
    with tempfile.TemporaryDirectory(prefix=".cfr-staging-", dir=game_path) as staging:
        archive = os.path.join(staging, "download.zip")
        request = urllib.request.Request(
            url, headers={"User-Agent": "CrashForgeLauncher/0.3"})
        digest = hashlib.sha256()
        count = 0
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=20) as response:
            checked_https_url(response.geturl())
            total = int(response.headers.get("Content-Length", "0") or 0)
            if total > MAX_MOD_BYTES:
                raise FeedError("Mod ZIP is too large.")
            with open(archive, "wb") as f:
                while True:
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    count += len(block)
                    if count > MAX_MOD_BYTES:
                        raise FeedError("Mod ZIP exceeds the size limit.")
                    digest.update(block)
                    f.write(block)
                    if progress:
                        progress(count, total, count / max(0.01, time.monotonic() - started))
        if digest.hexdigest() != sha256:
            raise FeedError("SHA-256 mismatch. Download was rejected without installing.")
        contents = os.path.join(staging, "contents")
        os.makedirs(contents)
        with zipfile.ZipFile(archive, "r") as z:
            members = _verify_archive(z)
            for info in members:
                if info.is_dir():
                    continue
                subpath = info.filename.replace("/", os.sep)
                path = os.path.normpath(os.path.join(contents, subpath))
                if os.path.commonpath((contents, path)) != contents:
                    raise FeedError("Mod ZIP attempted directory traversal.")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with z.open(info, "r") as src, open(path, "wb") as target:
                    shutil.copyfileobj(src, target)
        # Save only this mod's previous folder; leave all other mods untouched.
        if os.path.isdir(dest):
            backups = os.path.join(game_path, ".forge_mod_backups")
            os.makedirs(backups, exist_ok=True)
            backup = os.path.join(backups, slug + "_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
            if os.path.exists(backup):
                raise FeedError("Backup already exists; installation canceled.")
            os.replace(dest, backup)
        try:
            os.replace(contents, dest)
        except Exception:
            if backup and not os.path.exists(dest):
                os.replace(backup, dest)
            raise
    return dest
