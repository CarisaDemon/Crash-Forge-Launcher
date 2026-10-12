"""Export multiple existing native CFR mods in one Launcher-compatible Modpack ZIP.

The bundled launcher already installs each component as its own native mod.
This exporter intentionally does not modify games, source mods or Forge Hub.
"""
from __future__ import annotations

import configparser
import hashlib
import os
from pathlib import Path
import re
import tempfile
import zipfile

from companion_tools.mod_packager import mod_packager_core as single
import forge_modpacks

FOLDER_CATEGORY = {
    "Character": "racers", "Kart": "karts",
    "Wheels": "wheels", "Track": "tracks",
}
MAX_COMPONENTS = 60
SLUG = forge_modpacks.SLUG


def _read_native(category, data: bytes, source: Path):
    expected, section = single.CATEGORIES[category]
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(data.decode("utf-8-sig"))
    except (configparser.Error, UnicodeDecodeError) as exc:
        raise single.PackageError(
            f"{source.name}: unreadable {expected}") from exc
    if category=="Wheels" and not parser.has_section(section) and parser.has_section("wheels"):
        section="wheels"
    if not parser.has_section(section):
        raise single.PackageError(
            f"{source.name}: [{section}] missing from {expected}")
    label = parser.get(section,"name",fallback="").strip()
    if not label or any(ch in label for ch in "\r\n[]") or len(label)>100:
        raise single.PackageError(
            f"{source.name}: {expected} needs a valid name")
    ident=(parser.get("forge_mod","id",fallback="").strip()
           if parser.has_section("forge_mod") else "")
    declared_type=(parser.get("forge_mod","type",fallback="").strip()
                   if parser.has_section("forge_mod") else "")
    if declared_type and declared_type.casefold()!=category.casefold():
        raise single.PackageError(
            f"{source.name}: [forge_mod] type doesn't match {category}")
    if ident and not SLUG.fullmatch(ident):
        # Bad/foreign IDs cannot silently turn into a web-authorized identity.
        raise single.PackageError(
            f"{source.name}: invalid [forge_mod] id")
    if not ident:
        ident=single.folder_name(source.name)
    if not SLUG.fullmatch(ident):
        raise single.PackageError(
            f"{source.name}: cannot create a safe mod ID")
    for key in ("id","slug"):
        explicit=parser.get(section,key,fallback="").strip()
        if explicit and explicit!=ident:
            raise single.PackageError(
                f"{source.name}: native {key} conflicts with the mod ID")
    return ident,label


def inspect_mod_folder(folder: str | Path) -> dict:
    """Validate one existing independent mod folder, without changing it."""
    path=Path(folder).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise single.PackageError("Select an ordinary mod folder, not a shortcut")
    path=path.resolve()
    pairs=single._list_assets(path)
    files=dict(pairs)
    found=[kind for kind,(ini,_) in single.CATEGORIES.items() if ini in files]
    if len(found)!=1:
        raise single.PackageError(
            f"{path.name}: select a folder containing exactly one "
            "character.ini, kart.ini, wheels.ini or track.ini")
    category=found[0]
    expected=single.CATEGORIES[category][0]
    for kind,(ini,_) in single.CATEGORIES.items():
        if kind!=category and any(Path(name).name.casefold()==ini
                                  for name in files):
            raise single.PackageError(
                f"{path.name}: {ini} belongs in a different mod folder")
    ident,label=_read_native(category,files[expected].read_bytes(),path)
    if category=="Track":
        lev=[name for name in files if name.lower().endswith(".lev")]
        vrm=[name for name in files if name.lower().endswith(".vrm")]
        if (len(lev)!=1 or len(vrm)!=1 or "/" in lev[0] or "/" in vrm[0]):
            raise single.PackageError(
                f"{path.name}: track.ini needs one root .lev and .vrm file")
    elif not any(name.lower().endswith((".obj",".glb",".gltf"))
                 for name in files):
        raise single.PackageError(
            f"{path.name}: missing model (.obj/.glb/.gltf)")
    return {
        "folder":path,"category":category,"directory":FOLDER_CATEGORY[category],
        "id":ident,"name":label,"files":pairs,
    }


