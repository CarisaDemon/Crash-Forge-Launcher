from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'companion_tools'/'model_importer'))
"""Native LEV/VRM-only track packager tests - never modify the real game."""
from pathlib import Path
import hashlib
import struct
import tempfile
import unittest

from crash_forge_native_tracks import (
    NativeTrackError, inspect_native_track, install_native_track, slugify
)


class NativeTrackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / "input"
        self.input.mkdir()
        self.lev = self.input / "data.lev"
        self.vrm = self.input / "data.vrm"
        self.lev.write_bytes(struct.pack("<i", 4000) + bytes(range(256)) * 64)
        self.vrm.write_bytes(struct.pack("<I", 0x20) + bytes(range(256)) * 9)
        self.game = self.root / "fake_game"
        self.game.mkdir()
        (self.game / "ctr-native.exe").write_bytes(b"EXE TEST SENTINEL")

    def build(self, **overrides):
        opts = dict(
            lev_path=self.lev, vrm_path=self.vrm, game_path=self.game,
            track_name="My Test Track", track_slug="my_test_track",
            description="Native pair", author="Tester")
        opts.update(overrides)
        return install_native_track(**opts)

    def test_native_only_installed_separately(self):
        result = self.build()
        target = Path(result["target"])
        self.assertEqual(sorted(p.name for p in target.iterdir()),
                         ["data.lev", "data.vrm", "track.ini"])
        self.assertEqual((target / "data.lev").read_bytes(), self.lev.read_bytes())
        self.assertEqual((target / "data.vrm").read_bytes(), self.vrm.read_bytes())
        ini = (target / "track.ini").read_text()
        self.assertIn("format = native_lev_vrm", ini)
        self.assertIn("replace_original = false", ini)
        self.assertIn("level_override = none", ini)
        self.assertFalse((self.game / "assets" / "mods" / "tracks" / "assembly_lane").exists())

    def test_dry_run_doesnt_touch_directory(self):
        p = self.game / "assets" / "mods"
        self.build(dry_run=True)
        self.assertFalse(p.exists())

    def test_reject_obj_replacement_and_any_wrong_suffix(self):
        other = self.input / "bad.obj"
        other.write_bytes(self.lev.read_bytes())
        with self.assertRaisesRegex(NativeTrackError, "Only"):
            self.build(lev_path=other)
        self.assertFalse((self.game / "assets" / "mods").exists())

    def test_reject_path_traversal_in_slug(self):
        with self.assertRaises(NativeTrackError):
            self.build(track_slug="../crash_cove")
        with self.assertRaises(NativeTrackError):
            self.build(track_slug="crash cove")

    def test_reject_invalid_lev_header(self):
        self.lev.write_bytes(struct.pack("<I", 999999999) + b"a" * 10000)
        with self.assertRaisesRegex(NativeTrackError, "pointer-map"):
            self.build()

    def test_reinstall_keeps_old_package_backup(self):
        first = self.build()
        target = Path(first["target"])
        (target / "note.txt").write_text("OLD USER PACKAGE")
        new = self.build()
        backup = Path(new["backup"])
        self.assertTrue((backup / "note.txt").is_file())
        self.assertEqual((backup / "note.txt").read_text(), "OLD USER PACKAGE")
        self.assertFalse((target / "note.txt").exists())

    def test_hashes_recorded(self):
        target = Path(self.build()["target"])
        ini = (target / "track.ini").read_text()
        self.assertIn(hashlib.sha256(self.lev.read_bytes()).hexdigest(), ini)
        self.assertIn(hashlib.sha256(self.vrm.read_bytes()).hexdigest(), ini)

    def test_slug_normalization(self):
        self.assertEqual(slugify("N. Sanity Coast"), "n_sanity_coast")
        self.assertEqual(slugify("  Crash Test #2  "), "crash_test_2")


if __name__ == "__main__":
    unittest.main()
