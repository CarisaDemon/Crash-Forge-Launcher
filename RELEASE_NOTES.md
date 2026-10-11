![Crash Forge Launcher official background](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases/download/v0.3.50/forge-news-v0.3.50.webp)

# Crash Forge: Racing Launcher v0.3.50 - Forge Hub Session & Mod Packager Account Fix

Windows snapshot / corrective update to v0.3.49.

- **Forge Hub account connection:** Supabase can reject expired/rotated refresh tokens with HTTP 400. The launcher now treats these as expired credentials, rather than looping on Reconnecting forever. It clearly offers **Sign in again**, without deleting your account or personal data. Genuine connectivity issues use bounded retry with backoff.
- **Token safety across multiple tools:** refresh-token renewal is synchronized between the launcher and separate editor EXEs on Windows; an editor can adopt the latest DPAPI-protected session when another process has already rotated it.
- **Sign-in required for Mod Packager:** selecting it in the launcher prompts for Forge Hub authentication when signed out. Opening the bundled CrashForgeModPackager.exe directly also requires a **server-verified** Forge Hub session before any packaging interface opens. The same Forge Hub user identity is used; no additional accounts are created.
- **Prior v0.3.49 features retained:** Model Importer, OGG and CSEQ share the game path saved in Launcher Settings, the Editor selector remains on the launcher's monitor, native Character/Kart/Wheels/Track Mod Packager includes previews, and arbitrary kart texture names remain supported.
- **Release artwork:** this version uses the launcher’s own Fondo.png rather than reusing unrelated illustrations.

A revoked/expired session cannot be silently restored by the launcher; if you see Sign in again after upgrading, authorize once in My Account (GitHub sign-in is supported). No user mod, ISO, save, secret token or game executable is distributed.
