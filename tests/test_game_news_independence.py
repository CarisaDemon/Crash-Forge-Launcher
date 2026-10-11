"""Live GAME and LAUNCHER NEWS stay independent; game experimental is opt-in."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import forge_game_news as gn
import forge_news_history as ln
import forge_releases as gr

ROOT=Path(__file__).resolve().parents[1]

def _release(version="2.1.0", prerelease=True, published="2026-10-11T10:12:20Z",
             *, asset=True, body=None):
    tag="v"+version
    name="Crash-Forge-Racing-Windows.zip"
    data={
        "tag_name":tag,
        "name":"Crash Forge Racing - Experimental",
        "html_url":"https://github.com/CarisaDemon/Crash-Forge-Racing/releases/tag/"+tag,
        "draft":False,
        "prerelease":prerelease,
        "published_at":published,
        "body":body if body is not None else (
            "- Playable Windows build\n- Better renderer\n"
            "- New online lobbies are an unreleased surprise\n- Custom tracks\n"),
        "assets":[{
            "name":name,"size":1400000,"digest":"sha256:"+"a"*64,
            "browser_download_url":
                "https://github.com/CarisaDemon/Crash-Forge-Racing/releases/download/"+tag+"/"+name
        }] if asset else [],
    }
    return data


class GameNewsIndependenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{"LOCALAPPDATA":self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_experimental_public_game_news_detected_but_draft_and_tools_ignored(self):
        actual=_release()
        news=gn.parse_public_game_releases([actual,dict(actual,draft=True),
                _release("9.0.0",asset=False),_release("3.0.0",published=None)])
        self.assertEqual(len(news),1)
        self.assertEqual(news[0]["source"],"GAME")
        self.assertEqual(news[0]["version"],"2.1.0")
        self.assertTrue(news[0]["prerelease"])
        self.assertTrue(news[0]["url"].startswith("https://github.com/CarisaDemon/Crash-Forge-Racing/"))
        self.assertTrue(any("Playable" in s for s in news[0]["notes"]))
        self.assertTrue(all("online" not in n.lower() and "lobbies" not in n.lower()
                            for n in news[0]["notes"]))

    def test_announcements_only_from_game_repo_not_launcher_or_malicious_sources(self):
        outsider=_release()
        outsider["html_url"]="https://example.org/games/2.1.0"
        missing_sha=_release("2.1.1")
        missing_sha["assets"][0]["digest"]=""
        self.assertEqual(gn.parse_public_game_releases([outsider]),[])
        self.assertEqual(gn.parse_public_game_releases([missing_sha])[0]["version"],"2.1.1")
        self.assertEqual(gn.parse_public_game_releases([
            {"tag_name":"v0.3.45","name":"Launcher","prerelease":False,
             "published_at":"2026-10-11T12:00:00Z","assets":[]},
            ]),[])

    def test_same_version_in_different_repos_keeps_separate_cards(self):
        launcher=ln.merge_history([{"version":"2.1.0","title":"Launcher",
                   "date":"2026-10-11","notes":["Launcher-only changes"]}])
        game=gn.parse_public_game_releases([_release()])
        combined=gn.combined_news(launcher,game)
        self.assertEqual(len(combined),2)
        self.assertEqual(set(i["identity"] for i in combined),
                         {"LAUNCHER/v2.1.0","GAME/v2.1.0"})
        self.assertEqual(combined[0]["source"],"GAME")
        self.assertEqual(combined[1]["source"],"LAUNCHER")
        self.assertNotEqual(combined[0]["url"],combined[1]["url"])

    def test_quiet_seen_indicator_persists_without_download(self):
        articles=gn.parse_public_game_releases([_release()])
        self.assertEqual(gn.latest_unread_game(articles)["version"],"2.1.0")
        self.assertTrue(gn.mark_game_seen("v2.1.0"))
        self.assertIsNone(gn.latest_unread_game(articles))
        newer=gn.parse_public_game_releases([_release("2.1.1")])
        self.assertEqual(gn.latest_unread_game(newer)["version"],"2.1.1")
        old=gn.parse_public_game_releases([_release("2.0.0")])
        self.assertIsNone(gn.latest_unread_game(old))
        self.assertFalse(gn.mark_game_seen("../../foo"))

    def test_prerelease_game_update_is_opt_in_only(self):
        sample=_release()
        self.assertIsNone(gr.parse_release(sample))
        parsed=gr.parse_release(sample,allow_prerelease=True)
        self.assertTrue(parsed["verified_package"])
        self.assertEqual(parsed["version"],"2.1.0")
        with patch.object(gr,"_read_json",return_value=[sample]):
            self.assertIsNone(gr.fetch_latest_release())
            self.assertEqual(gr.fetch_latest_release(allow_prerelease=True)["version"],"2.1.0")

    def test_launcher_release_version_is_unchanged_by_game_feed(self):
        v=(ROOT/"launcher_version.txt").read_text(encoding="utf-8").strip()
        self.assertRegex(v,r"^\d+\.\d+\.\d+$")
        game=gn.parse_public_game_releases([_release()])
        self.assertEqual(len(game),1)
        self.assertEqual((ROOT/"launcher_version.txt").read_text(encoding="utf-8").strip(),v)
        main=(ROOT/"forge_live_ui.py").read_text(encoding="utf-8")
        self.assertIn("ForgeIndependentNewsPoll",main)
        self.assertIn('("game_news_ok", published_game)',main)
        self.assertIn("self.after(600000, self._scheduled_news_history_check)",main)
        self.assertIn("self._acknowledge_game_news()", (ROOT/"launcher.py").read_text(encoding="utf-8"))
        self.assertIn("self._refresh_game_news_indicator()",main)
        self.assertNotIn("game_news.install",main)

    def test_game_news_fetch_errors_do_not_prevent_launcher_news(self):
        code=(ROOT/"forge_live_ui.py").read_text(encoding="utf-8")
        self.assertIn('("news_history_ok", merged)',code)
        self.assertIn('("game_news_error", str(error))',code)
        self.assertIn('("news_refresh_done", None)',code)
        self.assertIn("game_news.combined_news(",code)

    def test_cached_note_links_do_not_escape_official_source(self):
        not_game=_release()
        not_game["assets"][0]["browser_download_url"]="https://attacker.example/evil.zip"
        self.assertEqual(gn.parse_public_game_releases([not_game]),[])
        self.assertEqual(gn.latest_unread_game([]),None)


if __name__=="__main__":
    unittest.main()