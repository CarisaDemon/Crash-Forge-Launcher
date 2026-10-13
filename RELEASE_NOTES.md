![Crash Forge Launcher background](https://github.com/CarisaDemon/Crash-Forge-Launcher/releases/download/v0.3.56/forge-news-v0.3.56.webp)

# Crash Forge: Racing Launcher v0.3.56 - Safe PLAY & Auto-update Hotfix

This urgent Windows launcher hotfix addresses two reported problems without modifying the game, installed mods or saves.

- **No more five-second forced game exit:** Older Crash Forge: Racing executables can ignore unknown arguments. The previous Play Without Mods detection started an older game and terminated it after a five-second timeout. The launcher now checks native compatibility **without starting the game at all**.
- **Clear compatibility warning:** If the installed game does not support the --no-mods native argument, Play Without Mods shows a discreet status message (no popup) when a newer game release is needed; it will **not launch, time out or kill** the game. Play With Mods and Debug are unchanged.
- **Auto-update respects your choice:** Unchecking Auto-update Launcher prevents automatic staging, downloading and applying launcher updates. The preference must be explicitly enabled and saved; missing, malformed or disabled preferences default to OFF. Other launcher windows cannot silently restore an outdated setting.
- **No unrelated changes:** Forge Profiles, private Forge Hub cloud sync, Game Health Check, and same-monitor windows remain available.
- **Illustration:** Exactly the same original launcher Fondo.png artwork as before.

Launcher and game updates remain independent. This hotfix does **not** install or replace the game binary. Play Without Mods requires a compatible native game version.
