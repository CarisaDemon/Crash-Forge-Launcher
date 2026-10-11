"""Frozen Tcl/Tk initialization must work independently of system Python."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import forge_tcl_bootstrap as bootstrap


class PortableTclTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "_tcl_data"
        self.tk = self.root / "_tk_data"
        self.data.mkdir()
        self.tk.mkdir()
        (self.data / "init.tcl").write_bytes(b"# Tcl packaged 8.6\n")
        (self.tk / "tk.tcl").write_bytes(b"# Tk packaged 8.6\n")

    def test_source_does_not_modify_system_tcl(self):
        with patch.dict(os.environ, {"TCL_LIBRARY": "leave-unchanged"}, clear=False):
            self.assertIsNone(bootstrap.prepare_frozen_tcl(self.root, frozen=False))
            self.assertEqual(os.environ["TCL_LIBRARY"], "leave-unchanged")

    def test_frozen_forces_bundled_tcl_over_system_and_sets_tk(self):
        with patch.dict(os.environ, {"TCL_LIBRARY": r"C:\Invalid System Tcl",
                                     "TK_LIBRARY": r"C:\Invalid System Tk"}):
            result = bootstrap.prepare_frozen_tcl(self.root, frozen=True)
            self.assertEqual(result, (str(self.data.resolve()), str(self.tk.resolve())))
            self.assertEqual(os.environ["TCL_LIBRARY"], str(self.data.resolve()))
            self.assertEqual(os.environ["TK_LIBRARY"], str(self.tk.resolve()))

    def test_missing_scripts_have_actionable_extraction_message(self):
        (self.data / "init.tcl").unlink()
        with self.assertRaisesRegex(RuntimeError, "_internal"):
            bootstrap.prepare_frozen_tcl(self.root, frozen=True)

    def test_corrupt_script_rejected_before_tk_root_creation(self):
        (self.data / "init.tcl").write_bytes(b"corrupted")
        with self.assertRaisesRegex(RuntimeError, "available offline"):
            bootstrap.prepare_frozen_tcl(self.root, frozen=True)

    def test_legacy_tcl_directory_names_supported(self):
        other = self.root / "tcl8.6"
        other_tk = self.root / "tk8.6"
        other.mkdir()
        other_tk.mkdir()
        (other / "init.tcl").write_bytes(b"# older layout\n")
        (other_tk / "tk.tcl").write_bytes(b"# older layout\n")
        (self.data / "init.tcl").unlink()
        (self.tk / "tk.tcl").unlink()
        self.assertEqual(bootstrap.bundled_tcl_paths(self.root, frozen=True),
                         (other.resolve(), other_tk.resolve()))


if __name__ == "__main__":
    unittest.main()