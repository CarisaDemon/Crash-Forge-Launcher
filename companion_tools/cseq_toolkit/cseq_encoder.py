"""Experimental MIDI -> CSEQ encoder.

Only semantics confirmed by the current game code are emitted. Unsupported
MIDI features are reported by validator.py instead of being silently guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Callable, Iterable

from cseq_format import encode_vlq, align4
from midi_reader import MidiFile, MidiEvent
from instrument_map import RetailInstrument, RetailDrum


class CseqEncodeError(ValueError):
    pass


@dataclass
class SequenceBuild:
    channel: int
    is_drums: bool
    payload: bytes


@dataclass(frozen=True)
class MelodicInstrumentZone:
    instrument: object
    key_low: int = 0
    key_high: int = 127
    midi_pitch: int = 0

    def contains(self, note: int) -> bool:
        return self.key_low <= note <= self.key_high


def _u8_scaled(value_0_127: int) -> int:
    value_0_127 = max(0, min(127, int(value_0_127)))
    return min(255, value_0_127 * 2 + (1 if value_0_127 == 127 else 0))


def _effective_volume_u8(channel_volume: int, expression: int) -> int:
    """Combine MIDI CC7 and CC11 into CTR's single sequence-volume value."""
    channel_volume = max(0, min(127, int(channel_volume)))
    expression = max(0, min(127, int(expression)))
    effective = (channel_volume * expression + 63) // 127
    return _u8_scaled(effective)


def _first_bpm(midi: MidiFile, fallback: int = 120) -> int:
    for event in midi.events:
        if event.kind == "tempo" and event.a:
            bpm = int(round(60000000.0 / event.a))
            return max(1, min(32767, bpm))
    return fallback


def _event(delta: int, opcode: int, *args: int) -> bytes:
    if not (0 <= opcode <= 0x0A):
        raise CseqEncodeError(f"unsupported CSEQ opcode 0x{opcode:02x}")
    for arg in args:
        if not 0 <= arg <= 255:
            raise CseqEncodeError(f"opcode argument outside u8: {arg}")
    return encode_vlq(delta) + bytes((opcode, *args))


def _channel_events(midi: MidiFile, channel: int) -> list[MidiEvent]:
    return [
        e for e in midi.events
        if e.channel == channel
        and e.kind in ("note_on", "note_off", "program_change", "volume", "expression", "pan")
    ]


def _song_loop_end_tick(midi: MidiFile) -> int:
    """Return the last musical note boundary, excluding exported tail silence."""
    note_ticks = [
        int(e.tick)
        for e in midi.events
        if e.kind in ("note_on", "note_off")
    ]
    if note_ticks:
        return max(note_ticks)

    end_ticks = [int(e.tick) for e in midi.events if e.kind == "end_of_track"]
    if end_ticks:
        return max(end_ticks)
    return max((int(e.tick) for e in midi.events), default=0)


def _events_through_loop_end(
    events: list[MidiEvent],
    loop_end_tick: int | None,
) -> list[MidiEvent]:
    if loop_end_tick is None:
        return events
    boundary = int(loop_end_tick)
    return [e for e in events if int(e.tick) <= boundary]


LOOP_START_MARKERS = {
    "CFR_LOOP_START",
    "LOOP_START",
    "RACE_LOOP_START",
    "INTRO_END",
}


def find_loop_start_tick(midi: MidiFile) -> int | None:
    for event in midi.events:
        if event.kind != "marker":
            continue
        text = event.data.decode("utf-8", "replace").strip().upper()
        if text in LOOP_START_MARKERS:
            return int(event.tick)
    return None


def _emit_loop_marker_if_due(
    out: bytearray,
    last_tick: int,
    next_tick: int,
    loop_start_tick: int | None,
    emitted: bool,
) -> tuple[int, bool]:
    if emitted or loop_start_tick is None:
        return last_tick, emitted
    if loop_start_tick < last_tick or loop_start_tick > next_tick:
        return last_tick, emitted
    out += _event(loop_start_tick - last_tick, 0x02, 0xCF)
    return loop_start_tick, True


