"""NEWS must retain older releases and keep v0.3.37 / v0.3.38 separate.

No browser, network, game or GUI is started by these tests.
"""
from contextlib import contextmanager
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image

import forge_news_history as history

ROOT = Path(__file__).resolve().parents[1]


class NewsHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        patch = mock.patch.dict(os.environ, {
            "LOCALAPPDATA": self.temporary.name,
        })
        patch.start()
        self.addCleanup(patch.stop)

    def test_existing_ten_publications_are_preserved_offline(self):
        articles = history.local_publications(ROOT)
        versions = [item["version"] for item in articles]
        self.assertEqual(len(articles), 23)
        self.assertEqual(versions[:3], ["0.3.52", "0.3.51", "0.3.50"])
        self.assertIn("0.3.28", versions)
        self.assertEqual(len(versions), len(set(versions)))
        self.assertTrue(all(item["url"].startswith(history.GITHUB_RELEASES)
                            for item in articles))

    def test_new_release_appends_and_existing_release_edits_in_place(self):
        existing = history.local_publications(ROOT)
        patch = [
            {"version": "0.3.38", "title": "New headline",
             "notes": ["Updated Model Importer announcement"]},
            {"version": "0.3.40", "title": "Future update",
             "notes": ["Future changes"]},
        ]
        merged = history.save_history(patch, ROOT)
        self.assertEqual(len(merged), 24)
        self.assertEqual(merged[0]["version"], "0.3.52")
        self.assertEqual([x["version"] for x in merged].count("0.3.38"), 1)
        self.assertEqual(next(x["notes"] for x in merged if x["version"] == "0.3.38"),
                         ["Updated Model Importer announcement"])
        self.assertIn("0.3.28", [i["version"] for i in merged])
        again = history.save_history(patch, ROOT)
        self.assertEqual(merged, again)
        self.assertEqual(len(history.local_publications(ROOT)), 24)

    def test_release_urls_cannot_be_redirected_by_cache_content(self):
        fake = [{"version": "0.3.37",
                 "url": "http://malicious.invalid/redirect",
                 "title": "<p>Fake</p>", "notes": []},
                {"version": "../../etc/passwd", "url": "https://example.com"}]
        result = history.merge_history(fake)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], history.release_url("0.3.37"))
        self.assertNotIn("<p>", result[0]["title"])

    def test_published_release_metadata_parses_without_downloading(self):
        raw = [
            {"tag_name": "v0.3.38", "name": "v0.3.38", "published_at":
             "2026-10-10T13:00:00Z", "body": "- **Redesigned** importer\n- New wheels",
             "draft": False, "prerelease": False, "assets": []},
            {"tag_name": "v0.3.37", "draft": False, "prerelease": False,
             "body": "- Forge Hub live", "assets": []},
            {"tag_name": "v0.3.40", "draft": True, "body": "- Draft"},
            {"tag_name": "not-a-version", "body": "garbage"},
        ]
        entries, assets = history.parse_github_history(raw)
        self.assertEqual([x["version"] for x in entries], ["0.3.38", "0.3.37"])
        self.assertEqual(assets, [])
        self.assertIn("Redesigned importer", entries[0]["notes"])

    def test_two_existing_release_image_slots_never_cross(self):
        pictures = Path(self.temporary.name) / "site" / "assets" / "news"
        pictures.mkdir(parents=True)
        forge_hub = pictures / "forge-news-v0.3.37.webp"
        importer = pictures / "forge-news-v0.3.38.webp"
        forge_hub.write_bytes(b"forge-hub")
        importer.write_bytes(b"model-importer")
        self.assertEqual(history.artwork_file(pictures.parents[1], "0.3.37"),
                         str(forge_hub))
        self.assertEqual(history.artwork_file(pictures.parents[1], "0.3.38"),
                         str(importer))
        self.assertNotEqual(history.artwork_file(pictures.parents[1], "0.3.37"),
                            history.artwork_file(pictures.parents[1], "0.3.38"))
        self.assertIsNone(history.artwork_file(pictures.parents[1], "0.3.36"))

    def test_image_metadata_requires_exact_tag_and_hash(self):
        url = history.GITHUB_RELEASES + (
            "/download/v0.3.37/forge-news-v0.3.37.webp")
        item = {"name": "forge-news-v0.3.37.webp",
                "browser_download_url": url, "size": 1234,
                "digest": "sha256:" + "e"*64}
        valid = history.trusted_image_asset([item], "0.3.37")
        self.assertIsNotNone(valid)
        self.assertIsNone(history.trusted_image_asset([item], "0.3.38"))
        self.assertIsNone(history.trusted_image_asset(
            [dict(item, browser_download_url="https://unsafe.invalid/pic")],
            "0.3.37"))

    def test_guest_screenshot_image_is_trusted_with_verified_hash(self):
        img = ROOT / "assets" / "news" / "forge-news-v0.3.43.webp"
        from PIL import Image
        with Image.open(img) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (229, 91))
        digest = hashlib.sha256(img.read_bytes()).hexdigest()
        item = {"name": img.name, "size": img.stat().st_size,
                "browser_download_url": history.release_url("0.3.43").replace(
                    "/tag/", "/download/") + "/" + img.name,
                "digest": "sha256:" + digest}
        valid = history.trusted_image_asset([item], "0.3.43")
        self.assertIsNotNone(valid)
        self.assertIsNone(history.trusted_image_asset([item], "0.3.42"))

    def test_downloaded_artwork_has_correct_signature_and_hash(self):
        buffer = BytesIO()
        Image.new("RGB", (360, 160), "orange").save(buffer, "WEBP")
        payload = buffer.getvalue()
        info = {"version": "0.3.37",
                "name": "forge-news-v0.3.37.webp",
                "url": history.GITHUB_RELEASES +
                       "/download/v0.3.37/forge-news-v0.3.37.webp",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload)}
        class TestResponse(BytesIO):
            def geturl(self):
                return ("https://release-assets.githubusercontent.com/"
                        "archive/secure-content")
        with mock.patch.object(history.urllib.request, "urlopen",
                               side_effect=lambda *args, **kwargs: TestResponse(payload)):
            downloaded = history.sync_release_artwork([info])
        self.assertEqual(downloaded, ["0.3.37"])
        self.assertEqual(Path(history.artwork_file(ROOT, "0.3.37")).read_bytes(),
                         payload)

    def test_home_and_news_use_same_archive(self):
        ui = (ROOT / "forge_live_ui.py").read_text(encoding="utf-8")
        hero = (ROOT / "launcher.py").read_text(encoding="utf-8")
        build = (ROOT / "release_tools" / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("news_history.merge_history(", ui)
        self.assertIn("news_history.artwork_file(", ui)
        self.assertIn("news_history.artwork_file(", hero)
        self.assertIn("self.launcher_news_history = launcher_history", ui)
        self.assertIn("self._scheduled_news_history_check", ui)
        self.assertIn("--add-data $historyAsset", build)
        self.assertIn("@newsArtArguments", build)
        self.assertIn("is_featured = (index < 2 or", ui)
        workflow = (ROOT / ".github" / "workflows" / "windows-release.yml").read_text(
            encoding="utf-8")
        self.assertIn('gh release upload $tag $file --clobber', workflow)
        self.assertIn('$version = (Get-Content launcher_version.txt -Raw).Trim()', workflow)
        self.assertNotIn('foreach ($version in @("0.3.37",', workflow)
        self.assertNotIn('image_path = os.path.join(BASE_DIR, "assets", "news",',
                         hero)

    def test_image_update_does_not_create_a_new_version(self):
        old = history.local_publications(ROOT)
        self.assertEqual(old[0]["version"], "0.3.52")
        self.assertTrue(history.release_url("v0.3.38").endswith("/tag/v0.3.38"))
        self.assertTrue(history.release_url("v0.3.37").endswith("/tag/v0.3.37"))
        self.assertEqual((ROOT/"launcher_version.txt").read_text().strip(), "0.3.52")


if __name__ == "__main__":
    unittest.main()