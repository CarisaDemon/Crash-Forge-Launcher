"""Hidden Tk test: .bat source transitions to portable EXE without touching desktop.

Never starts the game or current launcher. An updater process is mocked.
"""
import sys
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
import launcher
from forge_launcher_updates import portable_target_for_source

real_tk_init = tk.Tk.__init__


def withdrawn(self, *args, **kwargs):
    real_tk_init(self, *args, **kwargs)
    self.withdraw()


def main():
    tk.Tk.__init__ = withdrawn
    app = None
    try:
        app = launcher.Launcher()
        assert app.state() == "withdrawn"
        restart_buttons = getattr(app, "_launcher_restart_buttons", [])
        assert restart_buttons, "Settings is missing RESTART & UPDATE TO EXE"
        assert all(button.cget("state") == "disabled" for button in restart_buttons)
        app.launcher_update_ready = {"version": "0.3.29"}
        app.launcher_auto_update = True
        app._set_restart_buttons_enabled(True)
        assert all(button.cget("state") == "normal" for button in restart_buttons)
        print("PASS: Restart & Update to EXE button only enabled after verified staging")
        with patch.object(launcher.launcher_updates, "is_portable_build", return_value=False), \
             patch.object(launcher.launcher_updates, "launch_update_after_exit",
                          return_value=True) as launch:
            app._restart_into_updated_launcher()
            assert launch.call_count == 1, "Source migration helper not requested"
            args, kwargs = launch.call_args
            assert kwargs.get("source_migration") is True
            assert Path(kwargs["source_dir"]).resolve() == SOURCE
            assert Path(args[0]) == portable_target_for_source(SOURCE)
            print("PASS: closing old .bat dispatches a separate portable updater")
        app = None
    finally:
        if app is not None:
            app.destroy()
        tk.Tk.__init__ = real_tk_init
    print("ALL HIDDEN .BAT->EXE TRANSITION TESTS PASS")


if __name__ == "__main__":
    main()
