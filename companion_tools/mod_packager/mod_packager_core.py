"""Native Crash Forge Racing mod ZIP builder. No uploads or account credentials."""
from __future__ import annotations
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import unicodedata
import zipfile

CATEGORIES = {
    "Character": ("character.ini", "character"),
    "Kart": ("kart.ini", "kart"),
    "Wheels": ("wheels.ini", "wheel"),
    "Track": ("track.ini", "track"),
}
ALLOWED_EXTENSIONS = frozenset({
    ".obj", ".mtl", ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".ini",
    ".cfg", ".json", ".txt", ".md", ".wav", ".ogg", ".cseq", ".bin",
    ".dds", ".webp", ".gif", ".xml", ".dat", ".gltf", ".glb", ".lev", ".vrm",
})
MAX_UPLOAD = 50 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_ITEMS = 2000
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
VERSION = re.compile(r"[a-zA-Z0-9._+-]{1,28}\Z")

class PackageError(ValueError):
    pass

def folder_name(title):
    value = unicodedata.normalize("NFKD", str(title)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:58].rstrip("_")
    if not value: value = "community_mod"
    reserved = {"con","aux","prn","nul","mods","racers","karts","wheels","tracks","music"}
    reserved.update("com"+str(x) for x in range(1,10))
    reserved.update("lpt"+str(x) for x in range(1,10))
    return "mod_"+value if value in reserved else value

def _safe_relative(raw):
    raw = str(raw).replace("\\","/")
    if not raw or len(raw) > 512 or raw.startswith("/") or ":" in raw:
        raise PackageError("Invalid file path inside mod.")
    parts = PurePosixPath(raw).parts
    if (not parts or any(p in ("",".","..") or p.startswith(".") for p in parts)
            or any(ord(c) < 32 or ord(c) == 127 for c in raw)):
        raise PackageError("Unsafe or hidden file path: "+raw)
    if PurePosixPath(raw).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise PackageError("File type not allowed in mod ZIP: "+raw)
    return "/".join(parts)

def _list_assets(folder=None, chosen_files=None):
    if folder is not None:
        root=Path(folder).expanduser().resolve()
        if not root.is_dir() or root.is_symlink():
            raise PackageError("Select a real mod folder, not a shortcut.")
        pairs=[]
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise PackageError("Mod folders cannot contain symbolic links.")
            if path.is_file():
                if not path.resolve().is_relative_to(root):
                    raise PackageError("Unsafe mod path.")
                pairs.append((_safe_relative(path.relative_to(root).as_posix()),path))
    else:
        files=[Path(p) for p in (chosen_files or [])]
        pairs=[(_safe_relative(path.name),path) for path in files]
        if not all(p.is_file() and not p.is_symlink() for _,p in pairs):
            raise PackageError("One of the selected files is missing or linked.")
    if not pairs or len(pairs)>MAX_ITEMS:
        raise PackageError("Choose 1 to 2000 mod files.")
    seen=set()
    total=0
    for name,path in pairs:
        key=name.casefold()
        if key in seen:raise PackageError("Duplicate filename: "+name)
        seen.add(key)
        total+=path.stat().st_size
        if total>MAX_EXPANDED:
            raise PackageError("Selected files exceed the 1 GiB extracted limit.")
    return pairs

def _native_ini(data,title,kind,version,asset_stem,lev="",vrm=""):
    ini,section=CATEGORIES[kind]
    if data is None:
        native=("["+section+"]\nname = "+title+"\nenabled = true\n")
        if kind=="Character":
            native+=("fallback_retail = crash\nengine = balanced\nhas_wheels = false\n"
                     "\n[model]\nscale = 1.0\n\n[assets]\nasset_name = "+asset_stem+"\n")
        elif kind in ("Kart","Wheels"):
            native+="\n[model]\nasset_name = "+asset_stem+"\nscale = 1.0\n"
        else:
            native+="format = native_lev_vrm\nlev = "+lev+"\nvrm = "+vrm+"\n"
    else:
        try:native=data.decode("utf-8-sig")
        except UnicodeDecodeError as e:raise PackageError(ini+" must be UTF-8.") from e
    cfg=configparser.ConfigParser(interpolation=None,strict=False)
    try:cfg.read_string(native)
    except configparser.Error as e:raise PackageError("Invalid native INI: "+ini) from e
    if not any(s.lower()==section for s in cfg.sections()):
        raise PackageError(ini+" needs ["+section+"] section.")
    original=""
    if cfg.has_section("forge_mod"):
        existing=cfg.get("forge_mod","type",fallback="")
        if existing and existing!=kind:raise PackageError("Wrong existing Forge mod type.")
        original=cfg.get("forge_mod","id",fallback="").strip()
    local_id=original if SLUG.fullmatch(original) else "local_"+folder_name(title)[:55]
    # Only regenerate Forge metadata: keep the native sections and imported settings.
    out=[];in_meta=False
    for line in native.replace("\r\n","\n").splitlines():
        match=re.match(r"^\s*\[([^\]]+)\]\s*$",line)
        if match:in_meta=match.group(1).strip().lower()=="forge_mod"
        if not in_meta:out.append(line)
    final="\n".join(out).rstrip()
    final+=("\n\n[forge_mod]\nid = "+local_id+"\ntype = "+kind+
            "\nname = "+title+"\nversion = "+version+
            "\nsource = local\nenabled = true\n")
    return final.encode("utf-8"),local_id