def build_melodic_sequence(
    midi: MidiFile,
    channel: int,
    program_to_local_instrument: dict[int, int],
    default_local_instrument: int,
    local_instrument_midi_pitch: dict[int, int] | None = None,
    loop_end_tick: int | None = None,
    loop_start_tick: int | None = None,
) -> SequenceBuild:
    source = _events_through_loop_end(_channel_events(midi, channel), loop_end_tick)
    out = bytearray()
    last_tick = 0
    current_program = 0
    current_local = default_local_instrument
    pitch_by_local = local_instrument_midi_pitch or {}
    loop_marker_emitted = False
    current_channel_volume = 127
    current_expression = 127
    current_volume = _effective_volume_u8(
        current_channel_volume, current_expression
    )
    current_pan = 0x80

    # Make the instrument state explicit at time zero.
    out += _event(0, 0x09, current_local)

    for event in source:
        if event.tick < last_tick:
            raise CseqEncodeError("events are not sorted")
        marker_was_emitted = loop_marker_emitted
        last_tick, loop_marker_emitted = _emit_loop_marker_if_due(
            out, last_tick, event.tick, loop_start_tick, loop_marker_emitted
        )
        if loop_marker_emitted and not marker_was_emitted:
            out += _event(0, 0x09, current_local)
            out += _event(0, 0x06, current_volume)
            out += _event(0, 0x07, current_pan)
        delta = event.tick - last_tick

        if event.kind == "program_change":
            current_program = int(event.a or 0)
            if current_program not in program_to_local_instrument:
                raise CseqEncodeError(
                    f"channel {channel + 1}: MIDI program {current_program} has no instrument mapping"
                )
            current_local = program_to_local_instrument[current_program]
            out += _event(delta, 0x09, current_local)
            last_tick = event.tick
        elif event.kind == "volume":
            current_channel_volume = int(event.b or 0)
            current_volume = _effective_volume_u8(
                current_channel_volume, current_expression
            )
            out += _event(delta, 0x06, current_volume)
            last_tick = event.tick
        elif event.kind == "expression":
            current_expression = int(event.b or 0)
            current_volume = _effective_volume_u8(
                current_channel_volume, current_expression
            )
            out += _event(delta, 0x06, current_volume)
            last_tick = event.tick
        elif event.kind == "pan":
            current_pan = _u8_scaled(int(event.b or 0))
            out += _event(delta, 0x07, current_pan)
            last_tick = event.tick
        elif event.kind == "note_on":
            midi_note = int(event.a or 0)
            # CTR-tools exports retail CSEQ as:
            # MIDI note = CSEQ note + instrument meta pitch.
            # Importing back must apply the inverse correction.
            note = midi_note - int(pitch_by_local.get(current_local, 0))
            if not 0 <= note <= 107:
                raise CseqEncodeError(
                    f"channel {channel + 1}: MIDI note {midi_note} becomes "
                    f"CSEQ note {note}, outside CTR's pitch table (0..107)"
                )
            velocity = _u8_scaled(int(event.b or 0))
            out += _event(delta, 0x05, note, velocity)
            last_tick = event.tick
        elif event.kind == "note_off":
            midi_note = int(event.a or 0)
            note = midi_note - int(pitch_by_local.get(current_local, 0))
            if not 0 <= note <= 107:
                raise CseqEncodeError(
                    f"channel {channel + 1}: MIDI note {midi_note} becomes "
                    f"CSEQ note {note}, outside CTR's pitch table (0..107)"
                )
            out += _event(delta, 0x01, note)
            last_tick = event.tick

    end_tick = last_tick if loop_end_tick is None else max(last_tick, int(loop_end_tick))
    marker_was_emitted = loop_marker_emitted
    last_tick, loop_marker_emitted = _emit_loop_marker_if_due(
        out, last_tick, end_tick, loop_start_tick, loop_marker_emitted
    )
    if loop_marker_emitted and not marker_was_emitted:
        out += _event(0, 0x09, current_local)
        out += _event(0, 0x06, current_volume)
        out += _event(0, 0x07, current_pan)
    if loop_start_tick is not None and not loop_marker_emitted:
        raise CseqEncodeError(
            f"channel {channel + 1}: loop-start marker is beyond the song end"
        )
    out += _event(end_tick - last_tick, 0x03)
    return SequenceBuild(channel, False, bytes(out))


