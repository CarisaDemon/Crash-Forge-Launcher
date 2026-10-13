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
            mock.patch.object(live.subprocess, "run"),
            mock.patch.object(live.messagebox, "showinfo"),
        ]
        self.mocks = [p.start() for p in self.patchers]
        for p in self.patchers:
            self.addCleanup(p.stop)
        self.Popen = self.mocks[4]
        self.run = self.mocks[5]
        self.info = self.mocks[6]

    def test_without_mods_passes_flag_after_capability_probe(self):
        self.run.return_value = subprocess.CompletedProcess(
            ["--supports-no-mods"], 0, b"CFR_NO_MODS_V1\n", b"")
        self.app._play_installed_game("clean")
        self.run.assert_called_once()
        self.Popen.assert_called_once()
        self.assertEqual(self.Popen.call_args.args[0],
                         ["C:\\QA Game\\ctr-native.exe", "--no-mods"])
        self.assertEqual(self.Popen.call_args.kwargs["cwd"], self.app.game_install_path)
        self.info.assert_not_called()

    def test_unsupported_game_not_started_and_not_modified(self):
        self.run.return_value = subprocess.CompletedProcess(
            ["--supports-no-mods"], 0, b"unknown flag\n", b"")
        self.app._play_installed_game("clean")
        self.Popen.assert_not_called()
        self.info.assert_called_once()

    def test_probe_timeout_never_runs_unpatched_game(self):
        self.run.side_effect = subprocess.TimeoutExpired(["--supports-no-mods"], 5)
        self.app._play_installed_game("clean")
        self.Popen.assert_not_called()
        self.info.assert_called_once()

    def test_normal_mode_passes_no_new_game_flag(self):
        self.app._play_installed_game("normal")
        self.run.assert_not_called()
        self.assertEqual(self.Popen.call_args.args[0],
                         ["C:\\QA Game\\ctr-native.exe"])

    def test_debug_mode_keeps_console_attached(self):
        self.app._play_installed_game("debug")
        self.run.assert_not_called()
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
