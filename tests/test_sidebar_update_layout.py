"""No-window regression for Play/Update emphasis and Settings simplification."""
import inspect
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import forge_live_ui as live
import forge_releases as releases
import launcher


class ButtonStub:
    def __init__(self):
        self.text = ""
        self.accent = False
        self.disabled = False
        self.calls = []

    def set_label(self, label):
        self.text = label
        self.calls.append(("label", label))

    def set_disabled(self, disabled):
        self.disabled = bool(disabled)
        self.calls.append(("disabled", self.disabled))

    def set_accent(self, enabled):
        self.accent = bool(enabled)
        self.calls.append(("accent", self.accent))


class ContextStub:
    def __init__(self, installed=True, release=None, updating=False):
        self.sidebar_buttons = [ButtonStub(), ButtonStub()]
        self.local_game_status = {"installed": installed}
        self.latest_game_release = release
        self.game_install_path = r"C:\DummyCFR"
        self.game_update_busy = updating


class SidebarColorTests(unittest.TestCase):
    def apply(self, installed, release, version=None, updating=False):
        stub = ContextStub(installed, release, updating)
        with patch.object(releases, "game_installed_version", return_value=version):
            live.ForgeLiveMixin._update_primary_game_button(stub)
        return stub.sidebar_buttons

    def test_no_release_keeps_play_orange_update_gray(self):
        play, update = self.apply(True, None, "2.0.9")
        self.assertEqual(play.text, "PLAY")
        self.assertTrue(play.accent)
        self.assertFalse(play.disabled)
        self.assertFalse(update.accent)
        self.assertFalse(update.disabled, "Grey UPDATE should still allow checking Github")

    def test_newer_verified_release_highlights_big_update(self):
        game_release = {"version": "2.0.10", "verified_package": True}
        play, update = self.apply(True, game_release, "2.0.9")
        self.assertEqual(play.text, "PLAY")
        self.assertFalse(play.accent)
        self.assertFalse(play.disabled, "Do not force updating to allow PLAY")
        self.assertTrue(update.accent)
        self.assertFalse(update.disabled)

    def test_current_version_does_not_show_new_update(self):
        release = {"version": "2.0.10", "verified_package": True}
        for version in ("2.0.10", "2.0.11"):
            with self.subTest(version=version):
                play, update = self.apply(True, release, version)
                self.assertTrue(play.accent)
                self.assertFalse(update.accent)

    def test_unchecked_and_unverified_versions_do_not_light_update(self):
        no_zip = {"version": "2.0.10", "verified_package": False}
        play, update = self.apply(True, no_zip, "2.0.9")
        self.assertTrue(play.accent)
        self.assertFalse(update.accent)

    def test_unknown_local_version_can_offer_verified_release(self):
        release = {"version": "2.0.10", "verified_package": True}
        play, update = self.apply(True, release, None)
        self.assertFalse(play.accent)
        self.assertTrue(update.accent)

    def test_install_without_release_stays_disabled(self):
        play, update = self.apply(False, None)
        self.assertEqual(play.text, "INSTALL")
        self.assertFalse(play.accent)
        self.assertTrue(play.disabled)
        self.assertFalse(update.accent)

    def test_install_with_verified_release_is_orange(self):
        release = {"version": "2.0.10", "verified_package": True}
        play, update = self.apply(False, release)
        self.assertEqual(play.text, "INSTALL")
        self.assertTrue(play.accent)
        self.assertFalse(play.disabled)
        self.assertFalse(update.accent)

    def test_during_install_buttons_are_inactive(self):
        release = {"version": "2.0.10", "verified_package": True}
        play, update = self.apply(True, release, "2.0.9", updating=True)
        self.assertTrue(play.disabled)
        self.assertTrue(update.disabled)

    def test_accent_toggle_redraws_instead_of_replacing_button(self):
        class Dummy:
            accent = False
            renders = 0
            def render(self):
                self.renders += 1
        button = Dummy()
        launcher.ForgeButton.set_accent(button, True)
        self.assertTrue(button.accent)
        self.assertEqual(button.renders, 1)
        launcher.ForgeButton.set_accent(button, True)
        self.assertEqual(button.renders, 1)
        launcher.ForgeButton.set_accent(button, False)
        self.assertFalse(button.accent)
        self.assertEqual(button.renders, 2)

    def test_big_update_remains_and_settings_has_only_launcher_updates(self):
        sidebar = inspect.getsource(launcher.Launcher._sidebar)
        self.assertIn('ForgeButton(self.sidebar, "UPDATE", "update", self._check_game_update)', sidebar)
        self.assertIn('ForgeButton(self.sidebar, "PLAY"', sidebar)
        settings = inspect.getsource(launcher.Launcher._settings_card)
        compact = inspect.getsource(launcher.Launcher._open_compact_settings)
        for method in (settings, compact):
            self.assertIn("_add_launcher_update_settings_controls(", method)
            self.assertNotIn("self._add_release_settings_controls(", method)
        responsive = inspect.getsource(launcher.Launcher._apply_responsive_layout)
        self.assertIn("max(320", responsive, "Settings column should not shrink too far")
        self.assertIn("settings_height = 255", responsive)


if __name__ == "__main__":
    unittest.main(verbosity=2)
