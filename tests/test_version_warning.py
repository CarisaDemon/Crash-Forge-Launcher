"""No-focus tests for verified-game-version popup and PLAY behavior."""
import inspect
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import forge_live_ui as live
import forge_releases as releases
import forge_version_dialog as dialog


class VersionWarningTests(unittest.TestCase):
    verified = {"version": "2.0.10", "verified_package": True}

    def test_only_older_verified_game_release_triggers_warning(self):
        with patch.object(releases, "game_installed_version", return_value="2.0.9"):
            item = live.available_game_update(r"C:\Fake", self.verified)
        self.assertEqual(item, {"installed": "2.0.9",
                                "available": "2.0.10", "unknown": False})

    def test_up_to_date_and_newer_game_do_not_warn(self):
        for current in ("2.0.10", "2.0.11"):
            with self.subTest(current=current), patch.object(
                    releases, "game_installed_version", return_value=current):
                self.assertIsNone(live.available_game_update(r"C:\Fake", self.verified))

    def test_never_warn_on_missing_or_unverified_release(self):
        for item in (None, {}, {"version": "2.0.10", "verified_package": False},
                     {"version": "bad", "verified_package": True}):
            with self.subTest(item=item), patch.object(
                    releases, "game_installed_version", return_value="2.0.9"):
                self.assertIsNone(live.available_game_update(r"C:\Fake", item))

    def test_unknown_version_displays_uncertainty(self):
        with patch.object(releases, "game_installed_version", return_value=None):
            item = live.available_game_update(r"C:\Fake", self.verified)
        self.assertEqual(item["unknown"], True)
        self.assertIsNone(item["installed"])

    def _fake_app(self, release=None, allow=True, busy=False):
        app = Mock()
        app.game_install_path = r"C:\Fake"
        app.latest_game_release = release
        app.game_update_busy = busy
        app._confirm_play_older_game.return_value = allow
        app.status_label = Mock()
        return app

    def _run_play(self, app, version="2.0.9"):
        fake_status = {"installed": True, "exe_path": r"C:\Fake\ctr-native.exe"}
        with patch.object(releases, "game_installed_version", return_value=version), \
             patch.object(live.services, "real_game_status", return_value=fake_status), \
             patch.object(live.subprocess, "Popen") as launch:
            live.ForgeLiveMixin._play_installed_game(app)
        return launch

    def test_cancel_never_starts_game(self):
        app = self._fake_app(self.verified, allow=False)
        started = self._run_play(app)
        started.assert_not_called()
        app._confirm_play_older_game.assert_called_once()
        self.assertIn("cancelled", app.status_label.configure.call_args.kwargs["text"])

    def test_play_anyway_starts_exactly_once(self):
        app = self._fake_app(self.verified, allow=True)
        started = self._run_play(app)
        started.assert_called_once_with(
            [r"C:\Fake\ctr-native.exe"], cwd=r"C:\Fake")
        item = app._confirm_play_older_game.call_args.args[0]
        self.assertEqual(item["available"], "2.0.10")

    def test_no_update_starts_directly_without_prompt(self):
        app = self._fake_app(None)
        started = self._run_play(app)
        started.assert_called_once()
        app._confirm_play_older_game.assert_not_called()

    def test_same_version_starts_without_prompt(self):
        app = self._fake_app(self.verified)
        started = self._run_play(app, version="2.0.10")
        started.assert_called_once()
        app._confirm_play_older_game.assert_not_called()

    def test_busy_update_never_launches(self):
        app = self._fake_app(self.verified, busy=True)
        started = self._run_play(app)
        started.assert_not_called()
        app._confirm_play_older_game.assert_not_called()

    def test_modal_is_branded_english_and_uses_no_wallpaper(self):
        code = inspect.getsource(dialog.ask_play_outdated)
        self.assertIn("VERSION WARNING", code)
        self.assertIn("PLAY ANYWAY", code)
        self.assertIn("CANCEL", code)
        self.assertIn("tk.Toplevel", code)
        self.assertIn("grab_set()", code)
        self.assertIn("wait_window", code)
        self.assertIn('create_polygon(', code)
        self.assertIn('colors["orange"]', code)
        self.assertIn("Future online features", code)
        self.assertNotIn("Fondo", code)
        self.assertNotIn("attach_fondo_background", code)
        self.assertNotIn("messagebox.askyesno", code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
