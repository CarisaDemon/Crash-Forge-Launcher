import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import forge_profiles as fp
import forge_mod_manager as mgr

class ProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/"mods").mkdir()
        self.folder=self.root/"mods"/"my_character"
        self.folder.mkdir()
        (self.folder/"character.ini").write_text(
            "[forge_mod]\nid = mod_foo\ntype = Character\nname = Test Character\n"
            "[character]\nid = tester\nname = Test Character\nenabled = true\n",encoding="utf-8")

    def test_save_and_reload(self):
        profile=fp.snapshot(str(self.root),"Racing mods")
        self.assertEqual(len(profile["mods"]),1)
        self.assertTrue(profile["mods"][0]["enabled"])
        self.assertEqual(fp.load(str(self.root))["profiles"][0]["name"],"Racing mods")
        self.assertTrue((self.root/".forge_profiles"/"profiles.json").exists())

    def test_profile_can_restore_native_ini(self):
        profile=fp.snapshot(str(self.root),"Mine")
        mgr.set_enabled(str(self.root),"Character","mod_foo",False)
        changes,missing=fp.plan_apply(str(self.root),profile)
        self.assertEqual(len(changes),1)
        self.assertEqual(missing,[])
        count,_=fp.apply(str(self.root),profile)
        self.assertEqual(count,1)
        self.assertTrue(mgr.read_mod(str(self.root),"Character","mod_foo")["enabled"])

    def test_no_installed_mods_deleted_when_applying(self):
        profile=fp.snapshot(str(self.root),"Old")
        profile["mods"]=[]
        fp.apply(str(self.root),profile)
        self.assertTrue((self.folder/"character.ini").is_file())

    def test_import_conflict_preserves_original(self):
        original=fp.snapshot(str(self.root),"Source")
        with self.assertRaises(fp.ProfileError):
            fp.cloud_import(str(self.root),original)
        self.assertEqual(len(fp.load(str(self.root))["profiles"]),1)

    def test_cloud_upload_is_explicit_and_checks_remote(self):
        profile=fp.snapshot(str(self.root),"Cloud")
        class Client:
            def token(self):return "fake"
            def profile(self):return {"id":"f9e7ac6e-8025-42fe-a042-2079f9c77f4b"}
            def _request(self,url,payload=None,**kwargs):
                self.last_url=url
                self.last_payload=payload
                return [] if kwargs["method"]=="GET" else {}
        client=Client()
        fp.cloud_upload_new(client,profile)
        self.assertEqual(client.last_payload["mod_states"],profile["mods"])
        self.assertEqual(client.last_payload["owner_id"],client.profile()["id"])

    def test_invalid_json_profile_mods_not_applied(self):
        profile=fp.snapshot(str(self.root),"Old")
        profile["mods"][0]["type"]="../../exploit"
        with self.assertRaises(fp.ProfileError):fp.apply(str(self.root),profile)

    def test_missing_mod_does_not_trigger_installation(self):
        profile=fp.snapshot(str(self.root),"Old")
        (self.folder/"character.ini").unlink()
        _,missing=fp.plan_apply(str(self.root),profile)
        self.assertEqual(len(missing),1)

if __name__=="__main__":
    unittest.main()
