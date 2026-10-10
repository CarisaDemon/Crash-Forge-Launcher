"""Native track package builder for Crash Forge: Racing.

Only CTR's paired LEV (level/collision/checkpoints) and VRM (textures) are
accepted. An OBJ or MTL can never be installed as a track using this tool.

Packages are staged under assets/mods/tracks/<slug>; they do not replace retail
levels or activate an unfinished renderer. The game must explicitly support
loading such packages before they are playable.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import uuid

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
MAX_LEV = 128 * 1024 * 1024
MAX_VRM = 64 * 1024 * 1024


class NativeTrackError(ValueError):
    pass


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    if not SLUG_RE.fullmatch(slug):
        raise NativeTrackError("Use a track ID of 1-64 lowercase letters, numbers, - or _.")
    return slug


def safe_text(value: str, limit: int, *, required: bool = True) -> str:
    value = str(value).strip()
    if required and not value:
        raise NativeTrackError("Track name and ID cannot be empty.")
    if len(value) > limit or any(ch in value for ch in "\r\n\x00[]="):
        raise NativeTrackError("Name/description contains invalid characters or is too long.")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def inspect_native_track(lev_path, vrm_path):
    """Check paired native files; do not pretend this proves every CTR pointer."""
    lev = Path(lev_path).resolve()
    vrm = Path(vrm_path).resolve()
    if lev.suffix.lower() != ".lev" or vrm.suffix.lower() != ".vrm":
        raise NativeTrackError("Only .lev + .vrm are supported. OBJ is not a native CTR track.")
    if lev == vrm or not lev.is_file() or not vrm.is_file() or lev.is_symlink() or vrm.is_symlink():
        raise NativeTrackError("Choose two existing, different, regular .lev and .vrm files.")
    ls, vs = lev.stat().st_size, vrm.stat().st_size
    if not 4096 <= ls <= MAX_LEV:
        raise NativeTrackError("Invalid LEV length (4 KiB to 128 MiB).")
    if not 128 <= vs <= MAX_VRM:
        raise NativeTrackError("Invalid VRM length (128 B to 64 MiB).")
    with lev.open("rb") as fh:
        head = fh.read(16)
    pointer_map = struct.unpack_from("<i", head, 0)[0]
    if pointer_map < -1 or pointer_map >= ls - 12:
        raise NativeTrackError("LEV pointer-map offset is outside the file.")
    if head == b"\0" * 16:
        raise NativeTrackError("Empty LEV header.")
    with vrm.open("rb") as fh:
        first = fh.read(16)
    if first == b"\0" * 16:
        raise NativeTrackError("Empty VRM header.")
    # Retail VRM usually begins with 0x20 for multiple TIM records.
    # Some contain a single TIM header; do not incorrectly reject those.
    return {
        "lev": str(lev), "vrm": str(vrm),
        "lev_size": ls, "vrm_size": vs,
        "lev_sha256": _sha256(lev), "vrm_sha256": _sha256(vrm),
        "vram_header": "tim_collection" if first[:4] == b"\x20\0\0\0" else "single_tim_or_custom",
        "lev_pointer_map": pointer_map,
    }


def game_mods_directory(game_path) -> Path:
    game = Path(game_path).expanduser().resolve()
    exe = game if game.is_file() else None
    if exe is not None:
        if exe.suffix.lower() != ".exe":
            raise NativeTrackError("Game path must be the game folder or ctr-native.exe.")
        game = exe.parent
    if not (game / "ctr-native.exe").is_file() and not (game / "ctr_native.exe").is_file():
        raise NativeTrackError("Select the installed CFR game directory (ctr-native.exe).")
    return game / "assets" / "mods" / "tracks"


def install_native_track(lev_path, vrm_path, game_path, *,
                         track_name: str, track_slug: str,
                         description: str = "", author: str = "",
                         dry_run: bool = False):
    """Stage one isolated track package; back up any prior same-ID package."""
    slug = safe_text(track_slug, 64)
    if not SLUG_RE.fullmatch(slug):
        raise NativeTrackError("Track ID must be lowercase (letters/numbers/_/-).")
    name = safe_text(track_name, 96)
    description = safe_text(description, 220, required=False)
    author = safe_text(author, 90, required=False)
    pair = inspect_native_track(lev_path, vrm_path)
    mod_root = game_mods_directory(game_path)
    destination = mod_root / slug
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise NativeTrackError("Unsafe existing track destination.")
    metadata = (
        "[track]\n"
        f"name = {name}\n"
        f"slug = {slug}\n"
        "format = native_lev_vrm\n"
        "lev = data.lev\n"
        "vrm = data.vrm\n"
        "enabled = true\n"
        "install_status = staged\n"
        "replace_original = false\n"
        f"description = {description}\n"
        f"author = {author}\n"
        "\n[compatibility]\n"
        "game = Crash Forge: Racing\n"
        "native_format = LEV_VRM\n"
        "level_override = none\n"
        "\n[checksums]\n"
        f"lev_sha256 = {pair['lev_sha256']}\n"
        f"vrm_sha256 = {pair['vrm_sha256']}\n"
    )
    result = dict(pair, slug=slug, name=name, target=str(destination),
                  activation="staged; game native track registration required")
    if dry_run:
        return result
    mod_root.mkdir(parents=True, exist_ok=True)
    stage = mod_root / (".forge_stage_" + slug + "_" + uuid.uuid4().hex[:12])
    if stage.exists():
        raise NativeTrackError("Unexpected existing staging folder.")
    stage.mkdir()
    previous = None
    try:
        shutil.copy2(pair["lev"], stage / "data.lev")
        shutil.copy2(pair["vrm"], stage / "data.vrm")
        # Recheck the copy before any installed package is replaced.
        if _sha256(stage / "data.lev") != pair["lev_sha256"] or \
           _sha256(stage / "data.vrm") != pair["vrm_sha256"]:
            raise NativeTrackError("Copied track data did not match its source (SHA-256).")
        (stage / "track.ini").write_text(metadata, encoding="utf-8")
        if destination.exists():
            backup_dir = mod_root.parent.parent / "track_package_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            previous = backup_dir / (slug + "_" + stamp + "_" + uuid.uuid4().hex[:6])
            os.replace(destination, previous)
        try:
            os.replace(stage, destination)
        except Exception:
            if previous is not None and previous.exists():
                os.replace(previous, destination)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    result["backup"] = str(previous) if previous else ""
    return result