def build_zoned_melodic_sequence(
    midi: MidiFile,
    channel: int,
    resolve_note: Callable[[int], tuple[int, int]],
    default_local_instrument: int,
    loop_end_tick: int | None = None,
    loop_start_tick: int | None = None,
) -> SequenceBuild:
    """Build a melodic sequence whose sample can change by MIDI key.

    resolve_note(note) returns (local_instrument_id, midi_pitch_offset).
    This is what lets one SF2 preset keep multiple key zones inside one CSEQ
    channel instead of flattening the whole SoundFont to a single sample.
    """
    source = _events_through_loop_end(_channel_events(midi, channel), loop_end_tick)
    out = bytearray()
    last_tick = 0
    current_local = default_local_instrument
    active_note_pitch: dict[int, list[int]] = {}
    loop_marker_emitted = False
    current_channel_volume = 127
    current_expression = 127
    current_volume = _effective_volume_u8(
        current_channel_volume, current_expression
    )
    current_pan = 0x80

    out += _event(0, 0x09, current_local)

    for event in source:
        if event.tick < last_tick:
            raise CseqEncodeError("events are not sorted")

        # The GUI maps one chosen source to the whole channel. Source MIDI
        # program changes are therefore intentionally ignored without
        # consuming timeline time.
        if event.kind == "program_change":
            continue

        marker_was_emitted = loop_marker_emitted
        last_tick, loop_marker_emitted = _emit_loop_marker_if_due(
            out, last_tick, event.tick, loop_start_tick, loop_marker_emitted
        )
        if loop_marker_emitted and not marker_was_emitted:
            out += _event(0, 0x09, current_local)
            out += _event(0, 0x06, current_volume)
            out += _event(0, 0x07, current_pan)
        delta = event.tick - last_tick
        if event.kind == "volume":
            current_channel_volume = int(event.b or 0)
            current_volume = _effective_volume_u8(
                current_channel_volume, current_expression
            )
            out += _event(delta, 0x06, current_volume)
            last_tick = event.tick
        elif event.kind == "expression":
            current_expression = int(event.b or 0)
            current_volume = _effective_volume_u8(
                current_channel_volume, current_expression
            )
            out += _event(delta, 0x06, current_volume)
            last_tick = event.tick
        elif event.kind == "pan":
            current_pan = _u8_scaled(int(event.b or 0))
            out += _event(delta, 0x07, current_pan)
            last_tick = event.tick
        elif event.kind == "note_on":
            midi_note = int(event.a or 0)
            local_id, midi_pitch = resolve_note(midi_note)
            if local_id != current_local:
                out += _event(delta, 0x09, local_id)
                current_local = local_id
                last_tick = event.tick
                delta = 0

            note = midi_note - int(midi_pitch)
            if not 0 <= note <= 107:
                raise CseqEncodeError(
                    f"channel {channel + 1}: MIDI note {midi_note} becomes "
                    f"CSEQ note {note}, outside CTR's pitch table (0..107)"
                )
            out += _event(delta, 0x05, note, _u8_scaled(int(event.b or 0)))
            active_note_pitch.setdefault(midi_note, []).append(int(midi_pitch))
            last_tick = event.tick
        elif event.kind == "note_off":
            midi_note = int(event.a or 0)
            stack = active_note_pitch.get(midi_note)
            if stack:
                midi_pitch = stack.pop(0)
                if not stack:
                    active_note_pitch.pop(midi_note, None)
            else:
                _local_id, midi_pitch = resolve_note(midi_note)

            note = midi_note - int(midi_pitch)
            if not 0 <= note <= 107:
                raise CseqEncodeError(
                    f"channel {channel + 1}: MIDI note {midi_note} becomes "
                    f"CSEQ note {note}, outside CTR's pitch table (0..107)"
                )
            out += _event(delta, 0x01, note)
            last_tick = event.tick

    end_tick = last_tick if loop_end_tick is None else max(last_tick, int(loop_end_tick))
    marker_was_emitted = loop_marker_emitted
    last_tick, loop_marker_emitted = _emit_loop_marker_if_due(
        out, last_tick, end_tick, loop_start_tick, loop_marker_emitted
    )
    if loop_marker_emitted and not marker_was_emitted:
        out += _event(0, 0x09, current_local)
        out += _event(0, 0x06, current_volume)
        out += _event(0, 0x07, current_pan)
    if loop_start_tick is not None and not loop_marker_emitted:
        raise CseqEncodeError(
            f"channel {channel + 1}: loop-start marker is beyond the song end"
        )
    out += _event(end_tick - last_tick, 0x03)
    return SequenceBuild(channel, False, bytes(out))


