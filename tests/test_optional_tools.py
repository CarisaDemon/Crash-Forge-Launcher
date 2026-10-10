"""Optional verified Windows model importer distribution (no network / no GUI)."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import forge_optional_tools as optional
import forge_launcher_updates as updates

VERSION="0.3.35"
BASE=f"https://github.com/{updates.REPOSITORY}/releases/download/v{VERSION}/"


class Stream(io.BytesIO):
    def __init__(self,data):
        super().__init__(data)
        self.headers={"Content-Length":str(len(data))}


def release_meta(data, host="github.com", valid_digest=True, tag=VERSION):
    sha=hashlib.sha256(data).hexdigest()
    return [{
        "tag_name":"v"+tag,"draft":False,"prerelease":False,
        "html_url":f"https://github.com/{updates.REPOSITORY}/releases/tag/v{tag}",
        "assets":[
            {"name":updates.ZIP_NAME,"size":1000,
             "browser_download_url":BASE+updates.ZIP_NAME,
             "digest":"sha256:"+("a"*64)},
            {"name":optional.TOOL_EXE,"size":len(data),
             "browser_download_url":f"https://{host}/{updates.REPOSITORY}/releases/download/v{tag}/"+optional.TOOL_EXE,
             "digest":"sha256:"+sha if valid_digest else ""}
        ]
    }]


class OptionalModelImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"optional-tools"
        self.binary=b"MZ"+b"\x90"*(10000)

    def test_find_exact_official_asset(self):
        result=optional.find_official_tool(release_meta(self.binary))
        self.assertEqual(result["version"], VERSION)
        self.assertEqual(result["asset"]["name"],optional.TOOL_EXE)
        self.assertEqual(result["asset"]["sha256"],hashlib.sha256(self.binary).hexdigest())

    def test_reject_other_host_and_unverified_asset(self):
        for payload in [release_meta(self.binary,host="evil.example"),
                        release_meta(self.binary,valid_digest=False)]:
            with self.assertRaises(updates.LauncherUpdateError):
                optional.find_official_tool(payload)

    def test_requires_explicit_download_no_file_at_start(self):
        with patch.object(updates,"_open_json",side_effect=AssertionError("Network access without user click")):
            self.assertIsNone(optional.installed_path(self.root))
        self.assertFalse(self.root.exists())

    def test_verified_install_and_stored_manifest(self):
        release=optional.find_official_tool(release_meta(self.binary))
        with patch.object(updates,"_read_download",return_value=Stream(self.binary)):
            path=optional.install_tool(release,root=self.root)
        self.assertEqual(path.read_bytes(),self.binary)
        self.assertEqual(optional.installed_version(self.root),VERSION)
        self.assertEqual(json.loads((self.root/optional.METADATA_NAME).read_text())["repository"],
                         updates.REPOSITORY)

    def test_reject_sha_mismatch_preserves_existing(self):
        release=optional.find_official_tool(release_meta(self.binary))
        with patch.object(updates,"_read_download",return_value=Stream(self.binary)):
            optional.install_tool(release,root=self.root)
        older=self.root/optional.TOOL_EXE
        tampered=b"MZ"+b"A"*10000
        with patch.object(updates,"_read_download",return_value=Stream(tampered)):
            with self.assertRaisesRegex(updates.LauncherUpdateError,"SHA-256"):
                optional.install_tool(release,root=self.root)
        self.assertEqual(older.read_bytes(),self.binary)
        self.assertEqual(optional.installed_version(self.root),VERSION)

    def test_reject_non_executable_even_if_hash_matches(self):
        invalid=b"NOT_WINDOWS"+b"."*10000
        release=optional.find_official_tool(release_meta(invalid))
        with patch.object(updates,"_read_download",return_value=Stream(invalid)):
            with self.assertRaisesRegex(updates.LauncherUpdateError,"not a Windows EXE"):
                optional.install_tool(release,root=self.root)
        self.assertFalse((self.root/optional.TOOL_EXE).exists())

    def test_missing_sidecar_mismatch(self):
        entry=release_meta(self.binary,valid_digest=False)[0]
        entry["assets"].append({
            "name":optional.TOOL_EXE+".sha256","size":96,
            "browser_download_url":BASE+optional.TOOL_EXE+".sha256"})
        release=optional.find_official_tool([entry])
        with patch.object(updates,"_read_download",return_value=Stream(
                ("f"*64+"  Wrong.exe\n").encode())):
            with self.assertRaises(updates.LauncherUpdateError):
                optional.install_tool(release,root=self.root)

    def test_asset_not_auto_in_launcher_zip(self):
        build=(Path(__file__).resolve().parents[1]/
               "release_tools"/"build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('$optionalRelease = Join-Path $releaseRoot "CrashForgeModelImporter.exe"',build)
        self.assertNotIn('Join-Path $toolsTarget "CrashForgeModelImporter.exe"',build)

    def test_installed_checksum_tamper_detected(self):
        release=optional.find_official_tool(release_meta(self.binary))
        with patch.object(updates,"_read_download",return_value=Stream(self.binary)):
            optional.install_tool(release,root=self.root)
        (self.root/optional.TOOL_EXE).write_bytes(b"MZ"+b"\x01"*10000)
        self.assertIsNone(optional.installed_path(self.root))

    def test_news_asset_is_officially_allowed(self):
        self.assertNotIn("assets/news/latest_update.webp", updates._OFFICIAL_ASSETS)


if __name__=="__main__":
    unittest.main()
