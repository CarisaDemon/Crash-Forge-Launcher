"""Bundled Model Importer: native single-OBJ palettes without personal data."""
from pathlib import Path
import hashlib
import importlib.util
import struct
import tempfile
import unittest
import zlib

MODULE = (Path(__file__).resolve().parents[1] /
          "companion_tools" / "model_importer" / "crash_forge_kart_colors.py")
spec = importlib.util.spec_from_file_location("forge_kart_colors_release", MODULE)
colors = importlib.util.module_from_spec(spec)
spec.loader.exec_module(colors)


def png(rgb):
    raw=b"\x00"+bytes(rgb)*2
    def chunk(t,data):
        return struct.pack(">I",len(data))+t+data+struct.pack(
            ">I",zlib.crc32(t+data)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(
        ">IIBBBBB",2,1,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(raw))+chunk(b"IEND",b"")


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.kart=self.root/"assets"/"mods"/"karts"/"test_kart"
        self.kart.mkdir(parents=True)
        self.source=self.root/"textures"
        self.source.mkdir()
        (self.kart/"test_kart.obj").write_text(
            "mtllib test_kart.mtl\n"
            "o Kart\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "vt 0 0\nvt 1 0\nvt 0 1\n"
            "usemtl Material\nf 1/1 2/2 3/3\n",encoding="utf-8")
        (self.kart/"test_kart.mtl").write_text(
            "newmtl Material\nmap_Kd test_kart.png\n",encoding="utf-8")
        (self.kart/"test_kart.png").write_bytes(png((40,60,255)))
        (self.kart/"kart.ini").write_text(
            "[kart]\nname = Test Kart\nenabled=true\n"
            "[model]\nasset_name = test_kart\n"
            "[attachments]\nseat_y = 55\n",encoding="utf-8")
        (self.source/"Blue_Kart Textures.png").write_bytes(png((40,60,255)))
        (self.source/"Red_Kart Textures.png").write_bytes(png((255,40,60)))
        (self.source/"Lime_Kart Textures.png").write_bytes(png((40,255,60)))

    def test_single_obj_reused_and_palette_registered(self):
        objhash=hashlib.sha256((self.kart/"test_kart.obj").read_bytes()).hexdigest()
        result=colors.install_colors(self.kart,self.source)
        self.assertEqual(list(result["variants"]),["blue","red","lime"])
        self.assertTrue(result["skipped_duplicate_blue"])
        self.assertEqual(len(list(self.kart.glob("*.obj"))),1)
        self.assertEqual(hashlib.sha256((self.kart/"test_kart.obj").read_bytes()).hexdigest(),objhash)
        self.assertEqual((self.kart/"test_kart.png").read_bytes(),png((40,60,255)))
        ini=(self.kart/"kart.ini").read_text()
        self.assertIn("seat_y = 55",ini)
        self.assertIn("red = color_red.png",ini)
        self.assertIn("lime = color_lime.png",ini)

    def test_reapply_is_idempotent(self):
        colors.install_colors(self.kart,self.source)
        colors.install_colors(self.kart,self.source)
        self.assertEqual((self.kart/"kart.ini").read_text().count("[colors]"),1)
        self.assertEqual(len(list(self.kart.glob("color_*.png"))),2)

    def test_reject_texture_dimension_mismatch(self):
        new=self.source/"Pink_Alt.png"
        new.write_bytes(png((250,25,100)).replace(
            struct.pack(">I",2),struct.pack(">I",3),1))
        with self.assertRaises(colors.KartColorError):
            colors.install_colors(self.kart,self.source)
        self.assertFalse((self.kart/"color_red.png").exists())

    def test_dry_run_does_not_modify_game(self):
        prior={p.name:p.read_bytes() for p in self.kart.iterdir()}
        result=colors.install_colors(self.kart,self.source,dry_run=True)
        self.assertEqual(len(result["new_textures"]),2)
        self.assertEqual(prior,{p.name:p.read_bytes() for p in self.kart.iterdir()})


if __name__=="__main__":
    unittest.main()
