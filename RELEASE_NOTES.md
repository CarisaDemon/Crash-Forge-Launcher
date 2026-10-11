![Forge Hub account: Guest profile widget](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases/download/v0.3.43/forge-news-v0.3.43.webp)

# Crash Forge: Racing Launcher v0.3.43

**Changes since v0.3.42 (Windows).** This release contains the account work, UI changes and fixes made after the last published launcher. **The game itself is not updated by this download.**

## Forge Hub identity and login
- Added a **Forge Hub account system** inside the launcher: GitHub login opens the browser; email or username with password is supported; new accounts can register and confirm their email.
- Existing Forge Hub identities can connect through a short-lived, one-time browser approval code. The account links to the same Forge Hub creator identity; no parallel user database is created.
- Added a profile view, account username management, GitHub provider-link flow and explicit sign out. GitHub passwords are never entered inside the launcher.
- Session refresh credentials are protected with Windows DPAPI; account network requests run without blocking the game launcher window.

## Account widget / menus
- A **single compact profile widget** now lives in the upper-right header, with your GitHub avatar when available, username and connection indicator.
- **Guest** mode has a visible person silhouette, gray status and only **LOG IN / OPEN FORGE HUB** in the popup. A verified active session shows a green **Online** indicator, **MY ACCOUNT / OPEN FORGE HUB / SIGN OUT**.
- Styled the popup with Crash Forge's orange borders; removed the duplicate **ACCOUNT** header button.
- Fixed the modal account popup that could freeze input or resist closing. Account window and launcher now close independently.

## Windows and multi-monitor
- The account popup now stays beside the user widget on **whichever monitor** contains the launcher; it also follows window movement.
- **Fit to Window / maximize** now uses the active monitor's work area instead of jumping from monitor 2 to monitor 1. Restore returns to the previous size and position.
- Improved desktop coordinate handling for secondary monitors with negative positions and taskbar space.

## Portable release and safety
- The ZIP remains a **standalone Windows app** with embedded Python/Tk/Pillow runtime, launcher updater, and bundled OGG, CSEQ/MIDI and Model Importer executables. **No system Python or pip install is needed.**
- Expanded build checks for portable use with Python removed from PATH, verified extracted ZIPs, account login safety, menu interactions, second-monitor behavior and integrity/rollback checks.
- Existing game installation, saves, ISO/disc image, settings and mods are **not** changed by this launcher update.

**Notes:** Internet access is required for live Forge Hub sign-in. The OGG editor's optional advanced FFmpeg operation can offer an FFmpeg download when needed. Extract the official launcher ZIP intact instead of moving only the EXE.