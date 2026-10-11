"""Windows launcher v0.3.38: real Model Importer v1.8 packaging checks."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
TOOL_DIR=ROOT/"companion_tools"/"model_importer"
sys.path.insert(0,str(TOOL_DIR))
import crash_forge_character_tool as importer
from crash_forge_model_imports import import_mod,ImportErrorMod


class ModelImporterV18Tests(unittest.TestCase):
    def test_the_exact_updated_tool_is_bundled(self):
        self.assertEqual(importer.APP_VERSION,"1.8")
        source=(TOOL_DIR/"crash_forge_character_tool.py").read_text(encoding="utf-8")
        for item in ('"CHARACTER"','"KART"','"WHEELS"','"TRACKS"',
                     'def _show_section(', 'def _import_mod(', 'def _load_forge_background('):
            self.assertIn(item,source)

    def test_standalone_resource_bundling(self):
        ps=(ROOT/"release_tools"/"build_windows.ps1").read_text(encoding="utf-8")
        source=(TOOL_DIR/"crash_forge_character_tool.py").read_text(encoding="utf-8")
        self.assertIn("Model Importer v1.8",ps)
        self.assertIn("--add-data $modelImporterBackground",ps)
        self.assertIn("--add-data $modelImporterIcon",ps)
        self.assertIn('Path(bundled_root) / "assets" / relative',source)
        self.assertIn('self._forge_art_file("Fondo.png")',source)
        self.assertIn('self._forge_art_file("icons/cfr_icon.ico")',source)

    def test_kart_and_wheel_imports_are_actually_packaged(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            (base/"assets").mkdir()
            obj=base/"sample.obj"
            obj.write_text("o wheel_fl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
                           encoding="utf-8")
            offsets={k:"0" for k in "xyz"}
            a=import_mod(obj,base,"kart","Demo Kart","demo_kart","1.0",offsets)
            self.assertTrue((base/"mods"/"demo_kart"/"kart.ini").is_file())
            self.assertIn("type = Kart", (base/"mods"/"demo_kart"/"kart.ini").read_text())
            self.assertFalse((base/"assets"/"mods"/"karts"/"demo_kart").exists())
            self.assertTrue((base/"mods"/"demo_kart"/"demo_kart.obj").is_file())
            self.assertEqual(a["backup"],None)
            # The same mod cannot be overwritten without explicit consent.
            with self.assertRaises(ImportErrorMod):
                import_mod(obj,base,"kart","Demo Kart","demo_kart","1.0",offsets)
            b=import_mod(obj,base,"kart","New Demo Kart","demo_kart","1.0",
                         offsets,replace=True)
            self.assertIsNotNone(b["backup"])
            self.assertTrue(Path(b["backup"]).is_dir())
            self.assertTrue(str(b["backup"]).startswith(
                str(base/".forge_mod_backups"/"model_import")))

    def test_wheel_import_requires_four_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            (base/"assets").mkdir()
            obj=base/"wheels.obj"
            obj.write_text("o wheel_fl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
                           encoding="utf-8")
            with self.assertRaisesRegex(ImportErrorMod,"Missing wheel groups"):
                import_mod(obj,base,"wheels","My Wheels","my_wheels","1",
                           {k:"0" for k in "xyz"})

    def test_track_importer_never_replaces_retail_maps(self):
        source=(TOOL_DIR/"crash_forge_character_tool.py").read_text(encoding="utf-8")
        self.assertIn('install_native_track(',source)
        self.assertIn('"LEV + VRM only',source)
        self.assertTrue((TOOL_DIR/"crash_forge_native_tracks.py").is_file())


if __name__=="__main__":
    unittest.main()
