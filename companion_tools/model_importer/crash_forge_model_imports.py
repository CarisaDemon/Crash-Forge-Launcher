"""Kart and wheels OBJ mod builder for Crash Forge Racing."""
from pathlib import Path
from datetime import datetime
import re
import shutil
import tempfile
from crash_forge_kart_colors import install_colors, KartColorError

class ImportErrorMod(ValueError):
    pass

def import_mod(obj, game_root, kind, name, slug, scale, offsets, mounts=None,
               colors=None, replace=False):
    if kind not in ("kart", "wheels"):
        raise ImportErrorMod("Unknown model type")
    if not re.fullmatch(r"[a-z0-9_]{1,32}", slug):
        raise ImportErrorMod("Mod ID: 1-32 lowercase letters, numbers or underscore")
    if not name.strip() or any(c in name for c in "\r\n[]"):
        raise ImportErrorMod("Enter a valid display name")
    obj = Path(obj)
    root = Path(game_root)
    if not obj.is_file() or obj.suffix.lower() != ".obj":
        raise ImportErrorMod("Choose a Wavefront OBJ")
    if not (root / "assets").is_dir():
        raise ImportErrorMod("Choose a valid game folder")
    try:
        numbers = {key: float(val) for key, val in offsets.items()}
        numbers["scale"] = float(scale)
        attachments = {key: float(val) for key, val in (mounts or {}).items()}
    except ValueError as exc:
        raise ImportErrorMod("Scale, offsets and wheel mounts must be numbers") from exc
    if not 0 < numbers["scale"] < 1000000:
        raise ImportErrorMod("Scale must be greater than zero")
    dest_root = root / "mods"
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / slug
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        raise ImportErrorMod("Unsafe existing mod destination: " + str(dest))
    expected_ini = "kart.ini" if kind == "kart" else "wheels.ini"
    if dest.is_dir() and not (dest / expected_ini).is_file():
        raise ImportErrorMod("Mod ID is already assigned to another category: " + str(dest))
    if dest.exists() and not replace:
        raise ImportErrorMod("Mod already exists: " + str(dest))
    lines = obj.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    groups = set()
    nverts = nfaces = 0
    material_name = None
    for line in lines:
        s = line.strip()
        if s.startswith(("g ", "o ")):
            groups.update(x.lower() for x in s[2:].split())
        elif s.startswith("v "):
            nverts += 1
        elif s.startswith("f "):
            nfaces += max(0, len(s.split()) - 3)
        elif s.startswith("mtllib ") and not material_name:
            material_name = s[7:].strip().strip('"')
    if not nverts or not nfaces or nverts > 100000 or nfaces > 100000:
        raise ImportErrorMod("OBJ must have 1-100000 vertices and triangles")
    if kind == "wheels":
        missing = {"wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr"} - groups
        if missing:
            raise ImportErrorMod("Missing wheel groups in OBJ: " + ", ".join(sorted(missing)))
    mtl = None
    if material_name:
        mtl_name = Path(material_name.replace("\\", "/"))
        for p in (obj.parent / mtl_name, obj.parent / mtl_name.name):
            if p.is_file():
                mtl = p
                break
        if mtl is None:
            raise ImportErrorMod("MTL not found: " + material_name)
    temp = Path(tempfile.mkdtemp(prefix="._model_import_", dir=dest_root))
    backup = None
    try:
        out_obj = []
        changed = False
        for line in lines:
            if line.lstrip().startswith("mtllib ") and not changed:
                out_obj.append("mtllib " + slug + ".mtl")
                changed = True
            else:
                out_obj.append(line)
        (temp / (slug + ".obj")).write_text("\n".join(out_obj) + "\n", encoding="utf-8")
        if mtl:
            texture_names = {}
            mtl_lines = []
            for line in mtl.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                s = line.strip()
                if not s.startswith("map_Kd "):
                    mtl_lines.append(line)
                    continue
                texture_name = s[7:].strip().strip('"')
                texture_path = Path(texture_name.replace("\\", "/"))
                texture = next((p for p in (mtl.parent / texture_path,
                                             mtl.parent / texture_path.name) if p.is_file()), None)
                if texture is None:
                    raise ImportErrorMod("Missing texture: " + texture_name)
                if texture.name.lower() in texture_names and texture != texture_names[texture.name.lower()]:
                    raise ImportErrorMod("Duplicate texture filename: " + texture.name)
                texture_names[texture.name.lower()] = texture
                shutil.copy2(texture, temp / texture.name)
                mtl_lines.append("map_Kd " + texture.name)
            (temp / (slug + ".mtl")).write_text("\n".join(mtl_lines) + "\n", encoding="utf-8")
        ini = ["[" + ("kart" if kind == "kart" else "wheel") + "]",
               "name = " + name.strip(), "enabled = true", "",
               "[model]", "asset_name = " + slug,
               "scale = " + str(numbers["scale"])]
        for axis in "xyz":
            ini.append("offset_" + axis + " = " + str(numbers[axis]))
        if kind == "kart":
            ini.extend(["", "[attachments]"])
            for key in ("seat_x", "seat_y", "seat_z"):
                ini.append(key + " = " + str(attachments.get(key, 0.0)))
            for wheel in ("fl", "fr", "rl", "rr"):
                for axis in "xyz":
                    key = "wheel_" + wheel + "_" + axis
                    ini.append(key + " = " + str(attachments.get(key, 0.0)))
        ini.extend(["", "[forge_mod]", "id = " + slug,
                    "type = " + ("Kart" if kind == "kart" else "Wheels"),
                    "source = local", "version = 1.0", "enabled = true"])
        (temp / ("kart.ini" if kind == "kart" else "wheels.ini")).write_text(
            "\n".join(ini) + "\n", encoding="utf-8")
        if colors:
            if kind != "kart":
                raise ImportErrorMod("Only karts can have additional colors")
            try:
                install_colors(temp, colors, dry_run=True)
                install_colors(temp, colors)
                for p in temp.glob("kart.ini.before_colors_*.bak"):
                    p.unlink()
            except KartColorError as exc:
                raise ImportErrorMod("Kart colors: " + str(exc)) from exc
        if dest.exists():
            backup_root = root / ".forge_mod_backups" / "model_import"
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / (kind + "_" + slug + "_" +
                                    datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
            shutil.copytree(dest, backup)
            shutil.rmtree(dest)
        try:
            temp.rename(dest)
        except OSError:
            if backup and not dest.exists():
                shutil.copytree(backup, dest)
            raise
        return {"folder": str(dest), "backup": str(backup) if backup else None}
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
