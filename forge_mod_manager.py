"""Crash Forge modular mod library and native INI switches.

One game-readable folder per new mod: mods/<readable_mod_name>/ next to ctr-native.exe.
The *native* [character]/[kart]/[wheel(s)]/[music]/[track] enabled value
is the authority, not an independent launcher setting. [forge_mod] supplies
an ID/version so Forge Hub can match an exact published package.

No game/source/ISO changes, no implicit migration of existing user folders.
"""
from __future__ import annotations

import configparser
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata

CATEGORIES = {
    "Character": ("racers", "character.ini", ("character",)),
    "Kart": ("karts", "kart.ini", ("kart",)),
    "Wheels": ("wheels", "wheels.ini", ("wheels", "wheel")),
    "Track": ("tracks", "track.ini", ("track",)),
    "Music": ("music", "music.ini", ("music",)),
    "Modpack": ("modpacks", "modpack.ini", ("modpack",)),
}
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
MANAGER_SECTION = "forge_mod"
_MAX_INI_BYTES = 1024 * 1024


class ModManagerError(ValueError):
    pass


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise ModManagerError("Invalid Forge mod ID. Use lowercase letters, numbers, - or _.")
    return slug


def category_for_directory(directory: str) -> str | None:
    return next((category for category, (part, _, _) in CATEGORIES.items()
                 if part == directory), None)


def game_mods(game_path) -> Path:
    """New name-based modules live next to ctr-native.exe, not within assets/."""
    return Path(game_path) / "mods"


def legacy_game_mods(game_path) -> Path:
    """Old, category-grouped mods remain in assets/mods and are never moved."""
    return Path(game_path) / "assets" / "mods"


def folder_name_for_title(title: str) -> str:
    """Portable, readable name for a module directory (never a web identifier).

    Folder names are intentionally filesystem-safe ASCII slugs to work on
    Windows, native game scanners and Wine; full display names stay in INI.
    """
    human = unicodedata.normalize("NFKD", str(title or "")).encode(
        "ascii", "ignore").decode("ascii").lower()
    name = re.sub(r"[^a-z0-9]+", "_", human).strip("_")
    if not name:
        name = "community_mod"
    name = name[:58].rstrip("_") or "community_mod"
    # The native assets router reserves these legacy category names, and
    # Windows forbids the old DOS device names as directory components.
    reserved = {"racers", "karts", "wheels", "music", "tracks",
                "vanilla_racer_masks", "con", "prn", "aux", "nul"}
    reserved.update("com" + str(i) for i in range(1, 10))
    reserved.update("lpt" + str(i) for i in range(1, 10))
    return "mod_" + name if name in reserved else name


def _find_existing_web_folder(game_path, stable_id: str):
    """Find an installed mod by its immutable [forge_mod] ID, NOT dirname."""
    root = game_mods(game_path)
    if not root.is_dir() or root.is_symlink():
        return None, None
    found = []
    for folder in root.iterdir():
        if not SLUG.fullmatch(folder.name) or not _safe_directory(folder, root):
            continue
        for kind, (_, filename, _) in CATEGORIES.items():
            ini = folder / filename
            if not ini.is_file() or ini.is_symlink():
                continue
            try:
                cfg = _read_ini(ini)
                if (cfg.has_section(MANAGER_SECTION) and
                    cfg.get(MANAGER_SECTION, "id", fallback="").strip() == stable_id):
                    declared_type = cfg.get(MANAGER_SECTION, "type", fallback="")
                    # Match by immutable ID; the requested category and the
                    # declared type are checked by read_mod/installer later.
                    found.append((folder, kind))
            except ModManagerError:
                continue
    if len(found) > 1:
        raise ModManagerError("Duplicate installed web mod ID: "+stable_id)
    return found[0] if found else (None, None)


