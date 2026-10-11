"""Regression coverage for v0.3.47: launch, repair, latest NEWS, account cache."""
from pathlib import Path
from types import SimpleNamespace
import os
import tempfile
import unittest
from unittest import mock

import forge_game_launch as game_launch
import forge_game_news as game_news
import forge_news_history as launcher_news
import forge_account_badge as badge
import forge_account_client as accounts
import forge_live_ui as live


class GameStartRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "ctr-native.exe").write_bytes(b"MZ")
        (self.root / "assets").mkdir()

    def test_play_explains_missing_disc_without_attempting_to_run(self):
        issue = game_launch.launch_issue(str(self.root))
        self.assertIn("assets/ctr-u.bin", issue)
        self.assertIn("legally obtained", issue)
        app = mock.Mock()
        app.game_install_path = str(self.root)
        app.game_update_busy = False
        with mock.patch.object(live.subprocess, "Popen") as popen, \
             mock.patch.object(live.messagebox, "showwarning") as warn:
            live.ForgeLiveMixin._play_installed_game(app)
        popen.assert_not_called()
        warn.assert_called_once()
        self.assertIn("GAME DATA NEEDED", str(app.set_download_status.call_args))

    def test_play_accepts_raw_disc_path_without_searching_elsewhere(self):
        (self.root / "assets" / "ctr-u.bin").write_bytes(b"x" * 2352)
        self.assertEqual(game_launch.launch_issue(str(self.root)), "")
        self.assertFalse((self.root / "mods").exists())

    def test_repair_creates_root_mods_and_never_legacy_or_disc(self):
        report = game_launch.repair_local_files(str(self.root))
        self.assertTrue(report["ok"])
        self.assertTrue(report["created_mods"])
        self.assertTrue(report["missing_disc"])
        self.assertTrue((self.root / "mods").is_dir())
        self.assertFalse((self.root / "assets" / "mods").exists())
        self.assertFalse((self.root / "assets" / "ctr-u.bin").exists())
        user = self.root / "mods" / "my_mod.txt"
        user.write_text("do not erase", encoding="utf-8")
        again = game_launch.repair_local_files(str(self.root))
        self.assertFalse(again["created_mods"])
        self.assertEqual(user.read_text(encoding="utf-8"), "do not erase")

    def test_repair_never_creates_game_or_mods_in_wrong_folder(self):
        empty = self.root / "other"
        empty.mkdir()
        self.assertFalse(game_launch.repair_local_files(str(empty))["ok"])
        self.assertFalse((empty / "mods").exists())
        self.assertFalse(game_launch.repair_local_files("")["ok"])


class LatestIndependentUpdatesTests(unittest.TestCase):
    def test_latest_game_or_launcher_uses_real_timestamp_on_same_day(self):
        original = launcher_news.merge_history([{
            "version": "0.3.47", "date": "2026-10-11",
            "published_at": "2026-10-11T13:11:00Z",
            "notes": ["Launcher fix"]}])
        game = [{"source":"GAME","tag":"v2.1.0","version":"2.1.0",
                 "date":"2026-10-11","published_at":"2026-10-11T15:07:37Z",
                 "url":"https://github.com/CarisaDemon/Crash-Forge-Racing/releases/tag/v2.1.0",
                 "title":"Crash Forge: Racing","notes":["New game"]}]
        combined = game_news.combined_news(original, game)
        self.assertEqual(combined[0]["source"], "GAME")
        self.assertEqual(combined[0]["identity"], "GAME/v2.1.0")
        newer_launch = launcher_news.merge_history([{
            "version":"0.3.47","date":"2026-10-11",
            "published_at":"2026-10-11T16:20:00Z"}])
        combined2 = game_news.combined_news(newer_launch, game)
        self.assertEqual(combined2[0]["source"], "LAUNCHER")
        self.assertEqual(combined2[1]["source"], "GAME")
        self.assertEqual(combined2[0]["url"],
                         launcher_news.release_url("0.3.47"))

    def test_feature_selector_uses_same_combined_timeline_as_news(self):
        from launcher import Launcher
        launches = launcher_news.merge_history([{
            "version":"0.3.47","published_at":"2026-10-11T11:00:00Z"}])
        game = [{"source":"GAME", "tag":"v2.1.0", "version":"2.1.0",
                 "published_at":"2026-10-11T15:00:00Z"}]
        app = SimpleNamespace(launcher_news_history=launches,
                              game_news_history=game)
        featured = Launcher._featured_news_update(app)
        self.assertEqual(featured["identity"], "GAME/v2.1.0")

    def test_launcher_publication_time_is_retained_in_cache(self):
        record = launcher_news.merge_history(
            [{"version":"0.3.47","published_at":"2026-10-11T17:01:31Z"}],
            [{"version":"0.3.47","date":"2026-10-11","notes":["Fixed issues"]}])
        self.assertEqual(record[0]["published_at"], "2026-10-11T17:01:31Z")


class SavedAccountIdentityTests(unittest.TestCase):
    def test_signed_in_pending_and_offline_never_show_guest(self):
        pending = badge.account_label({"username":"my_racer"},
                                      connected=False,signed_in=True,pending=True)
        self.assertEqual(pending["name"], "my_racer")
        self.assertEqual(pending["status"], "Connecting...")
        offline = badge.account_label({"username":"my_racer"},
                                      connected=False,signed_in=True,pending=False)
        self.assertEqual(offline["name"], "my_racer")
        self.assertEqual(offline["status"], "Offline")
        self.assertEqual(badge.account_label({},connected=False,
                         signed_in=True)["name"], "My Account")

    def test_encrypted_session_restores_identity_and_survives_offline_error(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(accounts, "_dpapi",
                               side_effect=lambda data,decrypt=False: data):
            client=accounts.AccountClient(root=tmp,persist=True)
            client._save_session({"access_token":"secret-access",
                                  "refresh_token":"secret-refresh","expires_in":3600})
            user={"id":"12345678-1234-1234-1234-123456789012",
                  "email":"test@example.invalid","identities":[]}
            rows=[{"username":"my_racer","display_name":"My Racer"}]
            with mock.patch.object(client,"_request",side_effect=[user,rows]):
                self.assertEqual(client.profile()["username"],"my_racer")
            restored=accounts.AccountClient(root=tmp,persist=True)
            self.assertTrue(restored.signed_in)
            self.assertEqual(restored.cached_profile()["username"],"my_racer")
            with mock.patch.object(restored,"_request",side_effect=accounts.AccountError("Temporary outage")):
                with self.assertRaises(accounts.AccountError):
                    restored.profile()
            self.assertTrue(restored.signed_in)
            self.assertEqual(restored.cached_profile()["username"],"my_racer")
            restored.sign_out()
            self.assertFalse(restored.cached_profile())
            self.assertFalse((Path(tmp)/"session.dat").exists())


if __name__=="__main__":
    unittest.main()
