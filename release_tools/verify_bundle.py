"""Verify Windows launcher portable binary folder or ZIP before a public Release.

Reject personal data, unexpected executables, scripts, symlinks, archives with
path traversal, invalid version metadata and missing out-of-process updater.
"""
from pathlib import Path
import os
import sys
import zipfile

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
import forge_launcher_updates as lu


REQUIRED_TCL_FILES=("_internal/_tcl_data/init.tcl","_internal/_tk_data/tk.tcl","_internal/tcl86t.dll","_internal/tk86t.dll","_internal/_tkinter.pyd")

def assert_tcl_payload(names):
    absent=[s for s in REQUIRED_TCL_FILES if s.lower() not in names]
    if absent: raise lu.LauncherUpdateError("Missing essential Tcl/Tk files: "+", ".join(absent))

def verify_folder(location):
    files=[]
    total=0
    for path in location.rglob("*"):
        if path.is_symlink():
            raise lu.LauncherUpdateError("Symlink in Windows release package")
        if not path.is_file():
            continue
        rel=path.relative_to(location).as_posix()
        lu._safe_member(rel,False)
        total+=path.stat().st_size
        if total>lu.MAX_EXTRACTED_BYTES:
            raise lu.LauncherUpdateError("Unpacked Windows release too large")
        files.append(rel)
    if len(files)>lu.MAX_FILES:
        raise lu.LauncherUpdateError("Too many files in Windows release")
    expected={lu.APP_EXE.lower(),lu.UPDATER_EXE.lower(),"launcher_version.txt"}
    names={x.lower() for x in files}
    assert_tcl_payload(names)
    if not expected.issubset(names):
        raise lu.LauncherUpdateError("Missing game launcher EXE, updater or version file")
    version=(location/"launcher_version.txt").read_text(encoding="utf-8-sig").strip()
    if not lu.parse_version(version):
        raise lu.LauncherUpdateError("Bad launcher_version.txt")
    return version,len(files),total


def verify_archive(path):
    with zipfile.ZipFile(path) as zf:
        version=zf.read("launcher_version.txt").decode("utf-8-sig").strip()
        if not lu.parse_version(version):
            raise lu.LauncherUpdateError("Bad ZIP version")
        files=lu.inspect_package(zf,version)
        assert_tcl_payload({x.filename.replace(chr(92),'/').lower() for x,_ in files})
        return version,len(files),sum(x.file_size for x,_ in files)


if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("Usage: verify_bundle.py <folder-or-zip>")
    source=Path(sys.argv[1]).resolve()
    try:
        if source.is_dir():
            version,files,size=verify_folder(source)
        elif source.is_file() and source.suffix.lower()==".zip":
            version,files,size=verify_archive(source)
        else:
            raise lu.LauncherUpdateError("Bundle path must be a folder or ZIP")
        print(f"PASS validated v{version}: {files} release files, {size} unpacked bytes")
    except (lu.LauncherUpdateError, zipfile.BadZipFile, ValueError, OSError) as exc:
        print("FAIL release validation:",str(exc))
        raise SystemExit(1)
