"""Game folder changes only on explicit Settings action, never on discovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import launcher
import forge_services as services
import forge_mod_manager as manager
import forge_releases as releases


class ManualGameFolderOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="CFR launcher settings ")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.settings=self.root/"launcher_settings.json"

    def load(self, payload=None):
        if payload is not None:
            self.settings.write_text(json.dumps(payload),encoding="utf-8")
        fake=types.SimpleNamespace()
        with mock.patch.object(launcher,"SETTINGS_FILE",str(self.settings)):
            data=launcher.Launcher._load_launcher_settings(fake)
        return fake,data

    def test_absent_game_folder_stays_empty_not_cwd_or_author_machine(self):
        app,data=self.load({})
        self.assertEqual(app.game_install_path,"")
        self.assertFalse(services.real_game_status("")["installed"])
        self.assertEqual(manager.scan_installed(""),[])
        self.assertTrue(self.settings.is_file())
        self.assertEqual(services.DEFAULT_GAME_PATH,"")

    def test_missing_old_folder_is_preserved_no_executable_autosearch(self):
        old=str(self.root/"missing_game_selected_by_user")
        app,data=self.load({"game_install_path":old,"launcher_auto_update":False})
        self.assertEqual(app.game_install_path,old)
        self.assertEqual(data["game_install_path"],old)
        self.assertEqual(json.loads(self.settings.read_text())["game_install_path"],old)

    def test_status_refresh_or_update_checker_does_not_change_selected_path(self):
        old=str(self.root/"uninstalled future game")
        app,_=self.load({"game_install_path":old,"release_check_frequency":"Daily"})
        with mock.patch.object(launcher,"SETTINGS_FILE",str(self.settings)):
            self.assertTrue(launcher.Launcher._save_launcher_settings(app))
        self.assertEqual(json.loads(self.settings.read_text())["game_install_path"],old)
        self.assertFalse(services.real_game_status(old)["installed"])
        self.assertEqual(json.loads(self.settings.read_text())["game_install_path"],old)

    def test_folder_selection_failed_to_save_rolls_back(self):
        source=(Path(__file__).parents[1]/"launcher.py").read_text(encoding="utf-8")
        self.assertIn("self.game_install_path = old_path",source)
        self.assertIn("Could not save folder selection",source)
        self.assertNotIn("_auto_recovered_game_path",source)
        self.assertNotIn("services.DEFAULT_GAME_PATH = r",source)

    def test_empty_game_path_refuses_release_install(self):
        with self.assertRaisesRegex(releases.ReleaseError,"Choose a game installation folder"):
            releases.install_game_release({
                "version":"2.1.0","asset":{"size":123},"verified_package":True,
            },"")
        self.assertIsNone(releases.game_installed_version(""))

if __name__=="__main__":
    unittest.main()