def mod_path(game_path, category: str, slug: str, title: str | None = None,
             *, prefer_readable: bool = False) -> Path:
    """Resolve existing stable ID; otherwise choose a collision-safe name."""
    if category not in CATEGORIES:
        raise ModManagerError("Unknown Forge mod type: " + str(category))
    stable_id = validate_slug(slug)
    found, kind = _find_existing_web_folder(game_path, stable_id)
    if found is not None:
        if kind != category:
            raise ModManagerError("Web mod ID belongs to a different category")
        # Old versions used the web ID as dirname. On explicit REINSTALL,
        # choose a readable path and let the transactional installer back up
        # the old folder; all ordinary lookups still resolve the existing ID.
        if not (prefer_readable and title and found.name == stable_id and
                folder_name_for_title(title) != stable_id):
            return found
    root = game_mods(game_path)
    # Until updated, existing ID-named folders still resolve by their INI.
    # Never rename/delete previous installed mods automatically.
    readable = folder_name_for_title(title or slug)
    for index in range(1, 999):
        name = readable if index == 1 else (readable[:54] + "_" + str(index))
        location = root / name
        if not location.exists() and not location.is_symlink():
            return location
        # A same-named folder with missing/invalid metadata is not ours.
        # Never overwrite it or assume ownership based on its title.
    raise ModManagerError("Unable to allocate a unique mod folder name")


def _safe_directory(path: Path, root: Path) -> bool:
    try:
        if path.is_symlink() or not path.is_dir() or root.is_symlink():
            return False
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def _read_ini(path: Path):
    if not path.is_file() or path.is_symlink():
        raise ModManagerError("Missing native mod INI: " + path.name)
    if path.stat().st_size > _MAX_INI_BYTES:
        raise ModManagerError("INI is unexpectedly large: " + path.name)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str.lower
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            parser.read_file(stream)
    except (OSError, UnicodeError, configparser.Error) as error:
        raise ModManagerError("Could not read native mod INI: " + path.name) from error
    return parser


def _native_section(config, kind: str) -> str:
    options = CATEGORIES[kind][2]
    for section in config.sections():
        if section.lower() in options:
            return section
    raise ModManagerError(CATEGORIES[kind][1] + " needs [" +
                          options[0] + "]")


def _identifier(config, kind: str, slug: str, *, reassignment=False):
    native = _native_section(config, kind)
    if config.has_section(MANAGER_SECTION):
        metadata_type=config.get(MANAGER_SECTION,"type",fallback="").strip()
        if metadata_type and metadata_type != kind:
            raise ModManagerError("INI mod type does not match ["+native+
                                  "] and requested category "+kind)
        declared=config.get(MANAGER_SECTION,"id",fallback="").strip()
        if declared and not SLUG.fullmatch(declared):
            raise ModManagerError("Invalid immutable web mod ID in native INI")
    # Native [character]/[kart] id is an asset identifier from the original
    # mod creator; the web package ID is assigned independently by Forge Hub.
    return native


