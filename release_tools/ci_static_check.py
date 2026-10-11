"""Headless GitHub Actions validation of the exact release ZIP.

A Windows Actions runner has no interactive desktop; executing a frozen
WinForms/Tk app there can block forever even if it is an --ui-smoke. Native
GUI processes are exercised on a real Windows desktop before publication.
This CI job verifies distributable bytes, integrity, UI subsystem and included
dependencies without opening any GUI process.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get("CFR_BUILD_DIR", "build"))
if not BUILD.is_absolute():
    BUILD = ROOT / BUILD
INSTALL = BUILD / "dist" / "CrashForgeLauncher"
ZIP = BUILD / "release" / "Crash-Forge-Launcher-Windows.zip"
CHECK = ZIP.with_name(ZIP.name + ".sha256")


def pe_gui(path: Path) -> None:
    assert path.is_file(), f"Missing editor/launcher: {path}"
    with path.open("rb") as f:
        head = f.read(8192)
    assert head.startswith(b"MZ"), f"Not a Windows executable: {path}"
    pe = int.from_bytes(head[0x3c:0x40], "little")
    assert pe + 96 < len(head), f"Invalid PE header: {path}"
    assert head[pe:pe + 4] == b"PE\x00\x00", f"Invalid PE signature: {path}"
    subsystem = int.from_bytes(head[pe + 24 + 68:pe + 24 + 70], "little")
    assert subsystem == 2, f"Editor opens a console: {path.name} (PE={subsystem})"
    print(f"PASS Windows GUI subsystem (no console): {path.name}", flush=True)


def main() -> int:
    current = (ROOT / "launcher_version.txt").read_text(encoding="utf-8").strip()
    bundled = (INSTALL / "launcher_version.txt").read_text(encoding="utf-8").strip()
    assert current == bundled, (current, bundled)
    assert ZIP.is_file() and CHECK.is_file()

    sha = hashlib.sha256()
    with ZIP.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    actual = sha.hexdigest()
    sidecar = CHECK.read_text(encoding="ascii").strip().split()
    assert len(sidecar) == 2, "Checksum format must be SHA256  filename"
    assert sidecar[0] == actual and sidecar[1] == ZIP.name
    print(f"PASS release v{current} SHA-256: {actual}", flush=True)

    mainexe = INSTALL / "CrashForgeLauncher.exe"
    updater = INSTALL / "ForgeLauncherUpdater.exe"
    toolfolder = INSTALL / "_internal" / "editor_tools"
    programs = (mainexe, updater,
                toolfolder / "CrashForgeOGGToolkit.exe",
                toolfolder / "CrashForgeCSEQToolkit.exe",
                toolfolder / "CrashForgeModelImporter.exe")
    for exe in programs:
        pe_gui(exe)

    embedded = (
        "_internal/python312.dll",
        "_internal/_tkinter.pyd",
        "_internal/_tcl_data/init.tcl",
        "_internal/_tk_data/tk.tcl",
        "_internal/tcl86t.dll",
        "_internal/tk86t.dll",
        "_internal/assets/news/latest_update.webp",
        "assets/icons/cfr_icon.ico",
        "assets/icons/cfr_icon.png",
        "launcher_version.txt",
        "ForgeLauncherUpdater.exe",
    )
    for relative in embedded:
        assert (INSTALL / relative).is_file(), f"Missing portable file {relative}"

    with zipfile.ZipFile(ZIP) as archive:
        entries = archive.infolist()
        names = {i.filename.replace("\\", "/") for i in entries if not i.is_dir()}
        assert len(entries) > 300 and len(entries) < 16000
        assert all(not item.filename.startswith(("/", "\\")) for item in entries)
        assert all(".." not in item.filename.replace("\\", "/").split("/") for item in entries)
        for relative in embedded:
            assert relative in names, f"ZIP missing bundled {relative}"
        for exe in programs:
            rel = exe.relative_to(INSTALL).as_posix()
            assert rel in names, f"ZIP missing {rel}"
            assert archive.getinfo(rel).file_size == exe.stat().st_size
        assert all(not n.lower().endswith((".iso", ".bin", ".cue", ".mcr", ".sav"))
                   for n in names), "Release contains game/private disc data"
        assert archive.testzip() is None, "ZIP failed CRC check"
    print("PASS clean, complete Windows ZIP, no ISO/disc images/saves", flush=True)

    sys.path.insert(0, str(ROOT))
    import forge_launcher_integrity
    result = forge_launcher_integrity.audit(INSTALL)
    assert result["status"] == "ok", f"Bundled integrity failed: {result}"
    print("PASS launcher manifest integrity, embedded Python, Tcl/Tk, icons", flush=True)
    print("PASS HEADLESS GITHUB CI READY: GUI lifecycle tested on local Windows desktop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())