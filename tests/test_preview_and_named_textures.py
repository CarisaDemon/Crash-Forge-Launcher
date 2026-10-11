"""Read-only 3D previews and arbitrary named kart textures for every mod type."""
from pathlib import Path
import tempfile
import unittest
import struct
import sys
from PIL import Image

import forge_model_preview as preview
from forge_editor_config import save_launcher_selection, selected_game_directory

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"companion_tools"/"model_importer"))
import crash_forge_kart_colors as colors


class NativePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_obj_preview_preserves_model_and_mtl_texture(self):
        obj=self.root/"my_racer.obj"
        obj.write_text(
            "mtllib my_racer.mtl\n"
            "v 0 0 0\nv 100 0 0\nv 0 100 0\n"
            "vt 0 0\nvt 1 0\nvt 0 1\n"
            "usemtl Custom\nf 1/1 2/2 3/3\n",encoding="utf-8")
        (self.root/"my_racer.mtl").write_text(
            "newmtl Custom\nmap_Kd Fancy_Skin.png\n",encoding="utf-8")
        Image.new("RGB",(32,32),"purple").save(self.root/"Fancy_Skin.png")
        scene=preview.load_obj(obj)
        self.assertEqual(scene.kind,"OBJ")
        self.assertEqual(len(scene.vertices),3)
        self.assertEqual(len(scene.faces),1)
        self.assertEqual(scene.textures["Custom"].name,"Fancy_Skin.png")

    def test_native_lev_preview_reads_real_mesh_arrays_read_only(self):
        lev=self.root/"scene.lev"
        data=bytearray(4096)
        struct.pack_into("<I",data,0,4092)
        struct.pack_into("<I",data,4,128)  # mesh header relative to container base 4
        header=4+128
        struct.pack_into("<8I",data,header,1,9,0,256,512,0,0,0)
        struct.pack_into("<9H",data,4+256,*range(9))
        for i in range(9):
            struct.pack_into("<hhhHBBBB",data,4+512+i*16,
                             i*30,(i%3)*20,(i//3)*30,0,0,64,128,255)
        lev.write_bytes(data)
        before=lev.read_bytes()
        scene=preview.load_ctr_lev(lev)
        self.assertEqual(scene.kind,"LEV")
        self.assertEqual(len(scene.vertices),9)
        self.assertEqual(len(scene.faces),8)
        self.assertEqual(len(scene.colors),9)
        self.assertEqual(lev.read_bytes(),before)

    def test_image_sources_and_model_sources_cover_all_categories(self):
        (self.root/"character.obj").write_bytes(b"v 0 0 0")
        (self.root/"course.lev").write_bytes(b"LEV")
        Image.new("RGB",(16,16),"cyan").save(self.root/"CANDY_PINK.png")
        for kind in ("Character","Kart","Wheels"):
            sources=preview.model_sources_from_folder(self.root,category=kind)
            self.assertEqual(sources[0].name,"character.obj")
        self.assertEqual(preview.model_sources_from_folder(
            self.root,category="Track")[0].name,"course.lev")
        self.assertEqual(preview.texture_sources_from_folder(
            self.root)[0].name,"CANDY_PINK.png")


class RandomKartSkinTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.game=self.root/"mods"/"my_kart"
        self.game.mkdir(parents=True)
        (self.game/"my_kart.obj").write_text(
            "mtllib my_kart.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3",
            encoding="utf-8")
        (self.game/"my_kart.mtl").write_text(
            "newmtl MAT\nmap_Kd my_kart.png\n",encoding="utf-8")
        Image.new("RGB",(4,4),"gray").save(self.game/"my_kart.png")
        (self.game/"kart.ini").write_text(
            "[kart]\nname=Wild Kart\n\n[model]\nasset_name=my_kart\n\n"
            "[attachments]\nseat_y=21\n",encoding="utf-8")
        self.skins=self.root/"skins"
        self.skins.mkdir()
        Image.new("RGB",(4,4),"orange").save(self.skins/"Party_Rainbow.png")
        Image.new("RGB",(4,4),"pink").save(self.skins/"Galaxy_Multi_Color.png")

    def test_random_names_propagate_to_actual_native_ini(self):
        found=colors.scan_palette(self.skins)
        self.assertEqual(len(found),2)
        self.assertEqual(set(item["filename"] for item in found),
                         {"Party_Rainbow.png","Galaxy_Multi_Color.png"})
        mapping={"Party_Rainbow.png":"Candy Chrome",
                 "Galaxy_Multi_Color.png":"Hyper Nova"}
        before=(self.game/"my_kart.obj").read_bytes()
        result=colors.install_colors(self.game,self.skins,variants=mapping,
                                     default_name="Factory",dry_run=True)
        self.assertEqual(list(result["variants"]),["Factory","Candy Chrome","Hyper Nova"])
        colors.install_colors(self.game,self.skins,variants=mapping,
                              default_name="Factory")
        ini=(self.game/"kart.ini").read_text(encoding="utf-8")
        self.assertIn("Candy Chrome = color_party_rainbow.png",ini)
        self.assertIn("Hyper Nova = color_galaxy_multi_color.png",ini)
        self.assertIn("seat_y=21",ini)
        self.assertEqual((self.game/"my_kart.obj").read_bytes(),before)

    def test_invalid_names_block_unsafe_metadata(self):
        with self.assertRaises(colors.KartColorError):
            colors.install_colors(self.game,self.skins,
                 variants={"Party_Rainbow.png":"Bad = Value"})

    def test_no_overwrite_for_existing_texture_different_contents(self):
        Image.new("RGB",(4,4),"blue").save(self.game/"color_party_rainbow.png")
        with self.assertRaises(colors.KartColorError):
            colors.install_colors(self.game,self.skins,
                 variants={"Party_Rainbow.png":"Summer"})

if __name__=="__main__":
    unittest.main()
