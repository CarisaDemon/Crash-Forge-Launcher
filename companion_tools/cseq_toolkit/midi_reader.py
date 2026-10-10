"""Small dependency-free Standard MIDI File reader for the CFR music tool."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Optional


class MidiError(ValueError):
    pass


@dataclass
class MidiEvent:
    tick: int
    track: int
    order: int
    kind: str
    channel: Optional[int] = None
    a: Optional[int] = None
    b: Optional[int] = None
    meta_type: Optional[int] = None
    data: bytes = b""


@dataclass
class MidiFile:
    format: int
    ticks_per_quarter: int
    track_count: int
    events: list[MidiEvent]
    warnings: list[str]


def _read_vlq(data: bytes, pos: int, end: int) -> tuple[int, int]:
    value = 0
    count = 0
    while True:
        if pos >= end:
            raise MidiError("truncated MIDI VLQ")
        byte = data[pos]
        pos += 1
        count += 1
        if count > 4:
            raise MidiError("MIDI VLQ longer than 4 bytes")
        value = (value << 7) | (byte & 0x7F)
        if (byte & 0x80) == 0:
            return value, pos


def _channel_data_len(status: int) -> int:
    high = status & 0xF0
    if high in (0xC0, 0xD0):
        return 1
    if 0x80 <= high <= 0xE0:
        return 2
    raise MidiError(f"not a channel status: 0x{status:02x}")


def _channel_kind(status: int, d1: int, d2: int | None) -> tuple[str, int | None, int | None]:
    high = status & 0xF0
    if high == 0x80:
        return "note_off", d1, d2
    if high == 0x90:
        return ("note_off" if (d2 or 0) == 0 else "note_on"), d1, d2
    if high == 0xA0:
        return "poly_pressure", d1, d2
    if high == 0xB0:
        names = {7: "volume", 10: "pan", 11: "expression"}
        return names.get(d1, "control_change"), d1, d2
    if high == 0xC0:
        return "program_change", d1, None
    if high == 0xD0:
        return "channel_pressure", d1, None
    if high == 0xE0:
        value = ((d2 or 0) << 7) | d1
        return "pitch_bend", value - 8192, None
    return "unknown_channel", d1, d2


def _parse_track(data: bytes, track_index: int, warnings: list[str]) -> list[MidiEvent]:
    pos = 0
    end = len(data)
    tick = 0
    running_status: int | None = None
    order = 0
    events: list[MidiEvent] = []

    while pos < end:
        delta, pos = _read_vlq(data, pos, end)
        tick += delta
        if pos >= end:
            raise MidiError(f"track {track_index}: event missing status")

        first = data[pos]
        if first & 0x80:
            status = first
            pos += 1
            if status < 0xF0:
                running_status = status
        else:
            if running_status is None:
                raise MidiError(f"track {track_index}: running status without previous status")
            status = running_status

        if status == 0xFF:
            running_status = None
            if pos >= end:
                raise MidiError("truncated meta event")
            meta_type = data[pos]
            pos += 1
            length, pos = _read_vlq(data, pos, end)
            if pos + length > end:
                raise MidiError("truncated meta payload")
            payload = data[pos : pos + length]
            pos += length

            kind = "meta"
            a = b = None
            if meta_type == 0x2F:
                kind = "end_of_track"
            elif meta_type == 0x51 and len(payload) == 3:
                kind = "tempo"
                a = int.from_bytes(payload, "big")
            elif meta_type == 0x03:
                kind = "track_name"
            elif meta_type == 0x06:
                kind = "marker"
            elif meta_type == 0x58:
                kind = "time_signature"

            events.append(MidiEvent(tick, track_index, order, kind, a=a, b=b, meta_type=meta_type, data=payload))
            order += 1
            if meta_type == 0x2F:
                break
            continue

        if status in (0xF0, 0xF7):
            running_status = None
            length, pos = _read_vlq(data, pos, end)
            if pos + length > end:
                raise MidiError("truncated SysEx payload")
            payload = data[pos : pos + length]
            pos += length
            events.append(MidiEvent(tick, track_index, order, "sysex", data=payload))
            order += 1
            continue

        if status >= 0xF0:
            running_status = None
            system_lengths = {
                0xF1: 1, 0xF2: 2, 0xF3: 1, 0xF6: 0,
                0xF8: 0, 0xFA: 0, 0xFB: 0, 0xFC: 0, 0xFE: 0,
            }
            n = system_lengths.get(status)
            if n is None:
                warnings.append(f"track {track_index}: unsupported system status 0x{status:02x}")
                n = 0
            if pos + n > end:
                raise MidiError("truncated system event")
            payload = data[pos : pos + n]
            pos += n
            events.append(MidiEvent(tick, track_index, order, "system", a=status, data=payload))
            order += 1
            continue

        n = _channel_data_len(status)
        if first & 0x80:
            if pos + n > end:
                raise MidiError("truncated channel event")
            d1 = data[pos]
            d2 = data[pos + 1] if n == 2 else None
            pos += n
        else:
            d1 = first
            pos += 1
            if n == 2:
                if pos >= end:
                    raise MidiError("truncated running-status event")
                d2 = data[pos]
                pos += 1
            else:
                d2 = None

        kind, a, b = _channel_kind(status, d1, d2)
        events.append(MidiEvent(tick, track_index, order, kind, channel=status & 0x0F, a=a, b=b))
        order += 1

    return events


def read_midi(path: str | Path) -> MidiFile:
    data = Path(path).read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiError("not a Standard MIDI File")

    header_len = struct.unpack_from(">I", data, 4)[0]
    if header_len < 6 or 8 + header_len > len(data):
        raise MidiError("bad MIDI header length")

    fmt, track_count, division = struct.unpack_from(">HHH", data, 8)
    if fmt not in (0, 1):
        raise MidiError(f"MIDI type {fmt} is not supported by the MVP")
    if division & 0x8000:
        raise MidiError("SMPTE time division is not supported yet")
    if division == 0:
        raise MidiError("ticks per quarter note is zero")

    warnings: list[str] = []
    pos = 8 + header_len
    all_events: list[MidiEvent] = []

    for track_index in range(track_count):
        if pos + 8 > len(data) or data[pos : pos + 4] != b"MTrk":
            raise MidiError(f"missing MTrk chunk {track_index}")
        length = struct.unpack_from(">I", data, pos + 4)[0]
        pos += 8
        if pos + length > len(data):
            raise MidiError(f"track {track_index} extends beyond file")
        all_events.extend(_parse_track(data[pos : pos + length], track_index, warnings))
        pos += length

    all_events.sort(key=lambda e: (e.tick, e.track, e.order))
    return MidiFile(fmt, division, track_count, all_events, warnings)


def summarize(midi: MidiFile) -> dict:
    channels = sorted({e.channel for e in midi.events if e.channel is not None})
    programs: dict[int, list[int]] = {}
    for ch in channels:
        programs[ch] = sorted({
            int(e.a) for e in midi.events
            if e.channel == ch and e.kind == "program_change" and e.a is not None
        })

    tempos = [
        {"tick": e.tick, "us_per_quarter": e.a, "bpm": (60000000.0 / e.a) if e.a else None}
        for e in midi.events if e.kind == "tempo"
    ]
    names = [
        e.data.decode("utf-8", "replace")
        for e in midi.events if e.kind == "track_name"
    ]
    markers = [
        {"tick": e.tick, "text": e.data.decode("utf-8", "replace")}
        for e in midi.events if e.kind == "marker"
    ]
    return {
        "format": midi.format,
        "tracks": midi.track_count,
        "ticks_per_quarter": midi.ticks_per_quarter,
        "events": len(midi.events),
        "last_tick": max((e.tick for e in midi.events), default=0),
        "channels": channels,
        "programs": programs,
        "tempos": tempos,
        "track_names": names,
        "markers": markers,
        "warnings": list(midi.warnings),
    }
