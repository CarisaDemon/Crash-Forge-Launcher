"""Forge Profiles: offline-first mod snapshots and private, explicit Forge Hub sync."""
from pathlib import Path
from uuid import uuid4, UUID
from datetime import datetime, timezone
import json
import os
import re
import tempfile
import urllib.parse

import forge_mod_manager as manager
from forge_account_client import SUPABASE

KINDS = frozenset({"Character","Kart","Wheels","Track","Music"})
VALID_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_PROFILES = 80
MAX_MODS = 512

class ProfileError(ValueError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def root_for(game_path):
    path=Path(game_path) if game_path else None
    if path is None or not path.is_dir():
        raise ProfileError("Select an existing game folder first.")
    if path.is_symlink():
        raise ProfileError("Game folder cannot be a symbolic link")
    return path/".forge_profiles"

def validate_profile(profile):
    if not isinstance(profile,dict):
        raise ProfileError("Invalid profile data")
    try:
        uid=str(UUID(str(profile.get("id", ""))))
    except ValueError as exc:
        raise ProfileError("Invalid profile ID") from exc
    name=profile.get("name")
    if not isinstance(name,str) or not (1<=len(name.strip())<=60) or any(ord(x)<32 for x in name):
        raise ProfileError("Invalid profile name")
    rows=profile.get("mods")
    if not isinstance(rows,list) or len(rows)>MAX_MODS:
        raise ProfileError("Invalid mod list")
    seen=set()
    for row in rows:
        if (not isinstance(row,dict) or row.get("type") not in KINDS or
            not isinstance(row.get("id"),str) or not VALID_ID.fullmatch(row["id"]) or
            not isinstance(row.get("enabled"),bool)):
            raise ProfileError("Invalid mod entry")
        key=(row["type"],row["id"])
        if key in seen: raise ProfileError("Duplicated mod entry")
        seen.add(key)
        if not isinstance(row.get("title",""),str) or len(row.get("title",""))>100:
            raise ProfileError("Invalid mod title")
    return {"id":uid,"name":name.strip(),"mods":rows,
            "updated_at":str(profile.get("updated_at") or now())[:40]}

def load(game_path):
    path=root_for(game_path)/"profiles.json"
    if not path.exists():
        return {"schema":1,"profiles":[]}
    if path.is_symlink() or path.stat().st_size>262144:
        raise ProfileError("Profile storage is unsafe")
    try:
        doc=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,ValueError) as exc:
        raise ProfileError("Could not read local profiles") from exc
    if not isinstance(doc,dict) or doc.get("schema")!=1 or not isinstance(doc.get("profiles"),list):
        raise ProfileError("Invalid Forge Profiles data")
    if len(doc["profiles"])>MAX_PROFILES:
        raise ProfileError("Too many profiles")
    doc["profiles"]=[validate_profile(x) for x in doc["profiles"]]
    if len(set(x["id"] for x in doc["profiles"]))!=len(doc["profiles"]):
        raise ProfileError("Duplicate profile IDs")
    return doc

def save(game_path,doc):
    if not isinstance(doc,dict) or doc.get("schema")!=1 or not isinstance(doc.get("profiles"),list) or len(doc["profiles"])>MAX_PROFILES:
        raise ProfileError("Invalid profile collection")
    doc={"schema":1,"profiles":[validate_profile(x) for x in doc["profiles"]]}
    base=root_for(game_path)
    if base.is_symlink():
        raise ProfileError("Linked profile directory is unsafe")
    base.mkdir(exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".forge_profiles_",dir=base,suffix=".tmp")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(doc,f,indent=2,ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,base/"profiles.json")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def snapshot(game_path,name):
    name=str(name).strip()
    if not 1<=len(name)<=60 or any(ord(c)<32 for c in name):
        raise ProfileError("Profile name must be 1-60 printable characters")
    states=[]
    for item in manager.scan_installed(game_path):
        if (item.get("type") in KINDS and item.get("manageable") and
            isinstance(item.get("enabled"),bool)):
            states.append({"type":item["type"],"id":item["id"],
                           "enabled":item["enabled"],"title":item.get("title","")[:100]})
    doc=load(game_path)
    if any(p["name"].casefold()==name.casefold() for p in doc["profiles"]):
        raise ProfileError("That name is already used on this PC")
    if len(doc["profiles"])>=MAX_PROFILES:raise ProfileError("Maximum local profile count reached")
    profile=validate_profile({"id":str(uuid4()),"name":name,"mods":states,"updated_at":now()})
    doc["profiles"].append(profile)
    save(game_path,doc)
    return profile

