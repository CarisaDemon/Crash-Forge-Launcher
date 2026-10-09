"""Install a verified Forge Hub Modpack as individual native CFR mods.

Archive format:
    modpack.ini                    [modpack] name, description, compatibility=cfr
    racers/<id>/character.ini      [character] name
    karts/<id>/kart.ini            [kart] name
    wheels/<id>/wheels.ini         [wheel] name
    tracks/<id>/track.ini          [track] name

Each included mod is installed independently. The pack itself is only an
inventory under assets/mods/modpacks/<pack-id>. Backups and rollback protect
existing user mods if any component fails.
"""
from __future__ import annotations

import configparser
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import uuid

FOLDERS = {
    "racers": ("character.ini", "character"),
    "karts": ("kart.ini", "kart"),
    "wheels": ("wheels.ini", "wheel"),
    "tracks": ("track.ini", "track"),
}
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


class ModpackError(ValueError):
    pass


def _read_ini(path: Path, section: str):
    cfg = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            cfg.read_file(stream)
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise ModpackError("Invalid or unreadable INI: " + path.name) from exc
    if not cfg.has_section(section):
        raise ModpackError(path.name + " requires [" + section + "]")
    return cfg


def inspect_modpack(contents: str | Path):
    """Validate every component before touching the game installation."""
    root = Path(contents)
    manifest = root / "modpack.ini"
    if not manifest.is_file():
        raise ModpackError("Modpack must contain modpack.ini at ZIP root.")
    cfg = _read_ini(manifest, "modpack")
    name = cfg.get("modpack", "name", fallback="").strip()
    description = cfg.get("modpack", "description", fallback="").strip()
    compatible = cfg.get("modpack", "compatibility", fallback="").strip().lower()
    if not 3 <= len(name) <= 100 or not 1 <= len(description) <= 300:
        raise ModpackError("modpack.ini needs a name and short description.")
    if compatible != "cfr":
        raise ModpackError("Modpack compatibility must be cfr.")

    components = []
    expected_roots = set(FOLDERS) | {"modpack.ini"}
    for entry in root.iterdir():
        if entry.name not in expected_roots:
            raise ModpackError("Unexpected Modpack root entry: " + entry.name)
        if entry.name == "modpack.ini":
            continue
        if not entry.is_dir() or entry.is_symlink():
            raise ModpackError("Each category must be a folder.")
        expected_file, section = FOLDERS[entry.name]
        for directory in entry.iterdir():
            slug = directory.name
            if not SLUG.fullmatch(slug) or not directory.is_dir() or directory.is_symlink():
                raise ModpackError("Invalid mod folder identity: " + slug)
            ini = directory / expected_file
            if not ini.is_file() or ini.is_symlink():
                raise ModpackError(slug + " requires its own " + expected_file)
            details = _read_ini(ini, section)
            title = details.get(section, "name", fallback="").strip()
            if not title:
                raise ModpackError(slug + " is missing its INI name.")
            for key in ("id", "slug"):
                declared = details.get(section, key, fallback="").strip()
                if declared and declared != slug:
                    raise ModpackError(slug + ": INI " + key + " must match its folder.")
            for path in directory.rglob("*"):
                if path.is_symlink():
                    raise ModpackError("Symlinks are not allowed in Modpacks.")
            components.append((entry.name, slug, directory, title))
    if not 2 <= len(components) <= 60:
        raise ModpackError("A Modpack must contain 2 to 60 separately identified mods.")
    return {"name": name, "description": description, "components": components}


def install_prepared_modpack(contents: str | Path, game_path: str | Path, pack_id: str):
    """All-or-rollback moves, with previous user folders retained in backups."""
    if not SLUG.fullmatch(pack_id):
        raise ModpackError("Invalid Modpack ID.")
    root = Path(contents)
    package = inspect_modpack(root)
    home = Path(game_path)
    mods_root = home / "assets" / "mods"
    inventory = mods_root / "modpacks" / pack_id
    destinations = []
    for category, slug, source, title in package["components"]:
        target = mods_root / category / slug
        destinations.append((source, target))
    # Keep a local inventory, but do NOT wrap the components in an extra folder.
    record_src = root / ".modpack-inventory"
    record_src.mkdir()
    shutil.copy2(root / "modpack.ini", record_src / "modpack.ini")
    (record_src / "contents.json").write_text(
        json.dumps({"id": pack_id, "name": package["name"],
                    "description": package["description"],
                    "mods": [{"type": category, "id": slug, "name": title}
                             for category, slug, _, title in package["components"]]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    destinations.append((record_src, inventory))

    # A surprising symlink or file at any destination must not be replaced.
    for _, target in destinations:
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise ModpackError("Unsafe or invalid existing mod destination: " + target.name)

    transaction = uuid.uuid4().hex[:10]
    backup_root = home / ".forge_mod_backups" / ("pack_" + pack_id + "_" +
                         datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + transaction)
    moved = []
    try:
        for source, target in destinations:
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = backup_root / target.parent.name / target.name
            had_previous = target.is_dir()
            if had_previous:
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            try:
                os.replace(source, target)
            except Exception:
                if had_previous:
                    os.replace(backup, target)
                raise
            moved.append((source, target, backup, had_previous))
    except Exception:
        for source, target, backup, had_previous in reversed(moved):
            if target.is_dir():
                shutil.rmtree(target)
            if had_previous and backup.is_dir():
                os.replace(backup, target)
        raise
    return str(inventory)
