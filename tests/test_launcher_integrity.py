"""Offline safety tests for read-only launcher verification and approved repair."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import forge_launcher_integrity as integrity
import forge_launcher_updates as updates
import launcher_update_helper as helper


class TestLauncherIntegrity(unittest.TestCase):
    def make_app(self, root):
        app=root/"portable"
        app.mkdir()
        names=list(integrity.CRITICAL)+["_internal/editor_tools/CrashForgeModelImporter.exe"]
        for name in names:
            item=app/name
            item.parent.mkdir(parents=True,exist_ok=True)
            item.write_bytes(b"valid-file-"+name.encode())
        (app/"launcher_version.txt").write_text("0.3.41",encoding="utf-8")
        (app/"launcher_settings.json").write_text('{"my_user_setting":true}')
        integrity.build_manifest(app,"0.3.41")
        return app

    def test_manifest_verified_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            app=self.make_app(Path(temp))
            self.assertEqual(integrity.audit(app)["status"],"ok")
            (app/"_internal/editor_tools/CrashForgeModelImporter.exe").write_bytes(b"tampered")
            result=integrity.audit(app)
            self.assertEqual(result["status"],"damaged")
            self.assertIn("wrong size",result["problems"][0])
            self.assertTrue((app/"launcher_settings.json").is_file())

    def test_missing_manifest_does_not_claim_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            app=self.make_app(Path(temp))
            (app/integrity.MANIFEST_PATH).unlink()
            self.assertEqual(integrity.audit(app)["status"],"unavailable")

    def test_verified_same_version_can_stage_explicit_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            app=self.make_app(root)
            memory=io.BytesIO()
            with zipfile.ZipFile(memory,"w",zipfile.ZIP_DEFLATED) as z:
                for file in app.rglob("*"):
                    if file.is_file() and file.name!="launcher_settings.json":
                        z.write(file,file.relative_to(app).as_posix())
            data=memory.getvalue()
            digest=hashlib.sha256(data).hexdigest()
            state=root/"state"
            updates.save_installed_release("0.3.41",digest,app,state)
            (app/"_internal/editor_tools/CrashForgeModelImporter.exe").unlink()
            self.assertEqual(integrity.audit(app)["status"],"damaged")
            release={"version":"0.3.41","verified":True,
                     "url":"https://github.com/"+updates.REPOSITORY+"/releases/tag/v0.3.41",
                     "asset":{"name":updates.ZIP_NAME,"size":len(data),"sha256":digest,
                              "url":"https://github.com/"+updates.REPOSITORY+
                                    "/releases/download/v0.3.41/"+updates.ZIP_NAME}}
            self.assertFalse(updates.update_required(release,"0.3.41",app_dir=app,root=state))
            self.assertTrue(updates.update_required(release,"0.3.41",app_dir=app,
                                                    root=state,force_repair=True))
            class Stream(io.BytesIO):
                headers={"Content-Length":str(len(data))}
            with patch.object(updates,"_read_download",return_value=Stream(data)):
                pending=updates.stage_release(release,"0.3.41",root=state,
                                              app_dir=app,force_repair=True)
            self.assertTrue(pending["repair"])
            self.assertTrue(updates.pending_update_required(pending,app,root=state))
            helper.apply_update(app,pending["payload"],pending["manifest"],state)
            self.assertEqual(integrity.audit(app)["status"],"ok")
            self.assertEqual((app/"launcher_settings.json").read_text(),
                             '{"my_user_setting":true}')
            self.assertFalse(updates.update_required(release,"0.3.41",app_dir=app,
                                                     root=state))


if __name__=="__main__":
    unittest.main()
