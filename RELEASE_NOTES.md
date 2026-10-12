![Crash Forge Launcher background](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases/download/v0.3.52/forge-news-v0.3.52.webp)

# Crash Forge: Racing Launcher v0.3.52 — Modpacks & Forge Hub Tools

Windows-only launcher and independent modding tools update. **The game binary is a separate project and has not been replaced by this release.**

- **Uninstall web mods:** Installed Forge Hub mods now show **UNINSTALL** in cards and details. Confirmation first, Windows Recycle Bin on removal, rollback on failure. Local and unrelated mods stay untouched. Uninstalling a Modpack handles only its verified child modules.
- **Modpack creator:** The standalone Mod Packager builds one ZIP from **2–60 independent** native mods. Their characters, karts, wheels, tracks, images and INIs stay in separate game folders, each with a stable ID. Forge Hub Creator Studio also supports building and reviewing Modpack ZIPs.
- **Model Importer updates:** Open an OBJ beside its character.ini, kart.ini or wheels.ini to load existing offsets, seats, wheels, rotations and exhaust attachment positions. **Save INI** (Ctrl+S) edits the linked file with a backup and protects changed disk data.
- **Modular characters:** Character imports use modular body by default and omit the obsolete `has_wheels` field. Existing authored INIs are untouched until exported or explicitly saved. The corresponding native-game runtime change will be distributed independently.
- **3D editor previews:** Faster GPU rendering on compatible Windows OpenGL hardware, with CPU fallback; previous editor resize and texture gallery controls retained.
- **Web account stability:** Logging out of the Windows app no longer invalidates the separate browser session. Native wheel packages using `[wheel]` or `[wheels]` are accepted.
- **Original background artwork:** This update uses the actual `assets/Fondo.png` launcher background as its illustration, both in NEWS and on the release page.

This portable Windows ZIP includes the launcher, updater, OGG toolkit, CSEQ toolkit, Model Importer and Mod Packager. It contains no game executable, retail disc data, private saves or user mods. For custom native game behavior, update the game separately when its corresponding release becomes available.