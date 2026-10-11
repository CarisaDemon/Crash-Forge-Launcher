"""Validation helpers for MIDI projects targeting CTR CSEQ."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from collections import defaultdict
from midi_reader import MidiFile


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str


@dataclass
class ValidationReport:
    peak_polyphony: int
    peak_polyphony_tick: int
    issues: list[ValidationIssue]

    def to_dict(self) -> dict:
        return {
            "peak_polyphony": self.peak_polyphony,
            "peak_polyphony_tick": self.peak_polyphony_tick,
            "issues": [asdict(x) for x in self.issues],
        }


SUPPORTED_EVENT_KINDS = {
    "note_on",
    "note_off",
    "program_change",
    "volume",
    "pan",
    "expression",
    "pitch_bend",
    "tempo",
    "marker",
    "track_name",
    "time_signature",
    "end_of_track",
    "meta",
}


def _polyphony(midi: MidiFile) -> tuple[int, int]:
    active: dict[tuple[int, int], int] = defaultdict(int)
    total = 0
    peak = 0
    peak_tick = 0

    # Note offs first at a shared tick so legato hand-off does not count as
    # an artificial extra voice.
    ordered = sorted(
        (e for e in midi.events if e.kind in ("note_on", "note_off")),
        key=lambda e: (e.tick, 0 if e.kind == "note_off" else 1, e.track, e.order),
    )

    for event in ordered:
        if event.channel is None or event.a is None:
            continue
        key = (event.channel, int(event.a))
        if event.kind == "note_on":
            active[key] += 1
            total += 1
            if total > peak:
                peak = total
                peak_tick = event.tick
        else:
            if active[key] > 0:
                active[key] -= 1
                total -= 1

    return peak, peak_tick


def validate_midi(midi: MidiFile, voice_limit: int = 24) -> ValidationReport:
    issues: list[ValidationIssue] = []
    peak, peak_tick = _polyphony(midi)

    if not any(e.kind == "tempo" for e in midi.events):
        issues.append(
            ValidationIssue(
                "warning",
                "NO_TEMPO",
                "MIDI has no tempo event; builder will need an explicit/default BPM.",
            )
        )

    if peak > voice_limit:
        issues.append(
            ValidationIssue(
                "warning",
                "VOICE_LIMIT",
                f"Peak polyphony is {peak} voices at tick {peak_tick}; CTR currently exposes {voice_limit} music/SFX channels.",
            )
        )

    channels = {e.channel for e in midi.events if e.channel is not None}
    if 9 in channels:
        drum_notes = {
            int(e.a)
            for e in midi.events
            if e.channel == 9 and e.kind == "note_on" and e.a is not None
        }
        if len(drum_notes) > 255:
            issues.append(
                ValidationIssue(
                    "error",
                    "DRUM_TABLE_TOO_LARGE",
                    "Channel 10 uses more than 255 distinct drum notes; CSEQ short-sample count is u8.",
                )
            )

    programs_by_channel: dict[int, set[int]] = defaultdict(set)
    for event in midi.events:
        if event.kind == "program_change" and event.channel is not None and event.a is not None:
            programs_by_channel[event.channel].add(int(event.a))

    for channel, programs in sorted(programs_by_channel.items()):
        if channel != 9 and len(programs) > 1:
            issues.append(
                ValidationIssue(
                    "info",
                    "PROGRAM_CHANGES",
                    f"Channel {channel + 1} changes program during the song ({sorted(programs)}); CSEQ can represent this but mapping must be explicit.",
                )
            )

    unsupported = sorted({
        e.kind
        for e in midi.events
        if e.kind not in SUPPORTED_EVENT_KINDS and e.kind not in ("sysex", "system")
    })
    if unsupported:
        issues.append(
            ValidationIssue(
                "warning",
                "UNSUPPORTED_EVENTS",
                "Unsupported event kinds: " + ", ".join(unsupported),
            )
        )

    if any(e.kind == "sysex" for e in midi.events):
        issues.append(
            ValidationIssue(
                "warning",
                "SYSEX_IGNORED",
                "SysEx events are present and are not representable in the CSEQ MVP.",
            )
        )

    if any(e.kind == "pitch_bend" for e in midi.events):
        issues.append(
            ValidationIssue(
                "warning",
                "PITCH_BEND_NOT_ENCODED",
                "Pitch bend is read and preserved in analysis, but the MVP encoder does not map it to CSEQ distortion yet.",
            )
        )

    tempo_events = [e for e in midi.events if e.kind == "tempo" and e.a]
    if len(tempo_events) > 1:
        issues.append(
            ValidationIssue(
                "warning",
                "TEMPO_CHANGES_NOT_ENCODED",
                f"MIDI contains {len(tempo_events)} tempo events; current CSEQ builder uses only the first BPM.",
            )
        )

    extreme_tempos = []
    for e in midi.events:
        if e.kind == "tempo" and e.a:
            bpm = 60000000.0 / e.a
            if bpm < 20 or bpm > 400:
                extreme_tempos.append((e.tick, bpm))
    if extreme_tempos:
        issues.append(
            ValidationIssue(
                "warning",
                "EXTREME_TEMPO",
                f"Found {len(extreme_tempos)} tempo event(s) outside 20..400 BPM.",
            )
        )

    return ValidationReport(peak, peak_tick, issues)
