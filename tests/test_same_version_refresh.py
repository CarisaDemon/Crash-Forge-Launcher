"""No re-download loop when a GitHub release ZIP changes without a version bump."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import forge_launcher_updates as lu
import launcher_update_helper as helper


def make_zip(version, description):
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("CrashForgeLauncher.exe",b"GUI EXE / "+description)
        z.writestr("ForgeLauncherUpdater.exe",b"Updater EXE / "+description)
        z.writestr("launcher_version.txt", (version+"\n").encode("utf-8"))
        z.writestr("_internal/fresh.dll", b"Module / "+description)
    return output.getvalue()


def sample_release(data,version):
    return {
        "version":version, "verified":True,
        "url":f"https://github.com/{lu.REPOSITORY}/releases/tag/v{version}",
        "asset":{"name":lu.ZIP_NAME,"size":len(data),
                 "url":f"https://github.com/{lu.REPOSITORY}/releases/download/v{version}/{lu.ZIP_NAME}",
                 "sha256":hashlib.sha256(data).hexdigest()},
        "sha_asset":None,
    }


class FakeDownload(io.BytesIO):
    def __init__(self,payload):
        super().__init__(payload)
        self.headers={"Content-Length":str(len(payload))}


class SameVersionSelfUpdateTests(unittest.TestCase):
    def test_only_verified_new_digest_updates_same_numeric_version(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            app=root/"app"
            app.mkdir()
            (app/"launcher_version.txt").write_text("0.3.38",encoding="utf-8")
            release=sample_release(make_zip("0.3.38",b"first"),"0.3.38")
            self.assertTrue(lu.update_required(release,"0.3.38",app_dir=app,root=root))
            self.assertFalse(lu.update_required(release,"0.3.40",app_dir=app,root=root))
            self.assertFalse(lu.update_required(
                dict(release,verified=False),"0.3.38",app_dir=app,root=root))
            self.assertFalse(lu.update_required(release,"0.3.38",app_dir=None,root=root))
            lu.save_installed_release("0.3.38",release["asset"]["sha256"],app,root=root)
            self.assertFalse(lu.update_required(release,"0.3.38",app_dir=app,root=root))
            newer=sample_release(make_zip("0.3.38",b"second"),"0.3.38")
            self.assertTrue(lu.update_required(newer,"0.3.38",app_dir=app,root=root))
            self.assertFalse(lu.update_required(newer,"0.3.38",
                         app_dir=root/"different-app",root=root) is False)

    def test_same_version_package_stages_applies_and_stops_repeating(self):
        version="0.3.38"
        old=make_zip(version,b"old")
        newer=make_zip(version,b"new")
        next_update=make_zip(version,b"newer")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            app=root/"portable"
            app.mkdir()
            (app/lu.APP_EXE).write_bytes(b"OLD GUI")
            (app/lu.UPDATER_EXE).write_bytes(b"OLD HELPER")
            (app/"launcher_version.txt").write_text(version+"\n",encoding="utf-8")
            state=root/"updates"
            lu.save_installed_release(version,hashlib.sha256(old).hexdigest(),app,state)
            next_release=sample_release(newer,version)
            self.assertTrue(lu.update_required(next_release,version,app_dir=app,root=state))
            with patch.object(lu,"_read_download",
                    side_effect=lambda *args,**kwargs:FakeDownload(newer)):
                pending=lu.stage_release(next_release,version,root=state,app_dir=app)
            self.assertEqual(pending["zip_sha256"],hashlib.sha256(newer).hexdigest())
            self.assertTrue(lu.pending_update_required(pending,app,root=state))
            # For same-version installs, the NEW helper is verified and run:
            # the installed older helper cannot apply a same-number revision.
            with patch.object(lu,"is_portable_build",return_value=True), \
                 patch.object(lu.subprocess,"Popen") as process:
                self.assertTrue(lu.launch_update_after_exit(
                    app,54321,root=state))
                self.assertEqual(process.call_args.args[0][0],
                                 str(state/"apply-launcher-update-54321.exe"))
                self.assertEqual((state/"apply-launcher-update-54321.exe").read_bytes(),
                                 b"Updater EXE / new")
            outcome=helper.apply_update(app,pending["payload"],pending["manifest"],state)
            self.assertEqual(outcome["old_version"],version)
            self.assertEqual(outcome["version"],version)
            self.assertEqual((app/lu.APP_EXE).read_bytes(),b"GUI EXE / new")
            self.assertFalse(lu.update_required(next_release,version,app_dir=app,root=state))
            self.assertFalse(lu.pending_update_required(pending,app,root=state))
            self.assertIsNone(lu.pending_update(state))
            with patch.object(lu,"_read_download") as read:
                self.assertIsNone(lu.stage_release(next_release,version,root=state,app_dir=app))
                read.assert_not_called()
            newer_release=sample_release(next_update,version)
            self.assertTrue(lu.update_required(newer_release,version,app_dir=app,root=state))

    def test_pending_same_version_wrong_digest_is_replaced(self):
        version="0.3.38"
        first=make_zip(version,b"first")
        changed=make_zip(version,b"changed")
        with tempfile.TemporaryDirectory() as folder:
            app=Path(folder)/"app"
            app.mkdir()
            (app/"launcher_version.txt").write_text(version,encoding="utf-8")
            root=Path(folder)/"updates"
            with patch.object(lu,"_read_download",
                              return_value=FakeDownload(first)):
                staged1=lu.stage_release(sample_release(first,version),
                    version,root=root,app_dir=app)
            with patch.object(lu,"_read_download",
                              return_value=FakeDownload(changed)):
                staged2=lu.stage_release(sample_release(changed,version),
                    version,root=root,app_dir=app)
            self.assertNotEqual(staged1["zip_sha256"],staged2["zip_sha256"])
            self.assertEqual(staged2["zip_sha256"],hashlib.sha256(changed).hexdigest())

    def test_update_receipt_is_bound_to_app_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            a,b=root/"app-a",root/"app-b"
            a.mkdir();b.mkdir()
            for p in (a,b):
                (p/"launcher_version.txt").write_text("0.3.38")
            digest="c"*64
            lu.save_installed_release("0.3.38",digest,a,root=root)
            self.assertIsNotNone(lu.read_installed_release(a,root=root))
            self.assertIsNone(lu.read_installed_release(b,root=root))
            self.assertIsNone(lu.read_installed_release(a,root=root/"different-state"))


if __name__=="__main__":
    unittest.main()
