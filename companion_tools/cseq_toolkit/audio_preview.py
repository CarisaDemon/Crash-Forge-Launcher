"""Small retail HOWL sample previewer for the Crash Forge CSEQ tool.

This decodes the original PSX SPU ADPCM blob directly from the audited KART.HWL
and writes a temporary mono WAV.  It is intentionally a sample/timbre preview,
not a full CSEQ/ADSR emulator.
"""
from __future__ import annotations

from pathlib import Path
import csv
import tempfile
import wave

try:
    import winsound
except ImportError:  # pragma: no cover - Windows is the normal tool host.
    winsound = None

from instrument_map import DEFAULT_AUDIT_DIR


_FILTERS = (
    (0, 0),
    (60, 0),
    (115, -52),
    (98, -55),
    (122, -60),
)
_temp_wav: Path | None = None


def _clamp16(value: int) -> int:
    if value < -32768:
        return -32768
    if value > 32767:
        return 32767
    return value


def _decode_spu_adpcm(blob: bytes) -> list[int]:
    """Decode standard PSX SPU ADPCM frames (16 bytes -> 28 PCM samples)."""
    pcm: list[int] = []
    hist1 = 0
    hist2 = 0

    for off in range(0, len(blob) - 15, 16):
        frame = blob[off : off + 16]
        predictor = (frame[0] >> 4) & 0x0F
        shift = frame[0] & 0x0F
        flags = frame[1]
        if predictor >= len(_FILTERS):
            predictor = 0
        f0, f1 = _FILTERS[predictor]

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

        # Bit 0 is the SPU end flag.  The blob length from HOWL is authoritative,
        # but honoring END avoids previewing padding after a one-shot sample.
        if flags & 0x01:
            break

    return pcm


def _load_storage(audit_dir: Path) -> dict[int, tuple[int, int]]:
    path = audit_dir / "sample_storage_catalog.csv"
    rows: dict[int, tuple[int, int]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            index = int(row["spuIndex"])
            offset = row.get("firstHwlOffset", "").strip()
            size = row.get("bytes", "").strip()
            if offset and size:
                rows[index] = (int(offset), int(size))
    return rows


def _preview_rate(pitch: int) -> int:
    # PSX SPU pitch 0x1000 means source plays at 44.1 kHz.
    rate = int(round(44100.0 * max(1, pitch) / 4096.0))
    return max(4000, min(48000, rate))


def render_sample_preview(
    spu_index: int,
    pitch: int = 4096,
    audit_dir: str | Path = DEFAULT_AUDIT_DIR,
) -> Path:
    root = Path(audit_dir)
    storage = _load_storage(root)
    if spu_index not in storage:
        raise ValueError(f"SPU sample {spu_index} has no stored HOWL blob")

    hwl_path = root / "KART.HWL"
    hwl = hwl_path.read_bytes()
    offset, size = storage[spu_index]
    if offset < 0 or size <= 0 or offset + size > len(hwl):
        raise ValueError(f"Invalid HOWL range for SPU sample {spu_index}")

    pcm = _decode_spu_adpcm(hwl[offset : offset + size])
    if not pcm:
        raise ValueError(f"SPU sample {spu_index} decoded to no PCM")

    global _temp_wav
    out = Path(tempfile.gettempdir()) / f"cfr_howl_preview_{spu_index}.wav"
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_preview_rate(pitch))
        frames = bytearray()
        for sample in pcm:
            frames += int(sample).to_bytes(2, "little", signed=True)
        wav.writeframes(bytes(frames))
    _temp_wav = out
    return out


def play_sample_preview(
    spu_index: int,
    pitch: int = 4096,
    audit_dir: str | Path = DEFAULT_AUDIT_DIR,
) -> Path:
    if winsound is None:
        raise RuntimeError("Internal preview currently requires Windows")
    out = render_sample_preview(spu_index, pitch, audit_dir)
    winsound.PlaySound(
        str(out),
        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
    )
    return out


def stop_preview() -> None:
    if winsound is not None:
        winsound.PlaySound(None, 0)
