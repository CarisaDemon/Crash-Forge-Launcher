![Crash Forge Launcher background](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases/download/v0.3.51/forge-news-v0.3.51.webp)

# Crash Forge: Racing Launcher v0.3.51 - Resizable Editor Workspaces

Windows editor layout and preview quality-of-life update.

- **Resizable Mod Packager panels:** drag orange dividers to decide how much room the mod form, real UV-mapped 3D preview, and texture thumbnails occupy. The model is no longer locked to an overly large or tiny fixed viewport.
- **Resizable Model Importer:** drag the separator between 3D preview and texture gallery, change the overall preview section height with its slider, and adjust the character settings columns on wider screens. Narrow and 4:3 windows continue to stack content accessibly.
- **Remember your workspace:** both tools independently save window size, screen position, maximized state and adjustable divider positions under the local user's app settings. The layout is restored when reopened, including on a secondary monitor; disconnected-screen positions are ignored.
- **UV-correct model rendering:** OBJ previews now draw the actual texture pixels rather than one sampled color per triangle, use proper UV interpolation and depth buffering, and keep all original model assets untouched.
- **Fondo.png release illustration:** uses the launcher background requested for v0.3.51.
- **Existing safeguards retained:** sign-in is still required to open Mod Packager; account fixes, game path selection, browser Creator Studio, and the independent game updater are unchanged.

Native LEV track preview shows geometry and vertex colors only; full VRM atlas decoding is not supported. No original CTR game data, mods, saves or account credentials are included in the Windows release.
