"""Real Tk UI test: DELETE label follows selected LOCAL or CLOUD profile."""
import sys, time
import tkinter as tk
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import forge_profiles
import forge_profiles_ui

class DynamicDeleteTests(TestCase):
    def test_delete_switches_and_cloud_only_deletes_remote(self):
        with TemporaryDirectory() as temp:
            local_profile=forge_profiles.snapshot(temp,"Local Sample")
            fake_remote={
                "id":"934a35e2-9f2d-4b64-88ca-695068315233",
                "name":"Cloud Sample","mods":[],"revision":2}
            root=tk.Tk()
            root.attributes("-alpha",0.0)
            root.deiconify()
            root.game_install_path=temp
            root.account_client=Mock()
            root.account_client.signed_in=True
            root._render_hub_cards=lambda:None
            try:
                with patch.object(forge_profiles_ui.profiles,"cloud_list",
                                  return_value=[fake_remote]), \
                     patch.object(forge_profiles_ui.profiles,"cloud_delete",
                                  return_value=fake_remote["id"]) as delete_remote, \
                     patch.object(forge_profiles_ui.messagebox,"askyesno",return_value=True):
                    forge_profiles_ui.show(root)
                    win=root._forge_profiles_window
                    win.attributes("-alpha",0.0)
                    root.update()
                    all_buttons=[]
                    lists=[]
                    def visit(widget):
                        for child in widget.winfo_children():
                            if isinstance(child,tk.Button):all_buttons.append(child)
                            if isinstance(child,tk.Listbox):lists.append(child)
                            visit(child)
                    visit(win)
                    local,cloud=lists
                    btn={b.cget("text"):b for b in all_buttons}
                    delete=btn["DELETE LOCAL"]
                    self.assertEqual(delete.cget("state"),"disabled")
                    self.assertEqual(local.size(),1)
                    local.selection_set(0)
                    local.event_generate("<<ListboxSelect>>")
                    root.update()
                    self.assertEqual(delete.cget("text"),"DELETE LOCAL")
                    cloud_fetch=btn["FETCH CLOUD"]
                    cloud_fetch.invoke()
                    for i in range(30):
                        root.update()
                        if cloud.size(): break
                        time.sleep(0.015)
                    self.assertEqual(cloud.size(),1)
                    cloud.selection_set(0)
                    cloud.event_generate("<<ListboxSelect>>")
                    root.update()
                    self.assertEqual(delete.cget("text"),"DELETE CLOUD")
                    self.assertFalse(local.curselection())
                    delete.invoke()
                    for i in range(30):
                        root.update()
                        if cloud.size()==0: break
                        time.sleep(0.015)
                    self.assertEqual(cloud.size(),0)
                    self.assertEqual(delete.cget("text"),"DELETE LOCAL")
                    delete_remote.assert_called_once()
                    self.assertEqual(forge_profiles.load(temp)["profiles"][0]["id"],
                                     local_profile["id"])
                    win.destroy()
            finally:
                root.destroy()
if __name__ == "__main__":
    import unittest
    unittest.main()
