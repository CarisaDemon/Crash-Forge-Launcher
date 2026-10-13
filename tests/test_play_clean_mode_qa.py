"""Non-interactive QA tests for the three launch modes and remember-choice behavior."""
import subprocess
import unittest
from unittest import mock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_live_ui as live


class FakeLauncher(live.ForgeLiveMixin):
    def __init__(self):
        self.game_install_path = "C:\\QA Game"
        self.game_update_busy = False
        self.latest_game_release = None
        self.remember_play_choice = False
        self.preferred_play_mode = "normal"
        self.status_label = mock.Mock()
        self.scheduled = []

    def set_download_status(self, **kwargs):
        raise AssertionError("Should not show install failure on a valid game")

    def after(self, milliseconds, callback):
        self.scheduled.append((milliseconds, callback))

    def _show_play_mode_selector(self, event=None):
        self.scheduled.append(("chooser", event))


class LaunchModesTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeLauncher()
        self.patchers = [
            mock.patch.object(live.game_launch, "launch_issue", return_value=""),
            mock.patch.object(live.services, "real_game_status", return_value={
                "installed": True, "exe_path": "C:\\QA Game\\ctr-native.exe"}),
            mock.patch.object(live, "available_game_update", return_value=None),
            mock.patch.object(live.iso_integrity, "start_background_check"),
            mock.patch.object(live.subprocess, "Popen"),
            mock.patch.object(live.game_launch, "supports_native_no_mods", return_value=True),
            mock.patch.object(live.messagebox, "showinfo"),
        ]
        self.mocks = [p.start() for p in self.patchers]
        for p in self.patchers:
            self.addCleanup(p.stop)
        self.Popen = self.mocks[4]
        self.supports = self.mocks[5]
        self.info = self.mocks[6]

    def test_clean_mode_checks_binary_without_starting_probe(self):
        with mock.patch.object(live.subprocess,"run",
                               side_effect=AssertionError("NEVER probe by starting the game")):
            self.app._play_installed_game("clean")
        self.supports.assert_called_once_with("C:\\QA Game\\ctr-native.exe")
        self.Popen.assert_called_once()
        self.assertEqual(self.Popen.call_args.args[0],
                         ["C:\\QA Game\\ctr-native.exe", "--no-mods"])
        self.info.assert_not_called()

    def test_unsupported_game_does_not_launch_even_for_probe(self):
        self.supports.return_value=False
        with mock.patch.object(live.subprocess,"run",
                               side_effect=AssertionError("Old EXE must never execute")):
            self.app._play_installed_game("clean")
        self.Popen.assert_not_called()
        self.info.assert_not_called()
        self.app.status_label.configure.assert_any_call(
            text="PLAY WITHOUT MODS needs a compatible native game release.")

    def test_old_game_never_gets_five_second_timeout(self):
        self.supports.return_value=False
        with mock.patch.object(live.subprocess,"run",
                               side_effect=AssertionError("Forbidden timeout probe")):
            self.app._play_installed_game("clean")
        self.Popen.assert_not_called()

    def test_normal_mode_passes_no_new_game_flag(self):
        self.app._play_installed_game("normal")
        self.supports.assert_not_called()
        self.assertEqual(self.Popen.call_args.args[0],
                         ["C:\\QA Game\\ctr-native.exe"])

    def test_debug_mode_keeps_console_attached(self):
        self.app._play_installed_game("debug")
        self.supports.assert_not_called()
        self.assertIsNone(self.Popen.call_args.kwargs["stdout"])
        self.assertIsNone(self.Popen.call_args.kwargs["stderr"])

    def test_no_remember_opens_choice(self):
        self.app._primary_game_action()
        self.assertEqual(self.app.scheduled, [("chooser", None)])

    def test_remember_launches_only_saved_choice(self):
        self.app.remember_play_choice = True
        self.app.preferred_play_mode = "clean"
        with mock.patch.object(self.app, "_play_installed_game") as launch:
            self.app._primary_game_action()
        launch.assert_called_once_with("clean")
        self.assertEqual(self.app.scheduled, [])


if __name__ == "__main__":
    unittest.main()
