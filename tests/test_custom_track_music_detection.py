"""Dynamic custom track music discovery and local package assignment tests."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CSEQ = ROOT / "companion_tools" / "cseq_toolkit"
sys.path.insert(0, str(CSEQ))
import track_discovery as finder


def create_track(game: Path, mod_id: str, name: str, *,
                 legacy: bool = False, enabled: bool = True) -> Path:
    base = game / "mods"
    if legacy:
        base = game / "assets" / "mods" / "tracks"
    mod = base / mod_id
    mod.mkdir(parents=True)
    (mod / "data.lev").write_bytes(b"lev")
    (mod / "data.vrm").write_bytes(b"vrm")
    meta = "" if legacy else f"[forge_mod]\nid = {mod_id}\ntype = Track\n"
    (mod / "track.ini").write_text(
        f"[track]\nname = {name}\nenabled = {'true' if enabled else 'false'}\n"
        "format = native_lev_vrm\nlev = data.lev\nvrm = data.vrm\n\n" + meta,
        encoding="utf-8",
    )
    return mod


class TrackMusicTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="Forge mods ")
        self.addCleanup(self.folder.cleanup)
        self.game = Path(self.folder.name) / "Game with spaces"
        self.game.mkdir()
        (self.game / "ctr-native.exe").write_bytes(b"game")

    def test_installed_modules_update_without_editor_rebuild(self):
        self.assertEqual(finder.discover_custom_tracks(self.game), [])
        create_track(self.game, "forge-5e3780a9cd", "Future Circuit")
        self.assertEqual(
            [(t.slug, t.name) for t in finder.discover_custom_tracks(self.game)],
            [("forge-5e3780a9cd", "Future Circuit")])
        create_track(self.game, "second_custom_track", "Second Circuit", legacy=True)
        create_track(self.game, "disabled_track", "Disabled", enabled=False)
        self.assertEqual(
            {t.slug for t in finder.discover_custom_tracks(self.game)},
            {"forge-5e3780a9cd", "second_custom_track"})

    def test_mod_music_writes_inside_mod_only(self):
        folder = create_track(self.game, "forge-b29", "Brand New")
        target = finder.discover_custom_tracks(self.game)[0]
        original = (folder / "track.ini").read_text(encoding="utf-8")
        with mock.patch("cseq_format.parse_pack", return_value={}):
            result = finder.install_cseq_on_custom_track(target, b"mock CSEQ")
        self.assertEqual(result.resolve(), (folder / "track.cseq").resolve())
        self.assertEqual(result.read_bytes(), b"mock CSEQ")
        ini = (folder / "track.ini").read_text()
        self.assertIn("[music]", ini)
        self.assertIn("source = cseq", ini)
        self.assertIn("file = track.cseq", ini)
        self.assertTrue(all(line in ini for line in original.strip().splitlines()))
        self.assertFalse((self.game / "assets" / "MUSIC_CUSTOM").exists())


if __name__ == "__main__":
    unittest.main()
