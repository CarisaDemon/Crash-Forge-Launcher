"""Create NEWS illustration from the actual bundled Crash Forge launcher background.

Called by Windows release CI after build dependencies are installed.
Writes ONLY current release art and latest_update.webp. Historical images
and original assets/Fondo.png remain byte-for-byte untouched.
"""
from __future__ import annotations

from pathlib import Path
import re

from PIL import Image


def prepare(root: Path):
    version=(root/"launcher_version.txt").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+",version):
        raise ValueError("Invalid launcher version")
    source=root/"assets"/"Fondo.png"
    if not source.is_file() or source.stat().st_size<10000:
        raise FileNotFoundError("Missing genuine launcher Fondo.png")
    folder=root/"assets"/"news"
    folder.mkdir(parents=True,exist_ok=True)
    release=folder/f"forge-news-v{version}.webp"
    latest=folder/"latest_update.webp"
    with Image.open(source) as image:
        img=image.convert("RGB")
        if img.width<1000 or img.height<600:
            raise ValueError("Launcher background is too small for NEWS")
        img.save(release,format="WEBP",quality=90,method=6)
        img.save(latest,format="WEBP",quality=90,method=6)
    with Image.open(release) as check:
        if check.size!=(img.width,img.height):
            raise ValueError("Invalid release artwork dimensions")
    print("RELEASE ARTWORK:",release)
    print("FEATURED HOME NEWS:",latest)
    print("SOURCE:",source,"size",img.size)


if __name__=="__main__":
    prepare(Path(__file__).resolve().parents[1])