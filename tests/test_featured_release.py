"""Offline verification of the featured Home image and release copy."""
from pathlib import Path
import unittest

from PIL import Image

import forge_services

ROOT = Path(__file__).resolve().parents[1]


class FeaturedReleaseTests(unittest.TestCase):
    def test_big_update_original_launcher_background_is_shipped(self):
        path = ROOT / "assets" / "news" / "latest_update.webp"
        self.assertTrue(path.is_file())
        with Image.open(path) as photo:
            self.assertEqual(photo.size, (1672, 941))
            self.assertEqual(photo.format, "WEBP")
            photo.verify()

    def test_home_and_news_use_same_image(self):
        launcher = (ROOT / "launcher.py").read_text(encoding="utf-8")
        news = (ROOT / "forge_live_ui.py").read_text(encoding="utf-8")
        self.assertIn('ImageOps.contain(', launcher)
        self.assertIn('text="LATEST UPDATE  /  "', launcher)
        self.assertIn('text="MORE DETAILS IN NEWS', launcher)
        self.assertIn('real_launcher_changelog(', launcher)
        self.assertIn('news_history.artwork_file(', launcher)
        self.assertIn('news_history.artwork_file(', news)
        self.assertIn('news_history.local_publications(', news)

    def test_release_highlights_have_english_summary_and_version(self):
        version, highlights = forge_services.real_launcher_changelog(str(ROOT), limit=3)
        self.assertTrue(version.startswith("v0.3.45"))
        self.assertEqual(len(highlights), 3)
        self.assertTrue(all(15 <= len(row) < 100 for row in highlights))

    def test_portable_windows_build_includes_artwork(self):
        script = (ROOT/"release_tools"/"build_windows.ps1").read_text(
            encoding="utf-8")
        self.assertIn('assets\\news\\latest_update.webp', script)
        self.assertIn('assets\\news\\publications.json', script)


if __name__ == "__main__":
    unittest.main()