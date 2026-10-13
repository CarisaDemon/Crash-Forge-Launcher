import sys
import tkinter as tk
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from forge_profiles_ui import show

class ProfilesUiSmoke(TestCase):
    def test_window_opens_in_hidden_tk_root(self):
        root=tk.Tk()
        root.withdraw()
        try:
            root.game_install_path=str(Path(__file__).resolve().parents[1])
            root.account_client=Mock(signed_in=False)
            root._render_hub_cards=lambda:None
            show(root)
            root.update_idletasks()
            win=root._forge_profiles_window
            self.assertTrue(win.winfo_exists())
            labels=[]
            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child,tk.Button):
                        labels.append(child.cget("text"))
                    walk(child)
            walk(win)
            self.assertTrue({"SAVE CURRENT","APPLY","DELETE LOCAL",
                             "UPLOAD","FETCH CLOUD","DOWNLOAD"}.issubset(set(labels)))
            win.destroy()
        finally:
            root.destroy()
