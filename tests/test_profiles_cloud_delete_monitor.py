"""Offline tests: cloud delete is guarded, and new dialogs follow launcher's monitor."""
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
import tkinter as tk

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import forge_profiles as profiles
import forge_window_policy as windows
import forge_mod_manager as mod_manager

USER="4d5f2f6a-28e3-4cdf-8b92-f0dd181bd01a"
CLOUD="893a12a4-f45b-4622-88b5-5ccfa455e540"

class CloudTests(TestCase):
    def setUp(self):
        self.profile={"id":CLOUD,"name":"My Test Profile","mods":[],"revision":3}
        self.account=Mock()
        self.account.profile.return_value={"id":USER}
        self.account.token.return_value="test-token"

    def test_cloud_delete_only_own_id_and_revision_and_confirm_server(self):
        self.account._request.return_value=[{"id":CLOUD}]
        result=profiles.cloud_delete(self.account,self.profile)
        self.assertEqual(result,CLOUD)
        args,kwargs=self.account._request.call_args
        self.assertIn("id=eq."+CLOUD,args[0])
        self.assertIn("owner_id=eq."+USER,args[0])
        self.assertIn("revision=eq.3",args[0])
        self.assertEqual(kwargs["method"],"DELETE")
        self.assertEqual(kwargs["prefer"],"return=representation")

    def test_cloud_delete_rejects_stale_revision(self):
        self.account._request.return_value=[]
        with self.assertRaises(profiles.ProfileError):
            profiles.cloud_delete(self.account,self.profile)

    def test_missing_revision_never_sends_delete(self):
        del self.profile["revision"]
        with self.assertRaises(profiles.ProfileError):
            profiles.cloud_delete(self.account,self.profile)
        self.account._request.assert_not_called()

    def test_cloud_list_keeps_valid_revision(self):
        self.account._request.return_value=[{
            "id":CLOUD,"name":"My Test Profile","mod_states":[],
            "revision":3,"updated_at":"2026-10-12T00:00:00Z"}]
        rows=profiles.cloud_list(self.account)
        self.assertEqual(rows[0]["revision"],3)

    def test_delete_cloud_does_not_access_local_game(self):
        with tempfile.TemporaryDirectory() as game_dir:
            keep=profiles.snapshot(game_dir,"Local Keep")
            self.account._request.return_value=[{"id":CLOUD}]
            profiles.cloud_delete(self.account,self.profile)
            self.assertEqual(profiles.load(game_dir)["profiles"][0]["id"],keep["id"])

class MonitorPolicyTests(TestCase):
    def test_native_dialog_parent_follows_launcher_when_missing(self):
        dialog=Mock(master=None,options={})
        owner=Mock()
        owner.winfo_exists.return_value=True
        opts=windows.native_dialog_options(dialog, {"title":"Select package"}, owner)
        self.assertIs(opts["parent"],owner)
        self.assertEqual(opts["title"],"Select package")
        # An explicit parent must never be overwritten.
        other=Mock()
        kept=windows.native_dialog_options(dialog, {"parent":other}, owner)
        self.assertIs(kept["parent"],other)

    def test_secondary_monitor_negative_left(self):
        area=(-1920,0,1920,1040)
        owner=(-1550,100,1100,700)
        child=(220,60,680,500)
        place=windows.choose_position(area,owner,child)
        self.assertIsNotNone(place)
        width,height,x,y=place
        self.assertGreaterEqual(x,-1920)
        self.assertLessEqual(x+width,0)
        self.assertGreaterEqual(y,0)
        self.assertLessEqual(y+height,1040)

    def test_fully_visible_child_keeps_intended_geometry(self):
        self.assertIsNone(windows.choose_position(
            (1920,0,1920,1080),(1980,100,1280,820),
            (2150,160,620,380)))

    def test_too_large_child_resizes_to_workarea(self):
        placement=windows.choose_position(
            (0,0,800,500),(0,0,760,480),(0,0,1400,1200))
        self.assertEqual(placement[:2],(800,500))

    def test_repositions_mapped_toplevel_including_future_dialogs(self):
        root=tk.Tk()
        root.withdraw()
        root.geometry("650x450+100+100")
        root._current_monitor_workarea=lambda:(0,0,1050,780)
        policy=windows.install(root)
        try:
            child=tk.Toplevel(root)
            child.geometry("360x220+1300+880")
            root.update()
            policy.place(child)
            root.update_idletasks()
            x=child.winfo_rootx()
            y=child.winfo_rooty()
            self.assertGreaterEqual(x,0)
            self.assertLessEqual(x+child.winfo_width(),1050)
            self.assertGreaterEqual(y,0)
            self.assertLessEqual(y+child.winfo_height(),780)
            child.destroy()
        finally:
            root.destroy()
