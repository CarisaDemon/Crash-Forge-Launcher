"""Shared Forge Hub metadata and human-readable labels.

The user-facing three kart types intentionally reuse the existing database
kart_drive/wheel_setup pairs. All previously uploaded/published mods keep
the same stored data, download URLs and checksums.
These labels do not modify native game physics.
"""
MOD_TYPES = ("Character", "Kart", "Wheels", "Track", "Modpack", "Music")
MAP_KINDS = ("Race Track", "Battle Arena", "Hub")
RACER_CLASSES = ("Balanced", "Speed", "Acceleration", "Turning")
KART_DRIVES = ("Wheeled", "Hovercraft")  # Backward-compatible storage
WHEEL_SETUPS = ("Included", "Modular")    # Backward-compatible storage
KART_TYPES = (
    ("Modular Body", "Wheeled", "Modular"),
    ("Modular Kart / Wheeled", "Wheeled", "Included"),
    ("Hovercraft", "Hovercraft", None),
)
KART_TYPE_LABELS = tuple(row[0] for row in KART_TYPES)
FIELDS = ("map_kind", "racer_class", "kart_drive", "wheel_setup")


class ModMetadataError(ValueError):
    """A published/submitted mod has invalid category information."""


def kart_type_fields(label):
    """Convert the three distinct UI kart choices into stored metadata."""
    for name, drive, setup in KART_TYPES:
        if name == label:
            return {"kart_drive": drive, "wheel_setup": setup}
    raise ModMetadataError("Choose Modular Body, Modular Kart / Wheeled or Hovercraft.")


def kart_type_from_fields(details):
    """Display existing mod records without migrating or changing their ZIPs."""
    if not isinstance(details, dict):
        return None
    for name, drive, setup in KART_TYPES:
        if details.get("kart_drive") == drive and details.get("wheel_setup") == setup:
            return name
    return None


def normalize(category, data, strict=False):
    """Return clean stored category fields; strict requires relevant values."""
    if category not in MOD_TYPES:
        raise ModMetadataError("Unsupported mod type: " + str(category))
    data = data if isinstance(data, dict) else {}
    out = {field: None for field in FIELDS}

    if category == "Track":
        kind = data.get("map_kind")
        if kind in MAP_KINDS:
            out["map_kind"] = kind
        elif strict:
            raise ModMetadataError("Maps require Race Track, Battle Arena or Hub.")
    elif category == "Character":
        kind = data.get("racer_class")
        if kind in RACER_CLASSES:
            out["racer_class"] = kind
        elif strict:
            raise ModMetadataError("Characters require a stats class.")
    elif category == "Kart":
        drive = data.get("kart_drive")
        if drive in KART_DRIVES:
            out["kart_drive"] = drive
        elif strict:
            raise ModMetadataError("Choose Modular Body, Modular Kart / Wheeled or Hovercraft.")
        if drive == "Wheeled":
            wheels = data.get("wheel_setup")
            if wheels in WHEEL_SETUPS:
                out["wheel_setup"] = wheels
            elif strict:
                raise ModMetadataError("Choose Modular Body or Modular Kart / Wheeled.")
        # Hovercraft always keeps wheel_setup=None, including for legacy data.
    return out


def summary(mod):
    """Describe existing metadata using the new three-choice kart taxonomy."""
    if not isinstance(mod, dict):
        return ""
    category = mod.get("type")
    if category not in MOD_TYPES:
        return ""
    meta = normalize(category, mod)
    if category == "Track":
        return meta["map_kind"] or "Map type not specified"
    if category == "Character":
        kind = meta["racer_class"]
        return (kind + " Stats") if kind else "Stats class not specified"
    if category == "Kart":
        name = kart_type_from_fields(meta)
        return {
            "Modular Body": "Modular Body / Adaptable Wheels",
            "Modular Kart / Wheeled": "Modular Kart / Wheeled (Wheels Included)",
            "Hovercraft": "Hovercraft / No Wheels",
        }.get(name, "Kart type not specified")
    if category == "Modpack":
        return "Bundle / Multiple individual CFR mods"
    return "Music / Individual sound module" if category == "Music" else "Wheel Set / Separate Add-on"
