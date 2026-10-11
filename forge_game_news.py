"""Public game RELEASE news only, independent of launcher updates.

Read published GitHub releases from pinned CarisaDemon/Crash-Forge-Racing.
Items show in the launcher's NEWS panel but DO NOT affect launcher version,
downloads, files, game folder or launcher update cadence. No game EXE/ISO
bundled in the launcher. A user explicitly opens NEWS to acknowledge the
quiet 'new game release' indicator.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

import forge_releases as game_releases
import forge_news_history as launcher_news

GAME_REPOSITORY = game_releases.REPOSITORY
GAME_RELEASES_URL = game_releases.RELEASES_URL
GAME_API_URL = game_releases.RELEASE_LIST_API_URL
MAX_POSTS = 24
SECRET_TERMS = re.compile(
    r"\b(?:online|multiplayer|netcode|networking|matchmaking|lobby|lobbies)\b",
    re.I,
)


def _published(raw):
    if not isinstance(raw, dict) or raw.get("draft"):
        return False
    date = str(raw.get("published_at") or "")
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T.{5,35}", date))


def parse_public_game_releases(releases):
    """Only real published GAME ZIP releases. Include announced experimental
    prereleases; those are never installed without the user's permission.
    """
    if not isinstance(releases, list):
        return []
    articles = []
    for item in releases[:100]:
        if not _published(item):
            continue
        try:
            parsed = game_releases.parse_release(item, allow_prerelease=True)
        except (game_releases.ReleaseError, ValueError, TypeError):
            continue
        if not parsed or not parsed.get("asset"):
            continue
        tag = str(parsed["tag"])
        if len(tag) > 96:
            continue
        body = str(item.get("body") or "")
        lines = []
        for entry in body[:14000].splitlines():
            line = entry.strip()
            if not line.startswith(("- ", "* ")):
                continue
            content = launcher_news._plain(line[2:])
            if not content or SECRET_TERMS.search(content):
                continue
            lines.append(content[:220])
            if len(lines) >= 5:
                break
        if not lines:
            lines = ["A new experimental game build is available. View release details."]
        articles.append({
            "source": "GAME",
            "tag": tag,
            "version": parsed["version"],
            "title": "Crash Forge: Racing v" + parsed["version"],
            "date": parsed.get("published_at","")[:10],
            "published_at": parsed.get("published_at","")[:30],
            "notes": lines,
            "url": parsed["url"],
            "prerelease": bool(item.get("prerelease")),
        })
    deduped = {a["tag"]: a for a in articles}
    return sorted(deduped.values(),
                  key=lambda a: (a["published_at"], a["tag"]),
                  reverse=True)[:MAX_POSTS]


def combined_news(launcher_entries, game_entries):
    """Timeline with source-specific identities (not one shared version)."""
    combined = []
    for entry in launcher_entries or []:
        if not isinstance(entry, dict):
            continue
        version = launcher_news.valid_version(entry.get("version"))
        if not version:
            continue
        combined.append({
            **entry, "source": "LAUNCHER",
            "identity": "LAUNCHER/v" + version,
            "display_version": "v" + version,
        })
    for entry in game_entries or []:
        if not isinstance(entry, dict) or entry.get("source") != "GAME":
            continue
        tag=entry.get("tag","")
        if (not isinstance(tag,str) or not tag.startswith("v") or
                not game_releases.parse_version(tag)):
            continue
        combined.append({
            **entry, "identity": "GAME/" + tag,
            "display_version": tag,
        })
    # Order by the full real publication timestamp, even on the same day.
    # Never compare game and launcher *version numbers* against each other.
    def chronology(entry):
        timestamp = str(entry.get("published_at") or "")
        if not timestamp:
            date = str(entry.get("date") or "")
            timestamp = date + "T00:00:00Z" if date else ""
        return timestamp, str(entry.get("identity", ""))
    return sorted(combined, key=chronology, reverse=True)


def _marker():
    return launcher_news.state_dir() / "last_seen_game_news.json"


def seen_game_tag():
    p=_marker()
    try:
        if p.is_file() and p.stat().st_size < 2048:
            raw=json.loads(p.read_text(encoding="utf-8"))
            tag=raw.get("tag","") if isinstance(raw,dict) else ""
            if isinstance(tag,str) and len(tag)<96 and game_releases.parse_version(tag):
                return tag
    except (OSError,ValueError,UnicodeError):
        pass
    return ""


def latest_unread_game(news_items, seen=None):
    articles=[a for a in news_items
              if isinstance(a,dict) and a.get("source")=="GAME"]
    if not articles:
        return None
    latest=max(articles,key=lambda x:(str(x.get("published_at","")),
                                    str(x.get("tag",""))))
    last=seen_game_tag() if seen is None else seen
    # Compare version tuples but also distinguish stable from prior experiment.
    if latest["tag"] == last:
        return None
    if last and game_releases.compare_versions(last,latest["tag"]) == 1:
        return None
    return latest


def mark_game_seen(tag):
    if not isinstance(tag,str) or len(tag)>96 or not game_releases.parse_version(tag):
        return False
    folder=_marker().parent
    tmp=None
    try:
        folder.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix="game_seen_",suffix=".tmp",dir=folder)
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump({"tag":tag},f)
        os.replace(tmp,_marker())
        return True
    except OSError:
        return False
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
