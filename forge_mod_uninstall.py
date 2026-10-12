"""Explicit, ID-verified removal of Forge Hub mods installed into ONE game.

An uninstall moves only the selected web-owned module(s) out of the game's
mods/ folder, then sends the moved folder to Windows Recycle Bin. Local mods,
legacy assets, game data, backups and symlinks/junctions are NEVER targeted.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import forge_mod_manager as manager


class UninstallError(ValueError):
    pass


@dataclass(frozen=True)
class UninstallPlan:
    game: Path
    category: str
    mod_id: str
    title: str
    paths: tuple[Path, ...]
    children: tuple[str, ...]
    child_ids: tuple[str, ...]


def _is_link(path):
    try:
        return path.is_symlink() or bool(
            getattr(os.path, "isjunction", lambda _: False)(path))
    except (OSError, RuntimeError):
        return True


def _game_root(game_path):
    if not game_path:
        raise UninstallError("Choose your game folder in Launcher Settings.")
    game=Path(game_path)
    try:
        if _is_link(game) or not game.is_dir():
            raise UninstallError("The selected game folder is not a real directory.")
        game=game.resolve(strict=True)
        exe=game/"ctr-native.exe"
        if not exe.is_file() or _is_link(exe):
            raise UninstallError("This folder does not contain ctr-native.exe.")
        mods=game/"mods"
        if not mods.is_dir() or _is_link(mods) or mods.resolve()!=game.joinpath("mods"):
            raise UninstallError("Missing or unsafe game mods directory.")
    except (OSError, RuntimeError) as exc:
        raise UninstallError("Cannot validate the selected game folder.") from exc
    return game


def _validate_owned_folder(game, kind, identity, expected_pack=None):
    root=game/"mods"
    try:
        item=manager.read_mod(game,kind,identity)
    except (OSError,manager.ModManagerError) as exc:
        raise UninstallError("This mod is not installed with a valid web ID.") from exc
    if (item.get("id")!=identity or item.get("type")!=kind or
        not item.get("manageable") or item.get("layout")!="web-id" or
        item.get("origin")!="forge_hub"):
        raise UninstallError("Only valid Forge Hub-installed mods can be uninstalled.")
    if expected_pack is not None and item.get("source_id")!=expected_pack:
        raise UninstallError(
            "A Modpack component changed ownership. Nothing was removed.")
    folder=Path(item["path"])
    if (not manager.SLUG.fullmatch(folder.name) or
        folder.parent!=root or _is_link(folder) or not folder.is_dir() or
        folder.resolve()!=root/folder.name):
        raise UninstallError("Unsafe mod path. Nothing was removed.")
    # Avoid deleting unrelated data reachable through symlinks or NTFS
    # junctions anywhere inside a mod, even if the native INI is valid.
    try:
        for item_path in folder.rglob("*"):
            if _is_link(item_path):
                raise UninstallError(
                    "Mod contains a link or junction. Uninstall manually after inspection.")
    except (OSError, RuntimeError) as exc:
        raise UninstallError("Cannot validate all mod files.") from exc
    return item,folder


def _pack_members(game, pack_id, pack_path):
    inventory=pack_path/"contents.json"
    try:
        if _is_link(inventory) or not inventory.is_file() or inventory.stat().st_size>100000:
            raise UninstallError("Modpack inventory is missing or unsafe.")
        raw=json.loads(inventory.read_text(encoding="utf-8"))
        entries=raw["mods"]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise UninstallError("Invalid Modpack inventory. Nothing was removed.") from exc
    if (not isinstance(raw,dict) or raw.get("id")!=pack_id or
        not isinstance(entries,list) or not 2<=len(entries)<=60):
        raise UninstallError("Modpack inventory does not match its installed ID.")
    found=[]
    unique={pack_id}
    for entry in entries:
        if not isinstance(entry,dict):
            raise UninstallError("Invalid Modpack component metadata.")
        kind=manager.category_for_directory(str(entry.get("type","")))
        identity=entry.get("id")
        if (kind in (None,"Modpack") or not isinstance(identity,str) or
            not manager.SLUG.fullmatch(identity) or identity in unique):
            raise UninstallError("Invalid or duplicate Modpack component ID.")
        unique.add(identity)
        try:
            item,folder=_validate_owned_folder(game,kind,identity,pack_id)
        except UninstallError as exc:
            # Removed components do not block uninstall of the remaining
            # bundle; a MODIFIED or reassigned component, however, must fail.
            existing, _=manager._find_existing_web_folder(game,identity)
            if existing is None:
                continue
            raise exc
        found.append((item,folder))
    return found


def plan_web_uninstall(game_path, kind, mod_id):
    """Read-only plan, used by the confirmation dialog and the final action."""
    game=_game_root(game_path)
    if kind not in manager.CATEGORIES:
        raise UninstallError("Unsupported mod category.")
    try:
        manager.validate_slug(mod_id)
    except manager.ModManagerError as exc:
        raise UninstallError("Invalid Forge Hub mod ID.") from exc
    item,main=_validate_owned_folder(game,kind,mod_id)
    if kind!="Modpack":
        source=item.get("source_id")
        # A child installed from a bundled release belongs to the pack and
        # cannot be removed alone without invalidating its inventory.
        if source and source!=mod_id:
            pack,_=manager._find_existing_web_folder(game,source)
            if pack is not None:
                owner_kind="Modpack"
                try:
                    owner=manager.read_mod(game,owner_kind,source)
                except (OSError,manager.ModManagerError):
                    owner={}
                if owner.get("manageable") and owner.get("origin")=="forge_hub":
                    raise UninstallError(
                        "This mod belongs to a Modpack. Uninstall the Modpack instead.")
        return UninstallPlan(game,kind,mod_id,item["title"],(main,),(),())
    children=_pack_members(game,mod_id,main)
    targets=[folder for _,folder in children]+[main]
    if len(set(targets))!=len(targets):
        raise UninstallError("Modpack inventory repeats a physical folder.")
    return UninstallPlan(
        game,kind,mod_id,item["title"],tuple(targets),
        tuple(child["title"] for child,_ in children),
        tuple(child["id"] for child,_ in children))


def _recycle_staging_folder(path):
    """Ask Windows to put the removed module(s) into Recycle Bin."""
    if sys.platform!="win32":
        # For cross-platform CI only; the distributed launcher is Windows.
        shutil.rmtree(path)
        return
    class FileOp(ctypes.Structure):
        _fields_=[
            ("hwnd",ctypes.c_void_p),("wFunc",ctypes.c_uint),
            ("pFrom",ctypes.c_wchar_p),("pTo",ctypes.c_wchar_p),
            ("fFlags",ctypes.c_ushort),("fAnyOperationsAborted",ctypes.c_int),
            ("hNameMappings",ctypes.c_void_p),
            ("lpszProgressTitle",ctypes.c_wchar_p),
        ]
    shell=ctypes.windll.shell32.SHFileOperationW
    shell.argtypes=[ctypes.POINTER(FileOp)]
    shell.restype=ctypes.c_int
    # Delete to Recycle Bin, not permanent deletion. No second Windows
    # confirmation: our custom Crash Forge dialog already confirmed.
    opts=FileOp()
    opts.wFunc=3  # FO_DELETE
    opts.pFrom=str(path)+"\0\0"
    opts.fFlags=0x40|0x10|0x4|0x400
    result=shell(ctypes.byref(opts))
    if result or opts.fAnyOperationsAborted:
        raise UninstallError(
            "Windows could not move the mod to Recycle Bin "
            f"(code {result}). Files will be restored if possible.")


def uninstall_web_mod(game_path, kind, mod_id, *, expected_paths=None):
    """Perform one explicitly requested uninstall; no network or game writes.

    All affected modules are moved off mods/ before disposal. If moving or
    recycling fails, every intact module is moved back to its original path.
    Existing .forge_mod_backups and user saves are never changed.
    """
    plan=plan_web_uninstall(game_path,kind,mod_id)
    if expected_paths is not None:
        observed=tuple(str(path) for path in plan.paths)
        if observed!=tuple(str(p) for p in expected_paths):
            raise UninstallError("Mod files changed since confirmation. Try again.")
    # mkdtemp uses an unpredictable basename and never reuses an old stage.
    stage=Path(tempfile.mkdtemp(prefix=".forge-uninstall-",dir=plan.game))
    moved=[]
    try:
        for index,path in enumerate(plan.paths):
            if not path.is_dir() or _is_link(path):
                raise UninstallError("Mod folder changed during uninstall.")
            target=stage/(f"{index:02d}_{path.name}")
            os.replace(path,target)
            moved.append((path,target))
        _recycle_staging_folder(stage)
        if stage.exists():
            # On Windows, a successful shell recycle must move the source.
            # If not, return the mods instead of claiming uninstall succeeded.
            raise UninstallError("Recycle Bin operation did not remove the staging folder.")
    except BaseException as exc:
        rollback_errors=[]
        for original,staged in reversed(moved):
            if not staged.exists():
                rollback_errors.append(str(original))
                continue
            try:
                if original.exists():
                    rollback_errors.append(str(original))
                else:
                    os.replace(staged,original)
            except OSError:
                rollback_errors.append(str(original))
        if stage.exists():
            try:
                stage.rmdir()
            except OSError:
                pass
        if rollback_errors:
            raise UninstallError(
                "Uninstall was interrupted; some files need manual recovery "
                "from the Recycle Bin or .forge-uninstall- folder.") from exc
        if isinstance(exc,UninstallError):
            raise
        raise UninstallError(
            "Windows could not uninstall this mod; all modules were restored.") from exc
    return {
        "id":plan.mod_id,"kind":plan.category,"title":plan.title,
        "removed_count":len(plan.paths),
        "removed_ids":(plan.mod_id,) + plan.child_ids,
        "recycled":True,
    }
