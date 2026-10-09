"""Out-of-process Windows updater for packaged Crash Forge Launcher.

This helper is copied out of the app directory and only applies verified,
fully staged official Github release files AFTER the Launcher GUI exits.
It does not fetch remote content, execute release scripts or touch game files.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

import forge_launcher_updates as updates


class UpdateApplyError(RuntimeError):
    pass


def _wait_for_process_exit(pid, seconds=150):
    """Wait for the owning app to exit without polling other processes."""
    if os.name != "nt":
        raise UpdateApplyError("The updater helper is Windows-only")
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel.WaitForSingleObject.restype = ctypes.c_uint
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    SYNCHRONIZE = 0x00100000
    handle = kernel.OpenProcess(SYNCHRONIZE, 0, int(pid))
    if not handle:
        # The app may already have exited before this subprocess initialized.
        return
    try:
        outcome = kernel.WaitForSingleObject(handle, max(1,int(seconds))*1000)
    finally:
        kernel.CloseHandle(handle)
    if outcome != 0:
        raise UpdateApplyError("Launcher did not exit before update deadline")


def _sha_file(path):
    digest = hashlib.sha256()
    with open(path,"rb") as handle:
        for chunk in iter(lambda: handle.read(512*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_staged(app_dir, payload, manifest_path, state_dir):
    """Rehash ALL files; never trust mutable staging metadata or remote paths."""
    root = Path(state_dir).resolve()
    stage = Path(payload).resolve()
    manifest_path = Path(manifest_path).resolve()
    dest = Path(app_dir).resolve()
    if not dest.is_dir() or not (dest / updates.APP_EXE).is_file():
        raise UpdateApplyError("Only an installed portable launcher can be updated")
    if not updates._inside(root / "stage", stage):
        raise UpdateApplyError("Update is not staged in the expected LOCALAPPDATA folder")
    if not updates._inside(root / "stage", manifest_path):
        raise UpdateApplyError("Manifest is not in the expected LOCALAPPDATA folder")
    if stage.parent != manifest_path.parent or not stage.is_dir():
        raise UpdateApplyError("Staging folder and manifest do not match")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError,OSError) as exc:
        raise UpdateApplyError("Could not read verified update manifest") from exc
    if not isinstance(manifest,dict) or manifest.get("schema")!=1 or \
       manifest.get("repository") != updates.REPOSITORY:
        raise UpdateApplyError("Invalid update origin or manifest schema")
    version = manifest.get("version")
    if not updates.parse_version(version):
        raise UpdateApplyError("Invalid launcher release version")
    current = updates.read_local_version(dest)
    if not updates.newer_release({"version":version},current):
        raise UpdateApplyError("This release would not upgrade the current launcher")
    files = manifest.get("files")
    if not isinstance(files,list) or not 3 <= len(files) <= updates.MAX_FILES:
        raise UpdateApplyError("Invalid release manifest file count")
    seen=set()
    total=0
    validated=[]
    for entry in files:
        if not isinstance(entry,dict):
            raise UpdateApplyError("Invalid file metadata")
        name = entry.get("path")
        if not isinstance(name,str):
            raise UpdateApplyError("Unsafe or missing file path")
        canonical=updates._safe_member(name,False)
        if canonical.lower() in seen:
            raise UpdateApplyError("Duplicate case-insensitive path")
        seen.add(canonical.lower())
        bytes_expected=entry.get("bytes")
        sha=entry.get("sha256")
        if (not isinstance(bytes_expected,int) or isinstance(bytes_expected,bool)
                or bytes_expected < 0 or not isinstance(sha,str)
                or not updates.SHA.fullmatch(sha)):
            raise UpdateApplyError("Invalid file length or hash")
        total+=bytes_expected
        if total > updates.MAX_EXTRACTED_BYTES:
            raise UpdateApplyError("Release exceeds safe unpacked limit")
        source=stage.joinpath(*canonical.split("/"))
        destination=dest.joinpath(*canonical.split("/"))
        if not updates._inside(stage,source) or not updates._inside(dest,destination):
            raise UpdateApplyError("Unsafe symlink or path outside installation")
        if not source.is_file() or source.stat().st_size!=bytes_expected:
            raise UpdateApplyError("Staged file missing or changed: "+canonical)
        if _sha_file(source)!=sha.lower():
            raise UpdateApplyError("A staged update file failed SHA-256 verification")
        validated.append((canonical,source,destination))
    for filename in (updates.APP_EXE.lower(),updates.UPDATER_EXE.lower(),
                     "launcher_version.txt"):
        if filename not in seen:
            raise UpdateApplyError("Verified update is incomplete")
    marker=(stage/"launcher_version.txt").read_text(encoding="utf-8-sig").strip()
    if marker!=version:
        raise UpdateApplyError("Launcher version marker does not match the release")
    return version,validated


def apply_update(app_dir, payload, manifest_path, state_dir):
    """Apply only allowlisted verified files, preserving user files and backups.

    No user settings, catalogs, mods, game files or personal project folders
    are included in the allowlist; existing forge_online_config.json is kept.
    """
    target=Path(app_dir).resolve()
    root=Path(state_dir).resolve()
    version,entries=validate_staged(target,payload,manifest_path,root)
    root.mkdir(parents=True,exist_ok=True)
    old_version=updates.read_local_version(target)
    backup=root/"backups"/(
        time.strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:8]+"-v"+old_version)
    backup.mkdir(parents=True,exist_ok=False)
    work=target/(".forge_update_stage_"+uuid.uuid4().hex[:10])
    work.mkdir(parents=True,exist_ok=False)
    changed=[]
    try:
        # Copy/verify all files BEFORE replacing any existing executable.
        prepared=[]
        for relative,source,destination in entries:
            if (relative.lower()=="forge_online_config.json"
                    and destination.exists()):
                continue
            prepared_path=work.joinpath(*relative.split("/"))
            prepared_path.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,prepared_path)
            if _sha_file(prepared_path)!=_sha_file(source):
                raise UpdateApplyError("Copy verification failed for "+relative)
            prepared.append((relative,prepared_path,destination))
        for relative,prepared_path,destination in prepared:
            if not updates._inside(target,destination):
                raise UpdateApplyError("Destination resolves outside the launcher directory")
            destination.parent.mkdir(parents=True,exist_ok=True)
            backup_path=backup.joinpath(*relative.split("/"))
            old_present=destination.exists() or destination.is_symlink()
            if old_present:
                if destination.is_symlink() or not destination.is_file():
                    raise UpdateApplyError("Cannot replace directory/link: "+relative)
                backup_path.parent.mkdir(parents=True,exist_ok=True)
                os.replace(destination,backup_path)
            changed.append((destination,backup_path if old_present else None))
            os.replace(prepared_path,destination)
        version_after=updates.read_local_version(target)
        if version_after!=version:
            raise UpdateApplyError("Version marker missing after replacement")
    except Exception as exc:
        failures=[]
        for destination,original in reversed(changed):
            try:
                if destination.exists():
                    destination.unlink()
                if original and original.exists():
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(original,destination)
            except OSError as problem:
                failures.append(str(problem))
        if failures:
            raise UpdateApplyError("Update failed; rollback also failed: "+
                "; ".join(failures[:2])) from exc
        raise UpdateApplyError("Launcher update failed; previous files restored: "+
            str(exc)) from exc
    finally:
        shutil.rmtree(work,ignore_errors=True)
    pending=root/"pending.json"
    try:
        record=json.loads(pending.read_text(encoding="utf-8"))
        if record.get("version")==version:
            pending.unlink()
    except (OSError,ValueError):
        pass
    try:
        log=root/"history.jsonl"
        with log.open("a",encoding="utf-8") as handle:
            handle.write(json.dumps({"at":int(time.time()),"before":old_version,
                "after":version,"files":len(entries),
                "backup":str(backup)},ensure_ascii=True)+"\n")
    except OSError:
        pass
    return {"old_version":old_version,"version":version,
            "files":len(entries),"backup":str(backup)}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true",required=True)
    parser.add_argument("--pid",type=int,required=True)
    parser.add_argument("--app-dir",required=True)
    parser.add_argument("--stage",required=True)
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--state-dir",required=True)
    args=parser.parse_args(argv)
    state=Path(args.state_dir)
    log=state/"updater-result.txt"
    try:
        _wait_for_process_exit(args.pid)
        result=apply_update(args.app_dir,args.stage,args.manifest,args.state_dir)
        outcome="SUCCESS v"+result["old_version"]+" -> v"+result["version"]
        code=0
    except Exception as exc:
        outcome="FAILED: "+str(exc)[:400]
        code=2
    try:
        state.mkdir(parents=True,exist_ok=True)
        log.write_text(outcome+"\n",encoding="utf-8")
    except OSError:
        pass
    return code


if __name__=="__main__":
    sys.exit(main())
