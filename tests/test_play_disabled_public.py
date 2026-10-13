"""Public UI regression: no-mods explicitly unavailable until native game release."""
import tkinter as tk
from types import MethodType
from unittest import TestCase, mock
import forge_live_ui as live
from test_play_clean_mode_qa import FakeLauncher

class PlayUnavailableTests(TestCase):
    def test_direct_clean_never_calls_subprocess_or_disk_and_warns_quietly(self):
        app=FakeLauncher()
        with mock.patch.object(live,"CLEAN_PLAY_PUBLIC_ENABLED",False), \
             mock.patch.object(live.subprocess,"Popen",
                               side_effect=AssertionError("Game must not start")), \
             mock.patch.object(live.subprocess,"run",
                               side_effect=AssertionError("No capability subprocess")), \
             mock.patch.object(live.game_launch,"launch_issue",
                               side_effect=AssertionError("No disk checks")), \
             mock.patch.object(live.messagebox,"showinfo",
                               side_effect=AssertionError("No popups")):
            app._play_installed_game("clean")
        app.status_label.configure.assert_called_once_with(
            text=live.CLEAN_PLAY_DEVELOPMENT_MESSAGE)

    def test_saved_clean_mode_opens_selector_not_silent_noop(self):
        app=FakeLauncher()
        app.remember_play_choice=True
        app.preferred_play_mode="clean"
        with mock.patch.object(live,"CLEAN_PLAY_PUBLIC_ENABLED",False), \
             mock.patch.object(live.services,"real_game_status",return_value={"installed":True}), \
             mock.patch.object(app,"_play_installed_game") as play:
            app._primary_game_action()
        play.assert_not_called()
        self.assertEqual(app.scheduled,[("chooser",None)])
        app.status_label.configure.assert_any_call(text=live.CLEAN_PLAY_DEVELOPMENT_MESSAGE)

    def test_selector_renders_grey_disabled_card_without_click_bind(self):
        root=tk.Tk()
        root.attributes("-alpha",0.0)
        root.game_install_path="C:\\Game Test"
        root.status_label=mock.Mock()
        root._save_launcher_settings=mock.Mock(return_value=True)
        root.remember_play_choice=False
        try:
            with mock.patch.object(live,"CLEAN_PLAY_PUBLIC_ENABLED",False):
                root._show_play_mode_selector=MethodType(
                    live.ForgeLiveMixin._show_play_mode_selector,root)
                root._show_play_mode_selector()
                root.update()
            win=root._play_mode_window
            self.assertTrue(win.winfo_exists())
            labels={}
            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child,tk.Label):
                        labels[child.cget("text")]=child
                    walk(child)
            walk(win)
            self.assertIn("PLAY WITHOUT MODS",labels)
            self.assertIn("IN DEVELOPMENT - We're working on it.",labels)
            self.assertEqual(labels["PLAY WITHOUT MODS"].cget("cursor"),"arrow")
            self.assertEqual(labels["PLAY WITHOUT MODS"].bind("<Button-1>"),"")
            self.assertEqual(labels["PLAY WITHOUT MODS"].master.bind("<Button-1>"),"")
            self.assertNotEqual(labels["PLAY WITH MODS"].bind("<Button-1>"),"")
            self.assertNotEqual(labels["DEBUG MODE"].bind("<Button-1>"),"")
            win.destroy()
        finally:
            root.destroy()
