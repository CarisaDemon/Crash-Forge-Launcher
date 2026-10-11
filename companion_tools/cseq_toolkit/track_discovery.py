"""Dynamic discovery and CSEQ assignment for native Crash Forge custom tracks.

Nothing is hardcoded: every newly installed Track module is read from the game's
own game-root mods directory (plus legacy assets/mods/tracks). A custom track's audio belongs INSIDE that track module.
"""
from __future__ import annotations

import configparser
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import tempfile

_SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$", re.I)
_SIMPLE_LEAF = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,90}$", re.I)


@dataclass(frozen=True)
class CustomTrack:
    slug: str
    name: str
    directory: Path
    ini: Path

    @property
    def target_label(self) -> str:
        return f"CUSTOM | {self.name} [{self.slug}]"


def valid_game_root(path: str | Path | None) -> Path | None:
    if not path:
        return None
    try:
        root = Path(path).expanduser().resolve(strict=True)
        if root.is_dir() and any((root / exe).is_file() for exe in
                                  ("ctr-native.exe", "ctr_native.exe")):
            return root
    except (ValueError, OSError):
        pass
    return None


def read_ini(path: Path) -> configparser.ConfigParser | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
            return None
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(path, encoding="utf-8-sig")
        return parser
    except (OSError, UnicodeError, configparser.Error):
        return None


def discover_custom_tracks(game_root: str | Path | None) -> list[CustomTrack]:
    root = valid_game_root(game_root)
    if not root:
        return []
    mods = root / "mods"
    candidates = [mods, root / "assets" / "mods" / "tracks"]
    found: dict[str, CustomTrack] = {}
    for directory in candidates:
        if directory.is_symlink() or not directory.is_dir():
            continue
        for mod in directory.iterdir():
            if mod.is_symlink() or not mod.is_dir() or not _SAFE_SLUG.fullmatch(mod.name):
                continue
            ini = mod / "track.ini"
            conf = read_ini(ini)
            if conf is None or not conf.has_section("track"):
                continue
            tr = conf["track"]
            if tr.get("enabled", "").strip().lower() not in {"true", "1", "yes"}:
                continue
            if tr.get("format", "").strip().lower() != "native_lev_vrm":
                continue
            if conf.has_section("forge_mod"):
                meta = conf["forge_mod"]
                web_id = meta.get("id", "").strip()
                if (not _SAFE_SLUG.fullmatch(web_id) or
                    meta.get("type", "").strip().lower() != "track"):
                    continue
            lev = tr.get("lev", "data.lev").strip()
            vrm = tr.get("vrm", "data.vrm").strip()
            if (not _SIMPLE_LEAF.fullmatch(lev) or not lev.lower().endswith(".lev") or
                not _SIMPLE_LEAF.fullmatch(vrm) or not vrm.lower().endswith(".vrm")):
                continue
            if not (mod / lev).is_file() or not (mod / vrm).is_file():
                continue
            display_name = tr.get("name", mod.name).strip()[:80] or mod.name
            found.setdefault(mod.name.lower(), CustomTrack(
                slug=mod.name, name=display_name, directory=mod, ini=ini))
    return sorted(found.values(), key=lambda x: (x.name.casefold(), x.slug.casefold()))


def _upsert_music_section(original: str, values: dict[str, str]) -> str:
    rows = original.replace("\r\n", "\n").splitlines()
    header = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    keys = {key.lower() for key in values}
    out = []
    inside_music = False
    inserted = False
    for line in rows:
        m = header.match(line)
        if m:
            if inside_music and not inserted:
                out.extend(f"{key} = {val}" for key, val in values.items())
                inserted = True
            inside_music = m.group(1).strip().lower() == "music"
            out.append(line)
            continue
        if inside_music:
            parts = line.split("=", 1)
            if len(parts) == 2 and parts[0].strip().lower() in keys:
                continue
        out.append(line)
    if inside_music and not inserted:
        out.extend(f"{key} = {val}" for key, val in values.items())
        inserted = True
    if not inserted:
        out.extend(["", "[music]"] + [f"{key} = {val}" for key, val in values.items()])
    return "\n".join(out).rstrip() + "\n"


def install_cseq_on_custom_track(
    track: CustomTrack, cseq: bytes, sample_paths: list[Path] | None = None,
) -> Path:
    """Write CSEQ and optional sample WAV files without touching retail songs."""
    from cseq_format import parse_pack
    parse_pack(cseq)
    conf = read_ini(track.ini)
    if conf is None or not conf.has_section("track") or \
       conf["track"].get("enabled", "").lower() not in {"true", "1", "yes"}:
        raise ValueError("Custom track is no longer enabled or readable")
    samples = [Path(s) for s in sample_paths or []]
    if len(samples) > 256 or any(not x.is_file() for x in samples):
        raise ValueError("Invalid or missing custom CSEQ sample")
    values = {
        "enabled": "true", "source": "cseq", "file": "track.cseq",
        "custom_samples": str(len(samples))
    }
    updated_ini = _upsert_music_section(track.ini.read_text(encoding="utf-8-sig"), values)
    with tempfile.TemporaryDirectory(prefix=".forge_cseq_", dir=track.directory) as temp:
        staging = Path(temp)
        staged_cseq = staging / "track.cseq"
        staged_cseq.write_bytes(cseq)
        for i, original in enumerate(samples):
            shutil.copy2(original, staging / f"sample_{i:03d}.wav")
        staged_ini = staging / "track.ini"
        staged_ini.write_text(updated_ini, encoding="utf-8")
        # Only approved, mod-local paths are overwritten.
        target_samples = track.directory / "samples"
        if samples:
            target_samples.mkdir(parents=True, exist_ok=True)
            for i in range(len(samples)):
                os.replace(staging / f"sample_{i:03d}.wav", target_samples / f"sample_{i:03d}.wav")
        os.replace(staged_cseq, track.directory / "track.cseq")
        os.replace(staged_ini, track.ini)
    return track.directory / "track.cseq"