def build_drum_sequence(
    midi: MidiFile,
    channel: int,
    note_to_local_drum: dict[int, int],
    loop_end_tick: int | None = None,
    loop_start_tick: int | None = None,
) -> SequenceBuild:
    source = _events_through_loop_end(
        [
            e for e in midi.events
            if e.channel == channel and e.kind in ("note_on", "note_off", "volume", "expression", "pan")
        ],
        loop_end_tick,
    )
    out = bytearray()
    last_tick = 0
    loop_marker_emitted = False
    current_channel_volume = 127
    current_expression = 127
    current_volume = _effective_volume_u8(
        current_channel_volume, current_expression
    )
    current_pan = 0x80

    for event in source:
        marker_was_emitted = loop_marker_emitted
        last_tick, loop_marker_emitted = _emit_loop_marker_if_due(
            out, last_tick, event.tick, loop_start_tick, loop_marker_emitted
        )
        if loop_marker_emitted and not marker_was_emitted:
            out += _event(0, 0x06, current_volume)
            out += _event(0, 0x07, current_pan)
        delta = event.tick - last_tick
        if event.kind == "volume":
            current_channel_volume = int(event.b or 0)
            current_volume = _effective_volume_u8(
                current_channel_volume, current_expression
            )
            out += _event(delta, 0x06, current_volume)
            last_tick = event.tick
        elif event.kind == "expression":
            current_expression = int(event.b or 0)
            current_volume = _effective_volume_u8(
                current_channel_volume, current_expression
            )
            out += _event(delta, 0x06, current_volume)
            last_tick = event.tick
        elif event.kind == "pan":
            current_pan = _u8_scaled(int(event.b or 0))
            out += _event(delta, 0x07, current_pan)
            last_tick = event.tick
        elif event.kind in ("note_on", "note_off"):
            midi_note = int(event.a or 0)
            if midi_note not in note_to_local_drum:
                # Explicitly unassigned drum notes are omitted from the CSEQ.
                continue
            drum_id = note_to_local_drum[midi_note]
            if event.kind == "note_on":
                out += _event(delta, 0x05, drum_id, _u8_scaled(int(event.b or 0)))
            else:
                out += _event(delta, 0x01, drum_id)
            last_tick = event.tick

    end_tick = last_tick if loop_end_tick is None else max(last_tick, int(loop_end_tick))
    marker_was_emitted = loop_marker_emitted
    last_tick, loop_marker_emitted = _emit_loop_marker_if_due(
        out, last_tick, end_tick, loop_start_tick, loop_marker_emitted
    )
    if loop_marker_emitted and not marker_was_emitted:
        out += _event(0, 0x06, current_volume)
        out += _event(0, 0x07, current_pan)
    if loop_start_tick is not None and not loop_marker_emitted:
        raise CseqEncodeError(
            f"channel {channel + 1}: loop-start marker is beyond the song end"
        )
    out += _event(end_tick - last_tick, 0x03)
    return SequenceBuild(channel, True, bytes(out))


