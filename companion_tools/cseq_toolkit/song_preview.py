"""Render a MIDI preview with the currently assigned retail CTR instruments.

The renderer is intentionally lightweight and local to the authoring tool:
- timing comes from the source MIDI,
- melodic channels use the selected retail HOWL instrument,
- Channel 10 uses the selected retail drum per MIDI note,
- unmapped channels/notes are simply skipped,
- the original KART.HWL SPU-ADPCM samples are decoded directly.

It is a preview renderer, not the in-game HOWL mixer. ADSR/reverb/distortion are
approximated or omitted, but pitch follows CTR's note-frequency convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import ctypes
import tempfile
import time
import wave

import numpy as np

try:
    import winsound
except ImportError:  # pragma: no cover
    winsound = None

from instrument_map import DEFAULT_AUDIT_DIR, RetailDrum, RetailInstrument
from midi_reader import MidiFile
from sf2_import import SoundFont, Sf2Preset, Sf2Zone, zone_base_pitch, zone_for_note, zone_volume


_FILTERS = (
    (0, 0),
    (60, 0),
    (115, -52),
    (98, -55),
    (122, -60),
)

OUTPUT_RATE = 32000
_RELEASE_SECONDS = 0.045
_GLOBAL_GAIN = 0.42

_last_render_path: Path | None = None

# The old song transport used WinMM/MCI. On some Windows audio setups MCI
# reports "playing" but produces no audible output, while winsound works
# normally (the tool's Audition buttons already prove that path works).
#
# Keep the public transport API unchanged, but use winsound for playback and
# track pause/seek position ourselves.
_transport_path: Path | None = None
_transport_mode = "closed"
_transport_length_ms = 0
_transport_position_ms = 0
_transport_play_start_ms = 0
_transport_started_at = 0.0
_transport_segment_path: Path | None = None


def _wav_length_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as wav:
        rate = max(1, int(wav.getframerate()))
        return max(0, int(round(wav.getnframes() * 1000.0 / rate)))


def _cleanup_transport_segment() -> None:
    global _transport_segment_path
    p = _transport_segment_path
    _transport_segment_path = None
    if p is not None:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def _render_transport_segment(path: Path, start_ms: int) -> Path:
    """Create a WAV beginning at start_ms so winsound can support seeking."""
    global _transport_segment_path

    _cleanup_transport_segment()

    with wave.open(str(path), "rb") as source:
        rate = max(1, int(source.getframerate()))
        start_frame = max(
            0,
            min(
                source.getnframes(),
                int(round(max(0, start_ms) * rate / 1000.0)),
            ),
        )
        source.setpos(start_frame)

        temp = tempfile.NamedTemporaryFile(
            prefix="cfr_song_transport_",
            suffix=".wav",
            delete=False,
        )
        out = Path(temp.name)
        temp.close()

        with wave.open(str(out), "wb") as target:
            target.setparams(source.getparams())
            while True:
                chunk = source.readframes(65536)
                if not chunk:
                    break
                target.writeframes(chunk)

    _transport_segment_path = out
    return out


def close_song_preview() -> None:
    global _transport_path
    global _transport_mode
    global _transport_length_ms
    global _transport_position_ms
    global _transport_play_start_ms
    global _transport_started_at

    if winsound is not None:
        try:
            winsound.PlaySound(None, 0)
        except Exception:
            pass

    _cleanup_transport_segment()
    _transport_path = None
    _transport_mode = "closed"
    _transport_length_ms = 0
    _transport_position_ms = 0
    _transport_play_start_ms = 0
    _transport_started_at = 0.0


def open_song_preview(path: str | Path) -> Path:
    global _transport_path
    global _transport_mode
    global _transport_length_ms
    global _transport_position_ms
    global _transport_play_start_ms
    global _transport_started_at

    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(p)

    if winsound is None:
        raise RuntimeError("Preview transport currently requires Windows")

    try:
        winsound.PlaySound(None, 0)
    except Exception:
        pass
    _cleanup_transport_segment()

    _transport_path = p
    _transport_length_ms = _wav_length_ms(p)
    _transport_mode = "stopped"
    _transport_position_ms = 0
    _transport_play_start_ms = 0
    _transport_started_at = 0.0
    return p


def _transport_current_position() -> int:
    global _transport_mode
    global _transport_position_ms

    if _transport_mode != "playing":
        return max(0, min(_transport_length_ms, _transport_position_ms))

    elapsed = max(0, int(round((time.monotonic() - _transport_started_at) * 1000.0)))
    pos = max(0, _transport_play_start_ms + elapsed)

    if _transport_length_ms > 0 and pos >= _transport_length_ms:
        _transport_position_ms = _transport_length_ms
        _transport_mode = "stopped"
        _cleanup_transport_segment()
        return _transport_length_ms

    _transport_position_ms = pos
    return pos


def play_rendered_preview(
    path: str | Path | None = None,
    start_ms: int | None = None,
) -> None:
    global _transport_mode
    global _transport_position_ms
    global _transport_play_start_ms
    global _transport_started_at

    if winsound is None:
        raise RuntimeError("Preview transport currently requires Windows")

    if path is not None:
        p = Path(path).resolve()
        if _transport_path != p or _transport_mode == "closed":
            open_song_preview(p)

    if _transport_path is None:
        raise RuntimeError("Render a song preview first")

    if start_ms is None:
        if _transport_mode == "paused":
            start_ms = _transport_current_position()
        else:
            start_ms = 0

    start = max(0, int(start_ms))
    if _transport_length_ms > 0:
        if start >= _transport_length_ms:
            start = 0
        else:
            start = min(start, _transport_length_ms - 1)

    winsound.PlaySound(None, 0)

    if start <= 0:
        _cleanup_transport_segment()
        source = _transport_path
    else:
        source = _render_transport_segment(_transport_path, start)

    winsound.PlaySound(
        str(source),
        winsound.SND_FILENAME
        | winsound.SND_ASYNC
        | winsound.SND_NODEFAULT,
    )

    _transport_mode = "playing"
    _transport_position_ms = start
    _transport_play_start_ms = start
    _transport_started_at = time.monotonic()


def pause_song_preview() -> None:
    global _transport_mode
    global _transport_position_ms
    global _transport_started_at

    if _transport_path is None or winsound is None:
        return

    if _transport_mode == "playing":
        position = _transport_current_position()
        winsound.PlaySound(None, 0)
        _transport_position_ms = position
        _transport_started_at = 0.0
        _transport_mode = "paused"


def stop_song_preview() -> None:
    global _transport_mode
    global _transport_position_ms
    global _transport_play_start_ms
    global _transport_started_at

    if winsound is not None:
        try:
            winsound.PlaySound(None, 0)
        except Exception:
            pass

    _cleanup_transport_segment()
    if _transport_path is None:
        _transport_mode = "closed"
    else:
        _transport_mode = "stopped"
    _transport_position_ms = 0
    _transport_play_start_ms = 0
    _transport_started_at = 0.0


def song_preview_state() -> tuple[str, int, int]:
    if _transport_path is None:
        return "closed", 0, 0

    pos = _transport_current_position()
    return _transport_mode, int(pos), int(_transport_length_ms)


# Exact 108-entry retail table from game/zGlobal_DATA.c::data.noteFrequency.
# HOWL initializes music distortion to 0x80, so howl_InstrumentPitch() indexes
# this table with the raw CSEQ note directly. Index 60 is 0x1000 (unity).
CTR_NOTE_FREQUENCY = (
    0x0080, 0x0087, 0x008F, 0x0098, 0x00A1, 0x00AA, 0x00B5, 0x00BF,
    0x00CB, 0x00D7, 0x00E4, 0x00F1, 0x0100, 0x010F, 0x011F, 0x0130,
    0x0142, 0x0155, 0x016A, 0x017F, 0x0196, 0x01AE, 0x01C8, 0x01E3,
    0x0200, 0x021E, 0x023E, 0x0260, 0x0285, 0x02AB, 0x02D4, 0x02FF,
    0x032C, 0x035D, 0x0390, 0x03C6, 0x0400, 0x043C, 0x047D, 0x04C1,
    0x050A, 0x0556, 0x05A8, 0x05FE, 0x0659, 0x06BA, 0x0720, 0x078D,
    0x0800, 0x0879, 0x08FA, 0x0983, 0x0A14, 0x0AAD, 0x0B50, 0x0BFC,
    0x0CB2, 0x0D74, 0x0E41, 0x0F1A, 0x1000, 0x10F3, 0x11F5, 0x1306,
    0x1428, 0x155B, 0x16A0, 0x17F9, 0x1965, 0x1AE8, 0x1C82, 0x1E34,
    0x2000, 0x21E7, 0x23EB, 0x260D, 0x2851, 0x2AB7, 0x2D41, 0x2FF2,
    0x32CB, 0x35D1, 0x3904, 0x3C68, 0x4000, 0x43CE, 0x47D6, 0x4C1B,
    0x50A2, 0x556E, 0x5A82, 0x5FE4, 0x6597, 0x6BA2, 0x7208, 0x78D0,
    0x8000, 0x879C, 0x8FAC, 0x9837, 0xA145, 0xAADC, 0xB504, 0xBFC8,
    0xCB2F, 0xD744, 0xE411, 0xF1A1,
)


@dataclass(frozen=True)
class DecodedSample:
    pcm: np.ndarray
    loop_start: int | None
    loop_end: int | None


@dataclass
class _ActiveNote:
    start_seconds: float
    velocity: int
    volume: int
    pan: int


@dataclass(frozen=True)
class _Voice:
    channel: int
    start_seconds: float
    end_seconds: float | None
    note: int
    velocity: int
    volume: int
    pan: int
    spu_index: int
    pitch: int
    is_drum: bool
    sf2_zone: Sf2Zone | None = None
    sample_gain: float = 1.0


_sample_cache: dict[tuple[Path, int], DecodedSample] = {}
_sf2_sample_cache: dict[tuple[Path, int, bool], DecodedSample] = {}


def _clamp16(value: int) -> int:
    return max(-32768, min(32767, value))


def _load_storage(audit_dir: Path) -> dict[int, tuple[int, int]]:
    path = audit_dir / "sample_storage_catalog.csv"
    out: dict[int, tuple[int, int]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            idx = int(row["spuIndex"])
            off = row.get("firstHwlOffset", "").strip()
            size = row.get("bytes", "").strip()
            if off and size:
                out[idx] = (int(off), int(size))
    return out


def _decode_spu_sample(blob: bytes) -> DecodedSample:
    pcm: list[int] = []
    hist1 = 0
    hist2 = 0
    loop_start: int | None = None
    loop_end: int | None = None

    for off in range(0, len(blob) - 15, 16):
        frame = blob[off : off + 16]
        predictor = (frame[0] >> 4) & 0x0F
        shift = frame[0] & 0x0F
        flags = frame[1]
        if predictor >= len(_FILTERS):
            predictor = 0
        f0, f1 = _FILTERS[predictor]

        frame_start = len(pcm)
        if flags & 0x04:
            loop_start = frame_start

        for packed in frame[2:16]:
            for nibble in (packed & 0x0F, (packed >> 4) & 0x0F):
                if nibble & 0x08:
                    nibble -= 0x10
                sample = (nibble << 12) >> shift
                sample += (hist1 * f0 + hist2 * f1 + 32) >> 6
                sample = _clamp16(sample)
                pcm.append(sample)
                hist2 = hist1
                hist1 = sample

        if flags & 0x01:
            if (flags & 0x02) and loop_start is not None:
                loop_end = len(pcm)
            break

    arr = np.asarray(pcm, dtype=np.float32)
    if arr.size:
        arr /= 32768.0
    return DecodedSample(arr, loop_start, loop_end)


def _get_sample(spu_index: int, audit_dir: Path) -> DecodedSample:
    key = (audit_dir.resolve(), int(spu_index))
    cached = _sample_cache.get(key)
    if cached is not None:
        return cached

    storage = _load_storage(audit_dir)
    if spu_index not in storage:
        raise ValueError(f"SPU sample {spu_index} has no stored HOWL blob")

    hwl = (audit_dir / "KART.HWL").read_bytes()
    off, size = storage[spu_index]
    if off < 0 or size <= 0 or off + size > len(hwl):
        raise ValueError(f"Invalid HOWL range for SPU sample {spu_index}")

    decoded = _decode_spu_sample(hwl[off : off + size])
    if decoded.pcm.size == 0:
        raise ValueError(f"SPU sample {spu_index} decoded to no PCM")
    _sample_cache[key] = decoded
    return decoded


def _get_sf2_sample(sf: SoundFont, zone: Sf2Zone) -> DecodedSample:
    cache_key = (sf.path.resolve(), int(zone.sample_index), bool(zone.loop_enabled))
    cached = _sf2_sample_cache.get(cache_key)
    if cached is not None:
        return cached

    sample = sf.samples[zone.sample_index]
    start = max(0, int(sample.start))
    end = min(len(sf.sample_pcm) // 2, int(sample.end))
    if end <= start:
        raise ValueError(f"SF2 sample {sample.name!r} has an invalid PCM range")

    raw = sf.sample_pcm[start * 2:end * 2]
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if pcm.size == 0:
        raise ValueError(f"SF2 sample {sample.name!r} decoded to no PCM")
    pcm /= 32768.0

    loop_start: int | None = None
    loop_end: int | None = None
    if zone.loop_enabled:
        ls = max(0, int(sample.loop_start) - start)
        le = min(end - start, int(sample.loop_end) - start)
        if le > ls:
            loop_start = ls
            loop_end = le

    decoded = DecodedSample(pcm, loop_start, loop_end)
    _sf2_sample_cache[cache_key] = decoded
    return decoded


def _timed_events(midi: MidiFile) -> list[tuple[object, float]]:
    """Return source events with absolute seconds using the MIDI tempo map."""
    tempo_us = 500000
    last_tick = 0
    seconds = 0.0
    result: list[tuple[object, float]] = []

    for event in sorted(midi.events, key=lambda e: (e.tick, e.track, e.order)):
        delta = event.tick - last_tick
        if delta:
            seconds += (
                delta * tempo_us
                / (1_000_000.0 * float(midi.ticks_per_quarter))
            )
            last_tick = event.tick

        result.append((event, seconds))
        if event.kind == "tempo" and event.a:
            tempo_us = int(event.a)

    return result


def _channel_volume_automation(
    midi: MidiFile,
) -> dict[int, list[tuple[float, float]]]:
    """Build stepwise effective CC7*CC11 gain curves per MIDI channel."""
    volume = {ch: 127 for ch in range(16)}
    expression = {ch: 127 for ch in range(16)}
    curves = {ch: [(0.0, 1.0)] for ch in range(16)}

    for event, seconds in _timed_events(midi):
        ch = event.channel
        if ch is None or event.b is None:
            continue

        if event.kind == "volume":
            volume[ch] = max(0, min(127, int(event.b)))
        elif event.kind == "expression":
            expression[ch] = max(0, min(127, int(event.b)))
        else:
            continue

        gain = (
            float(volume[ch]) * float(expression[ch])
            / float(127 * 127)
        )
        if abs(curves[ch][-1][0] - seconds) < 1e-9:
            curves[ch][-1] = (seconds, gain)
        elif abs(curves[ch][-1][1] - gain) > 1e-9:
            curves[ch].append((seconds, gain))

    return curves


def _apply_volume_automation(
    mono: np.ndarray,
    start_seconds: float,
    events: list[tuple[float, float]],
) -> np.ndarray:
    if mono.size == 0:
        return mono

    out = mono.copy()
    end_seconds = start_seconds + out.size / float(OUTPUT_RATE)

    current_gain = 1.0
    future: list[tuple[float, float]] = []
    for seconds, gain in events:
        if seconds <= start_seconds + 1e-9:
            current_gain = gain
        elif seconds < end_seconds:
            future.append((seconds, gain))
        else:
            break

    cursor = 0
    for seconds, gain in future:
        frame = int(round((seconds - start_seconds) * OUTPUT_RATE))
        frame = max(cursor, min(out.size, frame))
        if frame > cursor:
            out[cursor:frame] *= current_gain
        current_gain = gain
        cursor = frame

    if cursor < out.size:
        out[cursor:] *= current_gain
    return out


def ctr_note_pitch(base_pitch: int, cseq_note: int) -> int:
    """Mirror retail HOWL pitch calculation for the normal 0x80 state.

    SongPool initializes music distortion to 0x80. In that state,
    howl_InstrumentPitch() indexes data.noteFrequency with the raw CSEQ note.
    Table index 60 is 0x1000, so CSEQ note 60 plays at base_pitch.
    """
    note = max(0, min(len(CTR_NOTE_FREQUENCY) - 1, int(cseq_note)))
    pitch = (int(base_pitch) * CTR_NOTE_FREQUENCY[note]) >> 12
    return max(1, min(0xFFFF, pitch))


def _collect_voices(
    midi: MidiFile,
    channel_map: dict[int, RetailInstrument | Sf2Preset],
    drum_map: dict[int, RetailDrum | Sf2Preset],
    soundfont: SoundFont | None = None,
) -> list[_Voice]:
    timed = _timed_events(midi)
    channel_volume = {ch: 127 for ch in range(16)}
    channel_pan = {ch: 64 for ch in range(16)}
    active: dict[tuple[int, int], list[_ActiveNote]] = {}
    voices: list[_Voice] = []
    song_end = timed[-1][1] if timed else 0.0

    def sf2_voice_values(preset: Sf2Preset, note: int, is_drum: bool):
        if soundfont is None:
            raise ValueError("Load the SoundFont used by this preview")
        zone = zone_for_note(preset, note)
        base_pitch = zone_base_pitch(soundfont, zone)
        if is_drum:
            pitch = int(round(base_pitch * (2.0 ** ((note - zone.root_key) / 12.0))))
        else:
            pitch = ctr_note_pitch(base_pitch, note - (zone.root_key - 60))
        gain = zone_volume(zone) / 255.0
        return zone, max(1, min(0xFFFF, pitch)), gain

    for event, seconds in timed:
        ch = event.channel
        if ch is None:
            continue

        if event.kind == "volume" and event.b is not None:
            channel_volume[ch] = int(event.b)
            continue
        if event.kind == "pan" and event.b is not None:
            channel_pan[ch] = int(event.b)
            continue

        if ch == 9:
            if event.kind != "note_on" or event.a is None:
                continue
            note = int(event.a)
            drum = drum_map.get(note)
            if drum is None:
                continue

            if isinstance(drum, Sf2Preset):
                zone, pitch, gain = sf2_voice_values(drum, note, True)
                voices.append(
                    _Voice(
                        channel=ch,
                        start_seconds=seconds,
                        end_seconds=None,
                        note=note,
                        velocity=int(event.b or 0),
                        volume=channel_volume[ch],
                        pan=channel_pan[ch],
                        spu_index=-1,
                        pitch=pitch,
                        is_drum=True,
                        sf2_zone=zone,
                        sample_gain=gain,
                    )
                )
            else:
                voices.append(
                    _Voice(
                        channel=ch,
                        start_seconds=seconds,
                        end_seconds=None,
                        note=note,
                        velocity=int(event.b or 0),
                        volume=channel_volume[ch],
                        pan=channel_pan[ch],
                        spu_index=drum.spu_index,
                        pitch=drum.pitch,
                        is_drum=True,
                    )
                )
            continue

        inst = channel_map.get(ch)
        if inst is None or event.a is None:
            continue

        note = int(event.a)
        key = (ch, note)
        if event.kind == "note_on":
            active.setdefault(key, []).append(
                _ActiveNote(
                    start_seconds=seconds,
                    velocity=int(event.b or 0),
                    volume=channel_volume[ch],
                    pan=channel_pan[ch],
                )
            )
        elif event.kind == "note_off":
            stack = active.get(key)
            if not stack:
                continue
            started = stack.pop(0)

            if isinstance(inst, Sf2Preset):
                zone, pitch, gain = sf2_voice_values(inst, note, False)
                voices.append(
                    _Voice(
                        channel=ch,
                        start_seconds=started.start_seconds,
                        end_seconds=max(seconds, started.start_seconds + 0.01),
                        note=note,
                        velocity=started.velocity,
                        volume=started.volume,
                        pan=started.pan,
                        spu_index=-1,
                        pitch=pitch,
                        is_drum=False,
                        sf2_zone=zone,
                        sample_gain=gain,
                    )
                )
            else:
                voices.append(
                    _Voice(
                        channel=ch,
                        start_seconds=started.start_seconds,
                        end_seconds=max(seconds, started.start_seconds + 0.01),
                        note=note,
                        velocity=started.velocity,
                        volume=started.volume,
                        pan=started.pan,
                        spu_index=inst.spu_index,
                        pitch=ctr_note_pitch(
                            inst.base_pitch,
                            note - inst.midi_pitch,
                        ),
                        is_drum=False,
                    )
                )

    for (ch, note), stack in active.items():
        inst = channel_map.get(ch)
        if inst is None:
            continue
        for started in stack:
            if isinstance(inst, Sf2Preset):
                zone, pitch, gain = sf2_voice_values(inst, note, False)
                voices.append(
                    _Voice(
                        channel=ch,
                        start_seconds=started.start_seconds,
                        end_seconds=max(song_end, started.start_seconds + 0.1),
                        note=note,
                        velocity=started.velocity,
                        volume=started.volume,
                        pan=started.pan,
                        spu_index=-1,
                        pitch=pitch,
                        is_drum=False,
                        sf2_zone=zone,
                        sample_gain=gain,
                    )
                )
            else:
                voices.append(
                    _Voice(
                        channel=ch,
                        start_seconds=started.start_seconds,
                        end_seconds=max(song_end, started.start_seconds + 0.1),
                        note=note,
                        velocity=started.velocity,
                        volume=started.volume,
                        pan=started.pan,
                        spu_index=inst.spu_index,
                        pitch=ctr_note_pitch(
                            inst.base_pitch,
                            note - inst.midi_pitch,
                        ),
                        is_drum=False,
                    )
                )

    return voices


def _resample_voice(
    sample: DecodedSample,
    pitch: int,
    requested_seconds: float | None,
    is_drum: bool,
) -> np.ndarray:
    step = max(0.0001, (float(pitch) / 4096.0) * (44100.0 / OUTPUT_RATE))
    source = sample.pcm

    if is_drum or sample.loop_start is None or sample.loop_end is None:
        natural_frames = max(1, int(np.ceil(source.size / step)))
        if requested_seconds is None:
            out_frames = natural_frames
        else:
            out_frames = min(
                natural_frames,
                max(1, int((requested_seconds + _RELEASE_SECONDS) * OUTPUT_RATE)),
            )
        positions = np.arange(out_frames, dtype=np.float32) * step
        positions = np.minimum(positions, max(0, source.size - 1))
    else:
        target_seconds = max(0.02, float(requested_seconds or 0.02))
        out_frames = max(1, int((target_seconds + _RELEASE_SECONDS) * OUTPUT_RATE))
        positions = np.arange(out_frames, dtype=np.float32) * step
        ls = int(sample.loop_start)
        le = int(sample.loop_end)
        span = max(1, le - ls)
        mask = positions >= le
        positions[mask] = ls + np.mod(positions[mask] - ls, span)

    lo = np.floor(positions).astype(np.int64)
    hi = np.minimum(lo + 1, source.size - 1)
    frac = positions - lo
    out = source[lo] * (1.0 - frac) + source[hi] * frac

    if requested_seconds is not None and out.size:
        release_frames = min(out.size, max(1, int(_RELEASE_SECONDS * OUTPUT_RATE)))
        out[-release_frames:] *= np.linspace(1.0, 0.0, release_frames, dtype=np.float32)

    return out.astype(np.float32, copy=False)


def render_song_preview(
    midi: MidiFile,
    channel_map: dict[int, RetailInstrument | Sf2Preset],
    drum_map: dict[int, RetailDrum | Sf2Preset],
    audit_dir: str | Path = DEFAULT_AUDIT_DIR,
    soundfont: SoundFont | None = None,
) -> Path:
    if not channel_map and not drum_map:
        raise ValueError("Assign at least one instrument or drum before previewing the song.")

    voices = _collect_voices(midi, channel_map, drum_map, soundfont)
    if not voices:
        raise ValueError(
            "None of the currently assigned instruments are used by this MIDI."
        )

    root = Path(audit_dir)
    latest = 0.0
    prepared: list[tuple[_Voice, np.ndarray]] = []
    for voice in voices:
        requested = (
            None
            if voice.is_drum or voice.end_seconds is None
            else max(0.01, voice.end_seconds - voice.start_seconds)
        )
        if voice.sf2_zone is not None:
            if soundfont is None:
                raise ValueError("Load the SoundFont used by this preview")
            decoded = _get_sf2_sample(soundfont, voice.sf2_zone)
        else:
            decoded = _get_sample(voice.spu_index, root)
        rendered = _resample_voice(decoded, voice.pitch, requested, voice.is_drum)
        prepared.append((voice, rendered))
        latest = max(latest, voice.start_seconds + rendered.size / OUTPUT_RATE)

    total_frames = max(1, int(latest * OUTPUT_RATE))
    left = np.zeros(total_frames, dtype=np.float32)
    right = np.zeros(total_frames, dtype=np.float32)
    volume_automation = _channel_volume_automation(midi)

    for voice, mono in prepared:
        start = max(0, int(round(voice.start_seconds * OUTPUT_RATE)))
        end = min(total_frames, start + mono.size)
        if end <= start:
            continue
        mono = mono[: end - start]
        mono = _apply_volume_automation(
            mono,
            voice.start_seconds,
            volume_automation.get(voice.channel, [(0.0, 1.0)]),
        )

        amp = (
            (max(0, min(127, voice.velocity)) / 127.0)
            * max(0.0, min(1.0, voice.sample_gain))
            * _GLOBAL_GAIN
        )
        pan = max(0.0, min(1.0, voice.pan / 127.0))
        left_gain = np.sqrt(1.0 - pan) * amp
        right_gain = np.sqrt(pan) * amp
        left[start:end] += mono * left_gain
        right[start:end] += mono * right_gain

    peak = max(float(np.max(np.abs(left))), float(np.max(np.abs(right))), 1e-9)
    if peak > 0.97:
        scale = 0.97 / peak
        left *= scale
        right *= scale

    stereo = np.empty(total_frames * 2, dtype=np.int16)
    stereo[0::2] = np.clip(left * 32767.0, -32768, 32767).astype(np.int16)
    stereo[1::2] = np.clip(right * 32767.0, -32768, 32767).astype(np.int16)

    global _last_render_path

    previous = _last_render_path
    if previous is not None:
        try:
            previous.unlink(missing_ok=True)
        except OSError:
            # A stale preview may still be held open by an older app instance.
            # Never reuse that filename; the new render gets its own unique file.
            pass

    temp = tempfile.NamedTemporaryFile(
        prefix="cfr_song_preview_",
        suffix=".wav",
        delete=False,
    )
    out = Path(temp.name)
    temp.close()

    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(OUTPUT_RATE)
        wav.writeframes(stereo.tobytes())

    _last_render_path = out
    return out


def play_song_preview(
    midi: MidiFile,
    channel_map: dict[int, RetailInstrument | Sf2Preset],
    drum_map: dict[int, RetailDrum | Sf2Preset],
    audit_dir: str | Path = DEFAULT_AUDIT_DIR,
    soundfont: SoundFont | None = None,
    start_ms: int = 0,
    autoplay: bool = True,
) -> Path:
    # MCI keeps WAV files locked on Windows. Close the previous device before
    # overwriting the preview file so repeated renders never hit PermissionError.
    close_song_preview()
    out = render_song_preview(midi, channel_map, drum_map, audit_dir, soundfont)
    if autoplay:
        open_song_preview(out)
        play_rendered_preview(start_ms=max(0, int(start_ms)))
    return out
