"""Load and safely update a native model's nearby character/kart/wheels INI.

Only a matching INI in the same folder as an explicitly selected OBJ may be
edited. Saves are opt-in, preserve all unrelated sections/comments/Forge Hub IDs,
create a timestamped .bak, and refuse concurrent external modifications.
No new INI is silently created when a model lacks a linked config.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import configparser
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

KINDS = {"character": "character.ini", "kart": "kart.ini", "wheels": "wheels.ini"}
MODEL_KEYS = ("scale", "offset_x", "offset_y", "offset_z")
MOUNT_KEYS = (
    *("seat_" + axis for axis in "xyz"),
    *(f"wheel_{w}_{a}" for w in ("fl", "fr", "rl", "rr") for a in "xyz"),
    *(f"exhaust_{i}_{middle}{axis}"
      for i in range(4) for middle in ("", "rotation_") for axis in "xyz"),
)
TEXT_FIELDS = {"name", "asset_name", "fallback_retail", "engine", "kart", "icon"}
_NUMBER_FIELDS = set(MODEL_KEYS + MOUNT_KEYS)
_HEADER_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:[;#].*)?$")
_KV_RE = re.compile(r"^(\s*)([\w.-]+)(\s*=\s*)(.*)$")


class LinkedIniError(ValueError):
    pass


class LinkedIniConflict(LinkedIniError):
    pass


@dataclass(frozen=True)
class LinkedIni:
    path: Path
    kind: str
    fields: dict[str, str]
    digest: str


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_linked_ini(obj_path: str | Path, preferred: str) -> tuple[str, Path] | None:
    """Case-insensitive sibling matching; favor current editor when ambiguous."""
    obj = Path(obj_path)
    if not obj.is_file() or obj.suffix.lower() != ".obj":
        return None
    found = {}
    for candidate in obj.parent.iterdir():
        if not candidate.is_file() or candidate.is_symlink():
            continue
        for kind, file_name in KINDS.items():
            if candidate.name.casefold() == file_name.casefold():
                found[kind] = candidate
    if preferred in found:
        return preferred, found[preferred]
    if len(found) == 1:
        return next(iter(found.items()))
    # Two or more unrelated config types: never guess which file to edit.
    return None


def read_linked_ini(kind: str, path: str | Path) -> LinkedIni:
    if kind not in KINDS:
        raise LinkedIniError("Unsupported model category")
    path = Path(path).resolve()
    if path.name.casefold() != KINDS[kind]:
        raise LinkedIniError("The INI does not match this model category")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(text)
    except (UnicodeError, configparser.Error) as exc:
        raise LinkedIniError(f"Cannot read {path.name}: {exc}") from exc

    def item(section, name, default=""):
        return parser.get(section, name, fallback=default)

    fields = {
        "name": item("character" if kind == "character" else
                     "kart" if kind == "kart" else "wheel", "name"),
        "scale": item("model", "scale", "1.0"),
        **{"offset_" + a: item("model", "offset_" + a, "0.0") for a in "xyz"},
    }
    if kind == "character":
        fields.update({
            "asset_name": item("assets", "asset_name", path.parent.name),
            "fallback_retail": item("character", "fallback_retail", "coco"),
            "engine": item("character", "engine", "accel"),
            "kart": item("character", "kart"),
            "modular_body": item("character", "modular_body", "true"),
            "icon": item("assets", "icon", "retail:coco"),
        })
    else:
        fields["asset_name"] = item("model", "asset_name", path.parent.name)
        if kind == "kart":
            for key in MOUNT_KEYS:
                if key.startswith("seat_"):
                    fields[key] = item("attachments", key,
                                       item("seat", key[5:], "0.0"))
                elif key.startswith("exhaust_"):
                    fields[key] = item("attachments", key,
                                       item("exhaust", key, "0.0"))
                else:
                    fields[key] = item("attachments", key, "0.0")
            count = item("attachments", "exhaust_count",
                         item("exhaust", "count",
                              item("exhaust", "exhaust_count", "Default")))
            if count == "Default":
                for i in reversed(range(4)):
                    keys = [f"exhaust_{i}_{middle}{a}"
                            for middle in ("", "rotation_") for a in "xyz"]
                    if any(parser.has_option(s, k)
                           for s in ("attachments", "exhaust") for k in keys):
                        count = str(i + 1)
                        break
            fields["exhaust_count"] = count
    return LinkedIni(path=path, kind=kind, fields=fields, digest=_digest(raw))


def _target(kind: str, field: str, sections: set[str], content: list[str]):
    """Update legacy seat/exhaust keys in their original section if present."""
    if field in MODEL_KEYS or field == "asset_name" and kind != "character":
        return "model", ("asset_name" if field == "asset_name" else field)
    if field == "asset_name" or field == "icon":
        return "assets", field
    if field == "name":
        return ("character" if kind == "character" else
                "kart" if kind == "kart" else "wheel"), "name"
    if field in ("fallback_retail", "engine", "kart", "modular_body"):
        return "character", field
    if field == "exhaust_count":
        if "attachments" in sections:
            return "attachments", "exhaust_count"
        if "exhaust" in sections:
            for k in ("exhaust_count", "count"):
                if _has_key(content, "exhaust", k):
                    return "exhaust", k
            return "exhaust", "exhaust_count"
        return "attachments", "exhaust_count"
    if field.startswith("seat_") and not _has_key(content, "attachments", field):
        if _has_key(content, "seat", field[5:]):
            return "seat", field[5:]
    if field.startswith("exhaust_") and not _has_key(content, "attachments", field):
        if _has_key(content, "exhaust", field):
            return "exhaust", field
    return "attachments", field


def _has_key(lines: list[str], section: str, key: str) -> bool:
    active = ""
    for line in lines:
        header = _HEADER_RE.match(line.strip("\r\n"))
        if header:
            active = header.group(1).casefold()
        elif active == section:
            setting = _KV_RE.match(line.strip("\r\n"))
            if setting and setting.group(2).casefold() == key:
                return True
    return False


def _replace_setting(lines: list[str], section: str, key: str,
                     value: str | None, newline: str):
    active = ""
    positions = []
    section_end = None
    for i, line in enumerate(lines):
        clean = line.rstrip("\r\n")
        header = _HEADER_RE.match(clean)
        if header:
            if active == section and section_end is None:
                section_end = i
            active = header.group(1).casefold()
        elif active == section:
            entry = _KV_RE.match(clean)
            if entry and entry.group(2).casefold() == key.casefold():
                positions.append((i, entry))
    if active == section and section_end is None:
        section_end = len(lines)
    if positions:
        if value is None:
            for i, _ in reversed(positions):
                lines.pop(i)
        else:
            for i, match in positions:
                old_rest = match.group(4)
                suffix = re.search(r"(\s+[;#].*)$", old_rest)
                # Preserve comments and original key case/indentation.
                trailing = suffix.group(1) if suffix else ""
                end = "\r\n" if lines[i].endswith("\r\n") else (
                    "\n" if lines[i].endswith("\n") else newline)
                lines[i] = (match.group(1)+match.group(2)+
                            match.group(3)+value+trailing+end)
        return
    if value is None:
        return
    if section_end is not None:
        # Insert before blank lines at end of this section, preserving them.
        insert = section_end
        while insert > 0 and not lines[insert-1].strip():
            insert -= 1
        lines.insert(insert, f"{key} = {value}{newline}")
        return
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    if lines and lines[-1].strip():
        lines.append(newline)
    lines.extend((f"[{section}]{newline}", f"{key} = {value}{newline}"))


def save_linked_ini(link: LinkedIni, edited: dict[str, str]) -> Path | None:
    """Save only changed displayed values; create recovery copy and return it.

    Unmodified foreign keys and Forge Hub IDs are never rewritten. Editing
    follows user explicit Save button, not field keypresses.
    """
    changed = {k: str(v).strip() for k, v in edited.items()
               if k in link.fields and str(v).strip() != link.fields[k]}
    # has_wheels was a legacy character-side switch. When a user explicitly
    # saves a character, remove the obsolete field even when offsets did not
    # change. Preserve existing INIs until the user presses Save.
    deprecated_wheels = False
    if link.kind == "character":
        try:
            deprecated_wheels = _has_key(
                link.path.read_text(encoding="utf-8-sig").splitlines(),
                "character", "has_wheels")
        except (OSError, UnicodeError):
            pass
    if not changed and not deprecated_wheels:
        return None
    for field, value in changed.items():
        if field in _NUMBER_FIELDS:
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise LinkedIniError(f"{field}: enter a valid number") from exc
            if not math.isfinite(number):
                raise LinkedIniError(f"{field}: enter a finite number")
            if field == "scale" and number <= 0:
                raise LinkedIniError("Scale must be greater than zero")
        elif field == "exhaust_count" and (
            value.lower() != "default" and value not in ("0","1","2","3","4")
        ):
            raise LinkedIniError("Exhaust count must be Default or 0–4")
        elif field == "modular_body" and (
            value.lower() not in ("true","false")):
            raise LinkedIniError(field + " must be true or false")
        elif any(ch in value for ch in "\r\n[]"):
            raise LinkedIniError(f"{field}: invalid INI characters")

    path = link.path
    if path.is_symlink() or not path.is_file():
        raise LinkedIniConflict("The linked INI is missing or was replaced")
    raw = path.read_bytes()
    if _digest(raw) != link.digest:
        raise LinkedIniConflict("INI changed outside the editor. Reload it before saving.")
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        data = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LinkedIniError("INI is not UTF-8, cannot safely rewrite") from exc
    if "\r\n" in data:
        newline = "\r\n"
    else:
        newline = "\n"
    lines = data.splitlines(keepends=True)
    sections = {m.group(1).casefold()
                for line in lines if (m := _HEADER_RE.match(line.strip("\r\n")))}
    for field, value in changed.items():
        section, key = _target(link.kind, field, sections, lines)
        _replace_setting(lines, section, key,
                         None if field == "exhaust_count" and
                         value.lower() == "default" else value, newline)
        sections.add(section)
    if deprecated_wheels:
        _replace_setting(lines, "character", "has_wheels", None, newline)
    text = "".join(lines)
    try:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(text)
    except configparser.Error as exc:
        raise LinkedIniError("Updated INI is invalid: " + str(exc)) from exc

    encoded = (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")
    backup = path.with_name(
        path.name + ".before_model_importer_" +
        datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".bak")
    shutil.copy2(path, backup)
    handle = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix="._forge_ini_", dir=path.parent)
        handle = Path(temp_name)
        with os.fdopen(fd, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(handle, path.stat().st_mode)
        # Last-moment conflict protection before atomic replacement.
        if _digest(path.read_bytes()) != link.digest:
            raise LinkedIniConflict("INI changed during save. Reload it before saving.")
        os.replace(handle, path)
    finally:
        if handle is not None and handle.exists():
            handle.unlink()
    return backup