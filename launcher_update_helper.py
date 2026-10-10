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
import subprocess
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


def validate_staged(app_dir, payload, manifest_path, state_dir, allow_fresh=False):
    """Rehash ALL files; never trust mutable staging metadata or remote paths."""
    root = Path(state_dir).resolve()
    stage = Path(payload).resolve()
    manifest_path = Path(manifest_path).resolve()
    dest = Path(app_dir).resolve()
    installed = dest.is_dir() and (dest / updates.APP_EXE).is_file()
    if not installed:
        if not allow_fresh or dest != (root.parent / "app").resolve():
            raise UpdateApplyError("Only an installed portable launcher can be updated")
        if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
            raise UpdateApplyError("The first-install directory must be empty")
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
    candidate = {"version": version, "verified": True,
                 "asset": {"sha256": manifest.get("zip_sha256")}}
    if not updates.update_required(candidate, current, app_dir=dest, root=root,
                                   force_repair=manifest.get("repair") is True):
        raise UpdateApplyError("This verified package is already installed")
    if not updates.SHA.fullmatch(str(manifest.get("zip_sha256") or "")):
        raise UpdateApplyError("The staging manifest has no valid ZIP digest")
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


def apply_update(app_dir, payload, manifest_path, state_dir, allow_fresh=False):
    """Apply verified files. Source migration uses a clean EXE-only target.

    No user settings, catalogs, mods, game files or personal project folders
    are included in the allowlist; existing forge_online_config.json is kept.
    """
    target=Path(app_dir).resolve()
    root=Path(state_dir).resolve()
    version,entries=validate_staged(target,payload,manifest_path,root,
                                     allow_fresh=allow_fresh)
    if allow_fresh and not target.exists():
        target.mkdir(parents=True,exist_ok=False)
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
        # Receipt is part of successful installation; failure rolls back.
        metadata=json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        updates.save_installed_release(
            version, metadata["zip_sha256"], target, root=root)
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


def migrate_source_preferences(source_dir, app_dir):
    """Preserve source-launcher preferences during the one-time .bat -> EXE move.

    Only known local JSON configuration files are copied, and only if the
    portable installation has not already created its own user settings.
    Never modifies the original source or its game/mod files.
    """
    source = Path(source_dir).resolve()
    target = Path(app_dir).resolve()
    if source == target or updates._inside(source, target):
        raise UpdateApplyError("A source migration cannot target the developer directory")
    if not (source / "launcher.py").is_file():
        raise UpdateApplyError("Cannot verify original developer launcher folder")
    copied = []
    for filename, limit in (
        ("launcher_settings.json", 65536),
        ("installed_mods.json", 1048576),
        ("community_catalog.json", 2097152),
    ):
        origin = source / filename
        dest = target / filename
        if not origin.is_file() or dest.exists() or origin.is_symlink():
            continue
        if origin.stat().st_size > limit:
            continue
        try:
            data = json.loads(origin.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(data, dict):
            continue
        temporary = target / (filename + ".migrate.tmp")
        try:
            temporary.write_text(json.dumps(data, indent=2,
                                            ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, dest)
            copied.append(filename)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return copied


def relaunch_updated_exe(app_dir):
    """Start the new Windows GUI EXE, never Python, a BAT or a console shell."""
    executable = (Path(app_dir).resolve() / updates.APP_EXE)
    if not executable.is_file():
        raise UpdateApplyError("Updated Windows launcher executable was not installed")
    flags = 0
    if os.name == "nt":
        flags = (subprocess.CREATE_NO_WINDOW |
                 subprocess.DETACHED_PROCESS |
                 subprocess.CREATE_NEW_PROCESS_GROUP)
    process = subprocess.Popen(
        [str(executable)], cwd=str(executable.parent),
        creationflags=flags, close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return process.pid


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true",required=True)
    parser.add_argument("--pid",type=int,required=True)
    parser.add_argument("--app-dir",required=True)
    parser.add_argument("--stage",required=True)
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--state-dir",required=True)
    parser.add_argument("--source-dir",help="One-time source .bat to portable EXE migration")
    parser.add_argument("--allow-fresh",action="store_true",
                        help="Allow initial LOCALAPPDATA/CrashForgeLauncher/app install")
    # The isolated CLI smoke test uses dummy EXEs. Production never disables
    # restarting the updated GUI after a successful application.
    parser.add_argument("--no-restart",action="store_true")
    args=parser.parse_args(argv)
    state=Path(args.state_dir)
    log=state/"updater-result.txt"
    try:
        if args.allow_fresh and not args.source_dir:
            raise UpdateApplyError("Fresh installation requires a verified developer source")
        if args.source_dir and not (Path(args.source_dir) / "launcher.py").is_file():
            raise UpdateApplyError("Cannot verify the developer launcher directory")
        _wait_for_process_exit(args.pid)
        result=apply_update(args.app_dir,args.stage,args.manifest,args.state_dir,
                            allow_fresh=args.allow_fresh)
        moved=[]
        if args.source_dir:
            moved=migrate_source_preferences(args.source_dir,args.app_dir)
        outcome="SUCCESS v"+result["old_version"]+" -> v"+result["version"]
        if moved:
            outcome+="; migrated settings: "+", ".join(moved)
        code=0
        if args.no_restart:
            outcome += " (relaunch skipped only in isolated smoke test)"
        else:
            try:
                pid=relaunch_updated_exe(args.app_dir)
                outcome += " - restarted updated EXE, PID="+str(pid)
            except Exception as restart_error:
                outcome += " - relaunch FAILED: "+str(restart_error)[:280]
                code=3
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
