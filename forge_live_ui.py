"""Live data wiring for Crash Forge Launcher, isolated from its artwork/layout."""
import json
import os
import sys
import queue
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from tkinter import messagebox, simpledialog

import forge_services as services
import forge_releases as releases
import forge_launcher_updates as launcher_updates
import forge_iso_integrity as iso_integrity
from forge_version_dialog import ask_play_outdated


def available_game_update(game_path, release):
    """Verified game release needing action; keep 'unknown' distinct from old.

    Only authoritative GitHub game-release metadata can trigger the warning,
    never unrelated launcher versions, offline checks or unverified assets.
    """
    if not isinstance(release, dict) or not release.get("verified_package"):
        return None
    version = str(release.get("version") or "")
    if releases.parse_version(version) is None:
        return None
    installed = releases.game_installed_version(game_path)
    comparison = releases.compare_versions(installed, version)
    if comparison in (0, 1):
        return None
    return {"installed": installed, "available": version,
            "unknown": comparison is None}


class ForgeLiveMixin:
    def _post_init_live(self):
        self.remote_mods = []
        self.remote_news = []
        self.github_release_news = []
        self.remote_feed = {}
        self.online_status = "PUBLIC FEED NOT CONFIGURED"
        self.online_queue = queue.Queue()
        self.online_busy = False
        self.mod_download_busy = False
        self.game_update_busy = False
        self.release_check_busy = False
        self.launcher_update_busy = False
        self.launcher_update_ready = None
        self._launcher_update_retry_after = 0.0
        self._release_install_after_pending = False
        self.latest_game_release = None
        self._release_retry_after = 0.0
        self.online_cfg = services.read_online_config(self._forge_base_dir())
        self.installed_mods_record = self._load_installed_mods_record()
        self._refresh_real_install_ui()
        # Offline CTR-U audit; no dialogs or restriction on local gameplay.
        try:
            iso_integrity.start_background_check(self.game_install_path, "launcher_start")
        except Exception:
            pass  # ISO diagnostics must never break launcher startup.
        self._render_real_news()
        self._refresh_hub_source_status()
        if self.online_cfg.get("feed_url"):
            self._reload_live_source()
        if getattr(self, "_auto_recovered_game_path", False):
            self.status_label.configure(
                text="Detected an existing ctr-native.exe and recovered its install folder.")
        self.after(1600, self._startup_release_check)
        self.after(2700, self._startup_launcher_update_check)
        self.after(3600000, self._scheduled_launcher_update_check)
        self.after(60000, self._scheduled_release_check)
        self.after(250, self._poll_live_updates)

    def _forge_base_dir(self):
        return (os.path.dirname(os.path.abspath(sys.executable))
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__)))

    def _load_installed_mods_record(self):
        path = os.path.join(self._forge_base_dir(), "installed_mods.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
            return record if isinstance(record, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_installed_mods_record(self):
        path = os.path.join(self._forge_base_dir(), "installed_mods.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.installed_mods_record, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    def _primary_game_action(self):
        """PLAY if installed; INSTALL only when an official checked game ZIP exists."""
        status = services.real_game_status(self.game_install_path)
        if status["installed"]:
            self._play_installed_game()
            return
        release = self.latest_game_release
        if release and release.get("verified_package"):
            self._confirm_release_install(release)
        else:
            self.status_label.configure(
                text="INSTALL unavailable until a stable Windows game release is published.")

    def _update_primary_game_button(self):
        """Keep the large UPDATE button; swap the orange/grey emphasis by need.

        UPDATE remains clickable when grey so it can manually recheck GitHub.
        PLAY also stays clickable when grey: we never force a game update.
        """
        buttons = getattr(self, "sidebar_buttons", None)
        if not buttons or len(buttons) < 2:
            return
        main, update = buttons[:2]
        installed = bool(getattr(self, "local_game_status", {}).get("installed"))
        release = getattr(self, "latest_game_release", None)
        verified = bool(release and release.get("verified_package"))
        update_available = installed and bool(
            available_game_update(self.game_install_path, release))
        updating = bool(getattr(self, "game_update_busy", False))

        main.set_label("PLAY" if installed else "INSTALL")
        main.set_disabled((not installed and not verified) or updating)
        main.set_accent((installed and not update_available) or
                        (not installed and verified))

        # The user's forged UPDATE button is NEVER removed or replaced by
        # a duplicate in Settings. Muted when no verified game update exists.
        update.set_disabled(updating)
        update.set_accent(bool(update_available))

    def _refresh_real_install_ui(self):
        status = services.real_game_status(self.game_install_path)
        self.local_game_status = status
        self._update_primary_game_button()
        if hasattr(self, "build_state_label"):
            self.build_state_label.configure(
                text="LOCAL GAME FOUND" if status["installed"] else "NOT INSTALLED")
            self.build_indicator.configure(fg="#56C47A" if status["installed"] else "#D49A4A")
        if (hasattr(self, "download_percent")
                and not self.mod_download_busy
                and not self.game_update_busy):
            self.set_download_status(
                percent=100 if status["installed"] else 0,
                state="INSTALLED" if status["installed"] else "NOT INSTALLED",
                filename=status["detail"],
                amount="Local game executable detected" if status["installed"]
                else "Select a game folder in Settings",
                time_remaining="Ready to play" if status["installed"] else "No game found",
            )
        if hasattr(self, "hero_canvas"):
            self._paint_hero()

    def _live_news_fallback(self):
        version, notes = services.real_launcher_changelog(self._forge_base_dir(), limit=2)
        result = [{
            "category": "LOCAL LAUNCHER",
            "title": "Launcher " + (version or "build available"),
            "description": notes[0] if notes else "Local changelog is available.",
            "date": "LOCAL",
            "url": "",
        }]
        if not self.online_cfg.get("feed_url"):
            result.append({
                "category": "PUBLIC NEWS",
                "title": "No public news source configured",
                "date": "",
                "description": "Set an HTTPS feed in Forge Hub to show published updates.",
                "url": "",
            })
        return result

    def _render_real_news(self):
        if not hasattr(self, "news_rows"):
            return
        for child in self.news_rows.winfo_children():
            child.destroy()
        from tkinter import Frame, Label
        items = (self.github_release_news +
                 (self.remote_news if self.remote_news else self._live_news_fallback()))[:3]
        for item in items:
            row = Frame(self.news_rows, bg="#111419")
            row.pack(fill="x", pady=(0, 6))
            body = Frame(row, bg="#111419")
            body.pack(side="left", fill="both", expand=True, padx=9, pady=7)
            category = str(item.get("category") or "NEWS").upper()
            title = str(item.get("title") or "")[:70]
            Label(body, text=category, bg="#111419", fg="#E2A36A",
                  font=("Bahnschrift SemiBold", 7), anchor="w").pack(anchor="w")
            Label(body, text=title, bg="#111419", fg="#E5E5E1",
                  font=("Bahnschrift SemiBold", 9), anchor="w",
                  wraplength=310, justify="left").pack(anchor="w")
            when = str(item.get("date") or "").strip()
            if when:
                Label(row, text=when, bg="#111419", fg="#858990",
                      font=("Bahnschrift", 7)).pack(side="right", padx=8)
            url = item.get("url", "")
            try:
                url = services.checked_https_url(url)
            except services.FeedError:
                url = ""
            if url:
                row.bind("<Button-1>", lambda e, link=url: webbrowser.open(link))
                body.bind("<Button-1>", lambda e, link=url: webbrowser.open(link))
                row.configure(cursor="hand2")
        if hasattr(self, "_resize_news_content"):
            self._resize_news_content()

    def _open_all_news(self):
        if self.github_release_news or self.remote_news:
            for entry in self.github_release_news + self.remote_news:
                try:
                    link = services.checked_https_url(entry.get("url"))
                    webbrowser.open(link)
                    return
                except services.FeedError:
                    pass
        self.status_label.configure(text="No published news link is available yet.")

    def _refresh_hub_source_status(self):
        label = getattr(self, "hub_source_label", None)
        if label:
            label.configure(text=self.online_status + "  (SOURCE)")

    def _configure_feed_source(self):
        current = self.online_cfg.get("feed_url", "")
        feed = simpledialog.askstring(
            "Forge Hub - Public Source",
            "Paste the HTTPS URL of the public Crash Forge JSON catalog.\n"
            "Leave empty to disconnect the public catalog.",
            initialvalue=current, parent=self)
        if feed is None:
            return
        feed = feed.strip()
        submission = simpledialog.askstring(
            "Forge Hub - Submissions",
            "HTTPS URL where creators submit mods (optional).\n"
            "For example: a GitHub Issues or community submission page.",
            initialvalue=self.online_cfg.get("submit_url", ""), parent=self)
        if submission is None:
            return
        try:
            services.save_online_config(
                self._forge_base_dir(), {"feed_url": feed, "submit_url": submission.strip()})
        except (services.FeedError, OSError) as exc:
            messagebox.showerror("Forge Hub", str(exc), parent=self)
            return
        self.online_cfg = services.read_online_config(self._forge_base_dir())
        self.remote_mods = []
        self.remote_news = []
        self.remote_feed = {}
        self.online_status = "PUBLIC FEED NOT CONFIGURED"
        self._render_real_news()
        self._refresh_hub_source_status()
        self._render_hub_cards()
        if feed:
            self._reload_live_source()

    def _reload_live_source(self):
        if self.online_busy:
            return
        url = self.online_cfg.get("feed_url", "")
        if not url:
            self.online_status = "PUBLIC FEED NOT CONFIGURED"
            self._refresh_hub_source_status()
            return
        self.online_busy = True
        self.online_status = "CONNECTING..."
        self._refresh_hub_source_status()

        def worker():
            try:
                feed = services.fetch_public_feed(url)
                news = services.clean_news(feed)
                mods = services.clean_mods(feed)
                self.online_queue.put(("feed_ok", (url, feed, news, mods)))
            except Exception as exc:
                self.online_queue.put(("feed_error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="ForgeOnlineFeed").start()

    def _poll_live_updates(self):
        while True:
            try:
                event, data = self.online_queue.get_nowait()
            except queue.Empty:
                break
            if event == "feed_ok":
                url, feed, news, mods = data
                self.online_busy = False
                # A response from the old feed URL must not replace the new one.
                if url != self.online_cfg.get("feed_url"):
                    continue
                self.remote_feed = feed
                self.remote_news = news
                self.remote_mods = mods
                self.online_status = f"ONLINE - {len(mods)} CFR MODS"
                self._refresh_hub_source_status()
                self._render_real_news()
                if self.hub_overlay.winfo_ismapped():
                    self._render_hub_cards()
                self.hub_status_label.configure(
                    text=f"Online catalog connected; {len(mods)} compatible published mods.")
            elif event == "feed_error":
                self.online_busy = False
                self.remote_mods = []
                self.remote_news = []
                self.remote_feed = {}
                self.online_status = "OFFLINE"
                self._refresh_hub_source_status()
                self._render_real_news()
                if self.hub_overlay.winfo_ismapped():
                    self._render_hub_cards()
                self.hub_status_label.configure(text=("Public source unavailable: " + data)[:160])
            elif event == "launcher_update_progress":
                phase, done, total, version = data
                self.launcher_update_status_var.set(
                    "Launcher v" + version + ": " +
                    ("Downloading" if phase == "download" else "Verifying / staging") +
                    " " + (f"{(done / total * 100):.0f}%" if total else "..."))
            elif event == "launcher_update_ok":
                self.launcher_update_busy = False
                release, pending, installed, manual, portable = data
                self.launcher_last_check = time.time()
                self._launcher_update_retry_after = 0
                if pending and self.launcher_auto_update:
                    self.launcher_update_ready = pending
                    self._set_restart_buttons_enabled(True)
                    result = ("Launcher v" + pending["version"] +
                              " verified; the updated EXE will open automatically " +
                              "after you close this launcher.")
                elif release and launcher_updates.newer_release(release, installed):
                    result = ("Launcher v" + release["version"] +
                              " available. " +
                              ("Auto-update disabled." if not self.launcher_auto_update else
                               "Portable EXE migration available; activate auto-update."
                               if not portable else
                               "Download is waiting for the next auto-check."))
                elif not release:
                    result = "No public Launcher releases yet."
                else:
                    result = "Launcher is up to date (v" + installed + ")."
                self.launcher_last_result = result
                self.launcher_update_status_var.set(result)
                self._save_launcher_settings()
                if manual:
                    self.status_label.configure(text=result)
            elif event == "launcher_update_error":
                self.launcher_update_busy = False
                message, manual = data
                self._launcher_update_retry_after = time.time() + 15 * 60
                result = "Launcher update unavailable: " + message[:105]
                self.launcher_update_status_var.set(result)
                if manual:
                    self.status_label.configure(text=result[:170])
            elif event == "release_ok":
                self.release_check_busy = False
                release, manual, request_install = data
                if self._release_install_after_pending:
                    manual, request_install = True, True
                self._release_install_after_pending = False
                self._release_retry_after = 0
                self._show_release_check(release, manual, request_install)
            elif event == "release_error":
                self.release_check_busy = False
                error, manual = data
                if self._release_install_after_pending:
                    manual = True
                self._release_install_after_pending = False
                self._release_retry_after = time.time() + 15 * 60
                self.release_status_var.set("GitHub unavailable · retry in 15 min")
                if manual:
                    self.status_label.configure(
                        text=("GitHub check failed: " + error)[:180])
                # Failed checks never turn an installed game into 0%.
            elif event == "game_progress":
                phase, done, total, speed, version = data
                ratio = float(done) / max(1, total)
                if phase == "download":
                    pct = min(80, ratio * 80) if total else 0
                    mb = 1048576.0
                    description = f"{done / mb:.1f} / {total / mb:.1f} MB" if total else f"{done / mb:.1f} MB"
                    description += f"  {speed / mb:.1f} MB/s" if speed else ""
                    stage = "DOWNLOADING VERIFIED GAME"
                elif phase == "extract":
                    pct, description, stage = 80 + ratio * 10, "Checking game ZIP contents", "EXTRACTING"
                elif phase == "install":
                    pct, description, stage = 90 + ratio * 9, "Backing up and updating game files", "INSTALLING"
                else:
                    pct, description, stage = 100, "SHA-256 verified", "INSTALLED"
                self.set_download_status(
                    percent=pct, state=stage,
                    filename="Official GitHub game release · v" + version,
                    amount=description, time_remaining="Please keep the launcher open",
                )
            elif event == "game_installed":
                self.game_update_busy = False
                self._refresh_real_install_ui()
                try:
                    iso_integrity.start_background_check(self.game_install_path, "game_updated")
                except Exception:
                    pass
                self.release_status_var.set(
                    "Installed official game v" + data["version"])
                self.status_label.configure(
                    text="Updated " + str(data["files"]) +
                         " files to v" + data["version"] +
                         "; previous files backed up.")
                self.set_download_status(
                    percent=100, state="INSTALLED",
                    filename="Crash Forge: Racing · v" + data["version"],
                    amount=str(data["files"]) + " verified files installed",
                    time_remaining="Backup preserved",
                )
            elif event == "game_update_error":
                self.game_update_busy = False
                self._refresh_real_install_ui()
                valid = self.local_game_status["installed"]
                self.set_download_status(
                    percent=100 if valid else 0,
                    state="UPDATE FAILED",
                    filename=str(data)[:125],
                    amount="Existing game detected" if valid else "No installed game detected",
                    time_remaining="See error for rollback details",
                )
                self.status_label.configure(text=("GitHub update stopped: " + str(data))[:200])
            elif event == "mod_progress":
                done, total, speed = data
                pct = done * 100.0 / total if total > 0 else 0
                mb = 1048576.0
                total_text = f"{total / mb:.1f} MB" if total else "size unknown"
                self.set_download_status(
                    percent=pct, state="DOWNLOADING MOD",
                    filename="Verified ZIP transfer (SHA-256)",
                    amount=f"{done / mb:.1f} / {total_text}  ({speed / mb:.1f} MB/s)",
                    time_remaining=(f"{max(0, (total-done)/max(speed, 1)):.0f}s remaining"
                                    if total else "Receiving data"))
                self.hub_status_label.configure(text=f"Downloading mod: {pct:.0f}%" if total else
                                               f"Downloading mod: {done / mb:.1f} MB")
            elif event == "mod_ok":
                mod, destination = data
                self.mod_download_busy = False
                self.installed_mods_record[mod["id"]] = {
                    "version": mod["version"], "path": destination,
                    "game_path": os.path.normcase(self.game_install_path),
                    "sha256": mod["sha256"],
                }
                try:
                    self._save_installed_mods_record()
                except OSError as exc:
                    self.hub_status_label.configure(text="Installed, but could not save install state: " + str(exc))
                else:
                    self.hub_status_label.configure(text=f"{mod['title']} installed: {destination}")
                self.set_download_status(percent=100, state="MOD INSTALLED",
                                         filename=mod["title"], amount=destination,
                                         time_remaining="Verified SHA-256")
                if self.hub_overlay.winfo_ismapped():
                    self._render_hub_cards()
            elif event == "mod_error":
                self.mod_download_busy = False
                game_installed = services.real_game_status(self.game_install_path)["installed"]
                self.set_download_status(
                    percent=100 if game_installed else 0, state="MOD DOWNLOAD FAILED",
                    filename=str(data)[:110],
                    amount="Game installation remains valid" if game_installed
                    else "No local game found",
                    time_remaining="See Forge Hub")
                self.hub_status_label.configure(text=("Installation stopped: " + str(data))[:160])
        self.after(250, self._poll_live_updates)

    def _startup_launcher_update_check(self):
        """Launcher code uses its OWN GitHub repo, not game release tags."""
        if self.launcher_auto_update:
            pending = launcher_updates.pending_update()
            if launcher_updates.is_portable_build():
                version_dir = self._forge_base_dir()
            else:
                version_dir = launcher_updates.portable_target_for_source(
                    self._forge_base_dir())
            if pending and launcher_updates.newer_release(
                    {"version": pending["version"]},
                    launcher_updates.read_local_version(version_dir)):
                self.launcher_update_ready = pending
                self._set_restart_buttons_enabled(True)
                self.launcher_update_status_var.set(
                    ("Launcher v" + pending["version"] +
                     " verified; when you close, the updated EXE will open automatically."))
                return
        self._request_launcher_update_check(manual=False)

    def _scheduled_launcher_update_check(self):
        """At most every six hours when online; no interruptions to gameplay."""
        try:
            if (self.launcher_auto_update and not self.launcher_update_busy
                    and not self.launcher_update_ready
                    and time.time() >= self._launcher_update_retry_after
                    and time.time()-float(self.launcher_last_check) >= 6*3600):
                self._request_launcher_update_check(manual=False)
        finally:
            self.after(3600000, self._scheduled_launcher_update_check)

    def _request_launcher_update_check(self, manual=False):
        if self.launcher_update_busy:
            return
        if not manual and not self.launcher_auto_update:
            return
        if not manual and time.time() < self._launcher_update_retry_after:
            return
        self.launcher_update_busy = True
        self.launcher_update_status_var.set(
            "Checking the official Crash Forge Launcher repository...")
        portable = launcher_updates.is_portable_build()
        install_dir = (self._forge_base_dir() if portable else
                       launcher_updates.portable_target_for_source(
                           self._forge_base_dir()))
        installed = launcher_updates.read_local_version(install_dir)
        auto = bool(self.launcher_auto_update)

        def worker():
            try:
                release = launcher_updates.fetch_latest()
                pending = None
                if release and launcher_updates.newer_release(release, installed):
                    # In source/.bat mode this stages a SEPARATE portable
                    # installation. It never overwrites .py, .bat or source assets.
                    if auto:
                        def report(phase, done, total):
                            self.online_queue.put(
                                ("launcher_update_progress",
                                 (phase, done, total, release["version"])))
                        pending = launcher_updates.stage_release(
                            release, installed, progress=report)
                self.online_queue.put(
                    ("launcher_update_ok",
                     (release, pending, installed, manual, portable)))
            except Exception as exc:
                self.online_queue.put(
                    ("launcher_update_error", (str(exc), manual)))
        threading.Thread(target=worker, daemon=True,
                         name="ForgeLauncherAutoUpdate").start()

    def _startup_release_check(self):
        if self.release_check_busy or self.game_update_busy:
            return
        choice = getattr(self, "release_check_frequency", "Daily")
        # Startup is the only automatic event for "On launch".
        if releases.check_due(choice, getattr(self, "release_last_check", 0),
                              startup=True):
            self._request_release_check(manual=False, request_install=False)
        else:
            last = getattr(self, "release_last_result", "")
            if last:
                self.release_status_var.set("Last GitHub check: " + last)

    def _scheduled_release_check(self):
        try:
            if not self.release_check_busy and not self.game_update_busy:
                choice = getattr(self, "release_check_frequency", "Daily")
                if choice not in ("Manual only", "On launch") and time.time() >= self._release_retry_after:
                    if releases.check_due(choice, getattr(self, "release_last_check", 0)):
                        self._request_release_check(manual=False, request_install=False)
        finally:
            self.after(60000, self._scheduled_release_check)

    def _request_release_check(self, manual=False, request_install=False):
        """Check public GitHub metadata in a daemon; Tk is only touched on its own thread."""
        if self.release_check_busy or self.game_update_busy:
            if request_install and self.release_check_busy:
                self._release_install_after_pending = True
            if manual:
                self.release_status_var.set(
                    "Checking GitHub... Update will continue when the check finishes."
                    if self.release_check_busy and request_install
                    else "A release check or game update is already running.")
            return
        if not manual and time.time() < self._release_retry_after:
            return
        self.release_check_busy = True
        self.release_status_var.set("Checking GitHub Releases...")
        if manual:
            self.status_label.configure(text="Checking official GitHub Releases...")
        def worker():
            try:
                metadata = releases.fetch_latest_release()
                self.online_queue.put(("release_ok", (metadata, manual, request_install)))
            except Exception as exc:
                self.online_queue.put(("release_error", (str(exc), manual)))
        threading.Thread(target=worker, daemon=True,
                         name="CrashForgeReleaseCheck").start()

    def _show_release_check(self, release, manual=False, install_requested=False):
        self.latest_game_release = release
        self._update_primary_game_button()
        self.release_last_check = time.time()
        # News is added only for an actual official Windows game release.
        self.github_release_news = []
        if release and release.get("asset"):
            self.github_release_news = [{
                "category": "GITHUB GAME RELEASE",
                "title": "Crash Forge: Racing v" + release["version"],
                "date": release["published_at"][:10],
                "description": release["notes"][:450],
                "url": release["url"],
            }]
        self._render_real_news()
        if release is None:
            result = "No published stable Releases on GitHub"
        else:
            local = releases.game_installed_version(self.game_install_path)
            version_cmp = releases.compare_versions(local, release["version"])
            if version_cmp == 0:
                result = "Up to date · v" + release["version"]
            elif version_cmp == 1:
                result = "Local v" + local + " newer than GitHub v" + release["version"]
            elif not release["verified_package"]:
                result = "GitHub v" + release["version"] + " · no verified Windows ZIP"
            elif not local:
                result = "GitHub v" + release["version"] + " · local version unknown"
            else:
                result = "Game update available · v" + release["version"]
        self.release_last_result = result
        self.release_status_var.set(result)
        self._save_launcher_settings()
        if manual and not install_requested:
            self.status_label.configure(text=result)
        if install_requested:
            if release is None:
                self.status_label.configure(
                    text="No stable GitHub Releases have been published yet.")
            elif not release["verified_package"]:
                self.status_label.configure(
                    text="This release has no checked Windows ZIP. Use GITHUB to view its assets.")
            else:
                self._confirm_release_install(release)

    def _confirm_release_install(self, release):
        if self.game_update_busy or self.mod_download_busy:
            self.status_label.configure(text="Wait for the current verified transfer to finish.")
            return
        local = releases.game_installed_version(self.game_install_path)
        cmp = releases.compare_versions(local, release["version"])
        if cmp in (0, 1):
            self.status_label.configure(
                text="Local version is already the same or newer than GitHub v" +
                release["version"] + ". No downgrade will be performed.")
            return
        asset = release.get("asset") or {}
        confirmed = messagebox.askyesno(
            "Crash Forge: Racing - Verified GitHub Update",
            "Install the OFFICIAL Windows game release?\n\n"
            "Release: v" + release["version"] + "\n"
            "ZIP: " + str(asset.get("name", "")) + "\n"
            "Size: " + f"{asset.get('size', 0) / 1048576:.1f} MB" + "\n"
            "Installed version: " + (local or "unknown") + "\n"
            "Folder: " + self.game_install_path + "\n\n"
            "The ZIP is checked against its SHA-256 before any files are replaced.\n"
            "Original game files are backed up. User mods and saves are protected.\n"
            "Close the game first. Start this update?",
            parent=self
        )
        if not confirmed:
            return
        self.game_update_busy = True
        self.set_download_status(
            percent=0, state="CONNECTING TO GITHUB",
            filename="Verified Windows game release · v" + release["version"],
            amount="Waiting for signed-official release asset",
            time_remaining="SHA-256 required",
        )
        def report(phase, done, total, speed):
            self.online_queue.put(
                ("game_progress", (phase, done, total, speed, release["version"])))
        def worker():
            try:
                result = releases.install_game_release(
                    release, self.game_install_path, progress=report)
                self.online_queue.put(("game_installed", result))
            except Exception as exc:
                self.online_queue.put(("game_update_error", str(exc)))
        threading.Thread(target=worker, daemon=True,
                         name="CrashForgeVerifiedGameUpdate").start()

    def _local_record_version(self, mod):
        rec = self.installed_mods_record.get(str(mod.get("id", "")), {})
        if not isinstance(rec, dict) or not rec.get("path"):
            return ""
        if os.path.normcase(rec.get("game_path", "")) != os.path.normcase(self.game_install_path):
            return ""
        if not os.path.isdir(rec["path"]):
            return ""
        return str(rec.get("version", ""))

    def _download_public_mod(self, mod):
        if self.mod_download_busy or self.game_update_busy:
            self.hub_status_label.configure(text="Another verified download is already active.")
            return
        url = mod.get("download_url")
        sha256 = mod.get("sha256")
        if not url or not sha256:
            self.hub_status_label.configure(
                text="This publisher has not provided an HTTPS ZIP with SHA-256. Open its Details page.")
            return
        if not services.real_game_status(self.game_install_path)["installed"]:
            self.hub_status_label.configure(text="Select an installed ctr-native.exe game folder first.")
            return
        consent = messagebox.askyesno(
            "Forge Hub - Install Mod",
            f"Install {mod['title']} by {mod['author']}?\n\n"
            "Source: published community catalog.\n"
            "ZIP will be verified with SHA-256 and installed by category.\n"
            "A previous version of the same mod will be backed up.",
            parent=self)
        if not consent:
            return
        self.mod_download_busy = True
        self.hub_status_label.configure(text="Starting verified download...")
        self.set_download_status(percent=0, state="CONNECTING",
                                 filename=mod["title"], amount="0 MB", time_remaining="")

        def progress(done, total, speed):
            self.online_queue.put(("mod_progress", (done, total, speed)))

        def worker():
            try:
                dest = services.download_install_mod(
                    mod, self.game_install_path, progress=progress)
                self.online_queue.put(("mod_ok", (mod, dest)))
            except Exception as exc:
                self.online_queue.put(("mod_error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="ForgeModInstall").start()

    def _publish_local_mod(self):
        url = self.online_cfg.get("submit_url", "")
        if not url:
            self.upload_status_label.configure(
                text="Public uploads need a submission page. Configure SOURCE first.")
            return
        try:
            services.checked_https_url(url)
        except services.FeedError as exc:
            self.upload_status_label.configure(text=str(exc))
            return
        self.upload_status_label.configure(
            text="Opening submission page. The local ZIP is not uploaded automatically.")
        webbrowser.open(url)

    def _confirm_play_older_game(self, context):
        """Custom orange/steel modal. No copied launcher wallpaper."""
        icon_path = os.path.join(
            self._forge_base_dir(), "assets", "icons", "cfr_icon.png")
        return ask_play_outdated(self, context, icon_path=icon_path)

    def _play_installed_game(self):
        state = services.real_game_status(self.game_install_path)
        if not state["installed"]:
            self.status_label.configure(text="Cannot play: ctr-native.exe is not in the selected game folder.")
            self._refresh_real_install_ui()
            return
        if getattr(self, "game_update_busy", False):
            self.status_label.configure(text="Wait for the game update to finish before playing.")
            return
        new_version = available_game_update(
            self.game_install_path, getattr(self, "latest_game_release", None))
        if new_version and not self._confirm_play_older_game(new_version):
            self.status_label.configure(
                text="Game launch cancelled; no files or versions were changed.")
            return
        # Independent CTR-U audit always runs asynchronously, even if modded.
        try:
            iso_integrity.start_background_check(self.game_install_path, "play")
        except Exception:
            pass  # Even verifier failures cannot stop offline PLAY.
        try:
            subprocess.Popen([state["exe_path"]], cwd=self.game_install_path)
            self.status_label.configure(text="Started installed Crash Forge game.")
        except OSError as exc:
            self.status_label.configure(text="Could not start the game: " + str(exc))

    def _check_game_update(self):
        """UPDATE always checks GitHub Releases; install requires explicit consent."""
        self._request_release_check(manual=True, request_install=True)

    def _check_local_game_files(self):
        if self.game_update_busy:
            self.status_label.configure(
                text="Wait for the verified GitHub game update to finish.")
            return
        status = services.real_game_status(self.game_install_path)
        mods = os.path.join(self.game_install_path, "assets", "mods")
        if not status["installed"]:
            summary = "ctr-native.exe missing at selected location"
        elif not os.path.isdir(mods):
            summary = "Game found; assets/mods folder missing"
        else:
            summary = "Game executable and assets/mods present. This is a basic check, not a full repair."
        self.set_download_status(
            percent=100 if status["installed"] else 0,
            state="LOCAL FILE CHECK", filename=summary,
            amount=self.game_install_path, time_remaining="No files modified")
        self.status_label.configure(text=summary)
