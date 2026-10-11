"""Branded dialogs and correct root-mod display; no GUI needed."""
from pathlib import Path
import unittest
from unittest.mock import patch

import forge_dialogs as dialogs

ROOT = Path(__file__).resolve().parents[1]


class ForgeDialogsTests(unittest.TestCase):
    def test_mod_install_shows_new_root_not_legacy_path(self):
        mod = {
            "id": "forge-2634caf465b548e182d728c4339d378c",
            "title": "Team Bandicoot Kart (CNK)",
            "author": "Carisa_Demon",
        }
        with patch.object(dialogs, "_show_confirmation", return_value=True) as ask:
            self.assertTrue(dialogs.ask_mod_install(object(), mod))
        params = ask.call_args.kwargs
        self.assertEqual(params["category"], "INSTALL MOD")
        self.assertEqual(params["rows"][1],
                         ("DESTINATION", "mods/team_bandicoot_kart_cnk"))
        self.assertEqual(params["rows"][2], ("SECURITY", "SHA-256 VERIFIED"))
        self.assertEqual(params["accept"], "INSTALL MOD")

    def test_visual_preview_can_never_install(self):
        text = (ROOT / "forge_dialogs.py").read_text(encoding="utf-8")
        self.assertIn('result["accepted"] = bool(accept_it) and not preview', text)
        with patch.object(dialogs, "_show_confirmation", return_value=False) as ask:
            self.assertFalse(dialogs.ask_mod_install(
                object(), {"id": "forge-a", "title": "Example"}, preview=True))
        self.assertTrue(ask.call_args.kwargs["preview"])
        self.assertIn("preview=True", (ROOT / "launcher.py").read_text(encoding="utf-8"))

    def test_actual_download_and_release_updates_use_branded_modal(self):
        source = (ROOT / "forge_live_ui.py").read_text(encoding="utf-8")
        self.assertIn("consent = ask_mod_install(", source)
        self.assertIn("confirmed = ask_game_update(", source)
        self.assertNotIn("assets/mods/<mod-id>", source)
        self.assertNotIn("messagebox.askyesno(", source)

    def test_catalog_titles_sanitized_before_gui(self):
        self.assertEqual(dialogs._text("bad\nname\t"), "bad name")
        with patch.object(dialogs, "_show_confirmation", return_value=False) as ask:
            dialogs.ask_mod_install(
                object(), {"id": "../../evil", "title": "Safe"})
        self.assertEqual(ask.call_args.kwargs["rows"][1][1], "mods/safe")


if __name__ == "__main__":
    unittest.main()