def plan_apply(game_path,profile):
    profile=validate_profile(profile)
    installed={(p["type"],p["id"]):p for p in manager.scan_installed(game_path)
               if p.get("type") in KINDS and p.get("manageable")}
    changes=[];missing=[]
    for row in profile["mods"]:
        current=installed.get((row["type"],row["id"]))
        if current is None:missing.append(row)
        elif current["enabled"]!=row["enabled"]:
            changes.append((current,row["enabled"]))
    # New local mods NOT in a saved profile are left unchanged.
    return changes,missing

def apply(game_path,profile):
    steps,missing=plan_apply(game_path,profile)
    originals=[]
    try:
        for current,_ in steps:
            ini=Path(current["path"])/manager.CATEGORIES[current["type"]][1]
            if not ini.is_file() or ini.is_symlink():
                raise ProfileError("Mod INI no longer available")
            originals.append((ini,ini.read_bytes()))
        for current,enabled in steps:
            manager.set_enabled(game_path,current["type"],current["id"],enabled)
    except Exception as exc:
        # Restore actual bytes, not inferred toggle state, even on partial failure.
        for ini,data in reversed(originals):
            if not ini.is_file() or ini.is_symlink():continue
            try:
                fd,tmp=tempfile.mkstemp(prefix=".forge_profile_rollback_",dir=ini.parent)
                with os.fdopen(fd,"wb") as f:f.write(data)
                os.replace(tmp,ini)
            except OSError:pass
            finally:
                if "tmp" in locals() and os.path.exists(tmp):os.unlink(tmp)
        raise ProfileError("Profile failed; original INI contents were restored where possible: "+str(exc)) from exc
    return len(steps),missing

def delete(game_path,profile_id):
    doc=load(game_path)
    doc["profiles"]=[p for p in doc["profiles"] if p["id"]!=profile_id]
    save(game_path,doc)

def cloud_list(account):
    token=account.token()
    result=account._request(
        SUPABASE+"/rest/v1/forge_mod_profiles?select=id,name,mod_states,revision,updated_at&order=updated_at.desc",
        token=token,method="GET")
    if not isinstance(result,list) or len(result)>MAX_PROFILES:
        raise ProfileError("Invalid cloud profile response")
    profiles=[]
    for row in result:
        if not isinstance(row,dict):
            raise ProfileError("Invalid cloud profile entry")
        revision=row.get("revision")
        if isinstance(revision,bool) or not isinstance(revision,int) or not 1 <= revision < 2147483647:
            raise ProfileError("Invalid cloud profile revision")
        profile=validate_profile({"id":row["id"],"name":row["name"],
                 "mods":row["mod_states"],"updated_at":row["updated_at"]})
        profile["revision"]=revision
        profiles.append(profile)
    return profiles

def cloud_upload_new(account,profile):
    profile=validate_profile(profile)
    identity=account.profile()["id"]
    existing={p["id"] for p in cloud_list(account)}
    if profile["id"] in existing:
        raise ProfileError("This cloud profile already exists. Download it or create a new local snapshot; nothing was overwritten.")
    return account._request(SUPABASE+"/rest/v1/forge_mod_profiles",
        {"id":profile["id"],"owner_id":identity,"name":profile["name"],
         "mod_states":profile["mods"]},token=account.token(),method="POST")

def cloud_delete(account, profile):
    """Delete one private cloud copy, never touching installed mods or local snapshots.

    Revision makes a stale selection fail safely; Supabase RLS limits
    deletions to the authenticated owner, even if a client is compromised.
    """
    if not isinstance(profile, dict):
        raise ProfileError("Invalid cloud selection")
    revision = profile.get("revision")
    profile = validate_profile(profile)
    if not isinstance(revision, int) or isinstance(revision, bool) or not 1 <= revision < 2147483647:
        raise ProfileError("Cloud copy has no verified revision; fetch cloud profiles again")
    uid = account.profile()["id"]
    url = (SUPABASE + "/rest/v1/forge_mod_profiles?select=id"
           + "&id=eq." + profile["id"]
           + "&owner_id=eq." + str(uid)
           + "&revision=eq." + str(revision))
    rows = account._request(url, token=account.token(), method="DELETE",
                            prefer="return=representation")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("id") != profile["id"]:
        raise ProfileError("Cloud copy changed or is already deleted. Fetch again; no local data was changed.")
    return profile["id"]


def cloud_import(game_path,profile):
    doc=load(game_path)
    profile=validate_profile(profile)
    if any(p["id"]==profile["id"] for p in doc["profiles"]):
        raise ProfileError("A local copy already exists. Resolve the conflict manually; no data was changed.")
    if any(p["name"].casefold()==profile["name"].casefold() for p in doc["profiles"]):
        raise ProfileError("A local profile already uses that name. Rename it first.")
    if len(doc["profiles"])>=MAX_PROFILES:raise ProfileError("Too many local profiles")
    doc["profiles"].append(profile)
    save(game_path,doc)
    return profile
