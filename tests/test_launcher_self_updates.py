"""Windows launcher self-update tests: isolated fake packages, zero game mutations."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import forge_launcher_updates as lu
import launcher_update_helper as helper


def make_archive(members):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
        for name,data in members.items():
            archive.writestr(name,data)
    return buffer.getvalue()


def sample_release(data,version="0.3.29"):
    name=lu.ZIP_NAME
    return {
      "version":version,
      "tag":"v"+version,
      "url":"https://github.com/"+lu.REPOSITORY+"/releases/tag/v"+version,
      "asset":{"name":name,"size":len(data),"url":
                "https://github.com/"+lu.REPOSITORY+
                "/releases/download/v"+version+"/"+name,
               "sha256":hashlib.sha256(data).hexdigest()},
      "sha_asset":None,
      "verified":True,
    }


class MockDownload(io.BytesIO):
    def __init__(self,data):
        super().__init__(data)
        self.headers={"Content-Length":str(len(data))}


class SelfUpdateTests(unittest.TestCase):
    def test_repo_and_stable_version(self):
        self.assertEqual(lu.REPOSITORY,"CarisaDemon/Crash-Forge-Launcher")
        self.assertTrue(lu.newer_release({"version":"0.3.29"},"0.3.28"))
        self.assertFalse(lu.newer_release({"version":"0.3.28"},"0.3.29"))
        self.assertFalse(lu.newer_release({"version":"invalid"},"0.3.28"))
        self.assertIsNone(lu.parse_release({"prerelease":True}))
        self.assertIsNone(lu.parse_release({"draft":True}))
        self.assertFalse(lu.is_portable_build(),
            "Source dev mode should not self-replace")

    def test_valid_release_meta(self):
        url="https://github.com/"+lu.REPOSITORY+"/releases/download/v0.3.29/"+lu.ZIP_NAME
        release={
          "tag_name":"v0.3.29","draft":False,"prerelease":False,
          "html_url":"https://github.com/"+lu.REPOSITORY+"/releases/tag/v0.3.29",
          "assets":[{"name":lu.ZIP_NAME,"size":100,
            "browser_download_url":url,"digest":"sha256:"+("a"*64)}]
        }
        result=lu.parse_release(release)
        self.assertTrue(result["verified"])
        self.assertEqual(result["version"],"0.3.29")
        self.assertEqual(result["asset"]["sha256"],"a"*64)
        with patch.object(lu,"_open_json",return_value=[dict(release,draft=True),release]):
            self.assertEqual(lu.fetch_latest()["version"],"0.3.29")
        malicious=json.loads(json.dumps(release))
        malicious["assets"][0]["browser_download_url"]="https://evil.example/update.zip"
        self.assertIsNone(lu.parse_release(malicious))

    def test_checksum_sidecars_require_correct_release_name(self):
        binary=b"payload"
        release=sample_release(binary)
        release["asset"]["sha256"]=""
        release["sha_asset"]={
            "name":lu.ZIP_NAME+".sha256",
            "url":"https://github.com/"+lu.REPOSITORY+
                  "/releases/download/v0.3.29/"+lu.ZIP_NAME+".sha256",
            "size":100
        }
        digest=hashlib.sha256(binary).hexdigest()
        with patch.object(lu,"_read_download",return_value=MockDownload(
                (digest+"\n").encode())):
            self.assertEqual(lu.expected_digest(release),digest)
        release["sha_asset"]["name"]="SHA256SUMS.txt"
        with patch.object(lu,"_read_download",return_value=MockDownload(
                (digest+"\n").encode())):
            with self.assertRaises(lu.LauncherUpdateError):
                lu.expected_digest(release)
        with patch.object(lu,"_read_download",return_value=MockDownload(
                (digest+"  "+lu.ZIP_NAME+"\n").encode())):
            self.assertEqual(lu.expected_digest(release),digest)

    def test_restart_only_verified_new_exe_and_no_console(self):
        import launcher_update_helper as helper
        with tempfile.TemporaryDirectory() as temp:
            app=Path(temp)
            exe=app/lu.APP_EXE
            exe.write_bytes(b"simulated verified GUI executable")
            with patch.object(helper.subprocess,"Popen") as launch:
                helper.relaunch_updated_exe(str(app))
            launch.assert_called_once()
            args, kwargs = launch.call_args
            self.assertEqual(args[0], [str(exe.resolve())])
            self.assertEqual(kwargs["cwd"],str(app.resolve()))
            self.assertEqual(kwargs["creationflags"],
                             helper.subprocess.CREATE_NO_WINDOW |
                             helper.subprocess.DETACHED_PROCESS |
                             helper.subprocess.CREATE_NEW_PROCESS_GROUP)
            self.assertTrue(kwargs["close_fds"])
            exe.unlink()
            with patch.object(helper.subprocess,"Popen") as launch:
                with self.assertRaisesRegex(helper.UpdateApplyError,"not installed"):
                    helper.relaunch_updated_exe(str(app))
                launch.assert_not_called()

    def test_update_helper_restarts_only_after_success(self):
        import launcher_update_helper as helper
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)
            parameters=[
                "--apply","--pid","123",
                "--app-dir",str(state/"app"),
                "--stage",str(state/"staged"),
                "--manifest",str(state/"manifest.json"),
                "--state-dir",str(state),
            ]
            successful={"old_version":"0.3.28","version":"0.3.29","files":3}
            with patch.object(helper,"_wait_for_process_exit") as wait, \
                 patch.object(helper,"apply_update",return_value=successful), \
                 patch.object(helper,"relaunch_updated_exe",return_value=7654) as restart:
                self.assertEqual(helper.main(parameters),0)
                wait.assert_called_once_with(123)
                restart.assert_called_once_with(str(state/"app"))
                self.assertIn("restarted updated EXE, PID=7654",
                              (state/"updater-result.txt").read_text())
            with patch.object(helper,"_wait_for_process_exit"), \
                 patch.object(helper,"apply_update",side_effect=OSError("locked file")), \
                 patch.object(helper,"relaunch_updated_exe",return_value=7654) as restart:
                self.assertEqual(helper.main(parameters),2)
                restart.assert_not_called()
                self.assertIn("FAILED", (state/"updater-result.txt").read_text())

    def test_source_bat_migrates_to_separate_exe_without_touching_sources(self):
        import launcher_update_helper as helper
        version="0.3.29"
        binary=make_archive({
            "CrashForgeLauncher.exe":b"new standalone GUI",
            "ForgeLauncherUpdater.exe":b"new updater GUI",
            "launcher_version.txt":b"0.3.29\n",
            "assets/Fondo.png":b"official cover",
        })
        with tempfile.TemporaryDirectory() as td:
            parent=Path(td)
            dev=parent/"workspace"/"Crash Forge Launcher"
            dev.mkdir(parents=True)
            (dev/"launcher.py").write_text("SOURCE: NEVER REPLACE",encoding="utf-8")
            (dev/"launcher_settings.json").write_text(
                '{"game_install_path":"C:/Games/CTR","launcher_auto_update":true}',
                encoding="utf-8")
            state=parent/"user"/"CrashForgeLauncher"/"updates"
            target=lu.portable_target_for_source(dev,root=state)
            self.assertEqual(target,(state.parent/"app").resolve())
            with patch.object(lu,"_read_download",
                              side_effect=lambda *_a,**_k:MockDownload(binary)):
                pending=lu.stage_release(sample_release(binary),"0.0.0",root=state)
            with patch.object(lu.subprocess,"Popen") as spawn:
                self.assertTrue(lu.launch_update_after_exit(
                    target,43210,root=state,source_migration=True,
                    source_dir=dev))
                arguments=spawn.call_args.args[0]
            self.assertIn("--source-dir",arguments)
            self.assertIn("--allow-fresh",arguments)
            self.assertIn(str(dev.resolve()),arguments)
            self.assertEqual(arguments[0],str(state/"apply-launcher-update-43210.exe"))
            result=helper.apply_update(target,pending["payload"],
                                       pending["manifest"],state,allow_fresh=True)
            copied=helper.migrate_source_preferences(dev,target)
            self.assertEqual(result["version"],version)
            self.assertIn("launcher_settings.json",copied)
            self.assertEqual(
                json.loads((target/"launcher_settings.json").read_text())
                ["game_install_path"],"C:/Games/CTR")
            self.assertEqual((dev/"launcher.py").read_text(),
                             "SOURCE: NEVER REPLACE")
            self.assertEqual((target/"CrashForgeLauncher.exe").read_bytes(),
                             b"new standalone GUI")
            with patch.object(helper.subprocess,"Popen") as spawn:
                self.assertEqual(helper.relaunch_updated_exe(target),spawn.return_value.pid)
                self.assertEqual(spawn.call_args.args[0],
                                 [str((target/"CrashForgeLauncher.exe").resolve())])
            self.assertNotIn("launcher_version.txt",[x.name for x in dev.iterdir()])
            print("PASS .bat source stays intact; new EXE installed, prefs migrated and restarted")

    def test_fresh_migration_never_uses_untrusted_directory(self):
        import launcher_update_helper as helper
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            state=path/"updates"
            state.mkdir()
            # A normal installed directory cannot be bootstrapped without
            # a real existing portable EXE and verified release.
            target=path/"somebody-elses-files"
            target.mkdir()
            (target/"documents.txt").write_text("private")
            with self.assertRaises(helper.UpdateApplyError):
                helper.validate_staged(target,path/"fake-payload",
                                       path/"manifest.json",state,allow_fresh=True)
            self.assertEqual((target/"documents.txt").read_text(),"private")

    def test_stage_apply_preserves_personal_data_and_backup(self):
        version="0.3.29"
        binary=make_archive({
          "CrashForgeLauncher.exe":b"NEW EXE bytes",
          "ForgeLauncherUpdater.exe":b"NEW helper bytes",
          "launcher_version.txt":(version+"\n").encode(),
          "_internal/loader.dll":b"new runtime",
          "assets/Fondo.png":b"new branded backdrop",
          "forge_online_config.json":b'{"feed_url":"new default"}'
        })
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            app=root/"portable"
            app.mkdir()
            (app/"CrashForgeLauncher.exe").write_bytes(b"OLD EXE")
            (app/"ForgeLauncherUpdater.exe").write_bytes(b"OLD helper")
            (app/"launcher_version.txt").write_text("0.3.28",encoding="utf-8")
            (app/"launcher_settings.json").write_text("personal preference",encoding="utf-8")
            (app/"forge_online_config.json").write_text("user feed override",encoding="utf-8")
            custom=(app/"assets"/"mods"/"karts"/"personal.ini")
            custom.parent.mkdir(parents=True)
            custom.write_bytes(b"personal-mod-not-ours")
            with patch.object(lu,"_read_download",side_effect=lambda *_args,**_kw:MockDownload(binary)):
                pending=lu.stage_release(sample_release(binary),"0.3.28",root=root/"updates")
            self.assertIsNotNone(pending)
            self.assertEqual(lu.pending_update(root/"updates")["version"],version)
            self.assertEqual((app/"CrashForgeLauncher.exe").read_bytes(),b"OLD EXE",
                             "Staging must never replace live launcher files")
            result=helper.apply_update(str(app),pending["payload"],pending["manifest"],str(root/"updates"))
            self.assertEqual(result["version"],version)
            self.assertEqual((app/"CrashForgeLauncher.exe").read_bytes(),b"NEW EXE bytes")
            self.assertEqual((app/"_internal"/"loader.dll").read_bytes(),b"new runtime")
            self.assertEqual((app/"launcher_settings.json").read_text(),"personal preference")
            self.assertEqual((app/"forge_online_config.json").read_text(),"user feed override")
            self.assertEqual(custom.read_bytes(),b"personal-mod-not-ours")
            self.assertEqual((Path(result["backup"])/"CrashForgeLauncher.exe").read_bytes(),b"OLD EXE")
            self.assertIsNone(lu.pending_update(root/"updates"))
            with self.assertRaises(helper.UpdateApplyError):
                helper.apply_update(str(app),pending["payload"],pending["manifest"],str(root/"updates"))

    def test_invalid_archive_and_checksum_do_not_replace_files(self):
        entries=[
          {"CrashForgeLauncher.exe":b"new",
           "ForgeLauncherUpdater.exe":b"updater",
           "launcher_version.txt":b"0.3.29",
           "launcher_settings.json":b"steal personal settings"},
          {"CrashForgeLauncher.exe":b"new",
           "ForgeLauncherUpdater.exe":b"updater",
           "launcher_version.txt":b"0.3.29",
           "../escape.exe":b"escape"},
          {"CrashForgeLauncher.exe":b"new",
           "ForgeLauncherUpdater.exe":b"updater",
           "launcher_version.txt":b"0.3.29",
           "evil.ps1":b"unsafe script"},
          {"CrashForgeLauncher.exe":b"new",
           "ForgeLauncherUpdater.exe":b"updater",
           "launcher_version.txt":b"not-the-tag"},
          {"CrashForgeLauncher.exe":b"new",
           "ForgeLauncherUpdater.exe":b"updater",
           "launcher_version.txt":b"0.3.29",
           "assets/mods/wheels/private.ini":b"must not overwrite mods"},
          {"CrashForgeLauncher.exe":b"new",
           "ForgeLauncherUpdater.exe":b"updater",
           "launcher_version.txt":b"0.3.29",
           "assets/screenshot-private.png":b"must not overwrite screenshots"},
        ]
        with tempfile.TemporaryDirectory() as td:
            app=Path(td)/"app"
            app.mkdir()
            old=app/"CrashForgeLauncher.exe"
            old.write_bytes(b"live-program")
            for members in entries:
                content=make_archive(members)
                with patch.object(lu,"_read_download",side_effect=lambda *_a,**_k:MockDownload(content)):
                    with self.assertRaises(lu.LauncherUpdateError):
                        lu.stage_release(sample_release(content),"0.3.28",
                                         root=Path(td)/"updates")
                self.assertEqual(old.read_bytes(),b"live-program")
            good=make_archive({"CrashForgeLauncher.exe":b"new",
                               "ForgeLauncherUpdater.exe":b"updater",
                               "launcher_version.txt":b"0.3.29"})
            release=sample_release(good)
            release["asset"]["sha256"]="f"*64
            with patch.object(lu,"_read_download",side_effect=lambda *_a,**_k:MockDownload(good)):
                with self.assertRaisesRegex(lu.LauncherUpdateError,"checksum mismatch"):
                    lu.stage_release(release,"0.3.28",root=Path(td)/"updates")
            self.assertEqual(old.read_bytes(),b"live-program")

    def test_apply_rolls_back_if_new_exe_is_locked(self):
        binary=make_archive({"CrashForgeLauncher.exe":b"new",
                             "ForgeLauncherUpdater.exe":b"new updater",
                             "launcher_version.txt":b"0.3.29"})
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            app=root/"app"
            app.mkdir()
            exe=app/"CrashForgeLauncher.exe"
            exe.write_bytes(b"prior-build")
            (app/"launcher_version.txt").write_text("0.3.28")
            (app/"ForgeLauncherUpdater.exe").write_bytes(b"old updater")
            with patch.object(lu,"_read_download",side_effect=lambda *_a,**_k:MockDownload(binary)):
                staged=lu.stage_release(sample_release(binary),"0.3.28",root=root/"updates")
            original=helper.os.replace
            calls=[0]
            def fail_once(src,dst):
                if Path(dst).name.lower()=="crashforgelauncher.exe" and calls[0]==0:
                    calls[0]+=1
                    raise PermissionError("simulated Windows exe lock")
                return original(src,dst)
            with patch.object(helper.os,"replace",side_effect=fail_once):
                with self.assertRaisesRegex(helper.UpdateApplyError,"previous files restored"):
                    helper.apply_update(str(app),staged["payload"],staged["manifest"],str(root/"updates"))
            self.assertEqual(exe.read_bytes(),b"prior-build")
            self.assertEqual((app/"launcher_version.txt").read_text(),"0.3.28")

    def test_manifest_rejects_staged_tampering(self):
        bundle=make_archive({"CrashForgeLauncher.exe":b"new",
                             "ForgeLauncherUpdater.exe":b"updater",
                             "launcher_version.txt":b"0.3.29"})
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            app=root/"app"
            app.mkdir()
            (app/"CrashForgeLauncher.exe").write_bytes(b"OLD")
            (app/"launcher_version.txt").write_text("0.3.28")
            with patch.object(lu,"_read_download",side_effect=lambda *_a,**_k:MockDownload(bundle)):
                staged=lu.stage_release(sample_release(bundle),"0.3.28",root=root/"updates")
            (Path(staged["payload"])/"CrashForgeLauncher.exe").write_bytes(b"TAMPERED")
            with self.assertRaisesRegex(helper.UpdateApplyError,"Staged file"):
                helper.apply_update(str(app),staged["payload"],staged["manifest"],str(root/"updates"))
            self.assertEqual((app/"CrashForgeLauncher.exe").read_bytes(),b"OLD")


if __name__=="__main__":
    unittest.main(verbosity=2)
