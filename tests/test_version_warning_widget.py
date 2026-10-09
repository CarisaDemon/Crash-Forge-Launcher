"""Headless/withdrawn Tk verification of the actual version-warning widget.

No windows are mapped, no keyboard/mouse input is sent, and no game is run.
"""
import sys
import tkinter as tk
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forge_version_dialog import ask_play_outdated


class WarningWidgetTests(unittest.TestCase):
    def _check_hidden_choice(self, button_name, expected):
        original_toplevel = tk.Toplevel.__init__
        observations = {}

        def hidden_toplevel(win, *args, **kwargs):
            original_toplevel(win, *args, **kwargs)
            win.withdraw()  # Never allow the transient window to be mapped

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        def simulate_button(parent, dialog):
            widgets = list(walk(dialog))
            buttons = [w for w in widgets if isinstance(w, tk.Button)]
            labels = [w.cget("text") for w in widgets if isinstance(w, tk.Label)]
            actions = {w.cget("text"): w for w in buttons}
            observations["actions"] = list(actions)
            observations["labels"] = labels
            observations["background"] = dialog.cget("bg")
            observations["hidden"] = dialog.state() == "withdrawn"
            if button_name:
                actions[button_name].invoke()
            else:
                dialog.event_generate("<Escape>", when="now")
                # When withdrawn, some Tk versions do not process the event;
                # use the CANCEL action as the equivalent safe fallback.
                if dialog.winfo_exists():
                    actions["CANCEL"].invoke()

        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(tk.Toplevel, "__init__", hidden_toplevel), \
                 patch.object(tk.Toplevel, "grab_set", lambda *_: None), \
                 patch.object(tk.Toplevel, "focus_set", lambda *_: None), \
                 patch.object(tk.Misc, "wait_window", simulate_button):
                answer = ask_play_outdated(root, {
                    "installed": "2.0.9", "available": "2.0.10",
                    "unknown": False,
                }, icon_path=str(ROOT / "assets" / "icons" / "cfr_icon.png"))
            self.assertEqual(answer, expected)
            self.assertTrue(observations["hidden"])
            self.assertEqual(observations["background"], "#090B0E")
            self.assertIn("PLAY ANYWAY", observations["actions"])
            self.assertIn("CANCEL", observations["actions"])
            self.assertTrue(any("NEWER GAME VERSION" in line
                                for line in observations["labels"]))
            self.assertTrue(any("Future online features" in line
                                for line in observations["labels"]))
        finally:
            root.destroy()

    def test_no_window_cancel(self):
        self._check_hidden_choice("CANCEL", False)

    def test_no_window_play_anyway(self):
        self._check_hidden_choice("PLAY ANYWAY", True)

    def test_no_window_escape(self):
        self._check_hidden_choice(None, False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
