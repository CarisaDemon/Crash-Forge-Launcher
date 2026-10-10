"""Custom sample input validation for Crash Forge music mods.

Crash Forge is native PC, so the tool keeps WAV as the authoring/source format.
No PS1 ADPCM conversion is performed here. Runtime SampleRegistry support will
decide the final cached representation later.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import shutil
import wave


class SampleError(ValueError):
    pass


@dataclass
class WavInfo:
    path: str
    channels: int
    sample_width_bytes: int
    sample_rate: int
    frames: int
    duration_seconds: float
    compression: str
    sha256: str
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CustomInstrumentDescriptor:
    name: str
    sample: str
    root_note: int = 60
    fine_tune_cents: int = 0
    volume: int = 255
    pan: int = 128
    attack: int = 0
    decay: int = 0
    sustain: int = 255
    release: int = 0
    loop_start: int = 0
    loop_end: int = 0
    loop_enabled: bool = False

    def validate(self, wav: WavInfo | None = None) -> list[str]:
        issues: list[str] = []
        if not self.name.strip():
            issues.append("instrument name is empty")
        if not 0 <= self.root_note <= 127:
            issues.append("root_note must be 0..127")
        if not -1200 <= self.fine_tune_cents <= 1200:
            issues.append("fine_tune_cents must be -1200..1200")
        if not 0 <= self.volume <= 255:
            issues.append("volume must be 0..255")
        if not 0 <= self.pan <= 255:
            issues.append("pan must be 0..255")
        if min(self.attack, self.decay, self.sustain, self.release) < 0:
            issues.append("envelope values cannot be negative")
        if self.loop_enabled:
            if self.loop_start < 0 or self.loop_end <= self.loop_start:
                issues.append("enabled loop requires 0 <= loop_start < loop_end")
            if wav is not None and self.loop_end > wav.frames:
                issues.append("loop_end is beyond WAV frame count")
        return issues


def inspect_wav(path: str | Path) -> WavInfo:
    p = Path(path)
    raw = p.read_bytes()
    warnings: list[str] = []

    try:
        with wave.open(str(p), "rb") as w:
            channels = w.getnchannels()
            width = w.getsampwidth()
            rate = w.getframerate()
            frames = w.getnframes()
            compression = w.getcomptype()
    except (wave.Error, EOFError) as exc:
        raise SampleError(f"invalid WAV: {exc}") from exc

    if compression != "NONE":
        raise SampleError(f"compressed WAV is not supported as source ({compression})")
    if channels not in (1, 2):
        raise SampleError(f"unsupported channel count: {channels}")
    if width not in (1, 2, 3, 4):
        raise SampleError(f"unsupported PCM sample width: {width} bytes")
    if rate <= 0:
        raise SampleError("invalid sample rate")
    if frames <= 0:
        raise SampleError("WAV contains no audio frames")

    if channels == 2:
        warnings.append(
            "Stereo source: runtime importer must explicitly downmix or preserve stereo; never do it silently."
        )
    if width != 2:
        warnings.append(
            f"Source is {width * 8}-bit PCM; native cache conversion policy is still pending."
        )
    if rate < 8000 or rate > 96000:
        warnings.append(f"Unusual sample rate: {rate} Hz.")

    return WavInfo(
        path=str(p),
        channels=channels,
        sample_width_bytes=width,
        sample_rate=rate,
        frames=frames,
        duration_seconds=frames / float(rate),
        compression=compression,
        sha256=hashlib.sha256(raw).hexdigest(),
        warnings=warnings,
    )


def write_descriptor(
    descriptor: CustomInstrumentDescriptor,
    path: str | Path,
    wav_info: WavInfo | None = None,
) -> None:
    issues = descriptor.validate(wav_info)
    if issues:
        raise SampleError("; ".join(issues))
    payload = {
        "format_version": 1,
        "instrument": asdict(descriptor),
    }
    if wav_info is not None:
        payload["source_wav"] = wav_info.to_dict()
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def stage_custom_instrument(
    output_dir: str | Path,
    wav_path: str | Path,
    descriptor: CustomInstrumentDescriptor,
) -> Path:
    """Stage a custom instrument authoring folder without installing it."""
    info = inspect_wav(wav_path)
    issues = descriptor.validate(info)
    if issues:
        raise SampleError("; ".join(issues))

    root = Path(output_dir)
    samples = root / "samples"
    samples.mkdir(parents=True, exist_ok=True)

    src = Path(wav_path)
    sample_name = src.name
    dst = samples / sample_name
    shutil.copy2(src, dst)

    staged = CustomInstrumentDescriptor(**asdict(descriptor))
    staged.sample = f"samples/{sample_name}"
    write_descriptor(staged, root / "instrument.json", info)
    return root
