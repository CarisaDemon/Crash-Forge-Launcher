"""Cross-editor portable installation discovery, local mods, icons, and no console."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from forge_editor_config import find_game_installation, valid_game_root
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]


class EditorSharedInstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="CFR editor paths ")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.game = base / "My Native Game"
        self.game.mkdir()
        (self.game/"ctr-native.exe").write_bytes(b"MZTESTONLY")
        self.launcher = base/"Install"/"CrashForgeLauncher"
        self.launcher.mkdir(parents=True)
        self.tools = self.launcher/"_internal"/"editor_tools"
        self.tools.mkdir(parents=True)
        (self.tools/"CrashForgeOGGToolkit.exe").write_bytes(b"MZTESTONLY")
        self.settings = self.launcher/"launcher_settings.json"
        self.settings.write_text(json.dumps({"game_install_path":str(self.game)}),encoding="utf-8")

    def test_all_editor_exes_automatically_use_saved_launcher_folder(self):
        for name in ("CrashForgeOGGToolkit.exe","CrashForgeCSEQToolkit.exe",
                     "CrashForgeModelImporter.exe"):
            with self.subTest(exe=name):
                found=find_game_installation(
                    executable=self.tools/name, environment={})
                self.assertEqual(found,self.game.resolve())

    def test_valid_env_overrides_settings_but_bad_env_does_not(self):
        other=self.game.parent/"Other"
        other.mkdir()
        (other/"ctr_native.exe").write_bytes(b"MZTEST")
        self.assertEqual(find_game_installation(
            executable=self.tools/"CrashForgeOGGToolkit.exe",
            environment={"CFR_GAME_PATH":str(other)}),other.resolve())
        self.assertEqual(find_game_installation(
            executable=self.tools/"CrashForgeOGGToolkit.exe",
            environment={"CFR_GAME_PATH":"C:/invalid-path"}),self.game.resolve())

    def test_explicit_launcher_settings_are_supported(self):
        settings=self.game.parent/"outside-launcher.json"
        settings.write_text(json.dumps({"game_install_path":str(self.game)}),encoding="utf-8")
        self.assertEqual(find_game_installation(
            executable=self.game.parent/"random"/"editor.exe",
            environment={"CFR_LAUNCHER_SETTINGS":str(settings)}),
            self.game.resolve())

    def test_invalid_settings_do_not_create_fake_game_folder(self):
        self.settings.write_text('{"game_install_path":"Z:/not-a-game"}')
        self.assertIsNone(find_game_installation(
            executable=self.tools/"CrashForgeCSEQToolkit.exe",environment={}))
        self.assertIsNone(valid_game_root(""))

    def test_cseq_native_module_discovered_under_legacy_mod_tree(self):
        import sys
        module=str(ROOT/"companion_tools"/"cseq_toolkit")
        if module not in sys.path: sys.path.insert(0,module)
        from track_discovery import discover_custom_tracks
        track=self.game/"assets"/"mods"/"tracks"/"my_custom_track"
        track.mkdir(parents=True)
        (track/"data.lev").write_bytes(b"LEV")
        (track/"data.vrm").write_bytes(b"VRM")
        (track/"track.ini").write_text(
            "[track]\nname = Custom Track\nformat = native_lev_vrm\n"
            "enabled = true\nlev = data.lev\nvrm = data.vrm\n",encoding="utf-8")
        tracks=discover_custom_tracks(self.game)
        self.assertEqual(len(tracks),1)
        self.assertEqual(tracks[0].slug,"my_custom_track")

    def test_window_logo_resources_and_build_flags(self):
        for item in ("cfr_icon.png","cfr_icon.ico"):
            p=ROOT/"assets"/"icons"/item
            self.assertTrue(p.is_file())
            with Image.open(p) as picture:
                self.assertGreater(picture.width, 32)
        build=(ROOT/"release_tools"/"build_windows.ps1").read_text(encoding="utf-8")
        for exe in ("CrashForgeOGGToolkit","CrashForgeCSEQToolkit",
                    "CrashForgeModelImporter"):
            self.assertIn('--paths $Source --name "'+exe+'"',build)
        self.assertIn('$modelImporterLogo',build)
        ogg=(ROOT/"companion_tools"/"ogg_toolkit"/"ogg_launcher.py").read_text(encoding="utf-8")
        self.assertIn('subprocess.CREATE_NO_WINDOW',ogg)
        self.assertIn('subprocess.STARTF_USESHOWWINDOW',ogg)
        self.assertIn('find_game_installation',ogg)
        powershell=(ROOT/"companion_tools"/"ogg_toolkit"/"CTR_Music_Toolkit_GUI.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('99 = "HANGOUT_HUB"',powershell)
        self.assertIn('$script:ReferenceIds = @(0..64) + @(99)',powershell)
        self.assertIn('CrashForge.Racing.OGGToolkit',powershell)
        self.assertIn('$logo.BringToFront()',powershell)

    def test_ogg_script_is_utf8_with_bom_for_windows_powershell_5(self):
        script=ROOT/"companion_tools"/"ogg_toolkit"/"CTR_Music_Toolkit_GUI.ps1"
        self.assertEqual(script.read_bytes()[:3],b"\xef\xbb\xbf")


if __name__=="__main__":
    unittest.main()