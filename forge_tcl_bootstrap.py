"""Configure Tcl/Tk in the frozen Windows launcher before Tk starts.

PyInstaller's optional runtime hook normally handles this, but the launcher
may be run under OneDrive or with system Tcl/Tk variables from unrelated apps.
Always use our *bundled* Tcl scripts, never an installed Python distribution.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


def bundled_tcl_paths(base=None, frozen=None):
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return None
    if base is None:
        base = Path(getattr(sys, "_MEIPASS", "") or
                    Path(sys.executable).parent / "_internal")
    base = Path(base).resolve()
    candidates = [
        (base / "_tcl_data", base / "_tk_data"),
        (base / "tcl8.6", base / "tk8.6"),
    ]
    for tcl, tk in candidates:
        if (tcl.joinpath("init.tcl").is_file()
                and tk.joinpath("tk.tcl").is_file()):
            return tcl, tk
    return None


def prepare_frozen_tcl(base=None, frozen=None):
    """Select and hydrate included Tcl/Tk scripts before creating tkinter.Tk.

    Do not use this during development/source operation; normal system Tk
    works there. Only bundled scripts are trusted in frozen Windows builds.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return None
    found = bundled_tcl_paths(base=base, frozen=True)
    if found is None:
        raise RuntimeError(
            "Crash Forge Launcher portable files are incomplete: "
            "_internal/_tcl_data/init.tcl or _internal/_tk_data/tk.tcl "
            "is missing. Extract the complete official ZIP, preserving "
            "the _internal folder. Python installation is NOT required."
        )
    tcl, tk = found
    # A synced file may appear in a directory listing before being locally
    # available. Opening it now forces OneDrive files-on-demand hydration or
    # produces a clear error instead of Tk's unhelpful search-path traceback.
    for path in (tcl / "init.tcl", tk / "tk.tcl"):
        try:
            with path.open("rb") as f:
                if not f.read(64).startswith(b"#"):
                    raise OSError("Invalid bundled script content")
        except OSError as exc:
            raise RuntimeError(
                f"Crash Forge cannot read the bundled Tcl/Tk script "
                f"'{path}'. Keep _internal fully extracted and available "
                f"offline; Python does NOT need to be installed."
            ) from exc

    os.environ["TCL_LIBRARY"] = str(tcl)
    os.environ["TK_LIBRARY"] = str(tk)
    return str(tcl), str(tk)