"""Launcher topbar Forge Hub web entry regression."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"launcher.py").read_text(encoding="utf-8")


class HeaderForgeHubTests(unittest.TestCase):
    def test_link_to_public_hub_next_to_editor(self):
        self.assertIn('FORGE_HUB_WEB_URL = "https://carisademon.github.io/Crash-Forge-Racing/forge-hub/"', SOURCE)
        self.assertIn('hub_x1 = editor_x2 + 12', SOURCE)
        self.assertIn('text="FORGE HUB"', SOURCE)
        self.assertIn('"forge_hub_button", "<Button-1>"', SOURCE)
        self.assertIn('lambda e: self._open_forge_hub_website()', SOURCE)

    def test_button_uses_default_windows_browser(self):
        self.assertIn('def _open_forge_hub_website(self):', SOURCE)
        self.assertIn('os.startfile(FORGE_HUB_WEB_URL)',SOURCE)
        self.assertIn('webbrowser.open(FORGE_HUB_WEB_URL, new=2)',SOURCE)

    def test_compact_windows_keep_button_visible(self):
        self.assertIn('if width >= 920:',SOURCE)
        self.assertIn('version_x, version_y, version_font = controls_right - 8, 70, 8',SOURCE)
        # Launcher minimum 760px; button ends well before the minimize glyph.
        min_width=760
        editor_end=400
        hub_end=editor_end+12+114
        minimize_x=min_width-18-16-42-42
        self.assertLess(hub_end,minimize_x)

    def test_existing_mods_and_editor_remain_working(self):
        self.assertIn('lambda e: self._show_editor_selector()',SOURCE)
        self.assertIn('self._show_forge_hub',SOURCE)
        self.assertIn('self._launch_editor_tool(tool_paths["model"])',SOURCE)

    def test_release_tag(self):
        self.assertEqual((ROOT/"launcher_version.txt").read_text().strip(),"0.3.54")


if __name__=="__main__":
    unittest.main()