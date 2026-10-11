"""Modpack validation, folder routing and safe installer regression tests."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import forge_modpacks as packs
import forge_services as services


def zip_bytes(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


FILES = {
    "modpack.ini": "[modpack]\nname = Test Bundle\ndescription = Two native CFR mods\ncompatibility = cfr\n",
    "racers/test_racer/character.ini": "[character]\nname = Test Racer\n",
    "racers/test_racer/racer.obj": "v 0 0 0\n",
    "karts/test_kart/kart.ini": "[kart]\nname = Test Kart\n",
    "karts/test_kart/kart.obj": "v 1 1 1\n",
}


class Stream(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self.url = url

    def geturl(self):
        return self.url


class TestModpacks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root / "game"
        self.game.mkdir()
        (self.game / "ctr-native.exe").write_bytes(b"fake test exe only")
        self.staging = self.root / "contents"
        self.staging.mkdir()
        for key, data in FILES.items():
            path = self.staging / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data, encoding="utf-8")

    def test_distinct_ini_kept_in_flat_web_id_folders(self):
        result = packs.install_prepared_modpack(self.staging, self.game, "sample_pack")
        self.assertEqual(Path(result).name, "test_bundle")
        mods = self.game / "mods"
        self.assertTrue((mods / "test_racer" / "character.ini").is_file())
        self.assertTrue((mods / "test_kart" / "kart.ini").is_file())
        self.assertTrue((mods / "test_bundle" / "contents.json").is_file())
        self.assertFalse((mods / "test_bundle" / "racers").exists())

    def test_manager_can_toggle_all_components_from_pack_inventory(self):
        import forge_mod_manager as manager
        data = zip_bytes(FILES)
        url = "https://example.com/files/sample_pack.zip"
        mod = {"type": "Modpack", "id": "sample_pack", "download_url": url,
               "sha256": hashlib.sha256(data).hexdigest()}
        with patch.object(services.urllib.request, "urlopen", return_value=Stream(data, url)):
            services.download_install_mod(mod, str(self.game))
        manager.set_enabled(self.game, "Modpack", "sample_pack", False)
        for slug, ini in [("test_racer", "character.ini"), ("test_kart", "kart.ini")]:
            text = (self.game/"mods"/slug/ini).read_text()
            self.assertIn("enabled = false", text)
        manager.set_enabled(self.game, "Modpack", "sample_pack", True)
        self.assertTrue(manager.read_mod(self.game, "Modpack", "sample_pack")["enabled"])

    def test_reject_duplicate_web_ids_across_categories(self):
        (self.staging/"karts"/"test_kart").rename(self.staging/"karts"/"test_racer")
        with self.assertRaisesRegex(packs.ModpackError, "must be unique"):
            packs.inspect_modpack(self.staging)

    def test_reject_pack_id_equal_to_component_id(self):
        with self.assertRaisesRegex(packs.ModpackError, "cannot reuse"):
            packs.install_prepared_modpack(self.staging, self.game, "test_kart")

    def test_existing_different_kind_remains_untouched_and_new_mod_gets_suffix(self):
        conflict=self.game/"mods"/"test_racer"
        conflict.mkdir(parents=True)
        (conflict/"kart.ini").write_text("[kart]\nname=Do not clobber\n")
        packs.install_prepared_modpack(self.staging, self.game, "sample_pack")
        self.assertEqual((conflict/"kart.ini").read_text(),
                         "[kart]\nname=Do not clobber\n")
        self.assertTrue((self.game/"mods"/"test_racer_2"/"character.ini").is_file())

    def test_reject_missing_individual_ini(self):
        (self.staging / "karts" / "test_kart" / "kart.ini").unlink()
        with self.assertRaisesRegex(packs.ModpackError, "kart.ini"):
            packs.inspect_modpack(self.staging)

    def test_reject_incorrect_declared_id(self):
        ini = self.staging / "racers" / "test_racer" / "character.ini"
        ini.write_text("[character]\nname=Test Racer\nid=other_id\n", encoding="utf-8")
        with self.assertRaisesRegex(packs.ModpackError, "match its folder"):
            packs.inspect_modpack(self.staging)

    def test_reject_single_mod(self):
        import shutil
        shutil.rmtree(self.staging / "karts")
        with self.assertRaisesRegex(packs.ModpackError, "2 to 60"):
            packs.inspect_modpack(self.staging)

    def test_reinstall_preserves_previous_components_as_backups(self):
        existing = self.game / "mods" / "test_racer"
        existing.mkdir(parents=True)
        (existing / "character.ini").write_text(
            "[character]\nname = Test Racer\nenabled = true\n"
            "[forge_mod]\nid = test_racer\ntype = Character\n"
            "note = ORIGINAL USER MOD\n", encoding="utf-8")
        packs.install_prepared_modpack(self.staging, self.game, "sample_pack")
        backups = list((self.game / ".forge_mod_backups").rglob("character.ini"))
        self.assertEqual(len(backups), 1)
        self.assertIn("ORIGINAL USER MOD", backups[0].read_text())

    def test_rollback_restores_existing_mod_if_later_component_fails(self):
        existing = self.game / "mods" / "test_kart"
        existing.mkdir(parents=True)
        (existing / "kart.ini").write_text("USER ORIGINAL", encoding="utf-8")
        original = packs.os.replace
        triggered = [False]

        def fail_once(src, dst):
            if (not triggered[0] and Path(src).parent.name == "racers" and
                    Path(dst).parent.name == "mods"):
                triggered[0] = True
                raise OSError("simulated install failure")
            return original(src, dst)

        with patch.object(packs.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "simulated"):
                packs.install_prepared_modpack(self.staging, self.game, "sample_pack")
        self.assertTrue(triggered[0])
        self.assertEqual((existing / "kart.ini").read_text(), "USER ORIGINAL")
        self.assertFalse((self.game / "mods" / "test_bundle").exists())

    def test_download_verify_sha_and_install_bundle(self):
        data = zip_bytes(FILES)
        sha = hashlib.sha256(data).hexdigest()
        url = "https://example.com/files/sample_pack.zip"
        mod = {"type": "Modpack", "id": "sample_pack", "download_url": url, "sha256": sha}
        with patch.object(services.urllib.request, "urlopen", return_value=Stream(data, url)):
            target = services.download_install_mod(mod, str(self.game))
        self.assertTrue(Path(target).is_dir())
        self.assertTrue((self.game / "mods/test_kart/kart.ini").exists())
        self.assertTrue((self.game / "mods/test_racer/character.ini").exists())

    def test_reject_bad_sha_without_writing_mods(self):
        data = zip_bytes(FILES)
        url = "https://example.com/files/sample_pack.zip"
        mod = {"type": "Modpack", "id": "sample_pack", "download_url": url,
               "sha256": "0" * 64}
        with patch.object(services.urllib.request, "urlopen", return_value=Stream(data, url)):
            with self.assertRaisesRegex(services.FeedError, "SHA-256 mismatch"):
                services.download_install_mod(mod, str(self.game))
        self.assertFalse((self.game / "mods/test_bundle").exists())

    def test_reject_zip_traversal(self):
        data = zip_bytes({**FILES, "../evil.ini": "[evil]"})
        url = "https://example.com/files/sample_pack.zip"
        mod = {"type": "Modpack", "id": "sample_pack", "download_url": url,
               "sha256": hashlib.sha256(data).hexdigest()}
        with patch.object(services.urllib.request, "urlopen", return_value=Stream(data, url)):
            with self.assertRaises(services.FeedError):
                services.download_install_mod(mod, str(self.game))
        self.assertFalse((self.root / "evil.ini").exists())


if __name__ == "__main__":
    unittest.main()
