"""CTR-U original-disc integrity check for Crash Forge: Racing (offline v1).

An independent, report-only integrity layer; NOT an anti-cheat, not a
multiplayer/authentication service, not DRM. Reads the retail disc image
locally, compares to the published USA Redump fingerprint and records an
online-ready JSONL verdict. No network calls, popups, game control or writes
to the ISO/game. A mismatch NEVER prevents the game from launching.
"""
from __future__ import annotations

from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

PROTOCOL = "cfr.iso-attestation/1"
REFERENCE_ID = "ctr-ps1-usa-scus-94426-redump"
REFERENCE_SHA1 = "1bb785082def3fe25f6b46be06d4eaf33c5bc772"
REFERENCE_BYTES = 605_698_800
RAW_SECTOR_BYTES = 2352
HEADER_SYNC = bytes([0]) + bytes([255]) * 10 + bytes([0])
# SHA-1 is used as the published disc-dump identifier, not as cryptographic
# proof of a trusted client. SHA-256 is also recorded for future protocols.
REFERENCE_SOURCE = "https://redump.info/discs?letter=C&system=PSX"
LOG_NAME = "ctr_u_integrity.log"
JSONL_NAME = "ctr_u_attestations.jsonl"
SOURCE_CANDIDATES = (
    ("assets", "ctr-u.bin"),
    ("ctr-u.bin",),
    ("assets", "ctr-u.iso"),
    ("ctr-u.iso",),
)
_log_lock = threading.Lock()
_active_lock = threading.Lock()
_active_paths: set[str] = set()
_last_scanned: dict[str, tuple] = {}


def log_folder() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "CrashForgeLauncher" / "logs"


def locate_ctr_u(game_dir: str | os.PathLike) -> Path | None:
    """Match native game's assets/ctr-u.bin preference, then legacy root BIN."""
    home = Path(game_dir)
    for parts in SOURCE_CANDIDATES:
        file = home.joinpath(*parts)
        if file.is_file():
            return file
    return None


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _base_report(trigger: str) -> dict:
    return {
        "protocol": PROTOCOL,
        "checked_at": _timestamp(),
        "trigger": str(trigger or "unspecified")[:32],
        "reference_id": REFERENCE_ID,
        "reference_sha1": REFERENCE_SHA1,
        "reference_size": REFERENCE_BYTES,
        "method": "local_full_disc_hash",
        "transport": "none",
        "online_verified": False,
        "policy": "report_only",
        "allow_play": True,
        "status": "error",
        "reason": "NOT_CHECKED",
        "disc_path": None,
        "disc_bytes": None,
        "disc_sha1": None,
        "disc_sha256": None,
        "raw_mode2_2352": None,
    }


def verify_ctr_u(
    game_dir: str | os.PathLike,
    trigger: str = "manual",
    reference_sha1: str = REFERENCE_SHA1,
    reference_bytes: int = REFERENCE_BYTES,
) -> dict:
    """Verify exact USA raw MODE2/2352 BIN against Redump SHA-1 and size.

    Supports dependency-free synthetic references in tests. Never raises for
    ordinary missing, damaged, unreadable or concurrently changed images.
    """
    report = _base_report(trigger)
    path = locate_ctr_u(game_dir)
    if path is None:
        report.update(status="missing", reason="DISC_NOT_FOUND")
        return report
    # Keep the versioned report safe to extend with online transport later:
    # never include private absolute Windows paths in the attestation.
    report["disc_path"] = path.relative_to(Path(game_dir)).as_posix()
    try:
        before = path.stat()
        count = int(before.st_size)
        report["disc_bytes"] = count
        hasher = hashlib.sha1()
        sha256 = hashlib.sha256()
        with path.open("rb") as stream:
            first = stream.read(16)
            report["raw_mode2_2352"] = (
                count % RAW_SECTOR_BYTES == 0
                and len(first) == 16
                and first[:12] == HEADER_SYNC
                and first[15] == 2
            )
            hasher.update(first)
            sha256.update(first)
            while block := stream.read(4 * 1024 * 1024):
                hasher.update(block)
                sha256.update(block)
        after = path.stat()
        report["disc_sha1"] = hasher.hexdigest()
        report["disc_sha256"] = sha256.hexdigest()
        fingerprint_before = (before.st_dev, before.st_ino, before.st_size,
                              before.st_mtime_ns)
        fingerprint_after = (after.st_dev, after.st_ino, after.st_size,
                             after.st_mtime_ns)
        if fingerprint_before != fingerprint_after:
            report.update(status="error", reason="DISC_CHANGED_DURING_CHECK")
        elif not report["raw_mode2_2352"]:
            report.update(status="modified", reason="INVALID_RAW_MODE2_2352")
        elif count != int(reference_bytes):
            report.update(status="modified", reason="SIZE_MISMATCH")
        elif report["disc_sha1"] != str(reference_sha1).lower():
            report.update(status="modified", reason="SHA1_MISMATCH")
        else:
            report.update(status="verified", reason="RETAIL_USA_MATCH")
    except OSError as exc:
        report.update(status="error", reason="DISC_READ_ERROR",
                      technical_error=type(exc).__name__)
    return report


