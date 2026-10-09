# CTR-U Base Disc Verification (Offline / Report Only)

Crash Forge: Racing's launcher now includes a **separate** ISO/BIN verifier. It does **not** replace the existing game updater, ZIP hashes, Repair or Forge Hub moderation.

**What it checks:** The original USA PS1 raw MODE2/2352 dump of Crash Team Racing, serial **SCUS-94426**. It uses the verified Redump fingerprint (also indexed by TASVideos):

- File expected in the game: `assets/ctr-u.bin` (legacy `ctr-u.bin` at game root is a fallback).
- Verified size: **605,698,800 bytes**.
- Verified SHA-1: `1bb785082def3fe25f6b46be06d4eaf33c5bc772`.
- Sector format: raw MODE2/2352, **not** a cooked 2048-byte ISO.
- Sources: https://redump.info/discs?letter=C&system=PSX and https://tasvideos.org/Games/1754/Versions/View/2383.

**When it checks:** In a daemon thread at launcher startup, after changing the installation folder, when pressing PLAY (only if the file changed since its last successful check), and after a verified game update. It calculates the whole-file SHA-1 and SHA-256 on the local machine. The menu and PLAY never wait for that computation.

**Mismatch behavior:** It writes a single technical `[CFR ISO] ERROR` line to stderr (when the app is launched from a terminal), Windows debugger output, and local logs. **It never displays a popup, warns in the UI, prevents offline racing, replaces the ISO, or uploads anything.**

Logs:

```text
%LOCALAPPDATA%\CrashForgeLauncher\logs\ctr_u_integrity.log
%LOCALAPPDATA%\CrashForgeLauncher\logs\ctr_u_attestations.jsonl
```

The JSONL report has the versioned schema `cfr.iso-attestation/1`, SHA-1/SHA-256 digest, reference identifier, measured size and one of the statuses `verified`, `modified`, `missing`, or `error`. It always includes `allow_play: true`, `policy: report_only`, `transport: none`, and `online_verified: false`. The format can be extended to support a future authenticated multiplayer check, but **the current implementation is fully offline and not an anti-cheat**. An exact-match Redump fingerprint verifies identity of the disc dump, not licensing or authorization.

A mismatch simply means the image does not exactly match this **specific** retail dump. Different valid disc editions, trimmed images or modifications may differ; a mismatch alone does not identify *why*. There is no SHA-1 collision resistance guarantee for adversarial anti-cheat: a future online protocol must rely on a trusted server and a stronger authentication model.

Manual verification from a developer command prompt (exit code **always 0**, even with mismatch):

```bat
python forge_iso_integrity.py "C:\Crash Team Racing\Crash Team Racing Compiled Custom Music"
```

**Tests:** `python -m unittest discover -s tests -p "test_iso_integrity.py" -v`. Tests create only tiny synthetic raw-mode discs and never include or distribute game files.
