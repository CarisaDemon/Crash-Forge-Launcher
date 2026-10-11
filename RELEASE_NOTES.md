![Crash Forge Launcher background](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases/download/v0.3.49/forge-news-v0.3.49.webp)

# Crash Forge: Racing Launcher v0.3.49 - Editor Expansion & Account Reliability

Windows maintenance and creator-tools release.

- New **Mod Packager** is the fourth Editor tool, alongside OGG, CSEQ/MIDI and Model Importer. Import native Character, Kart, Wheels or Track files, validate them and export structured ZIP packages for the existing Forge Hub review system. Runs as a separate Windows GUI without visible console windows.
- **Live 3D previews in both Model Importer and Mod Packager** for characters, karts, wheels (Wavefront OBJ with MTL textures) and native CTR tracks (LEV geometry and vertex colors). Mouse drag rotates and scroll zooms; image thumbnails show filenames and sizes. Note: full VRM atlas decoding and in-game materials are not yet available for track previews.
- **Unified Kart Variants:** one texture manager instead of duplicated controls, auto-detection of PNG/BMP atlases, visible thumbnails, individual selection and user-editable display names. Custom names (including patterns and multicolored skins) are written to native kart.ini [colors] instead of being limited to Blue/Red/Lime/Pink. The original OBJ, MTL and offsets are preserved. Up to 12 variants including original, matching the game.
- **One launcher-selected game installation** for all four tools. Editor GUI uses Launcher Settings directly; manual game-root browse and source-tree fallback are removed. No automatic replacement or searching across other drives. Source file pickers (MIDI, OGG, OBJ, LEV, VRM, textures) remain independent.
- **Editor selector monitor fix**: borderless 2x2 tool selector remains with the launcher even when that monitor has negative virtual-desktop coordinates. The tools open on the launcher's monitor.
- **Forge Hub account status repair**: a temporary server/network error displays Reconnecting instead of incorrectly implying logout; automatic retry after 25 seconds, preserved encrypted account metadata, and an explicit Sign in again state when Supabase rejects an expired session.
- The Forge Hub website already offers a native guided Mod Packager with in-browser ZIP creation, export and GitHub-authenticated private review; the launcher and game continue to update independently.

Official game data, saves, user mods and personal account tokens are never included. Any ZIP uploaded by a creator remains subject to Forge Hub moderation.
