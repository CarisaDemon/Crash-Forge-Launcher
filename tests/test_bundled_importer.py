"""Regression: bundled Model Importer stays included, not an optional download."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BundledImporterTests(unittest.TestCase):
    def test_launcher_opens_bundled_importer(self):
        source = (ROOT/"launcher.py").read_text(encoding="utf-8")
        self.assertIn('editor_registry.editor_executable(', source)
        self.assertIn('self._launch_editor_tool(tool_paths["model"])', source)
        self.assertNotIn('CTR Music Toolkit.bat', source)
        self.assertIn('"CHARACTERS / KARTS / WHEELS / TRACKS"', source)
        self.assertNotIn("_install_or_open_model_importer", source)

    def test_build_includes_tool_not_separate_release_asset(self):
        build = (ROOT/"release_tools"/"build_windows.ps1").read_text(
            encoding="utf-8")
        self.assertIn('$toolsTarget = Join-Path $exeDir "_internal\\editor_tools"', build)
        self.assertNotIn("optionalRelease", build)
        workflow = (ROOT/".github"/"workflows"/"windows-release.yml").read_text(
            encoding="utf-8")
        self.assertNotIn("build/release/CrashForgeModelImporter.exe\n", workflow)

    def test_verification_runs_tool_and_home_art(self):
        smoke = (ROOT/"release_tools"/"smoke_portable.py").read_text(
            encoding="utf-8")
        self.assertIn('model_importer = PORTABLE/"_internal"/"editor_tools"', smoke)
        self.assertIn('featured = PORTABLE/"_internal"/"assets"/"news"', smoke)


if __name__ == "__main__":
    unittest.main()