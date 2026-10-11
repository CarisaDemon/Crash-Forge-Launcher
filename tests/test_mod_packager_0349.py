"""v0.3.49 Mod Packager and editor monitor regression tests (no GUI opened)."""
from __future__ import annotations
import configparser
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from companion_tools.mod_packager import mod_packager_core as core
import forge_mod_manager as manager

SOURCE=Path(__file__).resolve().parents[1]

class ModPackagerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.model=self.base/"source"
        self.model.mkdir()
    def output(self,slug):
        return self.base/(slug+".zip")
    def archive(self,category):
        if category=="Track":
            (self.model/"course.lev").write_bytes(b"TEST LEV")
            (self.model/"course.vrm").write_bytes(b"TEST VRM")
        else:
            (self.model/"sample.obj").write_text("o sample\nv 0 0 0\n",encoding="utf-8")
            (self.model/"texture.png").write_bytes(b"PNG\0TEST")
        kind=core.folder_name(category+" Test")
        result=core.build_mod_zip(title=category+" Test",
               kind=category,version="1.0",
               author="Sample Creator",description="Test import/export modular asset",
               source_folder=self.model,output=self.output(kind))
        return result
    def test_four_mod_types_build_game_readable_zip(self):
        for category,(_,section) in core.CATEGORIES.items():
            with self.subTest(category=category):
                for path in self.model.iterdir():path.unlink()
                result=self.archive(category)
                with zipfile.ZipFile(result["path"]) as z:
                    names=z.namelist()
                    ini=core.CATEGORIES[category][0]
                    base=core.folder_name(category+" Test")
                    self.assertIn(base+"/"+ini,names)
                    self.assertIn(base+"/forge_package.json",names)
                    text=z.read(base+"/"+ini).decode("utf-8")
                    conf=configparser.ConfigParser()
                    conf.read_string(text)
                    self.assertTrue(conf.has_section(section))
                    self.assertEqual(conf.get("forge_mod","type"),category)
                    self.assertEqual(conf.get(section,"enabled"),"true")
                    if category=="Track":
                        self.assertTrue(any(x.endswith("/course.lev") for x in names))
                    self.assertEqual(z.testzip(),None)
                    unpack=self.base/("unpack_"+category)
                    z.extractall(unpack)
                mod={"type":category,"id":"forge-test_"+category.lower(),
                     "title":category+" Test","version":"1.0","source":"online"}
                prepared=manager.prepare_single_mod(unpack,mod)
                self.assertTrue((prepared/ini).is_file())
                self.assertEqual(result["category"],category)
    def test_imported_ini_preserves_native_settings(self):
        (self.model/"sample.obj").write_text("o SAMPLE",encoding="utf-8")
        (self.model/"kart.ini").write_text(
            "[kart]\nname = Special Kart\nenabled = false\n\n"
            "[model]\nasset_name = sample\nscale = 2.5\n\n"
            "[forge_mod]\nid = forge-original\nsource = forge_hub\n",
            encoding="utf-8")
        result=core.build_mod_zip(title="Special Kart",kind="Kart",
            version="1.3",source_folder=self.model,output=self.output("kart"))
        with zipfile.ZipFile(result["path"]) as z:
            txt=z.read("special_kart/kart.ini").decode()
        self.assertIn("scale = 2.5",txt)
        self.assertIn("id = forge-original",txt)
        self.assertIn("version = 1.3",txt)
    def test_track_needs_both_native_files(self):
        (self.model/"course.lev").write_bytes(b"LEV")
        with self.assertRaisesRegex(core.PackageError,"one .lev and .vrm"):
            core.build_mod_zip(title="Broken Track",kind="Track",version="1.0",
                               source_folder=self.model,output=self.output("bad"))
        self.assertFalse(self.output("bad").exists())
    def test_forbidden_files_and_links_never_get_packaged(self):
        (self.model/"sample.obj").write_bytes(b"OBJ")
        (self.model/"game.iso").write_bytes(b"ISO")
        with self.assertRaisesRegex(core.PackageError,"not allowed"):
            core.build_mod_zip(title="Unsafe Racer",kind="Character",
                               version="1.0",source_folder=self.model,
                               output=self.output("unsafe"))
        self.assertFalse(self.output("unsafe").exists())
    def test_zip_cannot_replace_source_or_existing_file(self):
        (self.model/"sample.obj").write_bytes(b"OBJ")
        with self.assertRaisesRegex(core.PackageError,"outside"):
            core.build_mod_zip(title="My Racer",kind="Character",version="1.0",
                               source_folder=self.model,output=self.model/"inside.zip")
        existing=self.output("dont_overwrite")
        existing.write_bytes(b"PERSONAL DATA")
        with self.assertRaisesRegex(core.PackageError,"exists"):
            core.build_mod_zip(title="My Racer",kind="Character",version="1.0",
                               source_folder=self.model,output=existing)
        self.assertEqual(existing.read_bytes(),b"PERSONAL DATA")
    def test_selected_files_supported_without_mod_folder(self):
        obj=self.model/"sample.obj"
        obj.write_bytes(b"OBJ")
        result=core.build_mod_zip(title="Single File Racer",kind="Character",
               version="1.0",selected_files=[obj],output=self.output("single"))
        self.assertEqual(result["category"],"Character")
    def test_secondary_monitor_selector_is_pinned_with_windows_native_coords(self):
        src=(SOURCE/"launcher.py").read_text(encoding="utf-8")
        geometry=(SOURCE/"forge_editor_geometry.py").read_text(encoding="utf-8")
        self.assertIn('win.withdraw()',src)
        self.assertIn('enforce_native_window_position(win, x, y, width, height)',src)
        self.assertIn("SetWindowPos",geometry)
        self.assertIn('editor_geometry.tk_absolute_position(',src)
        self.assertIn('"MOD PACKAGER"',src)
        self.assertIn('tool_paths["modpackager"]',src)
    def test_bundle_registers_gui_executable_for_fourth_tool(self):
        from forge_editor_registry import EDITORS
        self.assertEqual(EDITORS["modpackager"],"CrashForgeModPackager.exe")
        build=(SOURCE/"release_tools"/"build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('--name "CrashForgeModPackager"',build)
        self.assertIn('--onefile --windowed',build)


if __name__=="__main__":
    unittest.main()
