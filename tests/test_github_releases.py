"""No game or browser launch. Fake GitHub downloads operate only on temp files."""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import forge_releases as releases

def make_zip(entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name, contents in entries.items():
            z.writestr(name,contents)
    return data.getvalue()

def fake_release(binary, has_asset_digest=True):
    name="Crash-Forge-Racing-Windows.zip"
    download = "https://github.com/"+releases.REPOSITORY+"/releases/download/v2.0.10/"+name
    return {
        "version":"2.0.10","tag":"v2.0.10","name":"Crash Forge Racing 2.0.10",
        "url":"https://github.com/"+releases.REPOSITORY+"/releases/tag/v2.0.10",
        "asset":{"name":name,"url":download,"size":len(binary),
                 "sha256":hashlib.sha256(binary).hexdigest() if has_asset_digest else ""},
        "checksum_asset":None,
        "verified_package":has_asset_digest,
    }

class Download(io.BytesIO):
    def __init__(self, contents):
        super().__init__(contents)
        self.headers={"Content-Length":str(len(contents))}

class ReleaseTests(unittest.TestCase):
    def test_valid_release_and_versions(self):
        sha="a"*64
        api={
            "tag_name":"v2.0.10","name":"Version 2.0.10",
            "html_url":"https://github.com/CarisaDemon/Crash-Forge-Racing/releases/tag/v2.0.10",
            "draft":False,"prerelease":False,
            "assets":[{"name":"Crash-Forge-Racing-Windows.zip",
                       "browser_download_url":"https://github.com/CarisaDemon/Crash-Forge-Racing/releases/download/v2.0.10/Crash-Forge-Racing-Windows.zip",
                       "size":9300,"digest":"sha256:"+sha}]
        }
        parsed=releases.parse_release(api)
        self.assertEqual(parsed["version"],"2.0.10")
        self.assertTrue(parsed["verified_package"])
        self.assertEqual(parsed["asset"]["sha256"],sha)
        self.assertEqual(releases.compare_versions("2.0.9","2.0.10"),-1)
        self.assertEqual(releases.compare_versions("2.0.10","2.0.10"),0)
        self.assertEqual(releases.compare_versions("2.0.11","2.0.10"),1)
        self.assertIsNone(releases.compare_versions(None,"2.0.10"))
        self.assertIsNone(releases.parse_release(dict(api,prerelease=True)))
        self.assertFalse(releases.parse_release(dict(api,assets=[]))["verified_package"])
        wrong=json.loads(json.dumps(api))
        wrong["assets"][0]["browser_download_url"]="https://evil.example/file.zip"
        self.assertFalse(releases.parse_release(wrong)["verified_package"])

    def test_release_selection_prefers_game_build_over_other_tools(self):
        def entry(version, assets):
            return {
                "tag_name":"v"+version,
                "html_url":"https://github.com/"+releases.REPOSITORY+
                           "/releases/tag/v"+version,
                "draft":False,"prerelease":False,"assets":assets
            }
        url="https://github.com/"+releases.REPOSITORY+"/releases/download/v2.0.10/Crash-Forge-Racing-Windows.zip"
        game=entry("2.0.10",[{
            "name":"Crash-Forge-Racing-Windows.zip",
            "browser_download_url":url,"size":3000,
            "digest":"sha256:"+("a"*64)
        }])
        tool=entry("9.0.0",[])
        with patch.object(releases,"_read_json",return_value=[tool,game]):
            selected=releases.fetch_latest_release()
        self.assertEqual(selected["version"],"2.0.10")
        self.assertTrue(selected["verified_package"])
        with patch.object(releases,"_read_json",return_value=[]):
            self.assertIsNone(releases.fetch_latest_release())

    def test_cadence(self):
        self.assertFalse(releases.check_due("Manual only",0,now=999999,startup=True))
        self.assertTrue(releases.check_due("On launch",999900,now=999999,startup=True))
        self.assertFalse(releases.check_due("On launch",0,now=999999,startup=False))
        self.assertFalse(releases.check_due("Daily",1000,now=2000))
        self.assertTrue(releases.check_due("Daily",1000,now=90000))
        self.assertTrue(releases.check_due("Every 6 hours",0,now=90000))
        self.assertFalse(releases.check_due("Weekly",5000,now=5100))

    def test_sha256sums_sidecar_for_windows_zip(self):
        archive=make_zip({"ctr-native.exe":b"future game"})
        release=fake_release(archive,has_asset_digest=False)
        name=release["asset"]["name"]
        sha=hashlib.sha256(archive).hexdigest()
        release["checksum_asset"]={
            "name":"SHA256SUMS.txt",
            "url":"https://github.com/"+releases.REPOSITORY+
                  "/releases/download/v2.0.10/SHA256SUMS.txt",
            "size":150
        }
        release["verified_package"]=True
        with patch.object(releases,"_open_trusted_download",
                          return_value=Download((sha+"  "+name+"\n").encode())):
            self.assertEqual(releases._expected_digest(release),sha)
        with patch.object(releases,"_open_trusted_download",
                          return_value=Download((sha+"  other-package.zip\n").encode())):
            with self.assertRaises(releases.ReleaseError):
                releases._expected_digest(release)

    def test_real_install_transaction_and_user_mod_safety(self):
        binary=make_zip({
            "ctr-native.exe":b"official new binary",
            "assets/config.ini":b"release defaults",
            "assets/shaders/main.glsl":b"shader contents",
        })
        release=fake_release(binary)
        with tempfile.TemporaryDirectory() as temp:
            game=Path(temp)/"game"
            game.mkdir()
            (game/"ctr-native.exe").write_bytes(b"existing binary")
            mods=game/"assets"/"mods"/"karts"/"personal"
            mods.mkdir(parents=True)
            (mods/"custom.ini").write_text("never overwrite")
            with patch.object(releases,"_game_running",return_value=False),\
                 patch.object(releases,"_open_trusted_download",
                              side_effect=lambda u:Download(binary)):
                result=releases.install_game_release(release,str(game))
            self.assertEqual(result["version"],"2.0.10")
            self.assertEqual((game/"ctr-native.exe").read_bytes(),b"official new binary")
            self.assertTrue((game/"assets"/"config.ini").exists())
            self.assertEqual((mods/"custom.ini").read_text(),"never overwrite")
            self.assertEqual(releases.game_installed_version(str(game)),"2.0.10")
            self.assertEqual((Path(result["backup"])/"ctr-native.exe").read_bytes(),
                             b"existing binary")

    def test_sha_and_unsafe_zip_fail_without_touching_game(self):
        with tempfile.TemporaryDirectory() as temp:
            game=Path(temp)/"game"
            game.mkdir()
            exe=game/"ctr-native.exe"
            exe.write_bytes(b"existing binary")
            good_zip=make_zip({"ctr-native.exe":b"new!"})
            bad_sha=fake_release(good_zip)
            bad_sha["asset"]["sha256"]="f"*64
            with patch.object(releases,"_game_running",return_value=False),\
                 patch.object(releases,"_open_trusted_download",
                              side_effect=lambda u:Download(good_zip)):
                with self.assertRaisesRegex(releases.ReleaseError,"SHA-256 mismatch"):
                    releases.install_game_release(bad_sha,str(game))
            self.assertEqual(exe.read_bytes(),b"existing binary")
            for bad_entries in [
                {"ctr-native.exe":b"bad","assets/mods/racers/a.ini":b"bad"},
                {"ctr-native.exe":b"bad","../evil.exe":b"bad"},
                {"ctr-native.exe":b"bad","setup.bat":b"bad"},
            ]:
                content=make_zip(bad_entries)
                with patch.object(releases,"_game_running",return_value=False),\
                     patch.object(releases,"_open_trusted_download",
                                  side_effect=lambda u:Download(content)):
                    with self.assertRaises(releases.ReleaseError):
                        releases.install_game_release(fake_release(content),str(game))
                self.assertEqual(exe.read_bytes(),b"existing binary")
                self.assertFalse((Path(temp)/"evil.exe").exists())

    def test_rollback_restores_existing_exe(self):
        data=make_zip({"ctr-native.exe":b"updated"})
        with tempfile.TemporaryDirectory() as temp:
            game=Path(temp)/"game"
            game.mkdir()
            exe=game/"ctr-native.exe"
            exe.write_bytes(b"original")
            original_replace=releases.os.replace
            failed=[False]
            def fail_once(src,dst):
                if not failed[0] and os.path.basename(src)=="ctr-native.exe" and\
                   os.path.normcase(dst)==os.path.normcase(str(exe)):
                    failed[0]=True
                    raise OSError("simulated blocked executable")
                return original_replace(src,dst)
            with patch.object(releases,"_game_running",return_value=False),\
                 patch.object(releases,"_open_trusted_download",
                              side_effect=lambda u:Download(data)),\
                 patch.object(releases.os,"replace",side_effect=fail_once):
                with self.assertRaisesRegex(releases.ReleaseError,"original files restored"):
                    releases.install_game_release(fake_release(data),str(game))
            self.assertTrue(failed[0])
            self.assertEqual(exe.read_bytes(),b"original")

if __name__=="__main__":
    unittest.main(verbosity=2)
