"""Crash Forge CSEQ/HOWL read-only format helpers.

This module intentionally starts as a parser/dumper.  It mirrors the structs
and opcode sizes used by CTR Native so we can prove round-trip fidelity before
letting the MIDI builder emit new music.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import struct
from typing import Any

SECTOR_SIZE = 2048

OPCODE_NAMES = {
    0x00: "empty00",
    0x01: "note_off",
    0x02: "empty02",
    0x03: "end",
    0x04: "empty04",
    0x05: "note_on",
    0x06: "volume",
    0x07: "pan",
    0x08: "reverb",
    0x09: "instrument",
    0x0A: "distort",
}
# Exact values from game/zGlobal_DATA.c::data.opcodeOffset.
OPCODE_SIZE = (1, 2, 2, 1, 2, 3, 2, 2, 2, 2, 2)


class CseqError(ValueError):
    pass


@dataclass
class Instrument:
    index: int
    always_one: int
    volume: int
    always_zero: int
    base_pitch: int
    spu_index: int
    ad: int
    sr: int


@dataclass
class Drum:
    index: int
    always_one: int
    volume: int
    pitch: int
    spu_index: int
    always_zero: int


@dataclass
class Event:
    offset: int
    delta: int
    opcode: int
    name: str
    args: list[int]


@dataclass
class Sequence:
    index: int
    flags: int
    unknown: int
    offset: int
    events: list[Event]


@dataclass
class Song:
    index: int
    offset: int
    unknown: int
    bpm: int
    tpqn: int
    sequences: list[Sequence]


@dataclass
class CseqPack:
    raw: bytes
    song_size: int
    num_long_samples: int
    num_short_samples: int
    num_songs: int
    instruments: list[Instrument]
    drums: list[Drum]
    song_offsets: list[int]
    song_data_offset: int
    songs: list[Song]

    def to_dict(self) -> dict[str, Any]:
        return {
            "song_size": self.song_size,
            "num_long_samples": self.num_long_samples,
            "num_short_samples": self.num_short_samples,
            "num_songs": self.num_songs,
            "song_data_offset": self.song_data_offset,
            "instruments": [asdict(x) for x in self.instruments],
            "drums": [asdict(x) for x in self.drums],
            "song_offsets": self.song_offsets,
            "songs": [asdict(x) for x in self.songs],
        }


def align4(value: int) -> int:
    return (value + 3) & ~3


def decode_vlq(data: bytes, pos: int, end: int | None = None) -> tuple[int, int]:
    if end is None:
        end = len(data)
    value = 0
    count = 0
    while True:
        if pos >= end:
            raise CseqError("truncated variable-length delta")
        byte = data[pos]
        pos += 1
        count += 1
        if count > 5:
            raise CseqError("unreasonable variable-length delta")
        value = (value << 7) | (byte & 0x7F)
        if (byte & 0x80) == 0:
            return value, pos


def encode_vlq(value: int) -> bytes:
    if value < 0:
        raise CseqError("negative delta")
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    out.reverse()
    return bytes(out)


def parse_events(data: bytes, start: int, end: int) -> list[Event]:
    events: list[Event] = []
    pos = start
    guard = 0
    while pos < end:
        guard += 1
        if guard > 100000:
            raise CseqError("event guard tripped")
        delta_start = pos
        try:
            delta, pos = decode_vlq(data, pos, end)
        except CseqError:
            break
        if pos >= end:
            break
        opcode = data[pos]
        if opcode >= len(OPCODE_SIZE):
            # Unknown data: preserve visibility in the dump and stop instead
            # of guessing a byte length and desynchronizing the rest.
            events.append(Event(delta_start, delta, opcode, "unknown", []))
            break
        size = OPCODE_SIZE[opcode]
        if pos + size > end:
            break
        args = list(data[pos + 1 : pos + size])
        events.append(
            Event(
                offset=delta_start,
                delta=delta,
                opcode=opcode,
                name=OPCODE_NAMES.get(opcode, f"opcode_{opcode:02x}"),
                args=args,
            )
        )
        pos += size
        if opcode == 0x03:
            break
    return events


def parse_pack(data: bytes) -> CseqPack:
    if len(data) < 8:
        raise CseqError("CSEQ pack shorter than header")
    song_size, n_long, n_short, n_songs = struct.unpack_from("<IBBH", data, 0)
    if song_size < 8 or song_size > len(data):
        raise CseqError(f"invalid song_size {song_size} for {len(data)} bytes")

    pos = 8
    instruments: list[Instrument] = []
    for index in range(n_long):
        if pos + 12 > song_size:
            raise CseqError("truncated SampleInstrument table")
        vals = struct.unpack_from("<BBhhhhh", data, pos)
        instruments.append(Instrument(index, *vals))
        pos += 12

    drums: list[Drum] = []
    for index in range(n_short):
        if pos + 8 > song_size:
            raise CseqError("truncated SampleDrums table")
        vals = struct.unpack_from("<BBhhh", data, pos)
        drums.append(Drum(index, *vals))
        pos += 8

    if pos + n_songs * 2 > song_size:
        raise CseqError("truncated song offset table")
    song_offsets = list(struct.unpack_from(f"<{n_songs}H", data, pos)) if n_songs else []
    pos += n_songs * 2
    song_data_offset = align4(pos)

    songs: list[Song] = []
    for song_index, rel_song_off in enumerate(song_offsets):
        song_start = song_data_offset + rel_song_off
        next_rel = song_offsets[song_index + 1] if song_index + 1 < len(song_offsets) else song_size - song_data_offset
        song_end = min(song_size, song_data_offset + next_rel)
        if song_start + 6 > song_end:
            raise CseqError(f"song {song_index} header outside pack")

        unknown, n_seq, bpm, tpqn = struct.unpack_from("<BBhh", data, song_start)
        seq_table = song_start + 6
        if seq_table + n_seq * 2 > song_end:
            raise CseqError(f"song {song_index} sequence offset table truncated")
        seq_offsets = list(struct.unpack_from(f"<{n_seq}H", data, seq_table)) if n_seq else []
        seq_base = align4(seq_table + n_seq * 2)

        sequences: list[Sequence] = []
        for seq_index, rel_seq_off in enumerate(seq_offsets):
            seq_start = seq_base + rel_seq_off
            if seq_index + 1 < len(seq_offsets):
                seq_end = min(song_end, seq_base + seq_offsets[seq_index + 1])
            else:
                seq_end = song_end
            if seq_start + 2 > seq_end:
                raise CseqError(f"song {song_index} sequence {seq_index} header truncated")
            flags = data[seq_start]
            unknown_seq = data[seq_start + 1]
            events = parse_events(data, seq_start + 2, seq_end)
            sequences.append(Sequence(seq_index, flags, unknown_seq, rel_seq_off, events))

        songs.append(Song(song_index, rel_song_off, unknown, bpm, tpqn, sequences))

    return CseqPack(
        raw=data[:song_size],
        song_size=song_size,
        num_long_samples=n_long,
        num_short_samples=n_short,
        num_songs=n_songs,
        instruments=instruments,
        drums=drums,
        song_offsets=song_offsets,
        song_data_offset=song_data_offset,
        songs=songs,
    )


def rebuild_preserving_song_data(pack: CseqPack) -> bytes:
    """Rebuild header/tables and preserve song bytes exactly.

    This is deliberately conservative.  It proves our understanding of the
    pack layout before the experimental encoder is allowed to create new song
    streams.
    """
    out = bytearray()
    out += struct.pack(
        "<IBBH",
        pack.song_size,
        pack.num_long_samples,
        pack.num_short_samples,
        pack.num_songs,
    )
    for x in pack.instruments:
        out += struct.pack(
            "<BBhhhhh",
            x.always_one,
            x.volume,
            x.always_zero,
            x.base_pitch,
            x.spu_index,
            x.ad,
            x.sr,
        )
    for x in pack.drums:
        out += struct.pack(
            "<BBhhh",
            x.always_one,
            x.volume,
            x.pitch,
            x.spu_index,
            x.always_zero,
        )
    if pack.song_offsets:
        out += struct.pack(f"<{len(pack.song_offsets)}H", *pack.song_offsets)

    # Preserve alignment/padding bytes byte-for-byte. Several retail packs use
    # non-zero bytes here, so normalizing them to zero would break an exact
    # round-trip even though the game ignores the padding.
    if len(out) > pack.song_data_offset:
        raise CseqError("metadata grew beyond parsed song-data offset")
    out += pack.raw[len(out) : pack.song_data_offset]
    out += pack.raw[pack.song_data_offset : pack.song_size]
    if len(out) != pack.song_size:
        raise CseqError(f"rebuilt size {len(out)} != declared {pack.song_size}")
    return bytes(out)


def parse_howl_header(hwl: bytes) -> dict[str, Any]:
    if len(hwl) < 40:
        raise CseqError("HOWL file shorter than header")
    vals = struct.unpack_from("<10I", hwl, 0)
    keys = (
        "magic", "version", "unk1", "unk2", "numSpuAddrs",
        "numOtherFX", "numEngineFX", "numBanks", "numSequences", "headerSize",
    )
    header = dict(zip(keys, vals))
    pos = 40 + header["numSpuAddrs"] * 4 + header["numOtherFX"] * 8 + header["numEngineFX"] * 8
    bank_bytes = header["numBanks"] * 2
    song_bytes = header["numSequences"] * 2
    if pos + bank_bytes + song_bytes > len(hwl):
        raise CseqError("HOWL offset tables outside file")
    header["bankOffsets"] = list(struct.unpack_from(f"<{header['numBanks']}H", hwl, pos))
    pos += bank_bytes
    header["songOffsets"] = list(struct.unpack_from(f"<{header['numSequences']}H", hwl, pos))
    return header


def extract_pack_from_hwl(hwl: bytes, pack_id: int) -> bytes:
    header = parse_howl_header(hwl)
    offsets = header["songOffsets"]
    if pack_id < 0 or pack_id >= len(offsets):
        raise CseqError(f"pack id {pack_id} outside 0..{len(offsets)-1}")
    start = offsets[pack_id] * SECTOR_SIZE
    if start + 8 > len(hwl):
        raise CseqError("CSEQ pack offset outside HOWL")
    song_size = struct.unpack_from("<I", hwl, start)[0]
    end = start + song_size
    if song_size < 8 or end > len(hwl):
        raise CseqError(f"bad CSEQ size {song_size} at pack {pack_id}")
    return hwl[start:end]


def load_pack_from_hwl(path: str | Path, pack_id: int) -> CseqPack:
    return parse_pack(extract_pack_from_hwl(Path(path).read_bytes(), pack_id))


def dump_pack_json(pack: CseqPack, path: str | Path | None = None) -> str:
    text = json.dumps(pack.to_dict(), indent=2)
    if path is not None:
        Path(path).write_text(text + "\n", encoding="utf-8")
    return text
