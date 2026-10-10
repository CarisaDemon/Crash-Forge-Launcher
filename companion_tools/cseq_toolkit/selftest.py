"""Offline self-test for CFR CSEQ tooling. Does not touch the game/runtime."""
from pathlib import Path
import struct
import tempfile
import wave

from cseq_encoder import build_simple_retail_project
from cseq_format import (
    extract_pack_from_hwl,
    parse_howl_header,
    parse_pack,
    rebuild_preserving_song_data,
)
from instrument_map import DEFAULT_AUDIT_DIR, load_retail_catalog
from midi_reader import MidiEvent, MidiFile, read_midi
from package_builder import build_music_package
from song_preview import ctr_note_pitch
from sample_import import CustomInstrumentDescriptor, inspect_wav, stage_custom_instrument
from validator import validate_midi


def _synthetic_midi() -> bytes:
    # Type 0, TPQN=96:
    # tempo 120 BPM, program 0, C4 on, 96 ticks, C4 off, end.
    track = bytes(
        [
            0x00, 0xFF, 0x51, 0x03, 0x07, 0xA1, 0x20,
            0x00, 0xC0, 0x00,
            0x00, 0x90, 0x3C, 0x64,
            0x60, 0x80, 0x3C, 0x40,
            0x00, 0xFF, 0x2F, 0x00,
        ]
    )
    return (
        b"MThd"
        + struct.pack(">IHHH", 6, 0, 1, 96)
        + b"MTrk"
        + struct.pack(">I", len(track))
        + track
    )


def _test_custom_sample_staging(root: Path) -> None:
    wav_path = root / "sample.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 2205)

    info = inspect_wav(wav_path)
    assert info.channels == 1
    assert info.sample_width_bytes == 2
    assert info.sample_rate == 22050
    assert info.frames == 2205

    desc = CustomInstrumentDescriptor(
        name="Self Test Instrument",
        sample=wav_path.name,
        root_note=60,
        loop_enabled=False,
    )
    staged = stage_custom_instrument(root / "custom_instrument", wav_path, desc)
    assert (staged / "instrument.json").is_file()
    assert (staged / "samples" / wav_path.name).is_file()


def _test_new_cseq_encoder(catalog) -> None:
    with tempfile.TemporaryDirectory(prefix="cfr_cseq_selftest_") as td:
        root = Path(td)
        midi_path = root / "test.mid"
        midi_path.write_bytes(_synthetic_midi())

        midi = read_midi(midi_path)
        report = validate_midi(midi)
        assert report.peak_polyphony == 1
        assert not any(x.severity == "error" for x in report.issues)

        cseq = build_simple_retail_project(
            midi,
            channel_to_instrument={0: catalog.instruments[0]},
            drum_note_to_instrument={},
        )
        pack = parse_pack(cseq)
        assert pack.num_songs == 1
        assert pack.num_long_samples == 1
        assert pack.num_short_samples == 0
        assert len(pack.songs[0].sequences) == 1

        opcodes = [e.opcode for e in pack.songs[0].sequences[0].events]
        assert 0x05 in opcodes, opcodes
        assert 0x01 in opcodes, opcodes
        assert opcodes[-1] == 0x03, opcodes

        # Regression: every CSEQ sequence must share one loop boundary. If a
        # channel ends early and gets END delta=0, it restarts before the other
        # instruments and the second loop drifts out of sync. Exported
        # end-of-track padding after the final note is intentionally trimmed.
        loop_midi = MidiFile(
            format=1,
            ticks_per_quarter=96,
            track_count=2,
            events=[
                MidiEvent(0, 0, 0, "program_change", channel=0, a=0),
                MidiEvent(0, 1, 0, "program_change", channel=1, a=0),
                MidiEvent(0, 0, 1, "note_on", channel=0, a=60, b=100),
                MidiEvent(0, 1, 1, "note_on", channel=1, a=64, b=100),
                MidiEvent(96, 0, 2, "note_off", channel=0, a=60, b=64),
                MidiEvent(192, 1, 2, "note_off", channel=1, a=64, b=64),
                MidiEvent(384, 0, 3, "end_of_track"),
                MidiEvent(384, 1, 3, "end_of_track"),
            ],
            warnings=[],
        )
        loop_cseq = build_simple_retail_project(
            loop_midi,
            channel_to_instrument={
                0: catalog.instruments[0],
                1: catalog.instruments[0],
            },
            drum_note_to_instrument={},
        )
        loop_pack = parse_pack(loop_cseq)
        loop_ticks = [
            sum(e.delta for e in seq.events)
            for seq in loop_pack.songs[0].sequences
        ]
        assert loop_ticks == [192, 192], loop_ticks

        package = build_music_package(
            root / "package",
            "selftest_track",
            "Self Test Track",
            "Crash Forge Tool",
            cseq,
            target="level_03",
        )
        assert (package / "track.cseq").read_bytes() == cseq
        manifest = (package / "music.ini").read_text(encoding="utf-8")
        assert "target = level_03" in manifest
        _test_custom_sample_staging(root)


def main() -> int:
    hwl_path = DEFAULT_AUDIT_DIR / "KART.HWL"
    hwl = hwl_path.read_bytes()
    header = parse_howl_header(hwl)
    assert header["numSequences"] == 33, header["numSequences"]

    total_songs = 0
    total_sequences = 0
    total_events = 0
    unknown_events = 0
    sequences_without_end = 0

    for pack_id in range(header["numSequences"]):
        raw = extract_pack_from_hwl(hwl, pack_id)
        pack = parse_pack(raw)
        rebuilt = rebuild_preserving_song_data(pack)
        assert raw == rebuilt, f"pack {pack_id} round-trip mismatch"

        total_songs += len(pack.songs)
        for song in pack.songs:
            for seq in song.sequences:
                total_sequences += 1
                total_events += len(seq.events)
                unknown_events += sum(e.name == "unknown" for e in seq.events)
                if not seq.events or seq.events[-1].opcode != 0x03:
                    sequences_without_end += 1

    catalog = load_retail_catalog()
    assert len(catalog.instruments) == 102
    assert len(catalog.drums) == 111

    # HOWL normal music state uses raw CSEQ note 60 as the 0x1000 unity
    # multiplier (SongPool starts seq->distort at 0x80, cancelling the -2 in
    # howl_InstrumentPitch's table index expression).
    assert ctr_note_pitch(4096, 60) == 4096
    assert ctr_note_pitch(1024, 60) == 1024
    assert ctr_note_pitch(4096, 48) == 2048
    assert ctr_note_pitch(4096, 72) == 8192

    _test_new_cseq_encoder(catalog)

    print("CFR CSEQ SELFTEST OK")
    print(f"HOWL: {hwl_path}")
    print(f"packs: {header['numSequences']}")
    print(f"songs: {total_songs}")
    print(f"sequences: {total_sequences}")
    print(f"events decoded: {total_events}")
    print(f"unknown opcodes: {unknown_events}")
    print(f"sequences without decoded END: {sequences_without_end}")
    print(f"global instruments: {len(catalog.instruments)}")
    print(f"global drums: {len(catalog.drums)}")
    print("synthetic MIDI -> new CSEQ -> parse -> package: OK")
    print("custom WAV inspect -> staged instrument descriptor: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
