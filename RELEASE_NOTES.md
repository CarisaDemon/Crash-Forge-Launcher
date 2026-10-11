![Original Crash Forge Launcher background](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases/download/v0.3.45/forge-news-v0.3.45.webp)

# Crash Forge: Racing Launcher v0.3.45 — BIG UPDATE

**Windows launcher update — changes since v0.3.44.**

## Editor overhaul
- Fixed Editor: it now opens the bundled CrashForgeOGGToolkit.exe, CrashForgeCSEQToolkit.exe and CrashForgeModelImporter.exe directly, instead of searching for obsolete batch scripts.
- No command windows: launcher, updater and all three editors are Windows GUI executables. The OGG component is launched hidden.
- The Editor chooser and editor windows open on **the same monitor as the launcher**, including monitor 2 and displays with negative screen coordinates.
- All editors retain CF:R taskbar icons and share the game directory selected in Launcher Settings.
- Removed old batch launchers and temporary Python caches from the project; **no separate Python or pip installation required**.

## Manual game directory
- Removed automatic game searches, fixed fallback paths and silent changes to the selected directory.
- Your game directory changes **only when you explicitly select it in Settings**; it remains saved even if the folder or EXE is temporarily unavailable.
- Invalid or missing folders never get replaced by another folder. If nothing was selected, the launcher asks for a game folder before installing.
- A failed settings save keeps the previous selected folder.

## Independent launcher & game NEWS
- NEWS now shows official **Launcher** and **Game** releases together, with each article labeled by product.
- The projects keep **separate repositories, release numbers, ZIP downloads, and update checks**. Publishing a game build does not require a launcher version change.
- The GAME news feed refreshes every **10 minutes** in the background, with no popups, sound, focus stealing or automatic downloads.
- A small **NEW GAME RELEASE** marker appears when a new official game package is announced and clears when NEWS is read.
- Public experimental game releases appear as optional news; installing or updating the game **always requires explicit confirmation**.
- Launcher updates download launcher files only. Game updates download game files only, independently.

## Release validation
- Windows-only portable ZIP, bundled runtime and three editor EXEs, no old BAT launchers and no required external Python.
- SHA-256 manifest, Tcl/Tk, icons, monitor handoff, fixed Settings directory and both NEWS sources are covered by QA.
- The launcher ZIP does **not** include the game or original ISO; neither game saves nor mods are overwritten by this launcher update.

**Launcher-only BIG UPDATE. The game follows its own independent release schedule.**