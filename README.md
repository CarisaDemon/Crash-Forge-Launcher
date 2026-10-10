# Crash Forge: Racing Launcher (Windows)

The independent launcher for **Crash Forge: Racing**, with Forge Hub community mods and GitHub Releases game updates.

**Official launcher repository:** https://github.com/CarisaDemon/Crash-Forge-Launcher  
**Game repository:** https://github.com/CarisaDemon/Crash-Forge-Racing  
**Mod catalog:** https://carisademon.github.io/Crash-Forge-Racing/forge-hub/

## Download for Windows

Open the [Launcher Releases](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases) page, download **Crash-Forge-Launcher-Windows.zip**, extract it into a writable folder and double-click **CrashForgeLauncher.exe**. The packaged Windows build does not require Python.

The ZIP also includes the separate **ForgeLauncherUpdater.exe** and the runtime files needed by the launcher. Do not move or delete its **_internal** or **assets** folders.

If no Releases are available, the launcher distribution has not been published yet. Do not download unofficial installers.

## Native tracks (experimental packager)

Model Importer v1.7 accepts only paired LEV + VRM files in its
CUSTOM TRACKS card. It validates basic headers and hashes, then installs
a non-destructive package to assets/mods/tracks/<track-id>/ with its
own track.ini. No OBJ tracks or retail Crash Cove replacements are made.
Runtime registration and menu selection are still needed before these
packages can be played; installing alone does not activate a track.

## Optional Model Importer

Starting with v0.3.35, the **EDITOR > MODEL IMPORTER** tool is optional: it is **not** downloaded automatically or packed inside the launcher ZIP. Click **INSTALL TOOL** to choose a separate, official GitHub Model Importer download. The standalone Windows EXE is checked against its SHA-256 before it is installed in the user's local Crash Forge tools directory, without changing the game or its mods. Installed tools show **OPEN TOOL** and can be updated voluntarily using **UPDATE TOOL**. Existing pre-v0.3.35 bundled Model Importer files remain usable; the updater does not silently erase those files. The tool includes native modular racers, kart colors and experimental LEV/VRM track package preparation.

## Separate automatic updates

This repository is exclusively for the **launcher application**, not game binaries or ripped game assets.

- The packaged launcher checks its own GitHub Releases automatically (at startup and about every six hours while open).
- If a newer stable launcher ZIP with a valid SHA-256 exists, the launcher downloads and verifies it in the background.
- The update is staged without touching the running app. The separate updater applies it **after you close the launcher**, and **reopens the updated `CrashForgeLauncher.exe` automatically**, without a console. The initial v0.3.28 release requires a one-time helper bootstrap for automatic restart on its first upgrade; without this bootstrap, users reopen the app once after moving to v0.3.29.
- Older launcher files are backed up, with a rollback attempt if replacement fails.
- Auto-update is enabled by default, with an **AUTO-UPDATE LAUNCHER** switch and a manual CHECK button in Settings.
- The Python development source deliberately never self-modifies.

**Game updates are completely separate:** UPDATE checks **CarisaDemon/Crash-Forge-Racing** for verified Windows game Releases and asks for confirmation before any game install.

When a game executable is detected, the launcher displays **PLAY** and **100% installed**. With no game installed, PLAY becomes **INSTALL** and stays disabled until an official verified stable Windows game ZIP exists.

**Original CTR-U disc diagnostic:** The launcher independently compares the user's local PS1 USA `assets/ctr-u.bin` against the Redump original in a background thread. A missing or different BIN logs an error only, with **no popup and no offline play restriction**. No ISO bytes or verification reports are sent online. See [ISO_INTEGRITY.md](ISO_INTEGRITY.md).

## Build Windows portable launcher

Requires Windows 10/11, Python 3.12 and PowerShell. Run the following commands:

    python -m pip install -r requirements-build.txt
    powershell -NoProfile -ExecutionPolicy Bypass -File release_tools\build_windows.ps1

Outputs (outside the source directory by default):

- Crash Forge Launcher Dist/dist/CrashForgeLauncher/ — portable Windows app folder.
- Crash Forge Launcher Dist/release/Crash-Forge-Launcher-Windows.zip — downloadable ZIP.
- Crash Forge Launcher Dist/release/Crash-Forge-Launcher-Windows.zip.sha256 — release checksum.
- Crash Forge Launcher Dist/release/CrashForgeModelImporter.exe and .exe.sha256 — optional editor download and its checksum (not included in launcher ZIP).

For CI use environment variable CFR_BUILD_DIR=build. Do not add private mod ZIPs, developer snapshots, personal settings or original game files to the launcher repository or its release bundles.

## Publishing new launcher versions

1. Bump **launcher_version.txt** (for example 0.3.29) and the changelog.
2. Run tests and commit the source to **main**. Include **[publish-launcher]** in the commit message to trigger a stable downloadable release, or push a matching tag such as **v0.3.29**.
3. GitHub Actions tests and builds the Windows package. A marked main commit creates the matching version tag and Release with the Windows ZIP and its SHA-256 automatically.
4. Ordinary commits without that marker do **not** publish a release; manual Actions runs only create build artifacts.
5. Existing public portable launchers then detect the newer verified version automatically.

The updater accepts only the official **Crash-Forge-Launcher-Windows.zip** from this pinned GitHub repository, with a matching SHA-256 obtained through GitHub asset metadata or a checksum sidecar.

## Security and legal notes

A GitHub SHA-256 checksum protects download integrity, but is not a third-party software signing certificate. Some unsigned executables can show Windows SmartScreen warnings. Code signing is recommended for broad distribution.

No GitHub token, private database key or personal installation settings are included in the package.

The launcher applies updates only when its own window closes. It does not force quit the game or interrupt gameplay. The public source can be viewed, but the owner has not yet granted a permissive redistribution license. Third-party game and media assets retain their original owners' rights.
