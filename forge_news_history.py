"""Append-only launcher NEWS history; images are tied to existing release tags."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request

REPOSITORY = "CarisaDemon/Crash-Forge-Launcher"
GITHUB_RELEASES = "https://github.com/" + REPOSITORY + "/releases"
_VERSION = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_IMAGES = {"0.3.37": "forge-news-v0.3.37.webp",
           "0.3.38": "forge-news-v0.3.38.webp",
           "0.3.39": "forge-news-v0.3.39.webp", "0.3.41": "forge-news-v0.3.41.webp", "0.3.42": "forge-news-v0.3.42.webp", "0.3.43": "forge-news-v0.3.43.webp", "0.3.44": "forge-news-v0.3.44.webp", "0.3.45": "forge-news-v0.3.45.webp"}
_TITLES = {"0.3.37": "Forge Hub Website Is Live",
           "0.3.38": "Model Importer v1.8 — Redesigned",
           "0.3.39": "Forge Hub Mod Manager", "0.3.41": "File verification system", "0.3.42": "Mod folder separation", "0.3.43": "Forge Hub Accounts & Multi-Monitor Fixes", "0.3.44": "Music Toolkits: Custom Tracks & Portable Editors", "0.3.45": "BIG UPDATE: Editors, Monitors & Independent NEWS"}


def valid_version(v):
    match = _VERSION.fullmatch(str(v or "").strip())
    return ".".join(match.groups()) if match else None


def release_url(version):
    version = valid_version(version)
    return f"{GITHUB_RELEASES}/tag/v{version}" if version else ""


def _plain(s):
    s = re.sub(r"\[([^\]]{1,180})\]\(https?://[^)]+\)", r"\1", str(s))
    s = s.replace("**", "").replace(chr(96), "").replace("\r", "")
    s = re.sub(r"<[^>]{1,200}>", "", s)
    return re.sub(r"\s+", " ", s).strip()[:240]


def _notes(body):
    if not isinstance(body, str):
        return []
    return [_plain(s.strip()[2:]) for s in body[:16000].splitlines()
            if s.lstrip().startswith(("- ", "* "))][0:8]


def normalized(raw):
    """Discard arbitrary URLs and asset paths from untrusted metadata."""
    if not isinstance(raw, dict):
        return None
    version = valid_version(raw.get("version", raw.get("tag_name")))
    if not version:
        return None
    title = _TITLES.get(version) or _plain(
        raw.get("title") or raw.get("name") or f"Crash Forge Launcher v{version}")
    date = str(raw.get("date", raw.get("published_at", "")) or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        date = ""
    notes = raw.get("notes")
    if not isinstance(notes, list):
        notes = []
    return {"version": version, "title": title[:95], "date": date,
            "notes": [s for s in (_plain(t) for t in notes[:8]) if s],
            "url": release_url(version)}


def merge_history(*collections):
    """New information replaces SAME-version metadata, never previous entries."""
    stored = {}
    for entries in collections:
        if not isinstance(entries, (list, tuple)):
            continue
        for raw in entries:
            current = normalized(raw)
            if current:
                previous = stored.get(current["version"], {})
                current["notes"] = current["notes"] or previous.get("notes", [])
                current["date"] = current["date"] or previous.get("date", "")
                stored[current["version"]] = current
    return sorted(stored.values(),
                  key=lambda x: tuple(map(int, x["version"].split("."))),
                  reverse=True)


def state_dir():
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "CrashForgeLauncher" / "news"


def asset_roots(base_dir):
    base = Path(base_dir)
    return (base / "assets" / "news",
            base / "_internal" / "assets" / "news",
            state_dir())


def _read_json(path):
    try:
        if not path.is_file() or path.stat().st_size > 480000:
            return {}
        content = json.loads(path.read_text(encoding="utf-8"))
        return content if isinstance(content, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def local_publications(base_dir):
    local = []
    for folder in asset_roots(base_dir)[:2]:
        data = _read_json(folder / "publications.json")
        if data.get("schema") == 1 and data.get("repository") == REPOSITORY:
            local = data.get("publications", [])
            break
    cache = _read_json(state_dir() / "history.json")
    if cache.get("schema") != 1:
        cache = {}
    return merge_history(local, cache.get("publications", []))


def save_history(items, base_dir):
    merged = merge_history(local_publications(base_dir), items)
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="history_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"schema": 1, "repository": REPOSITORY,
                       "publications": merged}, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, folder / "history.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return merged


def trusted_image_asset(raw, version):
    name = _IMAGES.get(version)
    if not name or not isinstance(raw, list):
        return None
    url = f"{GITHUB_RELEASES}/download/v{version}/{name}"
    for item in raw:
        if not isinstance(item, dict) or item.get("name") != name:
            continue
        digest = str(item.get("digest") or "")
        size = item.get("size")
        if (item.get("browser_download_url") == url
                and isinstance(size, int) and 512 <= size <= 6 * 1024 * 1024
                and digest.startswith("sha256:") and _SHA256.fullmatch(digest[7:])):
            return {"version": version, "name": name, "url": url,
                    "size": size, "sha256": digest[7:].lower()}
    return None


def parse_github_history(releases):
    if not isinstance(releases, list):
        return [], []
    news, images = [], []
    for raw in releases[:100]:
        if not isinstance(raw, dict) or raw.get("draft") or raw.get("prerelease"):
            continue
        version = valid_version(raw.get("tag_name"))
        if not version:
            continue
        entry = normalized({"version": version, "name": raw.get("name"),
                            "published_at": raw.get("published_at"),
                            "notes": _notes(raw.get("body"))})
        if entry:
            news.append(entry)
            image = trusted_image_asset(raw.get("assets"), version)
            if image:
                images.append(image)
    return merge_history(news), images


def sync_release_artwork(images):
    """Only download an exact version-named, SHA-256 checked WEBP file."""
    updated = []
    for item in images:
        if (not isinstance(item, dict) or
                item.get("name") != _IMAGES.get(item.get("version"))):
            continue
        directory = state_dir()
        dest = directory / item["name"]
        try:
            if dest.is_file() and dest.stat().st_size == item["size"]:
                if hashlib.sha256(dest.read_bytes()).hexdigest() == item["sha256"]:
                    continue
            req = urllib.request.Request(
                item["url"], headers={"User-Agent": "CrashForgeLauncher/News"})
            with urllib.request.urlopen(req, timeout=16) as response:
                redirect = urllib.parse.urlsplit(response.geturl())
                if (redirect.scheme != "https" or redirect.hostname not in
                        {"github.com", "release-assets.githubusercontent.com",
                         "objects.githubusercontent.com"}):
                    raise ValueError("Artwork redirected to an unexpected host")
                data = response.read(6 * 1024 * 1024 + 1)
            if (len(data) != item["size"] or
                    hashlib.sha256(data).hexdigest() != item["sha256"]):
                raise ValueError("News image failed SHA-256 or length verification")
            from io import BytesIO
            from PIL import Image
            with Image.open(BytesIO(data)) as im:
                if (im.format != "WEBP" or not
                        (100 <= im.width <= 6000 and 64 <= im.height <= 6000)):
                    raise ValueError("Unexpected news image type or dimensions")
                im.verify()
            directory.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="art_", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                os.replace(tmp, dest)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            updated.append(item["version"])
        except (OSError, ValueError, ImportError):
            continue  # Art is optional, and cannot block the updater or launcher.
    return updated


def artwork_file(base_dir, version):
    version = valid_version(version)
    name = _IMAGES.get(version)
    if not name and version == "0.3.35":
        name = "latest_update.webp"  # v0.3.35 historical screenshot only
    if not name:
        return None
    a, b, cache = asset_roots(base_dir)
    for directory in (cache, a, b):
        path = directory / name
        if path.is_file():
            return str(path)
    return None


def garage_fallback(base_dir):
    base = Path(base_dir)
    for item in (base / "assets" / "Fondo.png",
                 base / "_internal" / "assets" / "Fondo.png"):
        if item.is_file():
            return str(item)
    return None