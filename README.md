# Crash Forge: Racing Launcher (Windows)

The independent launcher for **Crash Forge: Racing**, with Forge Hub community mods and GitHub Releases game updates.

**Official launcher repository:** https://github.com/CarisaDemon/Crash-Forge-Launcher  
**Game repository:** https://github.com/CarisaDemon/Crash-Forge-Racing  
**Mod catalog:** https://carisademon.github.io/Crash-Forge-Racing/forge-hub/

## Download for Windows

Open the [Launcher Releases](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases) page, download **Crash-Forge-Launcher-Windows.zip**, extract it into a writable folder and double-click **CrashForgeLauncher.exe**. The packaged Windows build does not require Python.

The ZIP also includes the separate **ForgeLauncherUpdater.exe** and the runtime files needed by the launcher. Do not move or delete its **_internal** or **assets** folders.

If no Releases are available, the launcher distribution has not been published yet. Do not download unofficial installers.

## Separate automatic updates

This repository is exclusively for the **launcher application**, not game binaries or ripped game assets.

- The packaged launcher checks its own GitHub Releases automatically (at startup and about every six hours while open).
- If a newer stable launcher ZIP with a valid SHA-256 exists, the launcher downloads and verifies it in the background.
- The update is staged without touching the running app. The separate updater applies it **after you close the launcher**, so the updated version is ready next time you open it.
- Older launcher files are backed up, with a rollback attempt if replacement fails.
- Auto-update is enabled by default, with an **AUTO-UPDATE LAUNCHER** switch and a manual CHECK button in Settings.
- The Python development source deliberately never self-modifies.

**Game updates are completely separate:** UPDATE checks **CarisaDemon/Crash-Forge-Racing** for verified Windows game Releases and asks for confirmation before any game install.

When a game executable is detected, the launcher displays **PLAY** and **100% installed**. With no game installed, PLAY becomes **INSTALL** and stays disabled until an official verified stable Windows game ZIP exists.

## Build Windows portable launcher

Requires Windows 10/11, Python 3.12 and PowerShell. Run the following commands:

    python -m pip install -r requirements-build.txt
    powershell -NoProfile -ExecutionPolicy Bypass -File release_tools\build_windows.ps1

Outputs (outside the source directory by default):

- Crash Forge Launcher Dist/dist/CrashForgeLauncher/ — portable Windows app folder.
- Crash Forge Launcher Dist/release/Crash-Forge-Launcher-Windows.zip — downloadable ZIP.
- Crash Forge Launcher Dist/release/Crash-Forge-Launcher-Windows.zip.sha256 — release checksum.

For CI use environment variable CFR_BUILD_DIR=build. Do not add private mod ZIPs, developer snapshots, personal settings or original game files to the launcher repository or its release bundles.

## Publishing new launcher versions

1. Bump **launcher_version.txt** (for example 0.3.29) and the changelog.
2. Run tests and push the source.
3. Push a matching semantic version tag, e.g. v0.3.29.
4. GitHub Actions builds the Windows release, generates the SHA-256 and publishes both assets.
5. Existing public portable launchers detect the new verified version automatically.

The updater accepts only the official **Crash-Forge-Launcher-Windows.zip** from this pinned GitHub repository, with a matching SHA-256 obtained through GitHub asset metadata or a checksum sidecar.

## Security and legal notes

A GitHub SHA-256 checksum protects download integrity, but is not a third-party software signing certificate. Some unsigned executables can show Windows SmartScreen warnings. Code signing is recommended for broad distribution.

No GitHub token, private database key or personal installation settings are included in the package.

The launcher applies updates only when its own window closes. It does not force quit the game or interrupt gameplay. The public source can be viewed, but the owner has not yet granted a permissive redistribution license. Third-party game and media assets retain their original owners' rights.