def _console_line(report: dict) -> str:
    severity = "INFO" if report["status"] == "verified" else "ERROR"
    if report["status"] == "verified":
        detail = "CTR-U original USA disc verified"
    else:
        detail = (
            "CTR-U ISO integrity "
            + str(report["status"]).upper()
            + " (" + str(report["reason"]) + ")"
        )
    return (
        "[CFR ISO] " + severity + ": " + detail
        + " | expected_bytes=" + str(report["reference_size"])
        + " | actual_bytes=" + str(report["disc_bytes"])
        + " | sha1=" + str(report["disc_sha1"])
        + " | OFFLINE_REPORT_ONLY | GAME_ALLOWED"
    )


def record_result(report: dict, folder: Path | None = None) -> None:
    """One technical line + machine-readable JSONL. Never show an alert."""
    line = _console_line(report)
    try:
        stderr = sys.stderr
        if stderr is not None and not getattr(stderr, "closed", False):
            print(line, file=stderr, flush=True)
    except (OSError, ValueError, RuntimeError):
        pass
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.OutputDebugStringW(line)
        except (OSError, AttributeError, ValueError):
            pass
    home = Path(folder) if folder is not None else log_folder()
    try:
        with _log_lock:
            home.mkdir(parents=True, exist_ok=True)
            for target in (home / LOG_NAME, home / JSONL_NAME):
                if target.exists() and target.stat().st_size > 2 * 1024 * 1024:
                    previous = target.with_suffix(target.suffix + ".1")
                    os.replace(target, previous)
            with (home / LOG_NAME).open("a", encoding="utf-8") as handle:
                handle.write(str(report["checked_at"]) + " " + line + "\n")
            with (home / JSONL_NAME).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=True, sort_keys=True) + "\n")
    except OSError:
        # A read-only disk/log directory may not stop the game.
        pass


def start_background_check(
    game_dir: str | os.PathLike,
    trigger: str = "startup",
    folder: Path | None = None,
    force: bool = False,
) -> bool:
    """Start at most one concurrent scan per game; unchanged files are cached.

    Does no network I/O or UI work. Returns immediately; the calling game
    launch must never wait for the hash, log write or result.
    """
    try:
        directory = os.path.normcase(os.path.abspath(os.fspath(game_dir)))
        if not directory:
            return False
        selected = locate_ctr_u(directory)
    except (OSError, ValueError, TypeError):
        return False
    try:
        if selected is None:
            fingerprint = ("missing",)
        else:
            meta = selected.stat()
            fingerprint = (str(selected).lower(), meta.st_dev, meta.st_ino,
                           meta.st_size, meta.st_mtime_ns)
    except OSError:
        fingerprint = ("unavailable",)
    with _active_lock:
        if directory in _active_paths:
            return False
        if not force and _last_scanned.get(directory) == fingerprint:
            return False
        _active_paths.add(directory)

    def run() -> None:
        try:
            result = verify_ctr_u(directory, trigger=trigger)
            record_result(result, folder=folder)
            with _active_lock:
                if result["reason"] != "DISC_CHANGED_DURING_CHECK":
                    _last_scanned[directory] = fingerprint
        except Exception as exc:
            # Even unforeseen verifier failures must remain non-fatal.
            try:
                fallback = _base_report(trigger)
                fallback.update(status="error", reason="VERIFIER_EXCEPTION",
                                technical_error=type(exc).__name__)
                record_result(fallback, folder=folder)
            except Exception:
                pass
        finally:
            with _active_lock:
                _active_paths.discard(directory)

    try:
        threading.Thread(target=run, name="CFR-CTR-U-Integrity",
                         daemon=True).start()
    except (RuntimeError, OSError):
        with _active_lock:
            _active_paths.discard(directory)
        return False
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Offline CTR-U SHA-1 disc verification (report-only).")
    parser.add_argument("game_dir", help="Directory containing assets/ctr-u.bin")
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args()
    record_result(verify_ctr_u(args.game_dir, args.trigger))
    # Always report-only: even an invalid BIN never returns a blocking code.
    sys.exit(0)
