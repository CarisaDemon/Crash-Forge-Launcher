"""Native kart texture variants. One OBJ, one MTL, custom-named skin atlases.

The game reads [colors] entries in order, using each key as the on-screen
display name (up to 23 UTF-8 bytes), not a pre-defined color vocabulary.
The first entry is always the untouched default material texture.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import re
import shutil
import struct
import tempfile
import unicodedata

# Legacy order is retained for old mods; names outside this list are valid.
PALETTE = ("blue", "red", "lime", "pink", "blank", "green", "yellow",
           "orange", "purple", "black", "white", "silver", "gold")
IMAGE_TYPES = (".png", ".bmp")
MAX_VARIANTS = 12  # VEHICLE_PART_MAX_COLORS, including the original.
MAX_DISPLAY_BYTES = 23  # VehiclePartDef.colorNames[][24] including NUL.
ASSET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class KartColorError(ValueError):
    pass


def image_dimensions(path):
    with open(path, "rb") as fh:
        header = fh.read(26)
    if header[:8] == b"\x89PNG\r\n\x1a\n" and len(header) >= 24:
        return struct.unpack(">II", header[16:24])
    if header[:2] == b"BM" and len(header) >= 26:
        return struct.unpack("<I", header[18:22])[0], abs(struct.unpack("<i", header[22:26])[0])
    raise KartColorError("Supported color textures: PNG or BMP only (" + str(path) + ").")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _slug(text):
    ascii_name = unicodedata.normalize("NFKD", str(text))
    ascii_name = ascii_name.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_")[:46] or "variant"


def validate_display_name(value):
    title = str(value).strip()
    if (not title or len(title.encode("utf-8")) > MAX_DISPLAY_BYTES
            or any(ch in title for ch in "\r\n=[];#")
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in title)):
        raise KartColorError(
            "Color names must be 1-23 UTF-8 bytes and cannot contain = [ ] ; # or line breaks.")
    return title


def suggest_name(filename):
    stem = Path(filename).stem
    words = re.split(r"[_\-\s]+", stem)
    while len(words) > 1 and words[-1].lower() in (
            "texture", "textures", "atlas", "skin", "skins", "kart", "karts", "diffuse"):
        words.pop()
    suggested = " ".join(words).strip() or stem
    # The fixed colors are still good suggestions for old mods, but are NOT required.
    legacy = suggested.lower()
    if legacy in PALETTE:
        return legacy
    while len(suggested.encode("utf-8")) > MAX_DISPLAY_BYTES:
        suggested = suggested[:-1]
    return validate_display_name(suggested.strip() or "Variant")


def scan_palette(folder):
    """List every PNG/BMP texture, original filename and editable suggested name."""
    path = Path(folder)
    if not path.is_dir() or path.is_symlink():
        raise KartColorError("Select a folder containing the kart skin textures (PNG/BMP).")
    items = []
    for file in sorted(path.iterdir(), key=lambda p: p.name.casefold()):
        if not file.is_file() or file.is_symlink() or file.suffix.lower() not in IMAGE_TYPES:
            continue
        try:
            dimensions = image_dimensions(file)
            if dimensions[0] < 1 or dimensions[1] < 1:
                raise KartColorError("Invalid image dimensions: " + file.name)
        except (OSError, ValueError, struct.error) as exc:
            raise KartColorError("Invalid color texture " + file.name + ": " + str(exc)) from exc
        items.append({"file": file, "filename": file.name,
                      "suggested_name": suggest_name(file.name),
                      "dimensions": dimensions})
    if not items:
        raise KartColorError("No PNG/BMP textures found. Names can be anything.")
    return items


def find_palette(folder):
    """Compatibility helper; accepts arbitrary texture names, not just PALETTE."""
    found = {}
    for item in scan_palette(folder):
        key = _slug(item["suggested_name"])
        original = key
        suffix = 2
        while key in found:
            key = f"{original}_{suffix}"
            suffix += 1
        found[key] = item["file"]
    dimensions = {image_dimensions(p) for p in found.values()}
    if len(dimensions) != 1:
        raise KartColorError("Color textures must share the kart atlas dimensions.")
    return found


def read_kart_texture(kart_folder):
    folder = Path(kart_folder)
    if not (folder / "kart.ini").is_file():
        raise KartColorError("Kart folder has no kart.ini.")
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
        raise KartColorError("OBJ must reference its local MTL file.")
    mtl = folder / mtllib
    if not mtl.is_file():
        raise KartColorError("Missing kart MTL: " + mtllib)
    textures = []
    with mtl.open("r", encoding="utf-8-sig", errors="replace") as source:
        for line in source:
            if line.lstrip().startswith("map_Kd "):
                textures.append(line.strip()[7:].strip().strip('"'))
    if len(textures) != 1:
        raise KartColorError("Kart skin switching currently requires a single mapped texture atlas.")
    name = textures[0]
    if not name or "/" in name or "\\" in name or Path(name).suffix.lower() not in IMAGE_TYPES:
        raise KartColorError("MTL's map_Kd must reference one local PNG/BMP atlas.")
    return folder / name


def update_color_ini(text, named_textures):
    """Replace only [colors], preserving all native settings and other sections."""
    if not text.strip():
        raise KartColorError("Empty kart.ini.")
    match = re.search(r"(?im)^[ \t]*\[colors\][ \t]*$", text)
    if match:
        following = re.search(r"(?m)^[ \t]*\[[^\]\r\n]+\][ \t]*$",
                              text[match.end():])
        end = match.end() + following.start() if following else len(text)
        text = text[:match.start()] + text[end:]
    lines = ["[colors]"] + [name + " = " + filename
                           for name, filename in named_textures.items()]
    return text.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def _existing_default_name(ini, base_file):
    text = ini.read_text(encoding="utf-8-sig")
    match = re.search(r"(?im)^[ \t]*\[colors\][ \t]*$", text)
    if match:
        for line in text[match.end():].splitlines():
            if line.strip().startswith("["):
                break
            if "=" in line:
                label, filename = line.split("=", 1)
                if filename.strip().casefold() == base_file.casefold():
                    try:
                        return validate_display_name(label)
                    except KartColorError:
                        pass
                break
    return None


def install_colors(kart_folder, palette_folder, *, dry_run=False,
                   variants=None, default_name=None):
    """Copy chosen textures, saving arbitrary in-game names in kart.ini.

    variants: optional {source_filename: user_display_name}. When omitted,
    include all discovered compatible images, preserving old palette support.
    """
    folder = Path(kart_folder)
    ini = folder / "kart.ini"
    base = read_kart_texture(folder)
    scanned = scan_palette(palette_folder)
    by_file = {item["filename"].casefold(): item for item in scanned}
    if variants is not None:
        if not isinstance(variants, dict):
            raise KartColorError("Selected color variants must map filenames to display names.")
        chosen = []
        for name, title in variants.items():
            entry = by_file.get(str(name).casefold())
            if entry is None:
                raise KartColorError("Selected texture not found: " + str(name))
            chosen.append((entry, validate_display_name(title)))
    else:
        # Old palettes keep their familiar ordering. Unrecognized skins follow
        # alphabetically; there is no fixed color vocabulary.
        chosen = [(item, item["suggested_name"]) for item in sorted(
            scanned, key=lambda row: (
                PALETTE.index(row["suggested_name"]) if row["suggested_name"] in PALETTE
                else len(PALETTE), row["filename"].casefold()))]
    if not chosen:
        raise KartColorError("Select at least one extra texture to add.")
    available_default = None
    if base.is_file():
        expected = image_dimensions(base)
        base_hash = sha(base)
    else:
        fallback = next((item for item in scanned
                         if item["suggested_name"].casefold() == "blue"), scanned[0])
        available_default = fallback["file"]
        expected = fallback["dimensions"]
        base_hash = sha(available_default)
    if default_name is None:
        default_name = _existing_default_name(ini, base.name)
        if default_name is None:
            same = next((item for item in scanned if sha(item["file"]) == base_hash), None)
            default_name = same["suggested_name"] if same else "Original"
    default_name = validate_display_name(default_name)
    result = {default_name: base.name}
    used_names = {default_name.casefold()}
    used_files = {base.name.casefold()}
    used_hashes = {base_hash}
    plan = {}
    if available_default is not None:
        plan[base.name] = available_default
    for item, title in chosen:
        path = item["file"]
        if item["dimensions"] != expected:
            raise KartColorError(
                item["filename"] + " has different dimensions from the original kart atlas "
                + str(expected[0]) + "x" + str(expected[1]) + ".")
        digest = sha(path)
        if digest in used_hashes:
            continue
        used_hashes.add(digest)
        if title.casefold() in used_names:
            raise KartColorError("Duplicate name in game: " + title)
        used_names.add(title.casefold())
        if len(result) >= MAX_VARIANTS:
            raise KartColorError("At most 12 kart variants including the original.")
        slug = _slug(item["suggested_name"])
        # Preserve legacy color_red.png; arbitrary patterns also work.
        dest_name = "color_" + slug + path.suffix.lower()
        if dest_name.casefold() in used_files:
            raise KartColorError("Two skins have the same output filename: " + dest_name)
        used_files.add(dest_name.casefold())
        dest = folder / dest_name
        if dest.is_file() and sha(dest) != digest:
            raise KartColorError("Existing texture differs; not overwriting " + dest_name)
        result[title] = dest_name
        if not dest.is_file():
            plan[dest_name] = path
    if len(result) < 2:
        raise KartColorError("No additional textures differ from the default kart atlas.")
    updated = update_color_ini(ini.read_text(encoding="utf-8-sig"), result)
    response = {"kart": str(folder), "variants": result,
                "new_textures": list(plan),
                "skipped_duplicate_blue": any(
                    item["suggested_name"].lower() == "blue"
                    and sha(item["file"]) == base_hash for item in scanned)}
    if dry_run:
        return response
    original_ini = ini.read_bytes()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = ini.with_name("kart.ini.before_colors_" + timestamp + ".bak")
    created = []
    try:
        for name, source in plan.items():
            dest = folder / name
            if dest.exists():
                raise KartColorError("File already exists: " + name)
            shutil.copy2(source, dest)
            created.append(dest)
        shutil.copy2(ini, backup)
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=folder, prefix=".kart-colors-",
                suffix=".tmp", delete=False) as handle:
            tmp = Path(handle.name)
            handle.write(updated)
        try:
            tmp.replace(ini)
        finally:
            tmp.unlink(missing_ok=True)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        if backup.is_file():
            shutil.copy2(backup, ini)
        else:
            ini.write_bytes(original_ini)
        raise
    response["backup"] = str(backup)
    return response
