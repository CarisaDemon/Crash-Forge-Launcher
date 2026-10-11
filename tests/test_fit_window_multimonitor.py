"""Regression: FIT TO WINDOW must preserve the current physical monitor.

This reproduces the Windows 11 taskbar-wrapper HWND bug that previously
maximized a second-monitor window to +0+0 on the primary monitor.
"""
from __future__ import annotations

import os
import unittest


class FitWindowMonitorTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows monitor work area test")
    def test_fit_to_window_follows_secondary_monitor_then_restores(self):
        import forge_account_badge as badge
        os.environ["CFR_SCREENSHOT_PREVIEW"] = "1"
        from launcher import Launcher

        primary = badge.monitor_work_area_at(200, 160)
        secondary = badge.monitor_work_area_at(2250, 160)
        if primary == secondary:
            self.skipTest("Right-side secondary display is not connected")

        left, top, right, bottom = secondary
        root_x = left + 170
        root_y = top + 120
        app = Launcher()
        try:
            app.geometry(f"1040x700{root_x:+d}{root_y:+d}")
            app.update_idletasks()
            app.update()
            self.assertEqual(
                app._current_monitor_workarea(),
                (left, top, right - left, bottom - top),
            )
            old = app.geometry()
            app._toggle_maximize()
            app.update_idletasks()
            app.update()
            self.assertEqual(app.winfo_rootx(), left)
            self.assertEqual(app.winfo_rooty(), top)
            self.assertEqual(app.winfo_width(), right - left)
            self.assertEqual(app.winfo_height(), bottom - top)
            self.assertTrue(app._is_maximized)
            self.assertIsNone(app.grab_current())
            app._toggle_maximize()
            app.update_idletasks()
            app.update()
            self.assertEqual(app.geometry(), old)
            self.assertFalse(app._is_maximized)

            # Same app can fit to the primary screen after being moved.
            x, y = primary[:2]
            app.geometry(f"1040x700{x+85:+d}{y+110:+d}")
            app.update_idletasks()
            app.update()
            app._toggle_maximize()
            app.update_idletasks()
            app.update()
            self.assertEqual(app.winfo_rootx(), primary[0])
            self.assertEqual(app.winfo_rooty(), primary[1])
            self.assertEqual(app.winfo_width(), primary[2] - primary[0])
            self.assertEqual(app.winfo_height(), primary[3] - primary[1])
        finally:
            app.destroy()

    @unittest.skipUnless(os.name == "nt", "Windows monitor work area test")
    def test_workarea_lookup_survives_absent_native_hwnd(self):
        import forge_account_badge as badge
        os.environ["CFR_SCREENSHOT_PREVIEW"] = "1"
        from launcher import Launcher
        app = Launcher()
        try:
            app.geometry("1040x700+2250+130")
            app.update_idletasks()
            app.update()
            expected = badge.monitor_work_area_at(2300, 220)
            old = app._get_native_hwnd
            app._get_native_hwnd = lambda: None
            try:
                self.assertEqual(
                    app._current_monitor_workarea(),
                    (expected[0], expected[1],
                     expected[2] - expected[0],
                     expected[3] - expected[1]),
                )
            finally:
                app._get_native_hwnd = old
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()