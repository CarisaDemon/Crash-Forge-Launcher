"""Regression: the Forge account window must never take a modal Tk grab."""
import os
import tkinter as tk
import unittest
from unittest.mock import Mock
from forge_account_ui import AccountDialog

class TestAccountWindow(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt" and not os.environ.get("CI"), "Windows native window manager regression")
    def test_account_window_is_nonmodal_and_closeable(self):
        root = tk.Tk()
        try:
            root.title("account test - offscreen")
            root.geometry("880x630+3500+2400")
            root.update_idletasks()
            client = Mock()
            client.signed_in = False
            dialog = AccountDialog(root, client)
            try:
                self.assertFalse(bool(dialog.window.overrideredirect()))
                self.assertIsNone(root.grab_current())
                self.assertTrue(dialog.window.winfo_exists())
                root.update_idletasks()
                self.assertTrue(root.winfo_exists())
                self.assertEqual(dialog.mode, "signin")
                dialog._switch("register")
                self.assertEqual(dialog.mode, "register")
                dialog._switch("signin")
                self.assertEqual(dialog.mode, "signin")
            finally:
                dialog.close()
            self.assertTrue(root.winfo_exists())
            self.assertIsNone(root.grab_current())
        finally:
            root.destroy()

if __name__ == "__main__":
    unittest.main()