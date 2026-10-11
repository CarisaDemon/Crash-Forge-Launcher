"""Regression for Forge Hub orange dropdown and Guest menu."""
import os
import time
import tkinter as tk
from types import SimpleNamespace
import unittest

import forge_account_badge as badge


class BadgeDropdownTests(unittest.TestCase):
    def test_guest_entries_never_expose_account_or_logout(self):
        self.assertEqual(badge.account_menu_items(False),
                         ("LOG IN", "OPEN FORGE HUB"))
        self.assertEqual(badge.account_menu_items(True),
                         ("MY ACCOUNT", "OPEN FORGE HUB", "SIGN OUT"))

    @unittest.skipUnless(os.name == "nt" and not os.environ.get("CI"), "Actual Tk popup requires Windows")
    def test_orange_menu_and_no_duplicate_account_button(self):
        os.environ["CFR_SCREENSHOT_PREVIEW"] = "1"
        from launcher import Launcher
        from forge_account_client import AccountClient
        app = Launcher()
        app.account_client = AccountClient(persist=False)
        try:
            app.geometry("1280x820+3400+1600")
            app.update_idletasks()
            app._paint_floating_header()
            self.assertEqual(
                app._header_canvas.find_withtag("account_button"), (),
                "Old ACCOUNT button still visible")
            self.assertEqual(
                app._header_canvas.find_withtag("account_frame"), (),
                "Old ACCOUNT frame still visible")
            event = SimpleNamespace(x_root=3500, y_root=1650)
            app._account_badge_menu(event)
            popup = app._account_popup
            app.update()
            self.assertTrue(popup.winfo_exists(), "Guest menu disappeared immediately")
            app.after(370, app.quit)
            app.mainloop()
            self.assertTrue(popup.winfo_exists(),
                            "Guest menu dismissed itself without a user click")
            from launcher import COLORS
            self.assertEqual(popup.cget("bg").lower(), COLORS["orange"].lower())
            self.assertTrue(popup.overrideredirect(), "Native white-bordered menu still in use")
            self.assertIsNone(app.grab_current(), "Popup trapped keyboard/mouse")
            labels = self._labels(popup)
            self.assertIn("LOG IN", labels)
            self.assertIn("OPEN FORGE HUB", labels)
            self.assertNotIn("MY ACCOUNT", labels)
            self.assertNotIn("SIGN OUT", labels)
            # Dismiss by clicking outside the avatar chip.
            app._account_badge_parent_click(SimpleNamespace(
                widget=app._header_canvas, x=70, y=71))
            self.assertIsNone(app._account_popup)
            self.assertTrue(app.winfo_exists())

            app.account_client = SimpleNamespace(signed_in=True, profile=lambda: {
                "id": "fake", "username": "test", "avatar_url": ""
            })
            app._account_badge_menu(event)
            popup = app._account_popup
            app.update()
            labels = self._labels(popup)
            self.assertNotIn("LOG IN", labels)
            self.assertIn("MY ACCOUNT", labels)
            self.assertIn("OPEN FORGE HUB", labels)
            self.assertIn("SIGN OUT", labels)
            self.assertIsNone(app.grab_current())
            # Verify the signed-in action invokes the correct handler and
            # closes the orange menu without a modal grab.
            from unittest.mock import Mock
            app._account_badge_sign_out = Mock()
            app._close_account_badge_menu()
            app._account_badge_menu(event)
            popup = app._account_popup
            app.update_idletasks()
            app.update()
            self.assertTrue(popup.winfo_exists())
            def buttons(w):
                found = []
                for c in w.winfo_children():
                    if isinstance(c, tk.Label):
                        found.append(c)
                    found.extend(buttons(c))
                return found
            signout = next(c for c in buttons(popup)
                           if c.cget("text") == "SIGN OUT")
            signout.event_generate("<Button-1>")
            app.update()
            app._account_badge_sign_out.assert_called_once_with()
            self.assertIsNone(app._account_popup)
        finally:
            app._close_account_badge_menu()
            app.destroy()

    @staticmethod
    def _labels(widget):
        texts = []
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                texts.append(str(child.cget("text")))
            texts.extend(BadgeDropdownTests._labels(child))
        return texts


if __name__ == "__main__":
    unittest.main()