"""v0.3.48: PLAY disabled for any missing official release file."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import forge_game_launch as game
import forge_live_ui as live


class Control:
    def __init__(self):
        self.disabled = False
        self.accent = False
        self.text = None
    def set_label(self, value):
        self.text = value
    def set_disabled(self, value):
        self.disabled = bool(value)
    def set_accent(self, value):
        self.accent = bool(value)


class CompleteGameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in game.RELEASE_210:
            p = self.root.joinpath(*name.split("/"))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"MZ" if name.endswith(".exe") else b"release")
        iso = self.root.joinpath(*game.DISC_IMAGE.split("/"))
        iso.write_bytes(b"x" * 2352)
        (self.root / "forge_release_state.json").write_text(
            json.dumps({"version": "2.1.0", "tag":"v2.1.0"}), encoding="utf-8")

    def test_complete_legacy_release_is_ready(self):
        self.assertEqual(game.missing_game_files(self.root), [])
        self.assertEqual(game.launch_issue(self.root), "")

    def test_every_official_release_file_is_required_individually(self):
        for name in game.RELEASE_210:
            with self.subTest(name=name):
                target = self.root.joinpath(*name.split("/"))
                original = target.read_bytes()
                target.unlink()
                try:
                    self.assertIn(name, game.missing_game_files(self.root))
                    self.assertIn(name, game.launch_issue(self.root))
                finally:
                    target.write_bytes(original)

    def test_multiple_missing_files_are_reported_at_once(self):
        (self.root/"README_FIRST.txt").unlink()
        (self.root/"assets/UI_NATIVE/finalbuttons.png").unlink()
        result = game.missing_game_files(self.root)
        self.assertEqual(set(result), {"README_FIRST.txt", "assets/UI_NATIVE/finalbuttons.png"})

    def test_new_releases_use_their_own_complete_manifest(self):
        marker = self.root / "forge_release_state.json"
        extra = self.root/"assets"/"shaders"/"required.glsl"
        marker.write_text(json.dumps({"version": "2.1.1",
                                      "package_files": ["ctr-native.exe",
                                                        "assets/shaders/required.glsl",
                                                        "README_FIRST.txt"]}), encoding="utf-8")
        self.assertEqual(game.missing_game_files(self.root), ["assets/shaders/required.glsl"])
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("void main(){}", encoding="utf-8")
        self.assertEqual(game.launch_issue(self.root), "")
        # Invalid relative paths are never followed to outside the game root.
        marker.write_text(json.dumps({"version":"2.1.1","package_files":
                                      ["ctr-native.exe","../private.txt"]}), encoding="utf-8")
        self.assertIn("forge_release_state.json", game.launch_issue(self.root))

    def test_sidebar_greys_and_disables_play_when_any_file_is_missing(self):
        app = SimpleNamespace(
            sidebar_buttons=[Control(), Control()],
            local_game_status={"installed": True},
            latest_game_release=None, game_install_path=str(self.root),
            game_update_busy=False,
            _play_issue="Missing required game files: README_FIRST.txt")
        live.ForgeLiveMixin._update_primary_game_button(app)
        play = app.sidebar_buttons[0]
        self.assertEqual(play.text, "PLAY")
        self.assertTrue(play.disabled)
        self.assertFalse(play.accent)
        app._play_issue = ""
        live.ForgeLiveMixin._update_primary_game_button(app)
        self.assertFalse(play.disabled)
        self.assertTrue(play.accent)

    def test_status_and_live_refresh_notice_missing_or_restored_files(self):
        app = SimpleNamespace(
            game_install_path=str(self.root), game_update_busy=False,
            mod_download_busy=False, latest_game_release=None,
            sidebar_buttons=[Control(), Control()],
            build_state_label=mock.Mock(), build_indicator=mock.Mock(),
            download_percent=0.0, set_download_status=mock.Mock(),
            status_label=mock.Mock(), _paint_hero=mock.Mock())
        app._update_primary_game_button = lambda: live.ForgeLiveMixin._update_primary_game_button(app)
        (self.root/"THIRD_PARTY_NOTICES.txt").unlink()
        live.ForgeLiveMixin._refresh_real_install_ui(app)
        self.assertTrue(app.sidebar_buttons[0].disabled)
        self.assertIn("THIRD_PARTY_NOTICES.txt", app._play_issue)
        self.assertEqual(app.set_download_status.call_args.kwargs["state"],"GAME FILES MISSING")
        self.assertIn("THIRD_PARTY_NOTICES.txt", app.status_label.configure.call_args.kwargs["text"])
        app._refresh_real_install_ui = lambda: live.ForgeLiveMixin._refresh_real_install_ui(app)
        app._poll_game_play_ready = lambda: live.ForgeLiveMixin._poll_game_play_ready(app)
        app.after = mock.Mock()
        (self.root/"THIRD_PARTY_NOTICES.txt").write_bytes(b"restored")
        live.ForgeLiveMixin._poll_game_play_ready(app)
        self.assertEqual(app._play_issue,"")
        self.assertFalse(app.sidebar_buttons[0].disabled)
        app.after.assert_called_once()


if __name__=="__main__":
    unittest.main()
