"""No-window compiled EXE smoke tests, including a real compiled updater subprocess.

Tests only temporary mock installation folders. Does not open any GUI/game.
"""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
import forge_launcher_updates as updates

BUILD=Path(os.environ.get("CFR_BUILD_DIR") or
           (SOURCE.parent/"Crash Forge Launcher Dist"))
if not BUILD.is_absolute():
    BUILD=SOURCE/BUILD
PORTABLE=BUILD/"dist"/"CrashForgeLauncher"
MAIN=PORTABLE/updates.APP_EXE
HELPER=PORTABLE/updates.UPDATER_EXE


def no_window_run(cmd,timeout=40):
    kwargs={"timeout":timeout,"check":False,"capture_output":True,"text":True}
    if os.name=="nt":
        kwargs["creationflags"]=subprocess.CREATE_NO_WINDOW
        startup=subprocess.STARTUPINFO()
        startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow=0
        kwargs["startupinfo"]=startup
    return subprocess.run(cmd,**kwargs)


def release_zip():
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,"w",zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CrashForgeLauncher.exe",b"new mock launcher binary")
        archive.writestr("ForgeLauncherUpdater.exe",b"new mock helper binary")
        archive.writestr("launcher_version.txt",b"0.3.29\n")
        archive.writestr("assets/Fondo.png",b"new background")
    return memory.getvalue()


def main():
    assert MAIN.is_file() and HELPER.is_file()
    result=no_window_run([str(MAIN),"--self-test"])
    assert result.returncode==0,(
        "Packaged launcher failed background smoke: "+result.stderr[-1500:])
    print("PASS packaged launcher EXE self-test without showing window")

    binary=release_zip()
    expected=hashlib.sha256(binary).hexdigest()
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        app=root/"portable"
        app.mkdir()
        (app/"CrashForgeLauncher.exe").write_bytes(b"old mock launcher")
        (app/"ForgeLauncherUpdater.exe").write_bytes(b"old mock helper")
        (app/"launcher_version.txt").write_text("0.3.28")
        (app/"launcher_settings.json").write_text("personal")
        state=root/"state"
        url="https://github.com/"+updates.REPOSITORY+"/releases/download/v0.3.29/"+updates.ZIP_NAME
        release={
            "version":"0.3.29","tag":"v0.3.29","verified":True,
            "url":"https://github.com/"+updates.REPOSITORY+"/releases/tag/v0.3.29",
            "asset":{"name":updates.ZIP_NAME,"url":url,
                     "size":len(binary),"sha256":expected},
            "sha_asset":None
        }
        from unittest.mock import patch
        class Stream(io.BytesIO):
            def __init__(self,data):
                super().__init__(data)
                self.headers={"Content-Length":str(len(data))}
        with patch.object(updates,"_read_download",side_effect=lambda *_a,**_k:Stream(binary)):
            staged=updates.stage_release(release,"0.3.28",root=state)
        assert staged
        # Invalid PID is considered already exited by Windows; no user process
        # is touched, and the helper executes only against our temp folder.
        completed=no_window_run([
            str(HELPER),"--apply","--pid","999999",
            "--app-dir",str(app),
            "--stage",staged["payload"],
            "--manifest",staged["manifest"],
            "--state-dir",str(state),
        ],timeout=55)
        status=(state/"updater-result.txt").read_text(encoding="utf-8")
        assert completed.returncode==0 and status.startswith("SUCCESS"),(
            status+"\n"+completed.stderr[-1000:])
        assert (app/"CrashForgeLauncher.exe").read_bytes()==b"new mock launcher binary"
        assert (app/"launcher_settings.json").read_text()=="personal"
        assert (app/"launcher_version.txt").read_text().strip()=="0.3.29"
    print("PASS real compiled helper safely updates TEMP launcher and preserves settings")
    return 0


if __name__=="__main__":
    sys.exit(main())
