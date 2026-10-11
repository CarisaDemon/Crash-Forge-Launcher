"""Regression tests: bundled editors are GUI EXEs on the launcher monitor."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from forge_editor_geometry import (
    ENV_NAME, initial_geometry, parse_workarea, select_window_geometry,
    workarea_to_env,
)
from forge_editor_registry import editor_executable, EDITORS

ROOT = Path(__file__).resolve().parents[1]

class EditorMonitorAndConsoleTests(unittest.TestCase):
    def test_workarea_handles_secondary_monitor_right(self):
        bounds=(1920, 0, 1920, 1032)
        self.assertEqual(workarea_to_env(bounds),"1920,0,3840,1032")
        with patch.dict(os.environ,{ENV_NAME:"1920,0,3840,1032"}):
            self.assertEqual(initial_geometry(1200,800), "1200x800+2280+116")
            self.assertEqual(initial_geometry(1060,800), "1060x800+2350+116")

    def test_workarea_handles_secondary_monitor_left_negative_x(self):
        env={ENV_NAME:"-2560,-200,0,1240"}
        self.assertEqual(initial_geometry(1200,800,environment=env),
                         "1200x800-1880+120")
        self.assertEqual(initial_geometry(1060,800,environment=env),
                         "1060x800-1810+120")
        self.assertEqual(select_window_geometry(
            900, 520, (-2000, 0, 1200, 720), (-2560,-200,0,1240)),
            "900x520-1850+100")

    def test_safe_clamp_to_workarea_when_editor_exceeds_monitor(self):
        self.assertEqual(initial_geometry(1200,800,
                         workarea="640,0,1440,700"),"800x700+640+0")
        self.assertEqual(select_window_geometry(900,520,
                         (700,50,540,400),(640,0,1440,700)),
                         "800x520+640+0")

    def test_invalid_env_is_ignored_not_desktop_reset(self):
        for item in ("0,0,0,900", "junk","0,0,9999999,400",
                     "0,0,1800", "0,0,20000,20000", "-20,0,-30,500",
                     "\n0,0,1920,1080"):
            with self.subTest(item=item):
                self.assertIsNone(parse_workarea(item))
                self.assertIsNone(initial_geometry(1200,800,
                                  environment={ENV_NAME:item}))
        self.assertIsNone(initial_geometry(1200,800,environment={}))

    def test_editor_paths_use_packaged_exes_not_bat(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            bundled=root/"_internal"/"editor_tools"
            bundled.mkdir(parents=True)
            for name in EDITORS.values():
                (bundled/name).write_bytes(b"MZ")
            (root/"CTR Music Toolkit.bat").write_text("legacy",encoding="utf-8")
            for tool,name in EDITORS.items():
                with self.subTest(tool=tool):
                    resolved=editor_executable(tool,root)
                    self.assertEqual(Path(resolved).resolve(),(bundled/name).resolve())
                    self.assertTrue(resolved.lower().endswith(".exe"))

    def test_all_three_tools_and_updater_build_with_gui_subsystem(self):
        script=(ROOT/"release_tools"/"build_windows.ps1").read_text(encoding="utf-8")
        for name in (*EDITORS.values(),"ForgeLauncherUpdater.exe"):
            self.assertIn(f'--name "{name[:-4]}"',script)
        self.assertGreaterEqual(script.count("--windowed"),5)
        source=(ROOT/"launcher.py").read_text(encoding="utf-8")
        self.assertIn("editor_registry.editor_executable(",source)
        self.assertIn("startupinfo=startup",source)
        self.assertIn("subprocess.CREATE_NO_WINDOW",source)
        self.assertIn("CFR_EDITOR_WORKAREA", (ROOT/"forge_editor_geometry.py").read_text())
        ogg=(ROOT/"companion_tools"/"ogg_toolkit"/"ogg_launcher.py").read_text()
        self.assertIn('subprocess.CREATE_NO_WINDOW',ogg)
        self.assertIn('"-WindowStyle", "Hidden"',ogg)
        self.assertIn("STARTF_USESHOWWINDOW",ogg)
        self.assertIn("creationflags=hidden", (ROOT/"forge_live_ui.py").read_text(encoding="utf-8"))

    def test_no_batch_launchers_shipped_in_source(self):
        self.assertEqual(list(ROOT.rglob("*.bat")), [])
        self.assertEqual(list(ROOT.rglob("*.cmd")), [])

    def test_editor_ps1_receives_exact_monitor(self):
        script=(ROOT/"companion_tools"/"ogg_toolkit"/"CTR_Music_Toolkit_GUI.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$env:CFR_EDITOR_WORKAREA",script)
        self.assertIn("[System.Windows.Forms.FormStartPosition]::Manual",script)
        self.assertIn("$form.Location",script)
        self.assertTrue((ROOT/"release_tools"/"build_windows.ps1").is_file())


if __name__=="__main__":
    unittest.main()