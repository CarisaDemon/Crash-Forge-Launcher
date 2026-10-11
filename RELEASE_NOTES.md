![Crash Forge OGG Toolkit showing native custom music](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases/download/v0.3.44/forge-news-v0.3.44.webp)

# Crash Forge: Racing Launcher v0.3.44

**Changes since v0.3.43 — Windows Launcher and bundled editor tools.**

## Shared game installation
- **OGG Toolkit, CSEQ/MIDI Toolkit and Model Importer** now automatically use the game installation selected in Launcher Settings, even when opened directly from their own EXEs.
- The selected game path is validated before use; if the launcher has not configured a game yet, you can choose a folder manually.
- CSEQ has a clearly visible **GAME INSTALLATION / BROWSE GAME** bar on every tab, plus a **REFRESH MODS** action.
- Existing installations, mods, configuration and saved games are not changed by updating the launcher.

## Music track detection
- OGG Toolkit automatically discovers available music destinations and custom tracks, even when an OGG file has not been installed yet.
- Both OGG and CSEQ now discover enabled native track modules from the game's mods folders when the configured installation is available, including legacy assets/mods/tracks.
- CSEQ's list can show tracks such as **My Custom Track** using its native track.ini; OGG shows these modules even when no custom OGG is assigned yet.
- Custom native tracks remain experimental: discovery in the editors does **not** mean that the game-side track loader and collision behavior have been finalized.

## Native Windows editor windows
- Restored the **CF:R logo on the OGG Toolkit title header**, with a real form icon and Windows taskbar identity.
- Improved taskbar icon handling in the **CSEQ Toolkit and Model Importer**.
- The OGG Toolkit launches Windows PowerShell silently, using a hidden background process rather than a visible console.
- All three editors ship as self-contained Windows GUI EXEs, bundled with the launcher. **No installation of Python or pip is needed**; the OGG GUI uses Windows PowerShell/.NET already included with Windows.
- The OGG Toolkit script is encoded correctly for Windows PowerShell 5.1, avoiding non-ASCII character parse errors on machines using older locale settings.

## Package validation
- Expanded clean portable ZIP checks to verify all three editors launch without system Python.
- Added an OGG WinForms interface test covering the logo, taskbar and native track discovery.
- Keeps the launcher updater, separate editor EXEs and file-integrity validation intact.

**Windows only.** This is a launcher/editor update, not the v2.1.0 game release. The original CTR disc image is not included or required to open the launcher/editor tools.