def build_one_song_pack(
    midi: MidiFile,
    instruments: Iterable[RetailInstrument],
    drums: Iterable[RetailDrum],
    sequences: list[SequenceBuild],
    bpm: int | None = None,
) -> bytes:
    """Build one CSEQ pack containing one song.

    The caller owns mapping policy. This routine only serializes confirmed
    CSEQ structures/opcodes.
    """
    inst = list(instruments)
    drum = list(drums)
    if len(inst) > 255 or len(drum) > 255:
        raise CseqEncodeError("CSEQ sample table count exceeds u8")
    if len(sequences) > 24:
        raise CseqEncodeError("song has more than CTR's 24 sequence slots")
    if not sequences:
        raise CseqEncodeError("song has no sequences")

    bpm_value = _first_bpm(midi) if bpm is None else int(bpm)
    tpqn = midi.ticks_per_quarter
    if not (1 <= bpm_value <= 32767):
        raise CseqEncodeError("BPM outside signed 16-bit positive range")
    if not (1 <= tpqn <= 32767):
        raise CseqEncodeError("TPQN outside signed 16-bit positive range")

    # Song-local sequence area.
    song = bytearray()
    song += struct.pack("<BBhh", 0, len(sequences), bpm_value, tpqn)
    seq_table_pos = len(song)
    song += b"\x00" * (2 * len(sequences))
    while len(song) & 3:
        song.append(0)
    seq_base = len(song)

    seq_offsets: list[int] = []
    for seq in sequences:
        rel = len(song) - seq_base
        if rel > 0xFFFF:
            raise CseqEncodeError("sequence offset exceeds u16")
        seq_offsets.append(rel)
        # Retail SongNoteHeader is {flags, unk}; the second byte is not a
        # MIDI channel number. Keep it zero like retail CSEQ tracks.
        song += bytes((1 if seq.is_drums else 0, 0))
        song += seq.payload

    for i, rel in enumerate(seq_offsets):
        struct.pack_into("<H", song, seq_table_pos + i * 2, rel)

    # CSEQ pack metadata.
    meta = bytearray(b"\x00" * 8)
    for x in inst:
        meta += struct.pack(
            "<BBhhhhh",
            1,
            max(0, min(255, x.volume)),
            0,
            x.base_pitch,
            x.spu_index,
            x.ad,
            x.sr,
        )
    for x in drum:
        meta += struct.pack(
            "<BBhhh",
            1,
            max(0, min(255, x.volume)),
            x.pitch,
            x.spu_index,
            0,
        )

    # One song; its offset within songData is zero.
    meta += struct.pack("<H", 0)
    while len(meta) & 3:
        meta.append(0)

    result = meta + song
    struct.pack_into("<IBBH", result, 0, len(result), len(inst), len(drum), 1)
    return bytes(result)


def _instrument_signature(obj: object) -> tuple[int, int, int, int, int]:
    return (
        int(getattr(obj, "spu_index")),
        int(getattr(obj, "volume")),
        int(getattr(obj, "base_pitch")),
        int(getattr(obj, "ad")),
        int(getattr(obj, "sr")),
    )


