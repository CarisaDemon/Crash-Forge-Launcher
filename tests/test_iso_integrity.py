"""CTR-U original PS1 disc verification: strictly report-only, never DRM.

All test BIN files are tiny synthetic byte streams, not game assets.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1] if (HERE.parents[1] / "forge_iso_integrity.py").is_file() else HERE.parents[2]
sys.path.insert(0, str(ROOT))
import forge_iso_integrity as iso


def synthetic_bin(length_sectors=3):
    payload = bytearray(length_sectors * iso.RAW_SECTOR_BYTES)
    payload[0:12] = iso.HEADER_SYNC
    payload[15] = 2
    marker = b"TEST_SONY_SCUS_94426_RAW"
    payload[102:102 + len(marker)] = marker
    return bytes(payload)


class TestIntegrity(unittest.TestCase):
    def test_reference_is_published_ntsc_u_retail(self):
        self.assertEqual(iso.REFERENCE_SHA1,
                         "1bb785082def3fe25f6b46be06d4eaf33c5bc772")
        self.assertEqual(iso.REFERENCE_BYTES, 605_698_800)
        self.assertEqual(iso.PROTOCOL, "cfr.iso-attestation/1")

    def test_valid_raw_disc_and_unchanged_user_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"assets").mkdir()
            data = synthetic_bin()
            path = root/"assets"/"ctr-u.bin"
            path.write_bytes(data)
            before = path.read_bytes()
            report = iso.verify_ctr_u(
                root, "test_good",
                reference_sha1=hashlib.sha1(data).hexdigest(),
                reference_bytes=len(data)
            )
            self.assertEqual(report["status"], "verified")
            self.assertEqual(report["disc_path"], "assets/ctr-u.bin")
            self.assertEqual(report["reason"], "RETAIL_USA_MATCH")
            self.assertTrue(report["raw_mode2_2352"])
            self.assertEqual(report["disc_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(report["allow_play"])
            self.assertFalse(report["online_verified"])
            self.assertEqual(report["transport"], "none")
            self.assertEqual(report["policy"], "report_only")

    def test_content_modified_same_size_has_error_without_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"assets").mkdir()
            original = synthetic_bin()
            changed = bytearray(original)
            changed[2500] ^= 0x1
            (root/"assets"/"ctr-u.bin").write_bytes(changed)
            report = iso.verify_ctr_u(
                root,
                reference_sha1=hashlib.sha1(original).hexdigest(),
                reference_bytes=len(original))
            self.assertEqual(report["status"], "modified")
            self.assertEqual(report["reason"], "SHA1_MISMATCH")
            self.assertTrue(report["allow_play"])
            self.assertIn("ERROR:", iso._console_line(report))
            self.assertIn("GAME_ALLOWED", iso._console_line(report))

    def test_size_mismatch_and_invalid_cooked_iso(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = synthetic_bin()
            (root/"ctr-u.bin").write_bytes(original + bytes(iso.RAW_SECTOR_BYTES))
            report = iso.verify_ctr_u(root,
                     reference_sha1=hashlib.sha1(original).hexdigest(),
                     reference_bytes=len(original))
            self.assertEqual(report["reason"], "SIZE_MISMATCH")
            (root/"ctr-u.bin").unlink()
            (root/"ctr-u.iso").write_bytes(bytes(2048 * 3))
            report = iso.verify_ctr_u(root)
            self.assertEqual(report["status"], "modified")
            self.assertEqual(report["reason"], "INVALID_RAW_MODE2_2352")

    def test_disc_lookup_prioritizes_assets_before_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = synthetic_bin()
            (root/"ctr-u.bin").write_bytes(b"not-disc-image")
            (root/"assets").mkdir()
            image = root/"assets"/"ctr-u.bin"
            image.write_bytes(data)
            self.assertEqual(iso.locate_ctr_u(root), image)
            report = iso.verify_ctr_u(
                root, reference_sha1=hashlib.sha1(data).hexdigest(),
                reference_bytes=len(data))
            self.assertEqual(report["status"], "verified")

    def test_missing_disc_does_not_stop_game(self):
        with tempfile.TemporaryDirectory() as temp:
            report = iso.verify_ctr_u(temp, "launch")
            self.assertEqual(report["status"], "missing")
            self.assertEqual(report["reason"], "DISC_NOT_FOUND")
            self.assertTrue(report["allow_play"])
            self.assertIn("ERROR:", iso._console_line(report))

    def test_console_and_jsonl_only_no_popups_or_network(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/"logs"
            example = iso.verify_ctr_u(temp)
            out = io.StringIO()
            with mock.patch.object(iso.sys, "stderr", out):
                iso.record_result(example, folder=folder)
            self.assertIn("[CFR ISO] ERROR:", out.getvalue())
            self.assertIn("GAME_ALLOWED", (folder/iso.LOG_NAME).read_text())
            data = [json.loads(s) for s in (folder/iso.JSONL_NAME).read_text().splitlines()]
            self.assertEqual(data[0]["protocol"], iso.PROTOCOL)
            self.assertFalse(data[0]["online_verified"])
            self.assertTrue(data[0]["allow_play"])
            self.assertEqual(data[0]["transport"], "none")

    def test_background_scan_is_nonblocking_and_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"assets").mkdir()
            bin = root/"assets"/"ctr-u.bin"
            bin.write_bytes(synthetic_bin())
            folder = root/"logs"
            self.assertTrue(iso.start_background_check(root, "startup", folder=folder))
            deadline = time.monotonic() + 4
            while not (folder/iso.JSONL_NAME).is_file() and time.monotonic() < deadline:
                time.sleep(0.012)
            self.assertTrue((folder/iso.JSONL_NAME).exists())
            while os.path.normcase(str(root.resolve())) in iso._active_paths and time.monotonic() < deadline:
                time.sleep(0.012)
            self.assertFalse(iso.start_background_check(root, "play", folder=folder))
            self.assertEqual(len((folder/iso.JSONL_NAME).read_text().splitlines()), 1)
            bin.write_bytes(synthetic_bin() + bytes(iso.RAW_SECTOR_BYTES))
            self.assertTrue(iso.start_background_check(root, "play", folder=folder))
            while (len((folder/iso.JSONL_NAME).read_text().splitlines()) < 2
                   and time.monotonic() < deadline):
                time.sleep(0.012)
            self.assertEqual(len((folder/iso.JSONL_NAME).read_text().splitlines()), 2)

    def test_play_never_blocks_for_iso_verifier_failure(self):
        from types import SimpleNamespace
        from forge_live_ui import ForgeLiveMixin
        import forge_live_ui as live
        label = mock.Mock()
        example = SimpleNamespace(
            game_install_path="C:/a-fake-game",
            game_update_busy=False,
            latest_game_release=None,
            status_label=label,
            _refresh_real_install_ui=mock.Mock(),
            after=mock.Mock(),
        )
        with mock.patch.object(live.services, "real_game_status", return_value={
            "installed": True, "exe_path": "C:/a-fake-game/ctr-native.exe"
        }), mock.patch.object(live.game_launch,"launch_issue",return_value=""), mock.patch.object(
            live, "available_game_update", return_value=None,
            create=True), mock.patch.object(
            live.iso_integrity, "start_background_check",
            side_effect=RuntimeError("ISO checker unavailable")
        ), mock.patch.object(live.subprocess, "Popen") as game_spawn:
            ForgeLiveMixin._play_installed_game(example)
            game_spawn.assert_called_once()
            args, kwargs = game_spawn.call_args
            self.assertEqual(args[0], ["C:/a-fake-game/ctr-native.exe"])
            self.assertEqual(kwargs["cwd"], "C:/a-fake-game")
            self.assertEqual(kwargs["creationflags"],
                             live.subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.assertEqual(kwargs["stdout"], live.subprocess.DEVNULL)
        label.configure.assert_called_with(text="Starting Crash Forge: Racing...")

    def test_read_error_is_report_only(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path/"ctr-u.bin").write_bytes(synthetic_bin())
            with mock.patch.object(Path, "open", side_effect=OSError("locked")):
                report = iso.verify_ctr_u(path)
            self.assertEqual(report["reason"], "DISC_READ_ERROR")
            self.assertEqual(report["status"], "error")
            self.assertTrue(report["allow_play"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
