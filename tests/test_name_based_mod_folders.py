"""The stable Forge Hub ID is in INI; human mod name is the directory."""
from pathlib import Path
import hashlib
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import forge_mod_manager as manager
import forge_services as services


class NamedFolderTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="Forge readable mod names ")
        self.addCleanup(td.cleanup)
        self.home = Path(td.name)
        self.game = self.home / "Game"
        self.game.mkdir()
        (self.game / "ctr-native.exe").write_bytes(b"fake test exe")

    def install(self, *, stable_id="forge-aaa123", title="Team Bandicoot Kart (CNK)",
                version="1.0", kind="Kart"):
        archive = self.home / "mod.zip"
        ini = "kart.ini" if kind == "Kart" else "wheels.ini"
        native = "kart" if kind == "Kart" else "wheels"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("nested/" + ini,
                       "[" + native + "]\nname = " + title + "\nenabled=true\n")
            z.writestr("nested/mesh.obj", "v 0 0 0\n")
        mod = {"id":stable_id, "title":title, "type":kind, "source":"local",
               "version":version, "package_path":str(archive),
               "sha256":hashlib.sha256(archive.read_bytes()).hexdigest()}
        with patch.object(services, "real_game_status", return_value={"installed":True}):
            return Path(services.install_local_mod(mod,self.game))

    def test_name_folder_and_web_id_inside_ini(self):
        path = self.install()
        self.assertEqual(path.name, "team_bandicoot_kart_cnk")
        self.assertNotIn("forge-aaa123", str(path))
        self.assertIn("id = forge-aaa123", (path/"kart.ini").read_text())
        rows = manager.scan_installed(self.game)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["id"],"forge-aaa123")
        self.assertEqual(rows[0]["title"],"Team Bandicoot Kart (CNK)")
        self.assertTrue(rows[0]["manageable"])

    def test_update_follows_id_even_after_title_change(self):
        first = self.install()
        manager.set_enabled(self.game,"Kart","forge-aaa123",False)
        second = self.install(title="New Racing Kart",version="2.0")
        self.assertEqual(second,first)
        self.assertFalse(manager.read_mod(self.game,"Kart","forge-aaa123")["enabled"])
        self.assertEqual(manager.read_mod(self.game,"Kart","forge-aaa123")["title"],
                         "New Racing Kart")
        self.assertEqual(len(list((self.game/".forge_mod_backups").rglob("kart.ini"))),1)

    def test_duplicate_human_names_do_not_clobber_one_another(self):
        first = self.install(stable_id="forge-aaa123")
        second = self.install(stable_id="forge-bbb456")
        self.assertEqual(first.name,"team_bandicoot_kart_cnk")
        self.assertEqual(second.name,"team_bandicoot_kart_cnk_2")
        self.assertIn("id = forge-aaa123", (first/"kart.ini").read_text())
        self.assertIn("id = forge-bbb456", (second/"kart.ini").read_text())
        self.assertEqual(len(manager.scan_installed(self.game)),2)

    def test_reserved_and_unsafe_names(self):
        self.assertEqual(manager.folder_name_for_title("Music"),"mod_music")
        self.assertEqual(manager.folder_name_for_title("CON"),"mod_con")
        self.assertEqual(manager.folder_name_for_title("../../Racing!"),"racing")
        self.assertEqual(manager.folder_name_for_title("Kart: Remix ✨"),"kart_remix")

    def test_collision_with_other_category_uses_suffix(self):
        first = self.install(stable_id="forge-aaa123",kind="Kart")
        second = self.install(stable_id="forge-bbb456",kind="Wheels")
        self.assertNotEqual(first,second)
        self.assertEqual((first/"kart.ini").is_file(),True)
        self.assertEqual((second/"wheels.ini").is_file(),True)
        with self.assertRaises(services.FeedError):
            self.install(stable_id="forge-aaa123",kind="Wheels")

    def test_existing_id_named_folder_migrates_when_reinstalled(self):
        old = self.game/"mods"/"forge-aaa123"
        old.mkdir(parents=True)
        (old/"kart.ini").write_text(
            "[kart]\nname = Old Kart\nenabled = false\n"
            "[forge_mod]\nid = forge-aaa123\ntype = Kart\n"
            "version = 1.0\nsource = forge_hub\n", encoding="utf-8")
        new = self.install(stable_id="forge-aaa123")
        self.assertEqual(new.name, "team_bandicoot_kart_cnk")
        self.assertFalse(old.exists())
        self.assertFalse(manager.read_mod(
            self.game, "Kart", "forge-aaa123")["enabled"])
        previous = list((self.game/".forge_mod_backups").rglob("kart.ini"))
        self.assertEqual(len(previous), 1)
        self.assertIn("name = Old Kart", previous[0].read_text())

    def test_existing_web_id_folder_remains_detectable(self):
        old=self.game/"mods"/"forge-existing-id"
        old.mkdir(parents=True)
        (old/"kart.ini").write_text(
            "[kart]\nname = Old kart\nenabled=true\n"
            "[forge_mod]\nid = forge-existing-id\ntype = Kart\n"
            "version = 1.0\nsource = forge_hub\n",encoding="utf-8")
        row=manager.read_mod(self.game,"Kart","forge-existing-id")
        self.assertTrue(row["manageable"])
        self.assertEqual(row["path"],str(old))
        self.assertEqual(manager.mod_path(self.game,"Kart","forge-existing-id",
                                          title="Old Kart"),old)


if __name__ == "__main__":
    unittest.main()
