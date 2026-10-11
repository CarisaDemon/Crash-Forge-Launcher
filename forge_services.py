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
import forge_modpacks
import forge_mod_manager as mod_manager
from datetime import datetime

# No hard-coded game location: only an explicit selection in Launcher Settings.
DEFAULT_GAME_PATH = ""
MAX_FEED_BYTES = 1024 * 1024
MAX_MOD_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ZIP_ITEMS = 2000
ALLOWED_MOD_EXT = {
    ".obj", ".mtl", ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".ini",
    ".cfg", ".json", ".txt", ".md", ".wav", ".ogg", ".cseq", ".bin", ".sf2", ".lev", ".vrm",
    ".dds", ".webp", ".gif", ".xml", ".dat", ".gltf", ".glb",
}
MOD_FOLDERS = {"Character": "racers", "Kart": "karts", "Wheels": "wheels", "Track": "tracks", "Modpack": "modpacks", "Music": "music"}
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
    if not isinstance(game_path, (str, os.PathLike)) or not os.fspath(game_path):
        return {"installed": False, "exe_path": "",
                "detail": "Choose your game folder in Settings"}
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


def _install_verified_zip(mod, game_path, archive):
    """Transactional per-mod archive, with native IDs and a separate folder."""
    import forge_mod_manager as manager

    kind = str(mod.get("type", ""))
    slug = str(mod.get("id", ""))
    if kind not in MOD_FOLDERS or not SLUG_RE.fullmatch(slug):
        raise FeedError("Invalid mod identity or type.")
    if not real_game_status(game_path)["installed"]:
        raise FeedError("Select a valid Crash Forge game install before installing mods.")
    try:
        existing_folder, existing_kind = manager._find_existing_web_folder(
            game_path, slug)
        destination = manager.mod_path(
            game_path, kind, slug, title=str(mod.get("title") or slug),
            prefer_readable=True)
    except manager.ModManagerError as error:
        raise FeedError(str(error)) from error
    if existing_folder and existing_kind != kind:
        raise FeedError("Web mod ID belongs to a different category")
    parent = destination.parent
    if parent.is_symlink() or destination.is_symlink():
        raise FeedError("Cannot overwrite linked mod directories.")
    # A web ID names one stable module, not one module per category.
    # Do not silently overwrite a different type that happens to share an ID.
    if destination.is_dir():
        for other_kind, (_, config, _) in manager.CATEGORIES.items():
            if other_kind != kind and (destination / config).is_file():
                raise FeedError(
                    "Web mod ID already belongs to a different category: " +
                    other_kind)
    with tempfile.TemporaryDirectory(prefix=".forge-mod-prepare-", dir=game_path) as temp:
        contents = os.path.join(temp, "contents")
        os.makedirs(contents)
        try:
            with zipfile.ZipFile(archive, "r") as z:
                files = _verify_archive(z)
                for info in files:
                    if info.is_dir():
                        continue
                    rel = info.filename.replace("/", os.sep)
                    target = os.path.normpath(os.path.join(contents, rel))
                    if os.path.commonpath((contents, target)) != contents:
                        raise FeedError("Unsafe path inside mod ZIP.")
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with z.open(info,"r") as src,open(target,"wb") as output:
                        shutil.copyfileobj(src,output)
            if kind == "Modpack":
                # Apply the same stable identity scheme to a modpack and its
                # independently-scanned components before the game is touched.
                package = forge_modpacks.inspect_modpack(contents)
                for directory, child, path, title in package["components"]:
                    child_kind = manager.category_for_directory(directory)
                    ini = path / manager.CATEGORIES[child_kind][1]
                    manager._edit_ini(ini,child_kind,child,enabled=True,
                        meta={"id":child,"type":child_kind,"name":title,
                              "version":str(mod.get("version") or "1.0"),
                              "source":"forge_hub","source_id":slug})
                manager.ensure_modpack_identity(contents,slug,
                    str(mod.get("title") or package["name"])[:100],
                    str(mod.get("version") or "1.0")[:40],
                    "local" if mod.get("source")=="local" else "forge_hub")
                previous = None
                try:
                    previous = manager.read_mod(game_path,kind,slug)
                except manager.ModManagerError:
                    pass
                installed=forge_modpacks.install_prepared_modpack(contents,game_path,slug)
                if previous and previous.get("enabled") is False:
                    manager.set_enabled(game_path,kind,slug,False)
                return installed
            previous_enabled = None
            if existing_folder is not None:
                try:
                    previous_enabled = manager.read_mod(
                        game_path,kind,slug).get("enabled")
                except manager.ModManagerError:
                    pass
            prepared = manager.prepare_single_mod(
                contents, mod, preserve_enabled=previous_enabled)
        except (zipfile.BadZipFile, manager.ModManagerError,
                forge_modpacks.ModpackError) as exc:
            raise FeedError(str(exc)) from exc
        # Previous same-ID mod is backed up, never discarded. Older installs
        # named by web ID migrate to the readable folder during reinstall.
        # Never overwrite a different mod that now occupies the destination.
        if destination.is_symlink() or (
                destination.exists() and destination != existing_folder):
            raise FeedError("Mod destination was claimed by another package")
        if destination.exists() and not destination.is_dir():
            raise FeedError("Existing mod target is not a directory.")
        parent.mkdir(parents=True, exist_ok=True)
        backup = None
        backup_source = existing_folder
        if backup_source is not None:
            backups = os.path.join(game_path, ".forge_mod_backups")
            os.makedirs(backups, exist_ok=True)
            ident = manager.CATEGORIES[kind][0]+"_"+slug+"_"
            backup = os.path.join(
                backups, ident + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
            os.replace(backup_source, backup)
        try:
            os.replace(prepared, destination)
        except BaseException:
            if backup and not backup_source.exists():
                os.replace(backup,backup_source)
            raise
    return str(destination)


def _checked_mod(mod, game_path):
    kind=str(mod.get("type",""))
    slug=str(mod.get("id",""))
    if kind not in MOD_FOLDERS or not SLUG_RE.fullmatch(slug):
        raise FeedError("Invalid mod identity or type.")
    sha256 = str(mod.get("sha256", "")).lower()
    if not SHA256_RE.fullmatch(sha256):
        raise FeedError("A SHA-256 checksum is required to install.")
    if not real_game_status(game_path)["installed"]:
        raise FeedError("Select a valid Crash Forge game install before installing mods.")
    return sha256


def install_local_mod(mod, game_path, progress=None):
    """Install a local ZIP with the SAME validation and SHA-256 as online mods."""
    sha256 = _checked_mod(mod,game_path)
    package = os.path.abspath(str(mod.get("package_path", "")))
    if not os.path.isfile(package) or os.path.islink(package):
        raise FeedError("Choose a valid local .zip (not a shortcut).")
    if not package.lower().endswith(".zip"):
        raise FeedError("Only ZIP packages are supported.")
    if os.path.getsize(package)>MAX_MOD_BYTES:
        raise FeedError("Local mod ZIP exceeds the size limit.")
    size=os.path.getsize(package)
    digest=hashlib.sha256()
    done=0
    with open(package,"rb") as stream:
        while True:
            block=stream.read(262144)
            if not block: break
            digest.update(block)
            done+=len(block)
            if progress:
                progress(done,size,0)
    if digest.hexdigest()!=sha256:
        raise FeedError("Local ZIP changed since ADD LOCAL. Add it again before installing.")
    return _install_verified_zip(mod,game_path,package)


def download_install_mod(mod, game_path, progress=None):
    """Download a verified HTTPS ZIP and install isolated native mod modules."""
    sha256 = _checked_mod(mod,game_path)
    url = checked_https_url(mod.get("download_url", ""))
    digest = hashlib.sha256()
    received = 0
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".forge-download-",dir=game_path) as temp:
        package = os.path.join(temp,"download.zip")
        request = urllib.request.Request(
            url, headers={"User-Agent":"CrashForgeLauncher/ModManager"})
        with urllib.request.urlopen(request,timeout=20) as response:
            checked_https_url(response.geturl())
            total=int(response.headers.get("Content-Length","0") or 0)
            if total>MAX_MOD_BYTES:
                raise FeedError("Mod ZIP is too large.")
            with open(package,"wb") as out:
                while True:
                    block=response.read(262144)
                    if not block:break
                    received+=len(block)
                    if received>MAX_MOD_BYTES:
                        raise FeedError("Mod ZIP exceeds the size limit.")
                    digest.update(block)
                    out.write(block)
                    if progress:
                        speed=received/max(time.monotonic()-started,0.01)
                        progress(received,total,speed)
        if digest.hexdigest()!=sha256:
            raise FeedError("SHA-256 mismatch. Download was rejected without installing.")
        return _install_verified_zip(mod,game_path,package)