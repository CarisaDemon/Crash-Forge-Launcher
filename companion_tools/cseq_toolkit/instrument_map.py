"""Retail HOWL instrument/drum catalog adapter.

CTR-tools already contains hand-authored metadata for retail CSEQ instruments
and percussion.  This module joins that metadata to the audited global HOWL
catalog so the authoring tool can show meaningful names, MIDI programs and the
per-instrument pitch correction used by CTR-tools' CSEQ -> MIDI export.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import csv
import json


DEFAULT_AUDIT_DIR = Path(r"C:\Crash Team Racing\Auditoria_Musica_HOWL_v152_20260928")
DEFAULT_NAMES_FILE = Path(__file__).with_name("instrument_names.json")
DEFAULT_CTR_TOOLS_DATA_DIR = Path(
    r"C:\Crash Team Racing\CTR-tools-r14-source\ctr-tools\CTRFramework\Data"
)

# Retail NTSC-U HOWL sequence order from CTRFramework/Data/howlnames.txt.
CSEQ_META_KEYS = {
    0: "canyon",
    1: "mines",
    2: "bluff",
    3: "cove",
    4: "temple",
    5: "pyramid",
    6: "tubes",
    7: "skyway",
    8: "sewer",
    9: "caves",
    10: "castle",
    11: "labs",
    12: "pass",
    13: "station",
    14: "park",
    15: "arena",
    16: "coliseum",
    17: "turbo",
    18: "nitro_court",
    19: "rampage_ruins",
    20: "parking_lot",
    21: "skull_rock",
    22: "north_bowl",
    23: "rocky_road",
    24: "lab_basement",
    25: "boss_challenge",
    26: "adv_gem_valley",
    27: "character_select",
    28: "intro",
    29: "cutscenes",
    30: "cutscenes_oxide1",
    31: "cutscenes_oxide2",
    32: "credits",
}

PACK_NAMES = {
    0: "Dingo Canyon",
    1: "Dragon Mines",
    2: "Blizzard Bluff",
    3: "Crash Cove",
    4: "Tiger Temple",
    5: "Papu Pyramid",
    6: "Roo's Tubes",
    7: "Hot Air Skyway",
    8: "Sewer Speedway",
    9: "Mystery Caves",
    10: "Cortex Castle",
    11: "N. Gin Labs",
    12: "Polar Pass",
    13: "Oxide Station",
    14: "Coco Park",
    15: "Tiny Arena",
    16: "Slide Coliseum",
    17: "Turbo Track",
    18: "Nitro Court",
    19: "Rampage Ruins",
    20: "Parking Lot",
    21: "Skull Rock",
    22: "The North Bowl",
    23: "Rocky Road",
    24: "Lab Basement",
    25: "Boss Challenge",
    26: "Adventure Hub",
    27: "Character Select",
    28: "Intro",
    29: "Cutscenes",
    30: "Oxide Cutscene 1",
    31: "Oxide Cutscene 2",
    32: "Credits",
}


@dataclass(frozen=True)
class RetailInstrument:
    global_id: int
    spu_index: int
    volume: int
    base_pitch: int
    ad: int
    sr: int
    title: str = ""
    sample_name: str = ""
    midi_program: int = -1
    midi_pitch: int = 0

    @property
    def slug(self) -> str:
        return f"retail_inst_{self.global_id:03d}"

    @property
    def label(self) -> str:
        return self.title or self.sample_name or f"Retail Instrument {self.global_id:03d}"


@dataclass(frozen=True)
class RetailDrum:
    global_id: int
    spu_index: int
    volume: int
    pitch: int
    title: str = ""
    sample_name: str = ""
    midi_key: int = -1

    @property
    def slug(self) -> str:
        return f"retail_drum_{self.global_id:03d}"

    @property
    def label(self) -> str:
        return self.title or self.sample_name or f"Retail Drum {self.global_id:03d}"


@dataclass
class RetailCatalog:
    instruments: list[RetailInstrument]
    drums: list[RetailDrum]
    local_map: dict[tuple[int, str, int], int]
    aliases: dict[str, dict[int, str]]

    def _instrument(self, global_id: int) -> RetailInstrument | None:
        return next((x for x in self.instruments if x.global_id == global_id), None)

    def _drum(self, global_id: int) -> RetailDrum | None:
        return next((x for x in self.drums if x.global_id == global_id), None)

    def to_dict(self) -> dict:
        return {
            "instruments": [
                {
                    **asdict(x),
                    "slug": x.slug,
                    "label": x.label,
                    "friendly_name": self.instrument_name(x.global_id),
                    "display_name": self.instrument_display(x.global_id),
                    "origins": self.origins("instrument", x.global_id),
                }
                for x in self.instruments
            ],
            "drums": [
                {
                    **asdict(x),
                    "slug": x.slug,
                    "label": x.label,
                    "friendly_name": self.drum_name(x.global_id),
                    "display_name": self.drum_display(x.global_id),
                    "origins": self.origins("drum", x.global_id),
                }
                for x in self.drums
            ],
            "local_mappings": [
                {
                    "song_id": song_id,
                    "kind": kind,
                    "local_id": local_id,
                    "global_id": global_id,
                }
                for (song_id, kind, local_id), global_id in sorted(self.local_map.items())
            ],
        }

    def origins(self, kind: str, global_id: int) -> list[str]:
        label_kind = "Inst" if kind == "instrument" else "Drum"
        result: list[str] = []
        for (song_id, mapped_kind, local_id), mapped_global in sorted(self.local_map.items()):
            if mapped_kind != kind or mapped_global != global_id:
                continue
            pack = PACK_NAMES.get(song_id, f"CSEQ Pack {song_id}")
            result.append(f"{pack} {label_kind} {local_id}")
        return result

    def _generated_name(self, kind: str, global_id: int) -> str:
        origins = self.origins(kind, global_id)
        prefix = "Instrument" if kind == "instrument" else "Drum"
        if not origins:
            return f"Retail {prefix} {global_id:03d}"
        name = origins[0]
        if len(origins) > 1:
            name += " [shared]"
        return name

    def instrument_name(self, global_id: int) -> str:
        alias = self.aliases.get("instruments", {}).get(global_id, "").strip()
        if alias:
            return alias
        item = self._instrument(global_id)
        if item is not None:
            if item.title:
                return item.title
            if item.sample_name:
                return item.sample_name
        return self._generated_name("instrument", global_id)

    def drum_name(self, global_id: int) -> str:
        alias = self.aliases.get("drums", {}).get(global_id, "").strip()
        if alias:
            return alias
        item = self._drum(global_id)
        if item is not None:
            if item.title:
                return item.title
            if item.sample_name:
                return item.sample_name
        return self._generated_name("drum", global_id)

    def instrument_display(self, global_id: int) -> str:
        item = self._instrument(global_id)
        primary = self.instrument_name(global_id)
        if item is not None and item.sample_name and item.sample_name.lower() != primary.lower():
            return f"{primary} | sample: {item.sample_name}"
        return primary

    def drum_display(self, global_id: int) -> str:
        item = self._drum(global_id)
        primary = self.drum_name(global_id)
        if item is not None and item.sample_name and item.sample_name.lower() != primary.lower():
            return f"{primary} | sample: {item.sample_name}"
        return primary


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _load_aliases(path: Path = DEFAULT_NAMES_FILE) -> dict[str, dict[int, str]]:
    aliases: dict[str, dict[int, str]] = {"instruments": {}, "drums": {}}
    if not path.is_file():
        return aliases
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return aliases
    for kind in ("instruments", "drums"):
        section = raw.get(kind, {})
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            try:
                aliases[kind][int(key)] = str(value)
            except (TypeError, ValueError):
                continue
    return aliases


def _load_sample_names(data_dir: Path) -> dict[int, str]:
    path = data_dir / "samplenames.txt"
    result: dict[int, str] = {}
    if not path.is_file():
        return result
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        left, right = line.split("=", 1)
        try:
            result[int(left.strip())] = right.strip()
        except ValueError:
            continue
    return result


def _load_cseq_meta(data_dir: Path) -> dict:
    path = data_dir / "cseq.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    midi = raw.get("midi", {})
    return midi if isinstance(midi, dict) else {}


def _first_meta_entry(
    local_map: dict[tuple[int, str, int], int],
    cseq_meta: dict,
    kind: str,
    global_id: int,
) -> dict:
    section = "long" if kind == "instrument" else "short"
    for (song_id, mapped_kind, local_id), mapped_global in sorted(local_map.items()):
        if mapped_kind != kind or mapped_global != global_id:
            continue
        key = CSEQ_META_KEYS.get(song_id)
        if not key:
            continue
        pack = cseq_meta.get(key)
        if not isinstance(pack, dict):
            continue
        entries = pack.get(section, [])
        if isinstance(entries, list) and 0 <= local_id < len(entries):
            entry = entries[local_id]
            if isinstance(entry, dict):
                return entry
    return {}


def load_retail_catalog(
    audit_dir: str | Path = DEFAULT_AUDIT_DIR,
    names_file: str | Path = DEFAULT_NAMES_FILE,
    ctr_tools_data_dir: str | Path = DEFAULT_CTR_TOOLS_DATA_DIR,
) -> RetailCatalog:
    root = Path(audit_dir)
    data_dir = Path(ctr_tools_data_dir)
    inst_path = root / "global_instrument_catalog.csv"
    drum_path = root / "global_drum_catalog.csv"
    map_path = root / "song_local_to_global.csv"

    missing = [str(p) for p in (inst_path, drum_path, map_path) if not p.is_file()]
    if missing:
        raise FileNotFoundError("missing retail catalog file(s): " + ", ".join(missing))

    local_map: dict[tuple[int, str, int], int] = {}
    for row in _rows(map_path):
        local_map[
            (int(row["songID"]), row["kind"], int(row["localID"]))
        ] = int(row["globalID"])

    sample_names = _load_sample_names(data_dir)
    cseq_meta = _load_cseq_meta(data_dir)

    instruments: list[RetailInstrument] = []
    for row in _rows(inst_path):
        gid = int(row["globalID"])
        spu = int(row["spuIndex"])
        meta = _first_meta_entry(local_map, cseq_meta, "instrument", gid)
        instruments.append(
            RetailInstrument(
                global_id=gid,
                spu_index=spu,
                volume=int(row["volume"]),
                base_pitch=int(row["basePitch"]),
                ad=int(row["ad"]),
                sr=int(row["sr"]),
                title=str(meta.get("title", "")).strip(),
                sample_name=sample_names.get(spu, ""),
                midi_program=int(meta.get("midi", -1)),
                midi_pitch=int(meta.get("pitch", 0)),
            )
        )

    drums: list[RetailDrum] = []
    for row in _rows(drum_path):
        gid = int(row["globalID"])
        spu = int(row["spuIndex"])
        meta = _first_meta_entry(local_map, cseq_meta, "drum", gid)
        drums.append(
            RetailDrum(
                global_id=gid,
                spu_index=spu,
                volume=int(row["volume"]),
                pitch=int(row["pitch"]),
                title=str(meta.get("title", "")).strip(),
                sample_name=sample_names.get(spu, ""),
                midi_key=int(meta.get("key", -1)),
            )
        )

    return RetailCatalog(
        instruments,
        drums,
        local_map,
        _load_aliases(Path(names_file)),
    )


def export_catalog_json(
    path: str | Path,
    audit_dir: str | Path = DEFAULT_AUDIT_DIR,
) -> None:
    catalog = load_retail_catalog(audit_dir)
    Path(path).write_text(json.dumps(catalog.to_dict(), indent=2) + "\n", encoding="utf-8")
