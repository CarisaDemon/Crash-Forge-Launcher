"""Web mod uninstall: guarded identity, category, Recycle Bin and rollbacks."""
from pathlib import Path
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import forge_mod_manager as manager
import forge_mod_uninstall as uninstall


class WebUninstallTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="cfr_uninstall_")
        self.addCleanup(tmp.cleanup)
        self.game=Path(tmp.name)/"Game"
        self.game.mkdir()
        (self.game/"ctr-native.exe").write_bytes(b"placeholder only")
        self.mods=self.game/"mods"
        self.mods.mkdir()
        self.recycle=patch.object(uninstall,"_recycle_staging_folder",
                                  side_effect=lambda p:shutil.rmtree(p))
        self.recycle.start()
        self.addCleanup(self.recycle.stop)

    def mod(self,kind="Kart",stable_id="forge-blue",folder_name="blue_kart",
            origin="forge_hub",source_id=None,enabled=True):
        target=self.mods/folder_name
        target.mkdir(exist_ok=False)
        ini=manager.CATEGORIES[kind][1]
        native=manager.CATEGORIES[kind][2][0]
        (target/ini).write_text(
            f"[{native}]\nname = Demo {kind}\nenabled = {str(enabled).lower()}\n"
            f"[forge_mod]\nid = {stable_id}\n"
            f"type = {kind}\nname = Demo {kind}\n"
            "version = 1.7\n"
            f"source = {origin}\nsource_id = {source_id or stable_id}\n",
            encoding="utf-8")
        (target/"sample.obj").write_text("o Demo\nv 1 1 1\n",encoding="utf-8")
        return target

    def pack(self):
        bundle=self.mod(kind="Modpack",stable_id="forge-pack",folder_name="my_pack")
        a=self.mod(kind="Character",stable_id="child-crash",folder_name="crash_hd",
                   source_id="forge-pack")
        b=self.mod(kind="Wheels",stable_id="child-wheels",folder_name="retro_wheels",
                   source_id="forge-pack")
        (bundle/"contents.json").write_text(json.dumps({
            "id":"forge-pack",
            "name":"My Pack",
            "mods":[
                {"type":"racers","id":"child-crash","name":"Crash HD"},
                {"type":"wheels","id":"child-wheels","name":"Retro Wheels"}
            ]}),encoding="utf-8")
        return bundle,a,b

    def test_single_web_mod_uninstalls_and_returns_to_installable_state(self):
        web=self.mod()
        other=self.mod(kind="Kart",stable_id="forge-other",
                       folder_name="blue_kart_2")
        local=self.mod(kind="Character",stable_id="local-mod",
                       folder_name="my_custom_racer",origin="local")
        game_exe=(self.game/"ctr-native.exe").read_bytes()
        plan=uninstall.plan_web_uninstall(self.game,"Kart","forge-blue")
        self.assertEqual(plan.paths,(web.resolve(),))
        self.assertEqual(plan.children,())
        result=uninstall.uninstall_web_mod(
            self.game,"Kart","forge-blue",expected_paths=plan.paths)
        self.assertEqual(result["removed_ids"],("forge-blue",))
        self.assertFalse(web.exists())
        self.assertTrue(other.joinpath("kart.ini").is_file())
        self.assertTrue(local.joinpath("character.ini").is_file())
        self.assertEqual((self.game/"ctr-native.exe").read_bytes(),game_exe)
        self.assertFalse(list(self.game.glob(".forge-uninstall-*")))
        self.assertNotIn("forge-blue",
                         [mod["id"] for mod in manager.scan_installed(self.game)])
        self.assertIn("forge-other",
                      [mod["id"] for mod in manager.scan_installed(self.game)])

    def test_disabled_and_legacy_source_can_only_delete_downloaded_web(self):
        disabled=self.mod(stable_id="forge-disabled",folder_name="disabled",
                          enabled=False)
        uninstall.uninstall_web_mod(self.game,"Kart","forge-disabled")
        self.assertFalse(disabled.exists())
        local=self.mod(stable_id="my-handmade",folder_name="handmade",
                       origin="local")
        with self.assertRaisesRegex(uninstall.UninstallError,"Only valid Forge Hub"):
            uninstall.uninstall_web_mod(self.game,"Kart","my-handmade")
        self.assertTrue(local.exists())
        legacy=self.game/"assets"/"mods"/"karts"/"legacy_kart"
        legacy.mkdir(parents=True)
        (legacy/"kart.ini").write_text("[kart]\nname=Legacy\n")
        with self.assertRaises(uninstall.UninstallError):
            uninstall.uninstall_web_mod(self.game,"Kart","legacy_kart")
        self.assertTrue(legacy.joinpath("kart.ini").is_file())

    def test_wrong_id_or_category_never_removes_a_folder(self):
        path=self.mod()
        for kind,stable in (("Character","forge-blue"),("Kart","other-blue"),
                            ("Kart","../blue_kart"),("Wheels","forge-blue")):
            with self.subTest(kind=kind,stable=stable):
                with self.assertRaises(uninstall.UninstallError):
                    uninstall.uninstall_web_mod(self.game,kind,stable)
                self.assertTrue(path.joinpath("kart.ini").is_file())

    def test_stale_user_confirmation_aborts_without_modification(self):
        path=self.mod()
        with self.assertRaisesRegex(uninstall.UninstallError,"since confirmation"):
            uninstall.uninstall_web_mod(
                self.game,"Kart","forge-blue",
                expected_paths=(self.mods/"outdated_name",))
        self.assertTrue(path.exists())

    def test_symlinked_content_is_never_uninstalled(self):
        path=self.mod()
        other=self.game/"private.txt"
        other.write_text("must survive")
        try:
            (path/"shortcut.txt").symlink_to(other)
        except OSError:
            self.skipTest("Windows symlinks unavailable without permissions")
        with self.assertRaisesRegex(uninstall.UninstallError,"link or junction"):
            uninstall.uninstall_web_mod(self.game,"Kart","forge-blue")
        self.assertTrue(path.is_dir())
        self.assertEqual(other.read_text(),"must survive")

    def test_recycle_failure_rolls_back_all_original_bytes(self):
        path=self.mod()
        original=(path/"kart.ini").read_bytes()
        with patch.object(uninstall,"_recycle_staging_folder",
                          side_effect=PermissionError("Recycle Bin unavailable")):
            with self.assertRaisesRegex(uninstall.UninstallError,"restored"):
                uninstall.uninstall_web_mod(self.game,"Kart","forge-blue")
        self.assertEqual((path/"kart.ini").read_bytes(),original)
        self.assertFalse(list(self.game.glob(".forge-uninstall-*")))

    def test_modpack_removes_only_owned_children_and_inventory(self):
        bundle,a,b=self.pack()
        other=self.mod(stable_id="forge-unrelated",folder_name="my_other_mod")
        paths=uninstall.plan_web_uninstall(
            self.game,"Modpack","forge-pack")
        self.assertEqual(len(paths.paths),3)
        self.assertEqual(set(paths.child_ids),{"child-crash","child-wheels"})
        result=uninstall.uninstall_web_mod(
            self.game,"Modpack","forge-pack",expected_paths=paths.paths)
        for path in (bundle,a,b):
            self.assertFalse(path.exists())
        self.assertTrue(other.joinpath("kart.ini").is_file())
        self.assertEqual(result["removed_count"],3)
        self.assertEqual(set(result["removed_ids"]),
                         {"forge-pack","child-crash","child-wheels"})
        self.assertEqual([mod["id"] for mod in manager.scan_installed(self.game)],
                         ["forge-unrelated"])

    def test_modpack_child_must_be_removed_from_parent_pack(self):
        bundle,a,b=self.pack()
        with self.assertRaisesRegex(uninstall.UninstallError,"Uninstall the Modpack"):
            uninstall.uninstall_web_mod(self.game,"Wheels","child-wheels")
        for path in (bundle,a,b):
            self.assertTrue(path.exists())

    def test_pack_inventory_cannot_delete_other_owner(self):
        bundle,a,b=self.pack()
        fake=self.mod(kind="Character",stable_id="forge-unrelated",
                      folder_name="someone_elses_racer")
        inv=bundle/"contents.json"
        obj=json.loads(inv.read_text())
        obj["mods"][0]["id"]="forge-unrelated"
        inv.write_text(json.dumps(obj))
        with self.assertRaises(uninstall.UninstallError):
            uninstall.uninstall_web_mod(self.game,"Modpack","forge-pack")
        for path in (bundle,a,b,fake):
            self.assertTrue(path.exists())

    def test_pack_malformed_inventory_refuses_uninstall(self):
        bundle,a,b=self.pack()
        (bundle/"contents.json").write_text("{not JSON")
        with self.assertRaisesRegex(uninstall.UninstallError,"Invalid Modpack"):
            uninstall.uninstall_web_mod(self.game,"Modpack","forge-pack")
        for path in (bundle,a,b):
            self.assertTrue(path.exists())

    def test_pack_missing_child_uninstalls_existing_and_inventory(self):
        bundle,a,b=self.pack()
        shutil.rmtree(b)
        result=uninstall.uninstall_web_mod(self.game,"Modpack","forge-pack")
        self.assertEqual(result["removed_count"],2)
        self.assertFalse(bundle.exists())
        self.assertFalse(a.exists())

    def test_game_assets_and_symlinked_mod_root_refuse_operation(self):
        folder=self.mod()
        sibling=self.game.parent/"not_my_game"
        sibling.mkdir()
        path=sibling/"do-not-delete.txt"
        path.write_text("user")
        with self.assertRaises(uninstall.UninstallError):
            uninstall.uninstall_web_mod(sibling,"Kart","forge-blue")
        self.assertTrue(folder.exists())
        self.assertEqual(path.read_text(),"user")

    def test_modpack_move_failure_rolls_back_all_prior_moved_paths(self):
        bundle,a,b=self.pack()
        real_replace=uninstall.os.replace
        calls=[0]
        def fail_second(src,dst):
            if Path(src).parent.name=="mods" and calls[0]==1:
                calls[0]+=1
                raise PermissionError("Folder is in use")
            if Path(src).parent.name=="mods":
                calls[0]+=1
            return real_replace(src,dst)
        with patch.object(uninstall.os,"replace",side_effect=fail_second):
            with self.assertRaisesRegex(uninstall.UninstallError,"restored"):
                uninstall.uninstall_web_mod(self.game,"Modpack","forge-pack")
        self.assertGreaterEqual(calls[0],2)
        for path in (bundle,a,b):
            self.assertTrue(path.exists())
        self.assertFalse(list(self.game.glob(".forge-uninstall-*")))


if __name__ == "__main__":
    unittest.main()