"""Navigation regression: release highlights live in HERO and NEWS, not CHANGELOG."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class LauncherNewsInsteadOfChangelog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code=(ROOT/"launcher.py").read_text(encoding="utf-8")
        cls.news=(ROOT/"forge_live_ui.py").read_text(encoding="utf-8")

    def test_changelog_is_not_a_dashboard_tab(self):
        self.assertIn('("NEWS", "INSTALLATION", "SETTINGS")',self.code)
        self.assertIn('if tab not in ("NEWS", "INSTALLATION", "SETTINGS")',self.code)
        self.assertNotIn('"CHANGELOG": self.right_panel',self.code)
        self.assertNotIn('"CHANGELOG", "SETTINGS"',self.code)

    def test_no_changelog_card_remains(self):
        self.assertNotIn('def _changelog_card',self.code)
        self.assertNotIn('self.changelog_panel',self.code)
        self.assertNotIn('self.changelog_text',self.code)
        self.assertIn('self.settings_panel.pack(side="top", fill="both", expand=True)',self.code)

    def test_hero_keeps_release_summary_beside_art(self):
        self.assertIn('news_history.artwork_file(',self.code)
        self.assertIn('highlights = featured.get("notes", [])[:5]',self.code)
        self.assertIn('"LATEST GAME  /  "',self.code)
        self.assertIn('"LATEST LAUNCHER  /  "',self.code)
        self.assertIn('text="MORE DETAILS IN NEWS',self.code)
        self.assertIn('limit = 5 if h >= 470 else',self.code)

    def test_news_archive_unmodified(self):
        self.assertIn('self._render_real_news()',self.news)
        self.assertIn('news_history.merge_history(',self.news)
        self.assertIn('self.news_rows',self.news)

    def test_game_and_launcher_version_unchanged(self):
        self.assertEqual((ROOT/"launcher_version.txt").read_text().strip(),"0.3.47")

if __name__=="__main__":
    unittest.main()
