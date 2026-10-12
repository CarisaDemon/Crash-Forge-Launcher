"""Modpack exporter -> existing launcher installer -> independent game modules."""
from __future__ import annotations
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from companion_tools.mod_packager import mod_packager_modpacks as exporter
from companion_tools.mod_packager import mod_packager_core as single
import forge_mod_manager as manager
import forge_modpacks
import forge_services as services


class ModpackExporterTests(unittest.TestCase):
    def setUp(self):
        self.holder=tempfile.TemporaryDirectory()
        self.addCleanup(self.holder.cleanup)
        self.base=Path(self.holder.name)
        self.sources=self.base/"source"
        self.sources.mkdir()
        self.game=self.base/"game"
        self.game.mkdir()
        (self.game/"ctr-native.exe").write_bytes(b"fake game for offline test")
        self.char=self.new_mod(
            "coco_hd","Character","Coco HD",
            "[character]\nname = Coco HD\nengine = accel\nenabled = true\n"
            "[model]\nscale = 1.5\noffset_x = 2.5\n"
            "[forge_mod]\nid = test-coco-hd\ntype = Character\n")
        self.kart=self.new_mod(
            "bandicoot_kart","Kart","Kart CNK",
            "[kart]\nname = Kart CNK\nenabled = true\n"
            "[model]\nasset_name = kart\nscale = 1.0\n"
            "[attachments]\nexhaust_count = 2\n"
            "exhaust_0_x = 71\nexhaust_1_x = -71\n"
            "[forge_mod]\nid = test-kart-cnk\ntype = Kart\n")
        self.wheels=self.new_mod(
            "cnk_wheels","Wheels","CNK Wheels",
            "[wheel]\nname = CNK Wheels\nenabled = true\n"
            "[model]\nasset_name = model\nscale = 1.0\n")
        self.bundle=self.base/"my_cfr_bundle.zip"

    def new_mod(self,folder,category,name,ini):
        path=self.sources/folder
        path.mkdir()
        ini_name=single.CATEGORIES[category][0]
        (path/ini_name).write_text(ini,encoding="utf-8")
        (path/"model.obj").write_text(
            "mtllib model.mtl\no Test\nv 0 0 0\nv 1 0 0\n"
            "v 0 1 0\nf 1 2 3\n",encoding="utf-8")
        (path/"model.mtl").write_text(
            "newmtl Skin\nmap_Kd image.png\n",encoding="utf-8")
        (path/"image.png").write_bytes(b"PNG demo "+name.encode())
        return path

    def build(self,folders=None,**kwargs):
        return exporter.build_modpack_zip(
            title=kwargs.pop("title","My CFR Bundle"),
            description=kwargs.pop("description","Three separate native mods"),
            version=kwargs.pop("version","1.2"),
            author=kwargs.pop("author","QA"),
            source_folders=folders or [self.char,self.kart,self.wheels],
            output=kwargs.pop("output",self.bundle),**kwargs)

    def test_three_configs_are_independent_and_real_launcher_accepts_archive(self):
        original={p:hashlib.sha256(p.read_bytes()).hexdigest()
                  for root in (self.char,self.kart,self.wheels)
                  for p in root.rglob("*") if p.is_file()}
        info=self.build()
        self.assertEqual(info["component_count"],3)
        self.assertEqual(info["file_count"],1+3*4)
        self.assertEqual(len(info["components"]),3)
        with zipfile.ZipFile(self.bundle) as z:
            self.assertEqual(z.testzip(),None)
            files=z.namelist()
            self.assertIn("modpack.ini",files)
            self.assertIn("racers/test-coco-hd/character.ini",files)
            self.assertIn("karts/test-kart-cnk/kart.ini",files)
            self.assertIn("wheels/cnk_wheels/wheels.ini",files)
            kart_cfg=z.read("karts/test-kart-cnk/kart.ini").decode()
            self.assertIn("exhaust_count = 2",kart_cfg)
            self.assertIn("exhaust_1_x = -71",kart_cfg)
        for file,checksum in original.items():
            self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),checksum)

        metadata=manager.inspect_local_zip(self.bundle,"Modpack")
        self.assertEqual(metadata["kind"],"Modpack")
        self.assertEqual(metadata["id"],"local_my_cfr_bundle")
        record={"type":"Modpack","id":metadata["id"],
                "title":metadata["name"],"source":"local","version":"1.2",
                "package_path":str(self.bundle),"sha256":info["sha256"]}
        services.install_local_mod(record,self.game)
        mods=self.game/"mods"
        self.assertTrue((mods/"coco_hd"/"character.ini").is_file())
        self.assertTrue((mods/"kart_cnk"/"kart.ini").is_file())
        self.assertTrue((mods/"cnk_wheels"/"wheels.ini").is_file())
        self.assertTrue((mods/"my_cfr_bundle"/"contents.json").is_file())
        self.assertEqual([len(list((mods/name).glob("*.ini")))
                          for name in ("coco_hd","kart_cnk","cnk_wheels")],[1,1,1])
        inventory=(mods/"my_cfr_bundle"/"contents.json").read_text()
        self.assertIn("test-coco-hd",inventory)
        self.assertIn("test-kart-cnk",inventory)
        listed=manager.scan_installed(self.game)
        detected={x["type"] for x in listed}
        self.assertTrue({"Character","Kart","Wheels","Modpack"}.issubset(detected))
        # Exhaust config survives into the installed game, not just ZIP.
        final=(mods/"kart_cnk"/"kart.ini").read_text()
        self.assertIn("exhaust_count = 2",final)
        self.assertIn("exhaust_1_x = -71",final)

    def test_add_native_track_alongside_models(self):
        track=self.sources/"custom_track"
        track.mkdir()
        (track/"track.ini").write_text(
            "[track]\nname=Custom Track\nenabled=true\n",encoding="utf-8")
        (track/"race.lev").write_bytes(b"lev")
        (track/"race.vrm").write_bytes(b"vrm")
        out=self.build([self.char,self.kart,track])
        with zipfile.ZipFile(out["path"]) as z:
            self.assertIn("tracks/custom_track/track.ini",z.namelist())
            self.assertIn("tracks/custom_track/race.lev",z.namelist())

    def test_legacy_plural_wheels_section_is_kept_and_installs(self):
        wheels_ini=self.wheels/"wheels.ini"
        wheels_ini.write_text(
            wheels_ini.read_text().replace("[wheel]","[wheels]"),
            encoding="utf-8")
        info=self.build()
        with zipfile.ZipFile(info["path"]) as archive:
            self.assertIn(
                "[wheels]",
                archive.read("wheels/cnk_wheels/wheels.ini").decode("utf-8"))
        meta=manager.inspect_local_zip(self.bundle,"Modpack")
        services.install_local_mod(
            {"id":meta["id"],"title":meta["name"],"type":"Modpack",
             "version":"1.2","source":"local","package_path":str(self.bundle),
             "sha256":info["sha256"]},
            self.game)
        self.assertIn(
            "[wheels]",(self.game/"mods"/"cnk_wheels"/"wheels.ini").read_text())
        self.assertIn(
            "Wheels",{item["type"] for item in manager.scan_installed(self.game)})

    def test_reject_duplicate_ids_across_categories_and_duplicate_folder(self):
        cfg=(self.wheels/"wheels.ini")
        cfg.write_text(cfg.read_text()+"[forge_mod]\nid = test-kart-cnk\n")
        with self.assertRaisesRegex(single.PackageError,"same identity"):
            self.build()
        cfg.write_text("[wheel]\nname = CNK Wheels\n")
        with self.assertRaisesRegex(single.PackageError,"same mod folder"):
            self.build([self.char,self.char])

    def test_reject_unrelated_ini_or_scripts_and_no_file_written(self):
        (self.char/"kart.ini").write_text("[kart]\nname=Wrong\n")
        with self.assertRaises(single.PackageError):
            self.build()
        (self.char/"kart.ini").unlink()
        (self.char/"danger.exe").write_bytes(b"MZ")
        with self.assertRaisesRegex(single.PackageError,"not allowed"):
            self.build()
        self.assertFalse(self.bundle.exists())

    def test_reject_missing_native_ini_and_only_one_folder(self):
        (self.kart/"kart.ini").unlink()
        with self.assertRaisesRegex(single.PackageError,"one"):
            self.build()
        with self.assertRaisesRegex(single.PackageError,"2 to 60"):
            self.build([self.char])

    def test_never_overwrite_existing_zip(self):
        self.bundle.write_bytes(b"USER PRIVATE ZIP")
        with self.assertRaisesRegex(single.PackageError,"already exists"):
            self.build()
        self.assertEqual(self.bundle.read_bytes(),b"USER PRIVATE ZIP")

    def test_reject_export_inside_original_mod_folder(self):
        path=self.char/"bundle.zip"
        with self.assertRaisesRegex(single.PackageError,"outside"):
            self.build(output=path)
        self.assertFalse(path.exists())

    def test_symlink_rejected(self):
        link=self.sources/"shortcut"
        try:
            link.symlink_to(self.char,target_is_directory=True)
        except (NotImplementedError,OSError):
            self.skipTest("No symlink support")
        with self.assertRaisesRegex(single.PackageError,"shortcut"):
            self.build([self.kart,link])

    def test_pack_uses_compact_single_mod_size_and_file_limits(self):
        self.assertTrue(exporter.MAX_COMPONENTS>=60)
        self.assertLess(self.bundle.stat().st_size if self.bundle.exists() else 0,
                        single.MAX_UPLOAD)


if __name__=="__main__":
    unittest.main()