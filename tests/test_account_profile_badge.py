"""Live Forge account profile chip: Guest silhouette, connectivity, GitHub avatar."""
from io import BytesIO
import os
import unittest
from unittest.mock import patch, Mock

from PIL import Image
import forge_account_badge as badge


class AccountChipTests(unittest.TestCase):
    def test_guest_has_person_icon_state_and_gray_dot(self):
        result = badge.account_label({}, signed_in=False, connected=True)
        self.assertEqual(result["name"], "Guest")
        self.assertFalse(result["online"])
        self.assertEqual(result["status"], "Not signed in")
        self.assertIsNone(result["avatar_url"])

    def test_green_only_with_verified_account_and_network(self):
        person = {"username": "racer_test", "avatar_url":
                  "https://avatars.githubusercontent.com/u/12345?v=4"}
        online = badge.account_label(person, signed_in=True, connected=True)
        offline = badge.account_label(person, signed_in=True, connected=False)
        self.assertTrue(online["online"])
        self.assertFalse(offline["online"])
        self.assertEqual(offline["name"], "racer_test")
        self.assertEqual(online["status"], "Online")
        self.assertEqual(offline["status"], "Offline")

    def test_avatar_only_from_github_avatar_cdn(self):
        for url in (
            "http://avatars.githubusercontent.com/u/1",
            "https://avatars.githubusercontent.com.evil.test/u/1",
            "https://evil.test/image.png",
            "file:///C:/private.png",
            "https://user:pass@avatars.githubusercontent.com/u/1",
            "https://avatars.githubusercontent.com:8443/u/1",
            "https://avatars.githubusercontent.com:bad/u/1",
            "https://avatars.githubusercontent.com/avatar.png",
        ):
            self.assertIsNone(badge.github_avatar_url(url), url)
        actual = "https://avatars.githubusercontent.com/u/12345?v=4"
        self.assertEqual(badge.github_avatar_url(actual), actual)

    def test_avatar_circle_corners_are_transparent(self):
        img = Image.new("RGB", (90, 90), "red")
        raw = BytesIO()
        img.save(raw, "PNG")
        round_img = badge.avatar_photo(raw.getvalue(), size=44)
        self.assertEqual(round_img.size, (44, 44))
        self.assertEqual(round_img.getpixel((0, 0))[3], 0)
        self.assertGreater(round_img.getpixel((22, 22))[3], 250)

    def test_responsive_layout_does_not_overlap_navigation_or_controls(self):
        for width in (760, 800, 900, 920, 1024, 1050, 1199, 1200, 1280, 1650, 1920):
            coords = badge.header_layout(width)
            self.assertLess(coords["left"], coords["right"])
            self.assertGreater(coords["left"], 410 if not coords["show_hub_button"] else 526,
                               f"Navigation overlap at width {width}")
            self.assertLess(coords["right"], width - 117,
                            f"Overlaps Windows minimize button at {width}")
            if coords["show_legacy_account"]:
                self.assertGreater(coords["left"], 650,
                                   f"Overlaps left ACCOUNT at width {width}")

    @unittest.skipUnless(os.name=="nt", "Windows Tk smoke")
    def test_real_launcher_guest_badge_has_drawn_person_and_dropdown(self):
        os.environ["CFR_SCREENSHOT_PREVIEW"] = "1"
        from launcher import Launcher
        from forge_account_client import AccountClient
        app = Launcher()
        # The developer may have a real saved login; force Guest without
        # touching their encrypted session on disk.
        app.account_client = AccountClient(persist=False)
        try:
            for width in (760, 920, 1280, 1650):
                app.geometry(f"{width}x820+3500+2000")
                app.update_idletasks()
                app._paint_floating_header()
                ids = app._header_canvas.find_withtag("forge_account_chip")
                # Two ovals are the Guest silhouette's head and shoulders.
                ovals = [item for item in ids if app._header_canvas.type(item)=="oval"]
                self.assertGreaterEqual(len(ovals), 4)
                self.assertGreaterEqual(len(ids), 8)
                text = [app._header_canvas.itemcget(item,"text") for item in ids
                        if app._header_canvas.type(item)=="text"]
                self.assertIn("Guest",text)
                self.assertIn("Not signed in",text)
            self.assertIsNone(app.grab_current())
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()