def build_project_with_zones(
    midi: MidiFile,
    channel_zones: dict[int, list[MelodicInstrumentZone]],
    drum_note_to_instrument: dict[int, RetailDrum],
    loop_start_tick: int | None = None,
) -> bytes:
    """Build one song using retail instruments and/or SF2-derived key zones."""
    unique_inst: list[object] = []
    inst_local: dict[tuple[int, int, int, int, int], int] = {}

    for ch in sorted(channel_zones):
        for zone in channel_zones[ch]:
            sig = _instrument_signature(zone.instrument)
            if sig not in inst_local:
                inst_local[sig] = len(unique_inst)
                unique_inst.append(zone.instrument)

    unique_drums: list[RetailDrum] = []
    drum_local_by_global: dict[int, int] = {}
    note_to_local: dict[int, int] = {}
    for note, obj in sorted(drum_note_to_instrument.items()):
        if obj.global_id not in drum_local_by_global:
            drum_local_by_global[obj.global_id] = len(unique_drums)
            unique_drums.append(obj)
        note_to_local[note] = drum_local_by_global[obj.global_id]

    loop_end_tick = _song_loop_end_tick(midi)
    seqs: list[SequenceBuild] = []
    channels_with_notes = sorted({
        int(e.channel) for e in midi.events
        if e.channel is not None and e.kind in ("note_on", "note_off")
    })

    for ch in channels_with_notes:
        if ch == 9:
            if note_to_local:
                seqs.append(
                    build_drum_sequence(
                        midi,
                        ch,
                        note_to_local,
                        loop_end_tick,
                        loop_start_tick,
                    )
                )
            continue

        zones = channel_zones.get(ch, [])
        if not zones:
            continue

        def resolve(note: int, zones=zones) -> tuple[int, int]:
            matches = [z for z in zones if z.contains(note)]
            if matches:
                zone = min(
                    matches,
                    key=lambda z: (z.key_high - z.key_low, abs(((z.key_low + z.key_high) // 2) - note)),
                )
            else:
                zone = min(
                    zones,
                    key=lambda z: min(abs(note - z.key_low), abs(note - z.key_high)),
                )
            return inst_local[_instrument_signature(zone.instrument)], zone.midi_pitch

        default_zone = zones[0]
        default_local = inst_local[_instrument_signature(default_zone.instrument)]
        seqs.append(
            build_zoned_melodic_sequence(
                midi,
                ch,
                resolve,
                default_local,
                loop_end_tick,
                loop_start_tick,
            )
        )

    return build_one_song_pack(midi, unique_inst, unique_drums, seqs)


def build_simple_retail_project(
    midi: MidiFile,
    channel_to_instrument: dict[int, RetailInstrument],
    drum_note_to_instrument: dict[int, RetailDrum],
    loop_start_tick: int | None = None,
) -> bytes:
    """Convenience MVP builder with one fixed melodic instrument per channel."""
    unique_inst: list[RetailInstrument] = []
    inst_local: dict[int, int] = {}
    for ch in sorted(channel_to_instrument):
        obj = channel_to_instrument[ch]
        if obj.global_id not in inst_local:
            inst_local[obj.global_id] = len(unique_inst)
            unique_inst.append(obj)

    unique_drums: list[RetailDrum] = []
    drum_local_by_global: dict[int, int] = {}
    note_to_local: dict[int, int] = {}
    for note, obj in sorted(drum_note_to_instrument.items()):
        if obj.global_id not in drum_local_by_global:
            drum_local_by_global[obj.global_id] = len(unique_drums)
            unique_drums.append(obj)
        note_to_local[note] = drum_local_by_global[obj.global_id]

    seqs: list[SequenceBuild] = []
    loop_end_tick = _song_loop_end_tick(midi)
    channels_with_notes = sorted({
        e.channel for e in midi.events
        if e.channel is not None and e.kind in ("note_on", "note_off")
    })
    for ch in channels_with_notes:
        if ch == 9:
            if note_to_local:
                seqs.append(
                    build_drum_sequence(
                        midi,
                        ch,
                        note_to_local,
                        loop_end_tick,
                        loop_start_tick,
                    )
                )
            continue
        if ch not in channel_to_instrument:
            # Explicitly unassigned melodic channels are omitted from the CSEQ.
            continue
        obj = channel_to_instrument[ch]
        local = inst_local[obj.global_id]
        # Any program number encountered maps to the same chosen instrument in
        # this simple mode. Advanced projects can call build_melodic_sequence.
        programs = {
            int(e.a) for e in midi.events
            if e.channel == ch and e.kind == "program_change" and e.a is not None
        }
        program_map = {p: local for p in programs}
        program_map.setdefault(0, local)
        seqs.append(
            build_melodic_sequence(
                midi,
                ch,
                program_map,
                local,
                {local: obj.midi_pitch},
                loop_end_tick,
                loop_start_tick,
            )
        )

    return build_one_song_pack(midi, unique_inst, unique_drums, seqs)
