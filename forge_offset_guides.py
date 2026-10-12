"""Build non-destructive live guides for CTR modular attachment offsets.

The model viewport uses OBJ coordinates; attachments are native CTR model
units. The conversion matches platform/native_obj.c: normalize to 1016 per
axis, multiply by the 1000*extent model header and divide by 4096 (fixed
model scale). This is ~248.05 units per OBJ unit, not the legacy guessed 100.
INI settings and the source meshes are never changed.
"""
from __future__ import annotations

import configparser
import math
from pathlib import Path

EXHAUST_LIMIT = 4
DEFAULT_MOUNT_UNITS_PER_OBJ = (1016.0 * 1000.0) / 4096.0
WHEEL_CODES = ("fl", "fr", "rl", "rr")
COLORS = {
    "Model": (255, 165, 73),
    "Seat": (83, 221, 205),
    "Wheels": (102, 170, 255),
    "Exhaust": (255, 106, 96),
}


def _number(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _coords(source, prefix):
    if source is None:
        return None
    values = tuple(_number(source.get(prefix + axis)) for axis in "xyz")
    return values if all(value is not None for value in values) else None


def build_offset_markers(category, model_offsets, model_scale, mounts=None,
                         exhaust_count="Default", units_per_obj=DEFAULT_MOUNT_UNITS_PER_OBJ,
                         group="All"):
    """Return valid local-space viewport anchors; never infer real game physics."""
    if category not in ("Character", "Kart", "Wheels"):
        return []
    offset = _coords(model_offsets or {}, "")
    scale = _number(model_scale)
    divisor = _number(units_per_obj)
    if offset is None or scale is None or scale <= 0 or divisor is None or divisor <= 0:
        return []
    mounts = mounts or {}
    requested = str(group or "All").casefold()
    markers = []

    def add(kind, name, coordinates, rotation=None):
        if requested not in ("all", kind.casefold()):
            return
        if coordinates is None:
            return
        if kind == "Model":
            # A static OBJ viewport: show the native kart origin after
            # undoing the user-defined model translation.
            position = tuple(-axis for axis in offset)
        else:
            # Game applies: world ~= (OBJ + offset) * scale * 248.05.
            # Invert this for a marker drawn over the unchanged OBJ mesh.
            position = tuple(axis / (divisor * scale) - offset[i]
                             for i, axis in enumerate(coordinates))
        marker = {"name": name, "kind": kind, "position": position,
                  "values": coordinates, "color": COLORS[kind]}
        if kind == "Exhaust":
            # VehTurbo_ApplyCustomExhaustTransform divides custom native
            # attachment position by 16384, versus VehEmitter's /4096.
            # Thus the original 3D turbo mesh's INSTANCE origin is 1/4
            # the smoke mount, while marker position stays the true mount.
            # Both share the unchanged OBJ model offset.
            marker["effect_position"] = tuple(
                coordinates[i] / (divisor * scale * 4.0) - offset[i]
                for i in range(3))
            marker["native_units_per_obj"] = divisor
            marker["native_model_scale"] = scale
        if rotation is not None:
            marker["rotation"] = rotation
        markers.append(marker)

    add("Model", "MODEL ORIGIN", offset)
    if category != "Kart":
        return markers

    add("Seat", "SEAT", _coords(mounts, "seat_"))
    for wheel in WHEEL_CODES:
        add("Wheels", "W-" + wheel.upper(), _coords(mounts, "wheel_" + wheel + "_"))
    try:
        count = int(exhaust_count)
    except (TypeError, ValueError, OverflowError):
        count = 0
    count = max(0, min(EXHAUST_LIMIT, count))
    for n in range(count):
        pos = _coords(mounts, f"exhaust_{n}_")
        rot = tuple(_number(mounts.get(f"exhaust_{n}_rotation_{axis}")) for axis in "xyz")
        add("Exhaust", f"EX-{n + 1}", pos,
            rotation=rot if all(x is not None for x in rot) else None)
    return markers


def read_kart_offset_values(path):
    """Import current native kart.ini fields into the preview editor, read-only."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        parser.read_file(handle)
    model = {axis: parser.get("model", "offset_" + axis, fallback="0.0")
             for axis in "xyz"}
    scale = parser.get("model", "scale", fallback="1.0")
    mounts = {}
    for axis in "xyz":
        mounts["seat_" + axis] = parser.get(
            "attachments", "seat_" + axis,
            fallback=parser.get("seat", axis, fallback="0.0"))
    for wheel in WHEEL_CODES:
        for axis in "xyz":
            key = f"wheel_{wheel}_{axis}"
            mounts[key] = parser.get("attachments", key, fallback="0.0")
    for i in range(EXHAUST_LIMIT):
        for axis in "xyz":
            for middle in ("", "rotation_"):
                key = f"exhaust_{i}_{middle}{axis}"
                mounts[key] = parser.get(
                    "attachments", key,
                    fallback=parser.get("exhaust", key, fallback="0.0"))
    count = parser.get(
        "attachments", "exhaust_count",
        fallback=parser.get("exhaust", "count",
                            fallback=parser.get("exhaust", "exhaust_count", fallback="Default")))
    if count == "Default":
        # The game infers a count from the highest configured exhaust index.
        for i in reversed(range(EXHAUST_LIMIT)):
            keys = [f"exhaust_{i}_{axis}" for axis in "xyz"] + [
                f"exhaust_{i}_rotation_{axis}" for axis in "xyz"]
            if any(parser.has_option(section, key)
                   for section in ("attachments", "exhaust") for key in keys):
                count = str(i + 1)
                break
    return {"model": model, "scale": scale, "mounts": mounts, "exhaust_count": count}