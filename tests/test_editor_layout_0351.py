"""v0.3.51 editor size, window and pane preferences without a GUI test runner."""
import json
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace

from forge_editor_layout import (
    clamp_ratio, layout_file, load_layout, validate_saved_window,
    visible_on_desktop,
)

class LayoutSettingsTests(unittest.TestCase):
    def test_independent_persistent_files_for_both_editors(self):
        with tempfile.TemporaryDirectory() as home:
            environment={"LOCALAPPDATA":home}
            importer=layout_file("model-importer",environment=environment)
            exporter=layout_file("mod-packager",environment=environment)
            self.assertNotEqual(importer,exporter)
            self.assertEqual(importer.parent,exporter.parent)
            self.assertIn("CrashForgeRacing",str(importer))
            with self.assertRaises(ValueError):
                layout_file("../session.dat",environment=environment)

    def test_good_layout_preserves_panel_proportions_and_normal_window(self):
        with tempfile.TemporaryDirectory() as home:
            f=Path(home)/"layout.json"
            value={"schema":1,"window":{
                "width":1180,"height":765,"x":-1450,"y":36,"maximized":True},
                "panes":{"left_right":.61,"preview_textures":.72},
                "extra":{"preview_panel_height":680,"character_columns_percent":60}}
            f.write_text(json.dumps(value),encoding="utf-8")
            self.assertEqual(load_layout(f),value)
            self.assertEqual(validate_saved_window(value["window"])["x"],-1450)
            self.assertEqual(clamp_ratio(.72),.72)

    def test_corrupt_and_unbounded_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as home:
            f=Path(home)/"layout.json"
            f.write_text('{"schema":500, "window": {}}',encoding="utf-8")
            self.assertEqual(load_layout(f),{})
            f.write_text("{"*30000,encoding="utf-8")
            self.assertEqual(load_layout(f),{})
        self.assertIsNone(validate_saved_window({"width":20000,"height":800}))
        self.assertEqual(clamp_ratio(-3),.13)
        self.assertEqual(clamp_ratio(999),.87)

    def test_disconnected_display_falls_back_instead_of_disappearing(self):
        import forge_editor_layout as settings
        old=settings._screen_union
        try:
            settings._screen_union=lambda unused:(0,0,1920,1080)
            fake=SimpleNamespace(winfo_screenwidth=lambda:1920,
                                 winfo_screenheight=lambda:1080)
            self.assertFalse(visible_on_desktop(fake,{
                "x":-4000,"y":0,"width":1050,"height":715}))
            self.assertTrue(visible_on_desktop(fake,{
                "x":100,"y":150,"width":1050,"height":715}))
        finally:
            settings._screen_union=old

    def test_splitters_are_interactive_in_both_source_programs(self):
        root=Path(__file__).resolve().parents[1]
        exporter=(root/"companion_tools"/"mod_packager"/"mod_packager_gui.py").read_text(encoding="utf-8")
        importer=(root/"companion_tools"/"model_importer"/"crash_forge_character_tool.py").read_text(encoding="utf-8")
        common=(root/"forge_model_preview.py").read_text(encoding="utf-8")
        self.assertIn('self.main_split=tk.PanedWindow(',exporter)
        self.assertIn('self.right_split=tk.PanedWindow(',exporter)
        self.assertIn('self.layout.register_pane("left_right", self.main_split)',exporter)
        self.assertIn('self.layout.register_pane("preview_textures", self.right_split)',exporter)
        self.assertIn('self.preview_split = tk.PanedWindow(',importer)
        self.assertIn('self.layout.register_pane("preview_textures", self.preview_split)',importer)
        self.assertIn('self._char_sash.bind("<B1-Motion>"',importer)
        self.assertIn('self._preview_height_slider=ttk.Scale(',importer)
        self.assertIn('outer.pack(fill="both",expand=True)',common)
        self.assertIn('self.width=event.width',common)

if __name__=="__main__":
    unittest.main()
