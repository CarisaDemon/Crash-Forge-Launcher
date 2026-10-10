"""Native Forge mod ID, readable names, and INSTALLED/HIDE LOCAL filters."""
from pathlib import Path
import hashlib
import io
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import forge_mod_manager as manager
import forge_services as services
from launcher import Launcher

WEB_ID = "e375ca08-5566-45ff-89aa-8973cf6e120e"


class MockVar:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,v):self.value=v


class SummaryLabel:
    text=""
    def configure(self,**opts):self.text=opts.get("text",self.text)


class TestForgeModManager(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="forge-manager-tests-")
        self.addCleanup(t.cleanup)
        self.base=Path(t.name)
        self.game=self.base/"Game"
        self.game.mkdir()
        (self.game/"ctr-native.exe").write_bytes(b"test placeholder")
        (self.game/"assets"/"mods").mkdir(parents=True)

    def make_web(self,category="Kart",slug=WEB_ID,title="Cinematic Blue Kart",enabled=True,origin="forge_hub"):
        mod=manager.mod_path(self.game,category,slug)
        mod.mkdir(parents=True,exist_ok=True)
        file=manager.CATEGORIES[category][1]
        section=manager.CATEGORIES[category][2][0]
        content=(f"[{section}]\nname = Original Native Asset\nid = native_old_asset\n"
                 f"enabled = {'true' if enabled else 'false'}\n\n"
                 f"[forge_mod]\nid = {slug}\ntype = {category}\n"
                 f"name = {title}\nversion = 2.1\nsource = {origin}\n"
                 f"source_id = {slug}\nenabled = {'true' if enabled else 'false'}\n")
        (mod/file).write_text(content,encoding="utf-8")
        return mod

    def test_web_mod_has_a_human_name_but_private_id_inside_ini(self):
        folder=self.make_web()
        inv=manager.read_mod(self.game,"Kart",WEB_ID)
        self.assertEqual(inv["title"],"Cinematic Blue Kart")
        self.assertEqual(inv["id"],WEB_ID)
        self.assertEqual(inv["origin"],"forge_hub")
        self.assertEqual(inv["source_id"],WEB_ID)
        item={"type":"Kart","source":"installed","id":WEB_ID,"_installed":inv}
        self.assertEqual(manager.display_mod_name(item),"Cinematic Blue Kart")
        self.assertNotIn(WEB_ID,manager.display_mod_name(item))
        self.assertIn("id = "+WEB_ID,(folder/"kart.ini").read_text())

    def test_enabled_switch_writes_game_native_ini_and_web_metadata(self):
        path=self.make_web()
        off=manager.set_enabled(self.game,"Kart",WEB_ID,False)
        self.assertEqual(off["enabled"],False)
        ini=(path/"kart.ini").read_text(encoding="utf-8")
        self.assertEqual(ini.count("enabled = false"),2)
        self.assertIn("name = Cinematic Blue Kart",ini)
        self.assertIn("id = "+WEB_ID,ini)
        self.assertEqual(manager.set_enabled(self.game,"Kart",WEB_ID,True)["enabled"],True)

    def test_legacy_mods_are_visible_and_not_moved(self):
        old=self.game/"assets"/"mods"/"racers"/"legacy_racer"
        old.mkdir(parents=True)
        (old/"character.ini").write_text("[character]\nname = Old Crash HD\nenabled=true\n")
        inv=manager.scan_installed(self.game)
        self.assertEqual(len(inv),1)
        self.assertEqual(inv[0]["title"],"Old Crash HD")
        self.assertEqual(inv[0]["origin"],"legacy")
        self.assertEqual(inv[0]["layout"],"legacy")
        self.assertTrue(old.exists())

    def test_mod_type_validation_prevents_cross_category_id_claim(self):
        path=self.make_web()
        ini=path/"kart.ini"
        content=ini.read_text().replace("type = Kart","type = Character")
        ini.write_text(content)
        row=manager.read_mod(self.game,"Kart",WEB_ID)
        self.assertFalse(row["manageable"])
        self.assertEqual(row["status"],"INVALID INI")
        with self.assertRaises(manager.ModManagerError):
            manager.set_enabled(self.game,"Kart",WEB_ID,False)

    def test_hiding_local_mods_does_not_hide_downloaded_web_mods(self):
        self.assertTrue(manager.locally_sourced({"source":"local","id":"myfile"}))
        self.assertTrue(manager.locally_sourced(
            {"source":"installed","_installed":{"origin":"legacy"}}))
        self.assertFalse(manager.locally_sourced(
            {"source":"installed","_installed":{"origin":"forge_hub"}}))
        self.assertFalse(manager.locally_sourced({"source":"online","id":WEB_ID}))
        self.assertFalse(manager.locally_sourced({"source":"online","_installed":
                                                  {"origin":"local"}}))

    def test_filters_compose_with_installed_only(self):
        self.make_web()
        root=self.game/"assets"/"mods"/"racers"/"local_crash"
        root.mkdir(parents=True)
        (root/"character.ini").write_text("[character]\nname=My Local Crash\nenabled=false\n")
        internet={"source":"online","type":"Kart","id":WEB_ID,
                  "title":"Cinematic Blue Kart","version":"2.1","description":""}
        published_not_installed={"source":"online","type":"Kart","id":"future_kart",
                                "title":"Future Kart","version":"1.0","description":""}
        local_zip={"source":"local","type":"Wheels","id":"local_wheels",
                   "title":"My Local Wheels","version":"1.0","description":""}
        obj=SimpleNamespace(
            game_install_path=str(self.game),
            remote_mods=[internet,published_not_installed],
            _load_community_catalog=lambda:[local_zip],
            hub_installed_summary=SummaryLabel(),
            hub_hide_local_var=MockVar(True),
            hub_installed_only_var=MockVar(True),
            hub_search_var=MockVar(""),
            hub_type_var=MockVar("All"),
            hub_sort_var=MockVar("Name"))
        seen=Launcher._hub_filtered_catalog(obj)
        self.assertEqual([x["id"] for x in seen],[WEB_ID])
        self.assertEqual(manager.display_mod_name(seen[0]),"Cinematic Blue Kart")
        self.assertFalse(manager.locally_sourced(seen[0]))
        self.assertIn("2 INSTALLED",obj.hub_installed_summary.text)
        # Toggling is purely presentational and does not write to the native INI.
        obj.hub_hide_local_var.set(False)
        ids={item["id"] for item in Launcher._hub_filtered_catalog(obj)}
        self.assertEqual(ids,{WEB_ID,"local_crash"})
        self.assertFalse(
            (root/"character.ini").read_text().split("enabled=")[-1].strip()=="true")

    def test_installer_uses_web_id_directory_and_does_not_flatten_assets(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,"w",zipfile.ZIP_DEFLATED) as out:
            out.writestr("Cool Kart/kart.ini",
                         "[kart]\nname=Original Asset\nid=asset_native\n"
                         "enabled=true\n")
            out.writestr("Cool Kart/body.obj","o Body\nv 0 0 0\n")
        file=self.base/"kart.zip"
        file.write_bytes(data.getvalue())
        item={"source":"local","type":"Kart","id":WEB_ID,
              "title":"Blue Speedster","author":"Creator",
              "version":"1.0","package_path":str(file),
              "sha256":hashlib.sha256(data.getvalue()).hexdigest()}
        with patch.object(services,"real_game_status",return_value={"installed":True}):
            result=services.install_local_mod(item,self.game)
        root=Path(result)
        self.assertEqual(root.name,WEB_ID)
        self.assertEqual(root.parent.name,"mods")
        self.assertTrue((root/"body.obj").is_file())
        ini=(root/"kart.ini").read_text()
        self.assertIn("[forge_mod]",ini)
        self.assertIn("name = Blue Speedster",ini)
        self.assertIn("type = Kart",ini)
        self.assertIn("id = "+WEB_ID,ini)
        installed=manager.read_mod(self.game,"Kart",WEB_ID)
        self.assertEqual(installed["title"],"Blue Speedster")

    def test_title_is_not_the_folder_or_public_id(self):
        row={"id":WEB_ID,"title":"Racing Inferno","source":"online",
             "_installed":{"title":"Different Native Name"}}
        self.assertEqual(manager.display_mod_name(row),"Racing Inferno")
        self.assertNotEqual(manager.display_mod_name(row),row["id"])


if __name__=="__main__":
    unittest.main()
