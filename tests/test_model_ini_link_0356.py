"""No game files changed: regression tests for loading and saving linked model INIs."""
from pathlib import Path
import tempfile
import unittest

from forge_model_ini_link import (
    find_linked_ini, read_linked_ini, save_linked_ini,
    LinkedIniError, LinkedIniConflict,
)


class LinkedModelIniTests(unittest.TestCase):
    def setUp(self):
        self.holder=tempfile.TemporaryDirectory()
        self.addCleanup(self.holder.cleanup)
        self.folder=Path(self.holder.name)
        self.obj=self.folder/"TeamBandicootCNK.obj"
        self.obj.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",encoding="utf-8")

    def write(self,kind,text):
        filename={"character":"character.ini","kart":"kart.ini","wheels":"wheels.ini"}[kind]
        p=self.folder/filename
        p.write_bytes(text.encode("utf-8"))
        return p

    def test_find_ini_by_folder_and_auto_category(self):
        self.assertIsNone(find_linked_ini(self.obj,"kart"))
        kart=self.write("kart","[kart]\nname = Kart\n")
        self.assertEqual(find_linked_ini(self.obj,"kart"),("kart",kart))
        self.assertEqual(find_linked_ini(self.obj,"character"),("kart",kart))
        wheels=self.write("wheels","[wheel]\nname = Wheels\n")
        self.assertIsNone(find_linked_ini(self.obj,"character"))
        self.assertEqual(find_linked_ini(self.obj,"wheels"),("wheels",wheels))
        self.assertEqual(find_linked_ini(self.folder/"missing.obj","kart"),None)

    def test_read_character_metadata_offsets_icon_and_has_wheels(self):
        text=("[character]\nname = Coco HD\nfallback_retail = coco\n"
              "engine = balanced\nkart = bandicoot\nhas_wheels = true\n"
              "[model]\nscale = 2.5\noffset_x = -.4\n"
              "[assets]\nasset_name = coco_hd\nicon = retail:coco\n"
              "[forge_mod]\nid = forge-acb\n")
        p=self.write("character",text)
        a=read_linked_ini("character",p)
        self.assertEqual(a.fields["scale"],"2.5")
        self.assertEqual(a.fields["offset_x"],"-.4")
        self.assertEqual(a.fields["offset_y"],"0.0")
        self.assertEqual(a.fields["asset_name"],"coco_hd")
        self.assertEqual(a.fields["engine"],"balanced")
        self.assertEqual(a.fields["kart"],"bandicoot")
        self.assertNotIn("has_wheels",a.fields)

    def test_kart_legacy_mounts_and_default_exhaust_inference(self):
        p=self.write("kart",
            "[kart]\nname = Cnk Kart\n[model]\nscale = 1.3\n"
            "[seat]\nx=25\n[exhaust]\nexhaust_0_x=71\n"
            "exhaust_0_rotation_y=-14\n")
        link=read_linked_ini("kart",p)
        self.assertEqual(link.fields["seat_x"],"25")
        self.assertEqual(link.fields["exhaust_0_rotation_y"],"-14")
        self.assertEqual(link.fields["exhaust_count"],"1")
        self.assertEqual(link.fields["wheel_fl_y"],"0.0")
        before=p.read_bytes()
        backup=save_linked_ini(link,dict(link.fields,seat_x="26",
                          exhaust_0_rotation_y="-10",offset_z="2"))
        self.assertEqual(backup.read_bytes(),before)
        result=p.read_text(encoding="utf-8")
        self.assertIn("[seat]\nx=26",result)
        self.assertIn("exhaust_0_rotation_y=-10",result)
        self.assertIn("offset_z = 2",result)
        self.assertNotIn("[attachments]",result)

    def test_save_preserves_unknown_fields_comments_web_metadata_and_crlf(self):
        text=("[kart]\r\nname = Original Name\r\n"
              "enabled = true\r\n\r\n[model]\r\n"
              "asset_name = TeamBandicootCNK\r\nscale = 1.0\r\n"
              "offset_x = 0.0  ; hand tuned\r\n"
              "custom_unknown = keep-me\r\n\r\n"
              "[attachments]\r\nseat_y = 10\r\n"
              "wheel_fl_x = 110.41\r\nexhaust_count = 2\r\n"
              "exhaust_0_x = 71\r\n\r\n[colors]\r\nBlue = blue.png\r\n"
              "[forge_mod]\r\nid = forge-abc\r\nsource_id = forge-abc\r\n"
              "version = 5.1\r\n")
        p=self.write("kart",text)
        link=read_linked_ini("kart",p)
        fields=dict(link.fields,offset_x="1.25",seat_y="44",
                    exhaust_0_x="80")
        backup=save_linked_ini(link,fields)
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_bytes(),text.encode("utf-8"))
        out=p.read_bytes()
        self.assertIn(b"offset_x = 1.25  ; hand tuned\r\n",out)
        self.assertIn(b"seat_y = 44\r\n",out)
        self.assertIn(b"exhaust_0_x = 80\r\n",out)
        self.assertIn(b"custom_unknown = keep-me\r\n",out)
        self.assertIn(b"source_id = forge-abc\r\n",out)
        self.assertIn(b"[colors]\r\nBlue = blue.png\r\n",out)
        self.assertNotIn(b"wheel_rr_x",out)
        self.assertNotIn(b"exhaust_1_x",out)

    def test_save_no_changes_produces_no_write_or_backup(self):
        p=self.write("wheels","[wheel]\nname=Wheels\n[model]\nscale=1.0\n")
        link=read_linked_ini("wheels",p)
        initial=p.read_bytes()
        self.assertIsNone(save_linked_ini(link,link.fields))
        self.assertEqual(p.read_bytes(),initial)
        self.assertEqual(len(list(self.folder.glob("*.bak"))),0)

    def test_wheels_edit_and_category_sections(self):
        p=self.write("wheels","[wheel]\nname=Retro\n[model]\nasset_name = retro\nscale=1.0\n")
        link=read_linked_ini("wheels",p)
        save_linked_ini(link,dict(link.fields,name="NF Retro",offset_y="17"))
        out=p.read_text()
        self.assertIn("name=NF Retro",out)
        self.assertIn("offset_y = 17",out)
        self.assertNotIn("[attachments]",out)

    def test_exhaust_count_default_removes_existing_key(self):
        p=self.write("kart","[kart]\nname=A\n[attachments]\nexhaust_count=0\n")
        link=read_linked_ini("kart",p)
        save_linked_ini(link,dict(link.fields,exhaust_count="Default"))
        self.assertNotIn("exhaust_count=",p.read_text())

    def test_external_change_refuses_save_and_preserves_it(self):
        p=self.write("kart","[kart]\nname=A\n")
        link=read_linked_ini("kart",p)
        p.write_text(p.read_text()+"; external\n")
        with self.assertRaises(LinkedIniConflict):
            save_linked_ini(link,dict(link.fields,name="B"))
        self.assertIn("; external",p.read_text())
        self.assertEqual(len(list(self.folder.glob("*.bak"))),0)

    def test_bad_numeric_or_unsafe_string_refuses_save(self):
        p=self.write("kart","[kart]\nname=A\n[model]\nscale=1.0\n")
        link=read_linked_ini("kart",p)
        for updates in (dict(scale="0"),dict(scale="-1"),dict(offset_x="NaN"),
                        dict(offset_x="abc"),dict(name="bad\n[evil]"),
                        dict(exhaust_count="5")):
            with self.subTest(updates=updates):
                with self.assertRaises(LinkedIniError):
                    save_linked_ini(link,dict(link.fields,**updates))
        self.assertEqual(len(list(self.folder.glob("*.bak"))),0)

    def test_unicode_bom_preserved(self):
        p=self.write("character","[character]\nname=Coco\n")
        p.write_bytes(b"\xef\xbb\xbf"+p.read_bytes())
        link=read_linked_ini("character",p)
        save_linked_ini(link,dict(link.fields,name="Coquita"))
        self.assertTrue(p.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertIn("Coquita",p.read_text(encoding="utf-8-sig"))


if __name__=="__main__":
    unittest.main()