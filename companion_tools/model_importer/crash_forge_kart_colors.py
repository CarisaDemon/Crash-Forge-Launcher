"""Crash Forge: Racing - native kart palette support.

One OBJ, one MTL, one kart.ini. Only differently colored atlases are copied;
the source image matching the default MTL texture stays untouched.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import re
import shutil
import struct
import tempfile

PALETTE = ("blue", "red", "lime", "pink", "blank", "green", "yellow",
           "orange", "purple", "black", "white", "silver", "gold")
ASSET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
IMAGE_TYPES = (".png", ".bmp")


class KartColorError(ValueError):
    pass


def image_dimensions(path):
    with open(path, "rb") as f:
        h = f.read(26)
    if h[:8] == b"\x89PNG\r\n\x1a\n" and len(h) >= 24:
        return struct.unpack(">II", h[16:24])
    if h[:2] == b"BM" and len(h) >= 26:
        return struct.unpack("<I", h[18:22])[0], abs(struct.unpack("<i", h[22:26])[0])
    raise KartColorError("Only PNG and BMP textures are supported: " + str(path))


def sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_palette(folder):
    """Find a recognizable color name at the start of each image name."""
    directory = Path(folder)
    if not directory.is_dir():
        raise KartColorError("Select a valid folder containing colored PNG/BMP textures.")
    detected = {}
    for file in sorted(directory.iterdir(), key=lambda x: x.name.lower()):
        if not file.is_file() or file.suffix.lower() not in IMAGE_TYPES:
            continue
        normalized = re.sub(r"[^a-z]+", " ", file.stem.lower()).split()
        if not normalized:
            continue
        name = normalized[0]
        if name in PALETTE and name not in detected:
            detected[name] = file
    if not detected:
        raise KartColorError("No colored textures found. Prefix filenames with Blue_, Red_, etc.")
    dimensions = {c: image_dimensions(p) for c, p in detected.items()}
    if len(set(dimensions.values())) != 1:
        raise KartColorError("Color textures must all have the same size/UV layout.")
    return detected


def read_kart_texture(kart_folder):
    folder = Path(kart_folder)
    cfg = folder / "kart.ini"
    if not cfg.is_file():
        raise KartColorError("Selected folder has no kart.ini.")
    models = list(folder.glob("*.obj"))
    if len(models) != 1:
        raise KartColorError("Kart folder must contain exactly one OBJ.")
    obj = models[0]
    mtllib = None
    with obj.open("r", encoding="utf-8-sig", errors="replace") as source:
        for line in source:
            if line.lstrip().startswith("mtllib "):
                mtllib = line.strip()[7:].strip().strip('"')
                break
    if not mtllib or "/" in mtllib or "\\" in mtllib:
        raise KartColorError("OBJ needs a local mtllib entry.")
    mtl = folder / mtllib
    if not mtl.is_file():
        raise KartColorError("Missing material file: " + mtllib)
    textures = []
    with mtl.open("r", encoding="utf-8-sig", errors="replace") as source:
        for line in source:
            if line.lstrip().startswith("map_Kd "):
                textures.append(line.strip()[7:].strip().strip('"'))
    if len(textures) != 1:
        raise KartColorError("Color switching currently needs one mapped texture in the MTL.")
    filename = textures[0]
    if not filename or "/" in filename or "\\" in filename or Path(filename).suffix.lower() not in IMAGE_TYPES:
        raise KartColorError("MTL's map_Kd must name a local PNG/BMP image.")
    return folder / filename


def update_color_ini(text, pairs):
    """Preserve existing [kart], [model], [attachments], all comments and settings."""
    if not text.strip():
        raise KartColorError("Empty kart.ini")
    pattern = re.compile(r"(?ims)^\s*\[colors\][^\r\n]*\r?\n.*?(?=^\s*\[[^\]\r\n]+\]|\\Z)")
    # Use a precise line-oriented pattern instead of a generic INI rewriter.
    m = re.search(r"(?im)^\s*\[colors\]\s*$", text)
    if m:
        trailing = re.search(r"(?m)^\s*\[[^\]\r\n]+\]\s*$", text[m.end():])
        end = m.end() + trailing.start() if trailing else len(text)
        text = text[:m.start()] + text[end:]
    lines = ["[colors]"]
    for name in PALETTE:
        if name in pairs:
            lines.append(name + " = " + pairs[name])
    return text.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def install_colors(kart_folder, palette_folder, *, dry_run=False):
    """Add color variants to a native kart mod without touching its OBJ/MTL."""
    folder = Path(kart_folder)
    ini = folder / "kart.ini"
    base = read_kart_texture(folder)
    discovered = find_palette(palette_folder)
    # Blue already matches CTRCinematicKart.png, so never duplicate it.
    blue = discovered.get("blue")
    if not base.is_file() and blue is None:
        raise KartColorError("Default MTL texture missing; provide a Blue_ texture.")
    expected = image_dimensions(base if base.is_file() else blue)
    plan = {}
    if base.is_file():
        base_hash = sha(base)
    else:
        base_hash = sha(blue)
        plan[base.name] = blue

    selected = {"blue": base.name}
    for name in PALETTE:
        if name == "blue" or name not in discovered:
            continue
        original = discovered[name]
        if image_dimensions(original) != expected:
            raise KartColorError(name + " has different dimensions from the kart's default texture.")
        if sha(original) == base_hash:
            continue  # A texture identical to the default is not a new option.
        dest_name = "color_" + name + original.suffix.lower()
        dest = folder / dest_name
        if dest.is_file() and sha(dest) != sha(original):
            raise KartColorError("Existing variant differs, refusing overwrite: " + dest_name)
        selected[name] = dest_name
        if not dest.exists():
            plan[dest_name] = original
    if len(selected) < 2:
        raise KartColorError("No additional colors differ from the default texture.")
    updated = update_color_ini(ini.read_text(encoding="utf-8-sig"), selected)
    result = {"kart": str(folder), "variants": selected,
              "new_textures": list(plan), "skipped_duplicate_blue": blue is not None and sha(blue) == base_hash}
    if dry_run:
        return result
    original_ini = ini.read_bytes()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ini.with_name("kart.ini.before_colors_" + timestamp + ".bak")
    if backup.exists():
        backup = ini.with_name("kart.ini.before_colors_" + timestamp + "_2.bak")
    created = []
    try:
        for name, source in plan.items():
            target = folder / name
            if target.exists():
                raise KartColorError("File already exists: " + name)
            shutil.copy2(source, target)
            created.append(target)
        shutil.copy2(ini, backup)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder,
                                         prefix=".kart-colors-", suffix=".tmp",
                                         delete=False) as f:
            tmp = Path(f.name)
            f.write(updated)
        try:
            tmp.replace(ini)
        finally:
            tmp.unlink(missing_ok=True)
    except Exception:
        for p in created:
            p.unlink(missing_ok=True)
        if backup.is_file():
            shutil.copy2(backup, ini)
        else:
            ini.write_bytes(original_ini)
        raise
    result["backup"] = str(backup)
    return result
