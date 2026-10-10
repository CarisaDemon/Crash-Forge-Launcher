"""Preview-only regressions: web-ID modules and launcher native INI manager.

All game files live in TemporaryDirectory: user's mods are never modified.
"""
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

import forge_mod_manager as manager
import forge_services as services


WEB_ID="7e105efe-42f0-4959-944e-35932b7df5cb"


def package_zip(path, *, kind="Kart", name="Cool Kart", nested=True):
    ini={"Kart":"kart.ini", "Character":"character.ini",
         "Wheels":"wheels.ini", "Music":"music.ini", "Track":"track.ini"}[kind]
    section={"Kart":"kart","Character":"character","Wheels":"wheels",
             "Music":"music","Track":"track"}[kind]
    basename="creator-original-name/" if nested else ""
    content=f"[{section}]\nname = {name}\nenabled = true\n\n[model]\nasset = my_kart\n"
    if kind=="Character":
        content+="\n[model]\nfile = body.obj\n" if "[model]" not in content else ""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr(basename+ini,content)
        if kind=="Track":
            output.writestr(basename+"data.lev",b"LEV\x01")
            output.writestr(basename+"data.vrm",b"VRM\x01")
        else:
            output.writestr(basename+"my_kart.obj","o sample\nv 0 0 0\n")


class ModManagerInstalledTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.game=self.base/"game"
        self.game.mkdir()
        (self.game/"ctr-native.exe").write_bytes(b"test fake exe")
        self.archive=self.base/"community.zip"
        package_zip(self.archive)
        self.remote={
            "id":WEB_ID,"type":"Kart","title":"Cool Kart",
            "author":"Test Author","version":"2.2",
            "source":"local","package_path":str(self.archive),
            "sha256":hashlib.sha256(self.archive.read_bytes()).hexdigest(),
        }

    def install(self):
        return Path(services.install_local_mod(self.remote,str(self.game)))

    def test_each_web_mod_has_its_own_named_folder_with_ini_id_and_type(self):
        path=self.install()
        self.assertEqual(path, self.game/"assets"/"mods"/WEB_ID)
        self.assertTrue((path/"my_kart.obj").is_file())
        content=(path/"kart.ini").read_text()
        self.assertIn("[forge_mod]",content)
        self.assertIn("id = "+WEB_ID,content)
        self.assertIn("type = Kart",content)
        self.assertIn("version = 2.2",content)
        self.assertIn("enabled = true",content)
        self.assertEqual(manager.scan_installed(self.game)[0]["status"],"ENABLED")
        self.assertEqual(manager.scan_installed(self.game)[0]["layout"],"web-id")

    def test_toggle_changes_game_native_ini_and_workshop_metadata(self):
        path=self.install()
        item=manager.set_enabled(self.game,"Kart",WEB_ID,False)
        self.assertFalse(item["enabled"])
        content=(path/"kart.ini").read_text()
        self.assertEqual(content.count("enabled = false"),2)
        self.assertEqual(item["status"],"DISABLED")
        toggled=manager.set_enabled(self.game,"Kart",WEB_ID,True)
        self.assertTrue(toggled["enabled"])
        self.assertEqual((path/"kart.ini").read_text().count("enabled = true"),2)

    def test_reinstall_updates_same_web_id_and_preserves_disabled_state(self):
        self.install()
        manager.set_enabled(self.game,"Kart",WEB_ID,False)
        package_zip(self.archive, name="Cool Kart 2")
        self.remote.update({
            "title":"Cool Kart 2","version":"2.3",
            "sha256":hashlib.sha256(self.archive.read_bytes()).hexdigest()
        })
        new=self.install()
        self.assertEqual(new,self.game/"assets/mods"/WEB_ID)
        item=manager.read_mod(self.game,"Kart",WEB_ID)
        self.assertEqual(item["title"],"Cool Kart 2")
        self.assertEqual(item["version"],"2.3")
        self.assertFalse(item["enabled"])
        backups=list((self.game/".forge_mod_backups").rglob("kart.ini"))
        self.assertEqual(len(backups),1)
        self.assertIn("version = 2.2",backups[0].read_text())

    def test_category_mismatch_cannot_replace_another_web_mod(self):
        old=self.install()
        original=(old/"kart.ini").read_bytes()
        character=self.base/"character.zip"
        package_zip(character,kind="Character")
        other=dict(self.remote,type="Character",package_path=str(character),
                   sha256=hashlib.sha256(character.read_bytes()).hexdigest())
        with self.assertRaisesRegex(services.FeedError,"different category"):
            services.install_local_mod(other,str(self.game))
        self.assertEqual((old/"kart.ini").read_bytes(),original)
        self.assertFalse((old/"character.ini").exists())

    def test_wrong_sha_rejected_without_touching_files(self):
        self.remote["sha256"]="0"*64
        with self.assertRaisesRegex(services.FeedError,"changed since"):
            self.install()
        self.assertFalse(manager.mod_path(self.game,"Kart",WEB_ID).exists())

    def test_original_category_mods_remain_visible_and_unmoved(self):
        legacy=self.game/"assets"/"mods"/"wheels"/"retro_wheels"
        legacy.mkdir(parents=True)
        (legacy/"wheels.ini").write_text(
            "[wheels]\nname=Retro Wheels\nenabled=false\n",encoding="utf-8")
        item=manager.scan_installed(self.game)[0]
        self.assertEqual((item["id"],item["type"],item["layout"]),
                         ("retro_wheels","Wheels","legacy"))
        self.assertFalse(item["enabled"])
        self.assertTrue(legacy.is_dir())
        changed=manager.set_enabled(self.game,"Wheels","retro_wheels",True)
        self.assertTrue(changed["enabled"])
        self.assertTrue(legacy.is_dir())

    def test_track_staged_without_pretending_game_registry_support(self):
        package_zip(self.archive,kind="Track")
        data=dict(self.remote,type="Track",
                  sha256=hashlib.sha256(self.archive.read_bytes()).hexdigest())
        path=Path(services.install_local_mod(data,str(self.game)))
        entry=manager.read_mod(self.game,"Track",WEB_ID)
        self.assertEqual(entry["status"],"STAGED TRACK")
        self.assertTrue((path/"data.lev").exists())
        self.assertTrue((path/"data.vrm").exists())

    def test_executable_zip_is_rejected(self):
        with zipfile.ZipFile(self.archive,"w") as zipped:
            zipped.writestr("kart.ini","[kart]\nname=Game\n")
            zipped.writestr("bad.exe","malware")
        self.remote["sha256"]=hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with self.assertRaises(services.FeedError):
            self.install()
        self.assertFalse(manager.mod_path(self.game,"Kart",WEB_ID).exists())


if __name__=="__main__":
    unittest.main()
