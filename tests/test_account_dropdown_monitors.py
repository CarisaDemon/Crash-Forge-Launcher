"""Multi-monitor placement for the floating Forge account menu."""
import os
import unittest
from types import SimpleNamespace

import forge_account_badge as badge


class AccountPopupPlacementTests(unittest.TestCase):
    def test_primary_and_right_monitor_placement(self):
        layout = badge.header_layout(1050)
        work_primary = (0, 0, 1920, 1032)
        work_right = (1920, 0, 3840, 1032)
        x1, y1 = badge.account_popup_position(100, 130, layout, 194, 124,
                                               work_primary)
        x2, y2 = badge.account_popup_position(2120, 130, layout, 194, 124,
                                               work_right)
        self.assertEqual(x2 - x1, 2020)
        self.assertEqual(y1, y2)
        self.assertGreaterEqual(x2, 1920)
        self.assertLessEqual(x2 + 194, 3840)

    def test_negative_origin_monitor_placement(self):
        # Common vertical/side arrangement: second monitor LEFT of primary.
        work_left = (-1920, -250, 0, 830)
        layout = badge.header_layout(1024)
        x, y = badge.account_popup_position(-1720, -140, layout, 194, 134,
                                            work_left)
        self.assertTrue(-1920 <= x and x + 194 <= 0, (x, y))
        self.assertTrue(-250 <= y and y + 134 <= 830, (x, y))

    def test_edge_falls_back_above_avatar(self):
        layout = badge.header_layout(1024)
        work = (1920, 0, 3840, 720)
        x, y = badge.account_popup_position(2340, 665, layout, 194, 190, work)
        self.assertGreaterEqual(x, 1920)
        self.assertLess(y + 190, 720)
        self.assertLess(y, 665)  # Opens upwards when insufficient bottom room.

    @unittest.skipUnless(os.name == "nt", "Windows API monitor selection")
    def test_windows_api_chooses_second_monitor(self):
        first = badge.monitor_work_area_at(250, 150)
        second = badge.monitor_work_area_at(2350, 150)
        if first == second:
            self.skipTest("The machine has only one display / different arrangement")
        self.assertLessEqual(first[0], 250)
        self.assertGreaterEqual(first[2], 250)
        self.assertLessEqual(second[0], 2350)
        self.assertGreaterEqual(second[2], 2350)
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(second[0], first[2])

    @unittest.skipUnless(os.name == "nt", "Windows/Tk multi-monitor widget test")
    def test_real_launcher_dropdown_follows_second_monitor(self):
        first = badge.monitor_work_area_at(250, 150)
        second = badge.monitor_work_area_at(2350, 150)
        if first == second:
            self.skipTest("No right-side secondary monitor")
        os.environ["CFR_SCREENSHOT_PREVIEW"] = "1"
        from launcher import Launcher
        from forge_account_client import AccountClient
        app = Launcher()
        app.account_client = AccountClient(persist=False)
        try:
            base_x = second[0] + 100
            base_y = second[1] + 120
            app.geometry(f"960x700{base_x:+d}{base_y:+d}")
            app.update_idletasks()
            app.update()
            event = SimpleNamespace(x_root=base_x+730, y_root=base_y+35)
            app._account_badge_menu(event)
            app.update()
            popup = app._account_popup
            self.assertIsNotNone(popup)
            self.assertTrue(popup.winfo_exists())
            actual_x,actual_y = popup.winfo_rootx(), popup.winfo_rooty()
            exp_x, exp_y = app._account_badge_popup_xy(
                popup.winfo_width(),popup.winfo_height())
            self.assertLessEqual(abs(actual_x-exp_x), 3,
                                 (actual_x, exp_x, app.winfo_rootx()))
            self.assertLessEqual(abs(actual_y-exp_y), 3,
                                 (actual_y, exp_y))
            self.assertGreaterEqual(actual_x, second[0])
            self.assertLess(actual_x, second[2])
            self.assertIsNone(app.grab_current())

            # Moving the launcher across the same monitor must move dropdown.
            app.geometry(f"960x700{base_x+160:+d}{base_y+75:+d}")
            app.update()
            popup = app._account_popup
            if popup is not None:
                self.assertTrue(popup.winfo_exists())
                self.assertLessEqual(abs(popup.winfo_rootx() -
                                         (actual_x+160)), 3)
                self.assertLessEqual(abs(popup.winfo_rooty() -
                                         (actual_y+75)), 3)
            # Clicking avatar after moving monitors must open on new screen.
            app._close_account_badge_menu()
            app.geometry("960x700+95+120")
            app.update()
            app._account_badge_menu(event)
            app.update()
            popup = app._account_popup
            self.assertTrue(popup.winfo_exists())
            self.assertTrue(first[0] <= popup.winfo_rootx() < first[2])
            self.assertIsNone(app.grab_current())
        finally:
            app._close_account_badge_menu()
            app.destroy()


if __name__ == "__main__":
    unittest.main()