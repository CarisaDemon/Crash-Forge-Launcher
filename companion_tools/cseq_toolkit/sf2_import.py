"""Minimal SoundFont 2 loader for Crash Forge CSEQ authoring.

This parser intentionally focuses on the SF2 pieces needed by the music tool:
presets, instrument zones, PCM16 sample data, key ranges, tuning, attenuation,
pan, root key and sample loops. It has no third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import struct
import tempfile


class Sf2Error(ValueError):
    pass


@dataclass(frozen=True)
class Sf2Sample:
    index: int
    name: str
    start: int
    end: int
    loop_start: int
    loop_end: int
    sample_rate: int
    original_pitch: int
    pitch_correction: int
    sample_type: int


@dataclass(frozen=True)
class Sf2Zone:
    sample_index: int
    key_low: int
    key_high: int
    root_key: int
    tune_cents: int
    attenuation_cb: int
    pan: int
    loop_enabled: bool

    def contains(self, note: int) -> bool:
        return self.key_low <= note <= self.key_high


@dataclass(frozen=True)
class Sf2Preset:
    index: int
    bank: int
    preset: int
    name: str
    zones: tuple[Sf2Zone, ...]

    @property
    def key(self) -> str:
        return f"{self.bank}:{self.preset}"


@dataclass
class SoundFont:
    path: Path
    data: bytes
    sample_pcm: bytes
    samples: list[Sf2Sample]
    presets: list[Sf2Preset]


@dataclass(frozen=True)
class Sf2CseqInstrument:
    global_id: int
    spu_index: int
    volume: int
    base_pitch: int
    ad: int = -32513
    sr: int = 8129
    midi_program: int = -1
    midi_pitch: int = 0
    title: str = ""
    sample_name: str = ""


@dataclass(frozen=True)
class Sf2CseqDrum:
    global_id: int
    spu_index: int
    volume: int
    pitch: int
    midi_key: int = -1
    title: str = ""
    sample_name: str = ""


def _chunks(data: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        payload = pos + 8
        chunk_end = payload + size
        if chunk_end > end:
            raise Sf2Error(f"truncated RIFF chunk {cid!r}")
        yield cid, payload, size
        pos = chunk_end + (size & 1)


def _list_payload(data: bytes, payload: int, size: int):
    if size < 4:
        raise Sf2Error("invalid LIST chunk")
    return data[payload:payload + 4], payload + 4, payload + size


def _find_lists(data: bytes) -> dict[bytes, tuple[int, int]]:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"sfbk":
        raise Sf2Error("not a SoundFont 2 RIFF/sfbk file")
    riff_size = struct.unpack_from("<I", data, 4)[0]
    end = min(len(data), 8 + riff_size)
    out: dict[bytes, tuple[int, int]] = {}
    for cid, payload, size in _chunks(data, 12, end):
        if cid != b"LIST":
            continue
        kind, sub_start, sub_end = _list_payload(data, payload, size)
        out[kind] = (sub_start, sub_end)
    return out


def _subchunks(data: bytes, bounds: tuple[int, int]) -> dict[bytes, bytes]:
    start, end = bounds
    out: dict[bytes, bytes] = {}
    for cid, payload, size in _chunks(data, start, end):
        out[cid] = data[payload:payload + size]
    return out


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("latin-1", errors="replace").strip()


def _s16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _parse_generators(blob: bytes) -> list[tuple[int, int]]:
    if len(blob) % 4:
        raise Sf2Error("invalid generator table size")
    return [struct.unpack_from("<HH", blob, i) for i in range(0, len(blob), 4)]


def _zone_generators(bags, gens, bag_index: int) -> dict[int, int]:
    if bag_index < 0 or bag_index + 1 >= len(bags):
        return {}
    start = bags[bag_index][0]
    end = bags[bag_index + 1][0]
    result: dict[int, int] = {}
    for oper, amount in gens[start:end]:
        result[oper] = amount
    return result


def _key_range(gens: dict[int, int]) -> tuple[int, int]:
    amount = gens.get(43)
    if amount is None:
        return 0, 127
    return amount & 0xFF, (amount >> 8) & 0xFF


def _merge_generators(global_gens: dict[int, int], local_gens: dict[int, int]) -> dict[int, int]:
    out = dict(global_gens)
    for key, value in local_gens.items():
        if key in (51, 52, 48, 17) and key in out:
            out[key] = (out[key] + value) & 0xFFFF
        else:
            out[key] = value
    return out


def load_sf2(path: str | Path) -> SoundFont:
    p = Path(path)
    data = p.read_bytes()
    lists = _find_lists(data)
    if b"pdta" not in lists or b"sdta" not in lists:
        raise Sf2Error("SF2 is missing pdta or sdta")

    pdta = _subchunks(data, lists[b"pdta"])
    sdta = _subchunks(data, lists[b"sdta"])
    required = (b"phdr", b"pbag", b"pgen", b"inst", b"ibag", b"igen", b"shdr")
    missing = [x.decode() for x in required if x not in pdta]
    if missing:
        raise Sf2Error("SF2 missing tables: " + ", ".join(missing))
    sample_pcm = sdta.get(b"smpl", b"")
    if not sample_pcm:
        raise Sf2Error("SF2 has no smpl PCM pool")

    phdr_blob = pdta[b"phdr"]
    if len(phdr_blob) % 38:
        raise Sf2Error("invalid phdr size")
    phdr = []
    for off in range(0, len(phdr_blob), 38):
        name, preset, bank, bag = struct.unpack_from("<20sHHH", phdr_blob, off)
        phdr.append((_cstr(name), preset, bank, bag))

    def parse_bags(blob: bytes):
        if len(blob) % 4:
            raise Sf2Error("invalid bag table size")
        return [struct.unpack_from("<HH", blob, i) for i in range(0, len(blob), 4)]

    pbag = parse_bags(pdta[b"pbag"])
    pgen = _parse_generators(pdta[b"pgen"])
    ibag = parse_bags(pdta[b"ibag"])
    igen = _parse_generators(pdta[b"igen"])

    inst_blob = pdta[b"inst"]
    if len(inst_blob) % 22:
        raise Sf2Error("invalid inst size")
    inst = []
    for off in range(0, len(inst_blob), 22):
        name, bag = struct.unpack_from("<20sH", inst_blob, off)
        inst.append((_cstr(name), bag))

    shdr_blob = pdta[b"shdr"]
    if len(shdr_blob) % 46:
        raise Sf2Error("invalid shdr size")
    samples: list[Sf2Sample] = []
    for index, off in enumerate(range(0, len(shdr_blob) - 46, 46)):
        vals = struct.unpack_from("<20sIIIIIBbHH", shdr_blob, off)
        samples.append(Sf2Sample(
            index=index,
            name=_cstr(vals[0]),
            start=vals[1],
            end=vals[2],
            loop_start=vals[3],
            loop_end=vals[4],
            sample_rate=vals[5],
            original_pitch=vals[6],
            pitch_correction=vals[7],
            sample_type=vals[9],
        ))

    presets: list[Sf2Preset] = []
    for preset_index in range(max(0, len(phdr) - 1)):
        name, preset_no, bank, first_bag = phdr[preset_index]
        last_bag = phdr[preset_index + 1][3]
        preset_global: dict[int, int] = {}
        preset_refs: list[tuple[dict[int, int], int]] = []
        for bag_index in range(first_bag, last_bag):
            gens = _zone_generators(pbag, pgen, bag_index)
            if 41 in gens:
                preset_refs.append((gens, gens[41]))
            else:
                preset_global = _merge_generators(preset_global, gens)

        zones: list[Sf2Zone] = []
        for pgens, inst_index in preset_refs:
            if inst_index < 0 or inst_index + 1 >= len(inst):
                continue
            pgens = _merge_generators(preset_global, pgens)
            inst_first = inst[inst_index][1]
            inst_last = inst[inst_index + 1][1]
            inst_global: dict[int, int] = {}
            inst_zones: list[dict[int, int]] = []
            for bag_index in range(inst_first, inst_last):
                gens = _zone_generators(ibag, igen, bag_index)
                if 53 in gens:
                    inst_zones.append(gens)
                else:
                    inst_global = _merge_generators(inst_global, gens)

            p_low, p_high = _key_range(pgens)
            for zgens in inst_zones:
                gens = _merge_generators(inst_global, zgens)
                sample_index = gens.get(53, -1)
                if not 0 <= sample_index < len(samples):
                    continue
                z_low, z_high = _key_range(gens)
                low = max(p_low, z_low)
                high = min(p_high, z_high)
                if low > high:
                    continue
                sample = samples[sample_index]
                root = gens.get(58, sample.original_pitch)
                if root > 127:
                    root = sample.original_pitch
                coarse = _s16(pgens.get(51, 0)) + _s16(gens.get(51, 0))
                fine = _s16(pgens.get(52, 0)) + _s16(gens.get(52, 0))
                attenuation = max(0, _s16(pgens.get(48, 0)) + _s16(gens.get(48, 0)))
                pan = max(-500, min(500, _s16(pgens.get(17, 0)) + _s16(gens.get(17, 0))))
                modes = gens.get(54, 0)
                zones.append(Sf2Zone(
                    sample_index=sample_index,
                    key_low=low,
                    key_high=high,
                    root_key=int(root),
                    tune_cents=int(sample.pitch_correction + coarse * 100 + fine),
                    attenuation_cb=int(attenuation),
                    pan=int(pan),
                    loop_enabled=bool(modes & 0x3),
                ))

        if zones:
            zones.sort(key=lambda z: (z.key_low, z.key_high, z.sample_index))
            presets.append(Sf2Preset(preset_index, bank, preset_no, name, tuple(zones)))

    return SoundFont(p, data, sample_pcm, samples, presets)


def zone_for_note(preset: Sf2Preset, note: int) -> Sf2Zone:
    matches = [z for z in preset.zones if z.contains(note)]
    if matches:
        return min(matches, key=lambda z: (z.key_high - z.key_low, abs(z.root_key - note)))
    return min(
        preset.zones,
        key=lambda z: min(abs(note - z.key_low), abs(note - z.key_high)),
    )


def zone_base_pitch(sf: SoundFont, zone: Sf2Zone) -> int:
    sample = sf.samples[zone.sample_index]
    ratio = sample.sample_rate / 44100.0
    ratio *= 2.0 ** (zone.tune_cents / 1200.0)
    return max(1, min(32767, int(round(4096.0 * ratio))))


def zone_volume(zone: Sf2Zone) -> int:
    gain = 10.0 ** (-max(0, zone.attenuation_cb) / 200.0)
    return max(1, min(255, int(round(255.0 * gain))))


def make_cseq_instrument(sf: SoundFont, zone: Sf2Zone, sample_slot: int) -> Sf2CseqInstrument:
    sample = sf.samples[zone.sample_index]
    return Sf2CseqInstrument(
        global_id=0x10000 + sample_slot,
        spu_index=-1 - int(sample_slot),
        volume=zone_volume(zone),
        base_pitch=zone_base_pitch(sf, zone),
        midi_pitch=int(zone.root_key) - 60,
        title=f"SF2 {sample.name}",
        sample_name=sample.name,
    )


def make_cseq_drum(
    sf: SoundFont,
    zone: Sf2Zone,
    sample_slot: int,
    midi_key: int,
) -> Sf2CseqDrum:
    sample = sf.samples[zone.sample_index]
    # Drum pitch is a direct SPU-style playback ratio. The selected SF2 zone
    # already carries the sample-rate and fine/coarse tuning correction.
    pitch = zone_base_pitch(sf, zone)
    pitch *= 2.0 ** ((int(midi_key) - int(zone.root_key)) / 12.0)
    return Sf2CseqDrum(
        global_id=0x20000 + (int(sample_slot) << 7) + (int(midi_key) & 0x7F),
        spu_index=-1 - int(sample_slot),
        volume=zone_volume(zone),
        pitch=max(1, min(32767, int(round(pitch)))),
        midi_key=int(midi_key),
        title=f"SF2 {sample.name}",
        sample_name=sample.name,
    )


def _riff_chunk(chunk_id: bytes, payload: bytes) -> bytes:
    pad = b"\0" if len(payload) & 1 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + pad


def export_zone_wav(sf: SoundFont, zone: Sf2Zone, path: str | Path) -> Path:
    sample = sf.samples[zone.sample_index]
    start = max(0, sample.start)
    end = min(len(sf.sample_pcm) // 2, sample.end)
    if end <= start:
        raise Sf2Error(f"sample {sample.name!r} has an invalid PCM range")
    pcm = sf.sample_pcm[start * 2:end * 2]

    fmt = struct.pack("<HHIIHH", 1, 1, sample.sample_rate,
                      sample.sample_rate * 2, 2, 16)
    chunks = [_riff_chunk(b"fmt ", fmt), _riff_chunk(b"data", pcm)]

    if zone.loop_enabled:
        loop_start = max(0, sample.loop_start - start)
        loop_end = min(end - start, sample.loop_end - start)
        if loop_end > loop_start:
            sample_period = int(round(1_000_000_000 / max(1, sample.sample_rate)))
            header = struct.pack(
                "<9I", 0, 0, sample_period, zone.root_key, 0, 0, 0, 1, 0
            )
            loop = struct.pack(
                "<6I", 0, 0, loop_start, max(loop_start, loop_end - 1), 0, 0
            )
            chunks.append(_riff_chunk(b"smpl", header + loop))

    wave_payload = b"WAVE" + b"".join(chunks)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"RIFF" + struct.pack("<I", len(wave_payload)) + wave_payload)
    return out


def export_zone_temp(sf: SoundFont, zone: Sf2Zone, slot: int) -> Path:
    safe = "".join(c if c.isalnum() else "_" for c in sf.samples[zone.sample_index].name)
    path = Path(tempfile.gettempdir()) / f"cfr_sf2_{slot:03d}_{safe[:40]}.wav"
    return export_zone_wav(sf, zone, path)