def build_modpack_zip(*, title, version, author="", description="",
                      source_folders, output):
    """Produce the exact root layout expected by forge_modpacks.inspect_modpack.

    2-60 independent native INIs remain individually visible in the game.
    The exporter skips .bak files, refuses symlinks, forbidden extensions,
    duplicate child identities and collisions with the pack identity.
    """
    title=str(title).strip()
    version=str(version).strip()
    author=str(author).strip()
    description=str(description).strip()
    if not 3<=len(title)<=100 or any(ch in title for ch in "\r\n[]"):
        raise single.PackageError("Modpack name needs 3-100 safe characters")
    if not single.VERSION.fullmatch(version):
        raise single.PackageError("Invalid Modpack version")
    if len(author)>75 or any(c in author for c in "\r\n[]"):
        raise single.PackageError("Author must be 75 characters maximum")
    # Native launcher requires 1-300 chars in modpack.ini.
    if not 1<=len(description)<=300 or any(c in description for c in "\r\n[]"):
        raise single.PackageError("Modpack description needs 1-300 characters")
    folders=list(source_folders or [])
    if not 2<=len(folders)<=MAX_COMPONENTS:
        raise single.PackageError("Choose 2 to 60 independent mod folders")
    components=[inspect_mod_folder(p) for p in folders]
    child_ids=set()
    source_paths=set()
    for item in components:
        folder=item["folder"]
        key=os.path.normcase(str(folder)).casefold()
        if key in source_paths:
            raise single.PackageError("The same mod folder was selected twice")
        source_paths.add(key)
        ident=item["id"].casefold()
        if ident in child_ids:
            raise single.PackageError(
                "Two bundled mods have the same identity: "+item["id"])
        child_ids.add(ident)
    slug="local_"+single.folder_name(title)
    if len(slug)>64 or not SLUG.fullmatch(slug):
        raise single.PackageError("Modpack name produces an invalid ID")
    if slug in child_ids:
        raise single.PackageError(
            "Modpack ID cannot match a child mod's ID")
    out=Path(output).expanduser()
    if out.suffix.lower()!=".zip":
        raise single.PackageError("Export must be a .zip archive")
    if out.is_symlink() or out.exists():
        raise single.PackageError("ZIP destination already exists")
    out=out.resolve()
    if not out.parent.is_dir():
        raise single.PackageError("ZIP destination folder doesn't exist")
    if any(out.is_relative_to(comp["folder"]) for comp in components):
        raise single.PackageError("Save Modpack ZIP outside its mod folders")

    manifest=(
        "[modpack]\n"
        f"name = {title}\n"
        f"description = {description}\n"
        f"compatibility = cfr\n"
        f"author = {author}\n"
        f"version = {version}\n"
        "enabled = true\n"
        "\n[forge_mod]\n"
        f"id = {slug}\n"
        f"name = {title}\n"
        "type = Modpack\n"
        f"version = {version}\n"
        "source = local\n"
        "enabled = true\n")
    contents={"modpack.ini":manifest.encode("utf-8")}
    extracted=len(contents["modpack.ini"])
    file_count=1
    for component in components:
        base=f'{component["directory"]}/{component["id"]}'
        for name,path in component["files"]:
            dest=base+"/"+name
            if len(dest)>240 or not single._safe_relative(dest):
                raise single.PackageError("Modpack path is too long: "+dest)
            if dest.casefold() in (k.casefold() for k in contents):
                raise single.PackageError("Duplicate ZIP path: "+dest)
            size=path.stat().st_size
            extracted+=size
            file_count+=1
            if file_count>single.MAX_ITEMS or extracted>single.MAX_EXPANDED:
                raise single.PackageError(
                    "Modpack exceeds allowed file count or extracted size")
            if component["category"]=="Character" and name.casefold()=="character.ini":
                # A Modpack must obey the same no-character-wheels contract
                # as a single new character package, preserving source files.
                contents[dest]=single.normalize_character_ini(path.read_bytes())
            else:
                contents[dest]=path
    temp_path=None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".forge_modpack_",suffix=".zip",dir=out.parent,delete=False
        ) as stream:
            temp_path=Path(stream.name)
        with zipfile.ZipFile(temp_path,"w",compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6,allowZip64=False) as package:
            for name,contents_path in contents.items():
                if isinstance(contents_path,bytes):
                    package.writestr(name,contents_path)
                else:
                    package.write(contents_path,name)
        if temp_path.stat().st_size>single.MAX_UPLOAD:
            raise single.PackageError(
                "Modpack ZIP exceeds Forge Hub's 50 MiB limit")
        with zipfile.ZipFile(temp_path,"r") as package:
            if package.testzip() is not None:
                raise single.PackageError("Modpack ZIP CRC verification failed")
            # Round-trip through the *existing* Launcher Modpack verifier,
            # not a new installer with different rules.
            with tempfile.TemporaryDirectory(
                prefix=".forge_modpack_verify_",dir=out.parent) as staged:
                package.extractall(staged)
                inspected=forge_modpacks.inspect_modpack(staged)
                if len(inspected["components"])!=len(components):
                    raise single.PackageError(
                        "Modpack verification lost one or more modules")
        if out.exists():
            raise single.PackageError("ZIP destination appeared during export")
        os.replace(temp_path,out)
        temp_path=None
        digest=hashlib.sha256()
        with out.open("rb") as f:
            for chunk in iter(lambda:f.read(262144),b""):
                digest.update(chunk)
        return {
            "path":str(out),"size":out.stat().st_size,"sha256":digest.hexdigest(),
            "file_count":file_count,"category":"Modpack",
            "component_count":len(components),"id":slug,
            "components":[{"type":c["category"],"name":c["name"],"id":c["id"]}
                          for c in components],
        }
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)