def build_mod_zip(*,title,kind,version,author="",description="",
                  source_folder=None,selected_files=None,output):
    title=str(title).strip()
    author=str(author).strip()
    description=str(description).strip()
    if not 3<=len(title)<=100 or any(c in title for c in "\r\n[]"):
        raise PackageError("Mod name: 3-100 characters, without [ ] or newlines.")
    if kind not in CATEGORIES:raise PackageError("Choose Character, Kart, Wheels or Track.")
    if not VERSION.fullmatch(str(version)):
        raise PackageError("Invalid mod version (e.g. 1.0).")
    if len(author)>75 or any(c in author for c in "\r\n"):
        raise PackageError("Author: 75 characters maximum.")
    if len(description)>3000:raise PackageError("Description exceeds 3000 characters.")
    pairs=_list_assets(source_folder,selected_files)
    ini,_=CATEGORIES[kind]
    configs=[name for name,_ in pairs if PurePosixPath(name).name.lower() in
             {n for n,_ in CATEGORIES.values()}]
    if len(configs)>1 or (configs and configs[0]!=ini):
        raise PackageError("Select only one mod, with "+ini+" at the folder root.")
    entries=dict(pairs)
    obj=[PurePosixPath(name).stem for name,_ in pairs if name.lower().endswith(".obj")]
    if kind!="Track" and not obj:
        raise PackageError("A native model mod needs .obj. Use Model Importer first.")
    lev=[name for name,_ in pairs if name.lower().endswith(".lev")]
    vrm=[name for name,_ in pairs if name.lower().endswith(".vrm")]
    if kind=="Track" and (len(lev)!=1 or len(vrm)!=1 or
                          "/" in lev[0] or "/" in vrm[0]):
        raise PackageError("Track needs exactly one .lev and .vrm beside track.ini.")
    native=entries[ini].read_bytes() if ini in entries else None
    native,local_id=_native_ini(native,title,kind,str(version),
                               obj[0] if obj else "",
                               lev[0] if lev else "",vrm[0] if vrm else "")
    root=folder_name(title)
    out=Path(output).expanduser().resolve()
    if out.suffix.lower()!=".zip":raise PackageError("Export must be a .zip file.")
    if source_folder and out.is_relative_to(Path(source_folder).expanduser().resolve()):
        raise PackageError("Save the ZIP outside the mod's source folder.")
    if out.exists():raise PackageError("ZIP already exists. Pick a new file name.")
    if not out.parent.is_dir():raise PackageError("ZIP destination folder does not exist.")
    info={"schema":1,"name":title,"type":kind,"version":str(version),
          "author":author,"description":description,"id":local_id,
          "note":"Forge Hub assigns the permanent web ID on authenticated upload."}
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(prefix=".forge_pack_",suffix=".zip",
                                          dir=out.parent,delete=False) as f:
            tmp=Path(f.name)
        with zipfile.ZipFile(tmp,"w",compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6,allowZip64=False) as archive:
            for name,path in pairs:
                if name!=ini:archive.write(path,root+"/"+name)
            archive.writestr(root+"/"+ini,native)
            archive.writestr(root+"/forge_package.json",
                             json.dumps(info,ensure_ascii=False,indent=2).encode("utf-8"))
        size=tmp.stat().st_size
        if size>MAX_UPLOAD:raise PackageError("ZIP exceeds Forge Hub's 50 MiB limit.")
        with zipfile.ZipFile(tmp) as archive:
            if archive.testzip() is not None:raise PackageError("ZIP CRC test failed.")
        if out.exists():raise PackageError("ZIP path was created during packaging.")
        os.replace(tmp,out);tmp=None
        digest=hashlib.sha256(out.read_bytes()).hexdigest()
        return {"path":str(out),"size":size,"sha256":digest,
                "file_count":len(pairs)+1,"id":local_id,"category":kind}
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)