def _atomic_ini(path: Path, text: str):
    if not path.is_file() or path.is_symlink():
        raise ModManagerError("Cannot edit absent or linked native INI")
    fd, tmp = tempfile.mkstemp(prefix=".forge_ini_", suffix=".tmp", dir=path.parent)
    try:
        # Preserve the original file's read/write permissions.
        os.chmod(tmp, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        fd = -1
        os.replace(tmp, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)


def _section_bounds(lines: list[str], section: str):
    begin = end = None
    needle = section.lower()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*\[([^\]]+)\]\s*(?:[;#].*)?$", line.rstrip("\r\n"))
        if match:
            if begin is not None:
                end = index
                break
            if match.group(1).strip().lower() == needle:
                begin = index
    if begin is None:
        raise ModManagerError("Missing native [" + section + "]")
    return begin, end if end is not None else len(lines)


def _put_ini_key(lines: list[str], section: str, key: str, value: str):
    """Edit an INI value without rewriting its other settings or comments."""
    begin, end = _section_bounds(lines, section)
    newline = "\r\n" if any("\r\n" in x for x in lines) else "\n"
    pattern = re.compile(r"^([ \t]*" + re.escape(key) + r"[ \t]*=[ \t]*).*$", re.I)
    matches = []
    for index in range(begin + 1, end):
        body = lines[index].rstrip("\r\n")
        if body.lstrip().startswith((";", "#")):
            continue
        if pattern.match(body):
            matches.append(index)
    if len(matches) > 1:
        raise ModManagerError("Ambiguous duplicate ["+section+"] "+key)
    if matches:
        line = lines[matches[0]]
        prefix = pattern.match(line.rstrip("\r\n")).group(1)
        lines[matches[0]] = prefix + value + (
            "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else "")
    else:
        lines.insert(begin + 1, key + " = " + value + newline)
    return lines


def _edit_ini(path: Path, kind: str, slug: str, *,
              enabled: bool | None = None, meta: dict | None = None):
    cfg = _read_ini(path)
    native = _identifier(cfg, kind, slug, reassignment=bool(meta))
    raw = path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\r", "\n")):
        lines[-1] += "\r\n" if "\r\n" in raw else "\n"
    if enabled is not None:
        _put_ini_key(lines, native, "enabled", "true" if enabled else "false")
        if cfg.has_section(MANAGER_SECTION):
            _put_ini_key(lines, MANAGER_SECTION, "enabled",
                         "true" if enabled else "false")
    if meta is not None:
        if meta.get("type") != kind or not SLUG.fullmatch(str(meta.get("id", ""))):
            raise ModManagerError("Mismatched package identity")
        # Folder name is human-readable; immutable web identity lives here.
        # Preserve existing user-edited metadata whenever the package is local.
        if not cfg.has_section(MANAGER_SECTION):
            newline = "\r\n" if "\r\n" in raw else "\n"
            lines.append(newline + "[" + MANAGER_SECTION + "]" + newline)
        # Both the game and launcher read enabled from native [type].
        # Mirror it into [forge_mod] for workshop tooling and ZIP inspectors.
        if enabled is not None and not cfg.has_section(MANAGER_SECTION):
            _put_ini_key(lines, MANAGER_SECTION, "enabled",
                         "true" if enabled else "false")
        allowed = ("id", "type", "name", "version", "source", "source_id")
        for key in allowed:
            value = str(meta.get(key, "") or "").strip()
            if not value:
                continue
            if "\n" in value or "\r" in value or len(value) > 180:
                raise ModManagerError("Invalid metadata in mod ZIP: " + key)
            _put_ini_key(lines, MANAGER_SECTION, key, value)
    candidate = "".join(lines)
    # Validate the entire candidate BEFORE committing to an installed mod.
    check = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        check.read_string(candidate)
    except configparser.Error as exc:
        raise ModManagerError("Generated native INI is invalid") from exc
    _atomic_ini(path, candidate)
    return candidate


def read_mod(game_path, kind: str, slug: str, *, legacy=False):
    """Read new web-ID package or legacy category path without moving files."""
    root=game_mods(game_path)
    legacy_root=legacy_game_mods(game_path)
    validate_slug(slug)
    if kind not in CATEGORIES:
        raise ModManagerError("Unsupported installed mod category: "+str(kind))
    filename=CATEGORIES[kind][1]
    # Callers may supply web ID OR actual readable folder name.
    found, found_kind = _find_existing_web_folder(game_path,slug) if not legacy else (None,None)
    if found is not None and found_kind != kind:
        raise ModManagerError("Web ID belongs to another mod category")
    direct = root / slug
    unified = found or (direct if _safe_directory(direct,root) else
                        mod_path(game_path,kind,slug))
    old=legacy_root/CATEGORIES[kind][0]/slug
    folder=(old if legacy else unified)
    folder_root=legacy_root if legacy else root
    if not _safe_directory(folder,folder_root):
        if not legacy and _safe_directory(old,legacy_root):
            folder=old
            legacy=True
        else:
            raise ModManagerError("Mod folder is missing or unsafe")
    ini=folder/filename
    row={
        "id":slug,"type":kind,"title":slug.replace("_"," ").title(),
        "author":"LOCAL MOD","source":"installed","path":str(folder),
        "version":"","enabled":None,"manageable":False,
        "layout":"legacy" if legacy else "web-id",
        "origin":"legacy" if legacy else "local",
        "status":"MISSING INI",
        "description":"A native INI is required to enable this mod.",
    }
    if not ini.is_file() or ini.is_symlink():
        return row
    try:
        cfg=_read_ini(ini)
        section=_identifier(cfg,kind,slug)
        if not legacy and not cfg.has_section(MANAGER_SECTION):
            raise ModManagerError("Missing [forge_mod] id/type metadata")
        if not legacy and (
                not SLUG.fullmatch(cfg.get(MANAGER_SECTION,"id",fallback="")) or
                cfg.get(MANAGER_SECTION,"type",fallback="")!=kind):
            raise ModManagerError("Web ID or type not declared in native INI")
        if not legacy and found is not None and cfg.get(
                MANAGER_SECTION,"id",fallback="") != slug:
            raise ModManagerError("Resolved installed web ID does not match INI")
        raw=cfg.get(section,"enabled",fallback="true").strip().lower()
        if raw not in ("true","false","yes","no","on","off","1","0"):
            raise ModManagerError("Invalid native enabled value")
        enabled=raw in ("true","yes","on","1")
        section_name=MANAGER_SECTION if cfg.has_section(MANAGER_SECTION) else section
        title=(cfg.get(section_name,"name",fallback="").strip() or
               cfg.get(section,"name",fallback="").strip() or row["title"])
        row.update({
            "id":(cfg.get(MANAGER_SECTION,"id",fallback=slug)
                  if not legacy else slug),
            "folder":folder.name,
            "title":title[:100],
            "version":cfg.get(MANAGER_SECTION,"version",fallback="") if
                cfg.has_section(MANAGER_SECTION) else "",
            "enabled":enabled,"manageable":True,
            "source_id":cfg.get(MANAGER_SECTION,"source_id",fallback="") if
                cfg.has_section(MANAGER_SECTION) else "",
            "origin":cfg.get(MANAGER_SECTION,"source",fallback="local").strip().lower()
                     if cfg.has_section(MANAGER_SECTION) else "legacy",
            "status":"ENABLED" if enabled else "DISABLED",
            "description":("Game INI: "+filename+" / restart the game to apply changes."),
        })
    except (OSError,ModManagerError,ValueError) as exc:
        row["status"]="INVALID INI"
        row["description"]=str(exc)[:180]
    # Native LEV/VRM loading and custom track listing are now implemented;
    # do not report working installed custom tracks as 'staged'. 
    return row


def scan_installed(game_path):
    """List unified web-ID mods + untouched legacy category folders."""
    root=game_mods(game_path)
    old_root=legacy_game_mods(game_path)
    results={}
    if root.is_dir() and not root.is_symlink():
        try:
            names=list(root.iterdir())
        except OSError:
            names=[]
    else:
        names=[]
    # New flat modules: <game>/mods/<web-id>/{character.ini,...}
    for folder in names:
        if not SLUG.fullmatch(folder.name) or not _safe_directory(folder,root):
            continue
        for kind, (_, filename, _) in CATEGORIES.items():
            if (folder/filename).is_file():
                try:
                    result=read_mod(game_path,kind,folder.name,legacy=False)
                    results[(kind,result["id"])]=result
                except (OSError,ModManagerError):
                    continue
    # Existing mods/racers|karts|wheels|music/* are visible in INSTALLED,
    # but they are never copied, renamed, or made falsely compatible.
    for kind,(subfolder,filename,_) in CATEGORIES.items():
        parent=old_root/subfolder
        if not _safe_directory(parent,old_root):
            continue
        for folder in parent.iterdir():
            if not SLUG.fullmatch(folder.name) or not _safe_directory(folder,old_root):
                continue
            key=(kind,folder.name)
            if key in results:
                continue
            try:
                results[key]=read_mod(game_path,kind,folder.name,legacy=True)
            except (OSError,ModManagerError):
                continue
    return sorted(results.values(),key=lambda r:(r["type"],r["title"].casefold()))


def set_enabled(game_path, kind: str, slug: str, enabled: bool):
    if not isinstance(enabled,bool):
        raise ModManagerError("Enabled must be true or false")
    item=read_mod(game_path,kind,slug)
    if not item["manageable"]:
        raise ModManagerError(item["status"]+": "+item["description"])
    directory=Path(item["path"])
    if kind=="Modpack":
        _set_modpack_enabled(game_path,directory,slug,enabled)
    else:
        _edit_ini(directory/CATEGORIES[kind][1],kind,item["id"],enabled=enabled)
    return read_mod(game_path,kind,slug)


def _set_modpack_enabled(game_path, folder, slug, enabled):
    manifest = folder / "contents.json"
    if not manifest.is_file() or manifest.is_symlink() or manifest.stat().st_size>100000:
        raise ModManagerError("Modpack inventory is missing")
    try:
        items = json.loads(manifest.read_text(encoding="utf-8"))["mods"]
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise ModManagerError("Invalid Modpack component inventory") from exc
    if not isinstance(items, list) or not 2 <= len(items) <= 60:
        raise ModManagerError("Invalid Modpack component count")
    # All-or-rollback, not a set of independent best-effort switches.
    paths = [folder / "modpack.ini"]
    types_by_path = {paths[0]: "Modpack"}
    for item in items:
        if not isinstance(item, dict):
            raise ModManagerError("Invalid Modpack component")
        category = category_for_directory(str(item.get("type", "")))
        if category is None or category == "Modpack":
            raise ModManagerError("Invalid Modpack component category")
        component = read_mod(game_path, category, str(item.get("id", "")))
        if not component["manageable"]:
            raise ModManagerError("Modpack component is not manageable")
        component_ini = Path(component["path"])/CATEGORIES[category][1]
        paths.append(component_ini)
        types_by_path[component_ini] = category
    originals = {path:path.read_bytes() for path in paths}
    try:
        for path in paths:
            # Unified web-ID mod folders do not have a category parent.
            _edit_ini(path, types_by_path[path], path.parent.name,
                      enabled=enabled)
    except Exception:
        for path, data in originals.items():
            if path.is_file() and path.read_bytes() != data:
                tmp=path.with_name(".forge_modpack_rollback.tmp")
                tmp.write_bytes(data)
                os.replace(tmp,path)
        raise


def _find_package_root(contents: Path, kind: str, slug: str) -> Path:
    """Accept creator-written folders independently of the assigned web ID."""
    if not _safe_directory(contents,contents):
        raise ModManagerError("ZIP extraction root is unsafe")
    filename=CATEGORIES[kind][1]
    files=[
        item for item in contents.rglob("*")
        if item.is_file() and not item.is_symlink() and item.name.lower()==filename
        and len(item.relative_to(contents).parts)<=7
    ]
    if len(files)!=1:
        raise ModManagerError("ZIP needs exactly one "+filename+
                              " belonging to a "+kind+" mod")
    folder=files[0].parent
    if not _safe_directory(folder,contents) or any(p.is_symlink() for p in folder.rglob("*")):
        raise ModManagerError("Unsafe ZIP module directory")
    if kind=="Track" and (
            not list(folder.glob("*.lev")) or not list(folder.glob("*.vrm"))):
        raise ModManagerError("Native track requires both LEV and VRM")
    return folder


def prepare_single_mod(contents, mod, *, preserve_enabled=None):
    """Check identity and normalize a downloaded ZIP before any game write."""
    kind = mod.get("type")
    slug = validate_slug(mod.get("id"))
    if kind not in CATEGORIES or kind == "Modpack":
        raise ModManagerError("This ZIP is not a single supported native mod")
    root = _find_package_root(Path(contents), kind, slug)
    cfg = _read_ini(root / CATEGORIES[kind][1])
    _identifier(cfg, kind, slug, reassignment=True)
    meta = {
        "id":slug,
        "type":kind,
        "name":str(mod.get("title") or slug)[:100],
        "version":str(mod.get("version") or "1.0")[:40],
        "source":"forge_hub" if mod.get("source")!="local" else "local",
        "source_id":str(mod.get("public_id") or slug)[:90],
    }
    _edit_ini(root / CATEGORIES[kind][1], kind, slug,
              enabled=preserve_enabled if isinstance(preserve_enabled,bool) else True,
              meta=meta)
    return root


def ensure_modpack_identity(folder, pack_id, title, version, source="forge_hub"):
    """Decorate inventory INI; the installed components retain own native INIs."""
    slug=validate_slug(pack_id)
    path=Path(folder)/"modpack.ini"
    _edit_ini(path,"Modpack",slug,enabled=True,
              meta={"id":slug,"type":"Modpack","name":title,
                    "version":version,"source":source,"source_id":slug})

def inspect_local_zip(archive, kind: str):
    """Find stable mod identity from a local ZIP without extracting it.

    Explicit [forge_mod] id takes precedence. Otherwise a native INI id,
    named module folder, or sanitized ZIP name is used.
    """
    import zipfile

    if kind not in CATEGORIES:
        raise ModManagerError("Unsupported local mod category")
    path=Path(archive)
    if (not path.is_file() or path.is_symlink() or
            path.suffix.lower()!=".zip" or path.stat().st_size>1024**3):
        raise ModManagerError("Select an ordinary local .zip package")
    if kind == "Modpack":
        required="modpack.ini"
    else:
        required=CATEGORIES[kind][1]
    try:
        with zipfile.ZipFile(path,"r") as source:
            names=[i for i in source.infolist() if not i.is_dir() and
                   i.filename.replace("\\","/").rsplit("/",1)[-1].lower()==required]
            if len(names)!=1:
                raise ModManagerError("Local ZIP must have exactly one "+required)
            item=names[0]
            if item.file_size>_MAX_INI_BYTES:
                raise ModManagerError("Native INI is too large")
            cfg=configparser.ConfigParser(interpolation=None,strict=False)
            cfg.read_string(source.read(item).decode("utf-8-sig"))
            section=_native_section(cfg,kind)
            explicit=(cfg.get(MANAGER_SECTION,"id",fallback="") if
                      cfg.has_section(MANAGER_SECTION) else "").strip()
            if not explicit:
                explicit=cfg.get(section,"id",fallback="").strip() or cfg.get(
                    section,"slug",fallback="").strip()
            parent=Path(item.filename.replace("\\","/")).parent
            if not explicit and parent.name and parent.name.lower() not in (
                    "mods","assets",CATEGORIES[kind][0],"."):
                # If the native INI sits under a category folder, use that
                # module slug; a generic wrapper with a single mod also works.
                explicit=parent.name.lower()
            if not explicit:
                explicit=re.sub(r"[^a-z0-9_-]+","_",path.stem.lower()).strip("_")[:64]
            slug=validate_slug(explicit)
            if cfg.has_section(MANAGER_SECTION):
                declared_kind=cfg.get(MANAGER_SECTION,"type",fallback="").strip()
                if declared_kind and declared_kind!=kind:
                    raise ModManagerError("ZIP category does not match its Forge ID")
            return {"id":slug,"name":cfg.get(section,"name",fallback=slug).strip()[:100],
                    "kind":kind}
    except (zipfile.BadZipFile, UnicodeError, configparser.Error, OSError) as exc:
        raise ModManagerError("Invalid local ZIP/native INI") from exc



def display_mod_name(mod):
    """Readable name on a card; the web ID lives in Details and the INI."""
    if not isinstance(mod, dict):
        return "Untitled Mod"
    installed=mod.get("_installed") or {}
    source=mod.get("source")
    candidates=((installed.get("title"),mod.get("title"))
                if source in ("installed","local")
                else (mod.get("title"),installed.get("title")))
    for candidate in candidates:
        if isinstance(candidate,str) and candidate.strip():
            return candidate.strip()[:100]
    return "Untitled Mod"


def locally_sourced(mod):
    """Hide unpublished/local-only mods, not web mods already installed."""
    if not isinstance(mod,dict):
        return False
    source=str(mod.get("source") or "")
    installed=mod.get("_installed") or {}
    origin=str(installed.get("origin") or "").lower()
    if source=="online" or origin=="forge_hub":
        return False
    return source in ("local","installed") or origin in ("local","legacy")
