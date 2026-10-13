"""Urgent v0.3.56 regression: disabled auto-updates cannot stage or apply."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import forge_game_launch as game
import forge_launcher_updates as updates
import forge_live_ui as live

class BinaryCompatTests(unittest.TestCase):
    def test_non_executable_marker_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            binary=Path(temp)/"ctr-native.exe"
            binary.write_bytes(b"MZ"+b"A"*2000+b"CFR_NO_MODS_V1"+b"--supports-no-mods"+b"--no-mods")
            self.assertTrue(game.supports_native_no_mods(binary))
            binary.write_bytes(b"MZ"+b"A"*2000+b"--no-mods")
            self.assertFalse(game.supports_native_no_mods(binary))
            binary.write_bytes(b"not windows"+b"CFR_NO_MODS_V1--supports-no-mods--no-mods")
            self.assertFalse(game.supports_native_no_mods(binary))

class ConsentTests(unittest.TestCase):
    def setUp(self):
        self.work=tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.prefs=Path(self.work.name)/"launcher_settings.json"

    def put(self,value):
        self.prefs.write_text(json.dumps({"launcher_auto_update":value}),encoding="utf-8")

    def test_missing_invalid_or_string_settings_default_to_disabled(self):
        self.assertFalse(updates.automatic_updates_allowed(self.prefs))
        for value in (False,None,"true","false",0,1):
            self.put(value)
            self.assertFalse(updates.automatic_updates_allowed(self.prefs))
        self.prefs.write_text("{bad json",encoding="utf-8")
        self.assertFalse(updates.automatic_updates_allowed(self.prefs))

    def test_true_requires_explicit_persisted_opt_in(self):
        self.put(True)
        self.assertTrue(updates.automatic_updates_allowed(self.prefs))
        self.put(False)
        self.assertFalse(updates.automatic_updates_allowed(self.prefs))

    def test_stale_in_memory_true_still_denied(self):
        self.put(False)
        app=live.ForgeLiveMixin()
        app._forge_base_dir=lambda:self.work.name
        app.launcher_auto_update=True
        self.assertFalse(app._launcher_automatic_updates_allowed())
        self.put(True)
        app.launcher_auto_update=False
        self.assertFalse(app._launcher_automatic_updates_allowed())
        app.launcher_auto_update=True
        self.assertTrue(app._launcher_automatic_updates_allowed())

    def test_disabled_startup_never_checks_or_stages(self):
        self.put(False)
        app=live.ForgeLiveMixin()
        app._forge_base_dir=lambda:self.work.name
        app.launcher_auto_update=True
        app._request_launcher_update_check=mock.Mock()
        app._startup_launcher_update_check()
        app._request_launcher_update_check.assert_not_called()

    def test_manual_check_does_not_stage_when_disabled(self):
        self.put(False)
        app=live.ForgeLiveMixin()
        app._forge_base_dir=lambda:self.work.name
        app.launcher_auto_update=True
        app.launcher_update_busy=False
        app._launcher_integrity_needs_repair=False
        app._launcher_update_retry_after=0
        app.launcher_update_status_var=mock.Mock()
        app.online_queue=__import__("queue").Queue()
        with mock.patch.object(live.launcher_updates,"fetch_latest",return_value={"version":"9.9.9"}), \
             mock.patch.object(live.launcher_updates,"update_required",return_value=True), \
             mock.patch.object(live.launcher_updates,"stage_release",
                               side_effect=AssertionError("Must not stage")):
            with mock.patch.object(live.threading,"Thread") as thread:
                thread.return_value.start.side_effect=lambda: thread.call_args.kwargs["target"]()
                app._request_launcher_update_check(manual=True)
        self.assertEqual(app.online_queue.get_nowait()[0],"launcher_update_ok")

    def test_other_setting_saves_cannot_reenable_auto_update(self):
        import launcher
        self.put(False)
        class Fake:
            _launcher_settings_data={"launcher_auto_update":True}
            launcher_auto_update=True
            game_install_path=""
            release_check_frequency="Daily"
            release_last_check=0
            release_last_result=""
            launcher_last_check=0
            launcher_last_result=""
            remember_play_choice=False
            preferred_play_mode="normal"
            launcher_auto_update_var=mock.Mock()
        fake=Fake()
        with mock.patch.object(launcher,"SETTINGS_FILE",str(self.prefs)), \
             mock.patch.object(launcher.editor_config,"save_launcher_selection"):
            self.assertTrue(launcher.Launcher._save_launcher_settings(fake))
            self.assertFalse(json.loads(self.prefs.read_text())["launcher_auto_update"])
            self.assertTrue(launcher.Launcher._save_launcher_settings(fake,update_consent=True))
            self.assertTrue(updates.automatic_updates_allowed(self.prefs))
            self.assertTrue(launcher.Launcher._save_launcher_settings(fake,update_consent=False))
            self.assertFalse(updates.automatic_updates_allowed(self.prefs))
if __name__=="__main__":
    unittest.main()
