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
import forge_launcher_integrity as launcher_integrity
import forge_news_history as news_history
import forge_game_news as game_news
import forge_game_launch as game_launch
import forge_iso_integrity as iso_integrity
from forge_version_dialog import ask_play_outdated
from forge_dialogs import ask_mod_install, ask_game_update


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


# Deliberately disabled until a PUBLIC native game release supports
# --no-mods. Local experimental builds don't make this a public feature.
CLEAN_PLAY_PUBLIC_ENABLED = False
CLEAN_PLAY_DEVELOPMENT_MESSAGE = (
    "PLAY WITHOUT MODS is in development. We're working on it."
)


class ForgeLiveMixin:
    def _post_init_live(self):
        self.remote_mods = []
        self.remote_news = []
        self.github_release_news = []
        self.game_news_history = []  # The game's *own* GitHub repository.
        self._unread_game_announcement = None
        # Persistent, append-only history across launcher updates and offline use.
        self.launcher_news_history = news_history.local_publications(
            self._forge_base_dir())
        self._news_refresh_busy = False
        self._news_art_photos = {}
        self.remote_feed = {}
        self.online_status = "PUBLIC FEED NOT CONFIGURED"
        self.online_queue = queue.Queue()
        self.online_busy = False
        self.mod_download_busy = False
        self.game_update_busy = False
        self.release_check_busy = False
        self.launcher_update_busy = False
        self.launcher_update_ready = None
        self._launcher_integrity_busy = False
        self._launcher_integrity_needs_repair = False
        self._launcher_update_retry_after = 0.0
        self._release_install_after_pending = False
        self.latest_game_release = None
        self._global_release_checked = False
        self._global_release_error = False
        self._release_retry_after = 0.0
        self.online_cfg = services.read_online_config(self._forge_base_dir())
        self.installed_mods_record = self._load_installed_mods_record()
        self._refresh_real_install_ui()
        screenshot_preview = os.environ.get("CFR_SCREENSHOT_PREVIEW") == "1"
        # A screenshot preview never checks the game ISO, polls releases,
        # downloads packages or stages an automatic launcher update.
        if not screenshot_preview and self.game_install_path:
            try:
                iso_integrity.start_background_check(
                    self.game_install_path, "launcher_start")
            except Exception:
                pass  # ISO diagnostics must never break launcher startup.
        self._render_real_news()
        self._refresh_hub_source_status()
        if screenshot_preview:
            self.launcher_auto_update = False
            self.online_status = "SCREENSHOT PREVIEW | OFFLINE"
            self._refresh_hub_source_status()
            return
        if self.online_cfg.get("feed_url"):
            self._reload_live_source()
        # Game folders are never discovered or replaced automatically.
        # The selected Settings path remains authoritative.
        self.after(1300, self._refresh_news_history)
        self.after(600000, self._scheduled_news_history_check)
        self.after(650, self._check_launcher_integrity)
        self.after(1600, self._startup_release_check)
        self.after(2700, self._startup_launcher_update_check)
        self.after(3600000, self._scheduled_launcher_update_check)
        self.after(60000, self._scheduled_release_check)
        self.after(250, self._poll_live_updates)
        self.after(5000, self._poll_game_play_ready)

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
        """PLAY if installed; INSTALL only at a manually selected game folder."""
        if not self.game_install_path:
            self.status_label.configure(
                text="Choose the game install folder in Settings before continuing.")
            return
        status = services.real_game_status(self.game_install_path)
        if status["installed"]:
            mode = self.preferred_play_mode if getattr(self, "remember_play_choice", False) else None
            # Users who saved clean as a favourite on an older launcher
            # must not get a silent no-op, accidental game start, or loop.
            if mode == "clean" and not CLEAN_PLAY_PUBLIC_ENABLED:
                self.status_label.configure(text=CLEAN_PLAY_DEVELOPMENT_MESSAGE)
                self._show_play_mode_selector()
            elif mode:
                self._play_installed_game(mode)
            else:
                self._show_play_mode_selector()
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
        A missing official game file disables and greys PLAY until restored.
        A newer optional game release never disables an otherwise healthy PLAY.
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
        missing = installed and bool(getattr(self, "_play_issue", ""))

        main.set_label("PLAY" if installed else "INSTALL")
        main.set_disabled((not installed and not verified) or updating or missing)
        main.set_accent((installed and not update_available and not missing) or
                        (not installed and verified))

        # The user's forged UPDATE button is NEVER removed or replaced by
        # a duplicate in Settings. Muted when no verified game update exists.
        update.set_disabled(updating)
        update.set_accent(bool(update_available))

    def _refresh_global_game_status(self):
        """Show public game release availability, not a local executable state."""
        label = getattr(self, "build_state_label", None)
        if label is None:
            return
        release = getattr(self, "latest_game_release", None)
        busy = bool(getattr(self, "release_check_busy", False))
        checked = bool(getattr(self, "_global_release_checked", False))
        error = bool(getattr(self, "_global_release_error", False))
        if release:
            version = str(release.get("version") or "").strip()
            verified = bool(release.get("verified_package"))
            text = ("PUBLIC v" + version) if version else "PUBLIC RELEASE"
            if not verified:
                text = "RELEASE LISTED"
            color = "#56C47A" if verified else "#D49A4A"
        elif busy:
            text, color = "CHECKING RELEASES", "#D49A4A"
        elif error:
            text, color = "STATUS UNAVAILABLE", "#D49A4A"
        elif not checked:
            text, color = "CHECKING RELEASES", "#D49A4A"
        else:
            text, color = "NO PUBLIC RELEASE", "#D49A4A"
        label.configure(text=text)
        indicator = getattr(self, "build_indicator", None)
        if indicator is not None:
            indicator.configure(fg=color)

    def _refresh_real_install_ui(self):
        status = services.real_game_status(self.game_install_path)
        previous_issue = getattr(self, "_play_issue", None)
        self.local_game_status = status
        self._play_issue = (game_launch.launch_issue(self.game_install_path)
                            if status["installed"] else "")
        missing = bool(status["installed"] and self._play_issue)
        self._update_primary_game_button()
        # Global game publication status, never derived from the local install.
        ForgeLiveMixin._refresh_global_game_status(self)
        if (hasattr(self, "download_percent")
                and not self.mod_download_busy
                and not self.game_update_busy):
            self.set_download_status(
                percent=0 if missing else 100 if status["installed"] else 0,
                state=("GAME FILES MISSING" if missing else
                       "INSTALLED" if status["installed"] else "NOT INSTALLED"),
                filename=self._play_issue if missing else status["detail"],
                amount=("Restore missing official files or use verified UPDATE"
                        if missing else
                        "Local game files found" if status["installed"] else
                        "Select a game folder in Settings"),
                time_remaining=("PLAY disabled until files are restored"
                                if missing else "Ready to play" if status["installed"]
                                else "No game found"),
            )
        if hasattr(self, "status_label") and self._play_issue != previous_issue:
            self.status_label.configure(
                text=("PLAY DISABLED: " + self._play_issue if missing else
                      "Game files ready; PLAY is available." if status["installed"]
                      else "Choose or install your game folder in Settings."))
        if hasattr(self, "hero_canvas"):
            self._paint_hero()

    def _poll_game_play_ready(self):
        """Notice restored or removed official files without requiring restart."""
        try:
            if not getattr(self, "game_update_busy", False):
                status = services.real_game_status(self.game_install_path)
                issue = (game_launch.launch_issue(self.game_install_path)
                         if status["installed"] else "")
                if (issue != getattr(self, "_play_issue", None) or
                        bool(status["installed"]) != bool(getattr(
                            self, "local_game_status", {}).get("installed"))):
                    self._refresh_real_install_ui()
        finally:
            self.after(5000, self._poll_game_play_ready)

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

    def _refresh_news_history(self):
        """Fetch launcher and game NEWS independently; never install anything.

        Two official pinned GitHub repositories. Neither can modify the
        other's version, ZIP or updater state. Off-UI thread, quiet retry.
        """
        if getattr(self, "_news_refresh_busy", False):
            return
        self._news_refresh_busy = True

        def worker():
            # A GitHub API failure in ONE project never removes articles
            # already available from the OTHER project.
            try:
                raw = launcher_updates._open_json(launcher_updates.RELEASES_API)
                published, pictures = news_history.parse_github_history(raw)
                if published:
                    merged = news_history.save_history(
                        published, self._forge_base_dir())
                    news_history.sync_release_artwork(pictures)
                    self.online_queue.put(("news_history_ok", merged))
            except (ValueError, OSError, TypeError) as error:
                self.online_queue.put(("news_history_error", str(error)))
            try:
                raw_game = releases._read_json(game_news.GAME_API_URL)
                published_game = game_news.parse_public_game_releases(raw_game)
                self.online_queue.put(("game_news_ok", published_game))
            except (ValueError, OSError, TypeError) as error:
                self.online_queue.put(("game_news_error", str(error)))
            finally:
                self.online_queue.put(("news_refresh_done", None))

        threading.Thread(target=worker, daemon=True,
                         name="ForgeIndependentNewsPoll").start()

    def _scheduled_news_history_check(self):
        """Ten-minute release NEWS polling, separate from updater cadence."""
        self._refresh_news_history()
        self.after(600000, self._scheduled_news_history_check)

    def _refresh_game_news_indicator(self):
        """A tiny orange NEW label, with NO popups, sound or focus stealing."""
        self._unread_game_announcement = game_news.latest_unread_game(
            getattr(self, "game_news_history", []))
        unread = self._unread_game_announcement is not None
        label = getattr(self, "news_game_indicator", None)
        if label is not None:
            label.configure(text="\u25cf NEW GAME RELEASE" if unread else "",
                            cursor="hand2" if unread else "arrow")
        tab = getattr(self, "_dashboard_buttons", {}).get("NEWS")
        if tab is not None:
            tab.configure(text="NEWS  \u25cf" if unread else "NEWS")

    def _acknowledge_game_news(self, event=None):
        unread = getattr(self, "_unread_game_announcement", None)
        if unread and game_news.mark_game_seen(unread["tag"]):
            self._refresh_game_news_indicator()

    def _render_real_news(self):
        """Scrollable release archive: one article per published version."""
        if not hasattr(self, "news_rows"):
            return
        from tkinter import Frame, Label, Canvas
        for child in self.news_rows.winfo_children():
            child.destroy()
        self._news_art_photos = {}

        launcher_history = news_history.merge_history(
            news_history.local_publications(self._forge_base_dir()),
            getattr(self, "launcher_news_history", []))
        self.launcher_news_history = launcher_history
        history = game_news.combined_news(
            launcher_history, getattr(self, "game_news_history", []))

        # Live community announcements do not affect either project's updater.
        additional = self.remote_news
        for index, item in enumerate(history):
            version = item["version"]
            is_game = item.get("source") == "GAME"
            # Both products get prominent illustrated cards. A game release
            # without specific artwork uses neutral brand background, never
            # an unrelated launcher-version screenshot.
            is_featured = (index < 2 or
                           (not is_game and bool(news_history.artwork_file(
                               self._forge_base_dir(), version))))
            row = Frame(self.news_rows, bg="#111419",
                        highlightbackground="#30363E", highlightthickness=1)
            row.pack(fill="x", pady=(0, 9), padx=1)

            if is_featured:
                image_path = (
                    news_history.garage_fallback(self._forge_base_dir()) if is_game
                    else (news_history.artwork_file(self._forge_base_dir(), version)
                          or news_history.garage_fallback(self._forge_base_dir())))
                banner = Canvas(row, height=184, bg="#0D1014", bd=0,
                                highlightthickness=0)
                banner.pack(fill="x")

                date = item["date"]
                identity = item["identity"]
                product = "GAME" if is_game else "LAUNCHER"
                def paint_banner(event=None, canvas=banner, image_file=image_path,
                                 release_version=version, published=date,
                                 article_id=identity, product_name=product):
                    width = max(120, canvas.winfo_width())
                    height = 184
                    canvas.delete("all")
                    canvas.create_rectangle(0, 0, width, height,
                                            fill="#0B0F13", outline="")
                    if image_file and os.path.isfile(image_file):
                        try:
                            from PIL import Image, ImageTk, ImageOps
                            with Image.open(image_file) as original:
                                # Show the COMPLETE user illustration, no crop.
                                picture = ImageOps.contain(
                                    original.convert("RGB"),
                                    (max(width - 16, 1), 143),
                                    method=Image.Resampling.LANCZOS)
                            photo = ImageTk.PhotoImage(picture)
                            self._news_art_photos[article_id] = photo
                            canvas.create_image(width//2, 72, image=photo,
                                                anchor="center")
                        except (ImportError, OSError, ValueError):
                            pass
                    canvas.create_rectangle(0, 0, 5, height,
                                            fill="#FF7200", outline="")
                    canvas.create_rectangle(0, 146, width, height,
                                            fill="#0B0E12", outline="")
                    canvas.create_text(
                        15, 166, anchor="w",
                        text="CRASH FORGE  /  " + product_name + " v" + release_version,
                        fill="#F3F2EF", font=("Bahnschrift SemiBold", 11))
                    canvas.create_text(width - 12, 166, anchor="e",
                                       text=published,
                                       fill="#A5ADB7", font=("Bahnschrift", 8))

                banner.bind("<Configure>", paint_banner)

            body = Frame(row, bg="#111419")
            body.pack(fill="x", padx=13, pady=(9, 11))
            caption = (("GAME  /  " if is_game else "LAUNCHER  /  ") +
                       ("LATEST RELEASE" if index == 0 else
                        "RELEASE HISTORY  /  " + item["display_version"]))
            Label(body, text=caption, bg="#111419", fg="#F49A54",
                  font=("Bahnschrift SemiBold", 8), anchor="w"
                  ).pack(fill="x", pady=(0, 5))
            Label(body, text=item["title"], bg="#111419", fg="#F4F3F0",
                  font=("Bahnschrift SemiBold", 11 if is_featured else 10),
                  anchor="w", justify="left",
                  wraplength=420).pack(fill="x", anchor="w")
            notes = item.get("notes", [])
            if notes:
                summary = "\n".join("• " + str(note) for note in
                                    notes[:4 if (is_featured or is_game) else 2])
            else:
                summary = "Read the full release notes on GitHub."
            Label(body, text=summary,
                  bg="#111419", fg="#B6BDC5", font=("Bahnschrift", 9),
                  justify="left", wraplength=420, anchor="w"
                  ).pack(fill="x", pady=(7, 6))
            url = item["url"]
            open_link = Label(body, text="READ FULL UPDATE  ↗",
                              bg="#111419", fg="#E98D4E",
                              font=("Bahnschrift SemiBold", 8),
                              cursor="hand2", anchor="w")
            open_link.pack(anchor="w")
            open_link.bind("<Button-1>",
                           lambda event, link=url: webbrowser.open(link))

        # Keep official game releases and public community feed items too.
        for entry in additional[:8]:
            row = Frame(self.news_rows, bg="#101317",
                        highlightbackground="#2F363F", highlightthickness=1)
            row.pack(fill="x", pady=(0, 8), padx=1)
            Label(row, text=str(entry.get("category") or "COMMUNITY").upper(),
                  bg="#101317", fg="#EFA570",
                  font=("Bahnschrift SemiBold", 8), anchor="w"
                  ).pack(fill="x", padx=12, pady=(9, 2))
            Label(row, text=str(entry.get("title") or "")[:105],
                  bg="#101317", fg="#F4F2EE", justify="left",
                  font=("Bahnschrift SemiBold", 10),
                  wraplength=415, anchor="w"
                  ).pack(fill="x", padx=12)
            Label(row, text=str(entry.get("description") or "")[:360],
                  bg="#101317", fg="#A4ACB5",
                  font=("Bahnschrift", 8), justify="left",
                  wraplength=415, anchor="w"
                  ).pack(fill="x", padx=12, pady=(4, 10))
        self._refresh_game_news_indicator()
        if hasattr(self, "_resize_news_content"):
            self._resize_news_content()
        if hasattr(self, "hero_canvas"):
            self._paint_hero()

    def _open_all_news(self):
        """Both projects keep separate links; NEWS already combines the posts."""
        selector = getattr(self, "_select_dashboard_tab", None)
        if selector is not None:
            selector("NEWS")
        self._acknowledge_game_news()

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
            if event == "news_history_ok":
                self.launcher_news_history = news_history.merge_history(
                    self.launcher_news_history, data)
                self._render_real_news()
            elif event == "game_news_ok":
                # Game NEWS is metadata only: separate repository, ZIP,
                # version and updater. No automatic game/launcher downloads.
                self.game_news_history = data
                self._render_real_news()
            elif event == "news_refresh_done":
                self._news_refresh_busy = False
            elif event in ("news_history_error", "game_news_error"):
                # Retain the unaffected project's existing NEWS.
                pass
            elif event == "feed_ok":
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
            elif event == "launcher_integrity_result":
                result, manual = data
                self._launcher_integrity_busy = False
                if result["status"] == "ok":
                    self._launcher_integrity_needs_repair = False
                    message = ("Launcher files verified: " +
                               str(result["checked"]) + " OK.")
                elif result["status"] == "unavailable":
                    message = ("No file verification manifest found. " +
                               "Install the complete latest Launcher ZIP.")
                else:
                    self._launcher_integrity_needs_repair = True
                    issues = result.get("problems") or []
                    message = ("Launcher integrity: " +
                               str(len(issues)) + " issue(s). " +
                               "; ".join(issues[:2])[:105])
                self.launcher_update_status_var.set(message[:200])
                if manual or result["status"] == "damaged":
                    self.status_label.configure(text=message[:175])
                if (result["status"] == "damaged" and
                        self._launcher_automatic_updates_allowed() and
                        not self.launcher_update_busy):
                    self._request_launcher_update_check(manual=False)
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
                if pending and self._launcher_automatic_updates_allowed():
                    self.launcher_update_ready = pending
                    self._set_restart_buttons_enabled(True)
                    result = ("Launcher v" + pending["version"] +
                              " verified; the updated EXE will open automatically " +
                              "after you close this launcher.")
                elif release and launcher_updates.update_required(
                    release, installed,
                    app_dir=(self._forge_base_dir() if portable else
                             launcher_updates.portable_target_for_source(
                                 self._forge_base_dir()))):
                    result = ("Launcher v" + release["version"] +
                              " available. " +
                              ("Auto-update disabled." if not self._launcher_automatic_updates_allowed() else
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
                if (self._launcher_integrity_needs_repair and
                        self._launcher_automatic_updates_allowed() and not pending):
                    # A normal version check may have been in flight before
                    # the local integrity audit completed. Retry once as repair.
                    self.after(100, lambda: self._request_launcher_update_check(
                        manual=False))
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
                self._global_release_error = True
                self._refresh_global_game_status()
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
                issue = getattr(self, "_play_issue", "")
                if issue:
                    self.status_label.configure(text="PLAY DISABLED: " + issue)
                    self.set_download_status(
                        percent=0, state="GAME FILES MISSING", filename=issue,
                        amount="Restore the missing original/official files",
                        time_remaining="PLAY disabled until installation is complete")
                else:
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
            elif event == "mod_uninstall_ok":
                result, removed_game_path = data
                self.mod_download_busy = False
                # Remove only receipts for the same explicitly selected
                # installation, never state belonging to another game.
                changed = False
                for removed_id in result["removed_ids"]:
                    receipt = self.installed_mods_record.get(removed_id)
                    if (isinstance(receipt, dict) and
                            os.path.normcase(str(receipt.get("game_path",""))) ==
                            os.path.normcase(str(removed_game_path))):
                        del self.installed_mods_record[removed_id]
                        changed = True
                if changed:
                    try:
                        self._save_installed_mods_record()
                    except OSError as error:
                        self.hub_status_label.configure(
                            text="Mod removed, but receipt cleanup failed: " + str(error)[:110])
                self.set_download_status(
                    percent=100,state="MOD UNINSTALLED",
                    filename=result["title"],
                    amount=str(result["removed_count"])+" folder(s) moved to Recycle Bin",
                    time_remaining="Restart game to refresh mods")
                self.hub_status_label.configure(
                    text=result["title"]+
                         " uninstalled locally. It is still available on Forge Hub.")
                if self.hub_overlay.winfo_ismapped():
                    self._close_mod_details()
                    self._render_hub_cards()
            elif event == "mod_uninstall_error":
                title, detail = data
                self.mod_download_busy = False
                self.set_download_status(
                    percent=100,state="UNINSTALL FAILED",
                    filename=title,
                    amount="No other mods or game files were targeted",
                    time_remaining="See Forge Hub")
                self.hub_status_label.configure(
                    text=("Uninstall stopped: "+detail)[:170])
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

    def _check_launcher_integrity(self, manual=False):
        """Read-only SHA-256 scan: network/download work is separate."""
        if not launcher_updates.is_portable_build():
            if manual:
                self.launcher_update_status_var.set(
                    "File verification is available in packaged Windows EXEs.")
            return
        if self._launcher_integrity_busy:
            return
        self._launcher_integrity_busy = True
        if manual:
            self.launcher_update_status_var.set("Verifying launcher files...")
        base = self._forge_base_dir()
        def worker():
            try:
                report = launcher_integrity.audit(base)
            except Exception as exc:
                report = {"status": "damaged", "checked": 0,
                          "problems": ["Verification failed: " + str(exc)[:140]]}
            self.online_queue.put(("launcher_integrity_result",
                                   (report, manual)))
        threading.Thread(target=worker, daemon=True,
                         name="ForgeLauncherIntegrity").start()

    def _launcher_automatic_updates_allowed(self):
        """Both the live checkbox and the persisted permission must agree."""
        if getattr(self, "launcher_auto_update", False) is not True:
            return False
        return launcher_updates.automatic_updates_allowed(
            os.path.join(self._forge_base_dir(), "launcher_settings.json"))

    def _startup_launcher_update_check(self):
        """Launcher code uses its OWN GitHub repo, not game release tags."""
        if self._launcher_automatic_updates_allowed():
            pending = launcher_updates.pending_update()
            if launcher_updates.is_portable_build():
                version_dir = self._forge_base_dir()
            else:
                version_dir = launcher_updates.portable_target_for_source(
                    self._forge_base_dir())
            if pending and launcher_updates.pending_update_required(
                    pending, version_dir):
                self.launcher_update_ready = pending
                self._set_restart_buttons_enabled(True)
                self.launcher_update_status_var.set(
                    ("Launcher v" + pending["version"] +
                     " verified; when you close, the updated EXE will open automatically."))
                return
        if self._launcher_automatic_updates_allowed():
            self._request_launcher_update_check(manual=False)

    def _scheduled_launcher_update_check(self):
        """At most every six hours when online; no interruptions to gameplay."""
        try:
            if (self._launcher_automatic_updates_allowed() and not self.launcher_update_busy
                    and not self.launcher_update_ready
                    and time.time() >= self._launcher_update_retry_after
                    and time.time()-float(self.launcher_last_check) >= 6*3600):
                self._request_launcher_update_check(manual=False)
        finally:
            self.after(3600000, self._scheduled_launcher_update_check)

    def _request_launcher_update_check(self, manual=False):
        if self.launcher_update_busy:
            return
        if not manual and not self._launcher_automatic_updates_allowed():
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
        auto = self._launcher_automatic_updates_allowed()
        settings_file = os.path.join(self._forge_base_dir(), "launcher_settings.json")
        repair = bool(getattr(self, "_launcher_integrity_needs_repair", False))

        def worker():
            try:
                release = launcher_updates.fetch_latest()
                pending = None
                if release and launcher_updates.update_required(
                        release, installed, app_dir=install_dir,
                        force_repair=repair):
                    # In source/.bat mode this stages a SEPARATE portable
                    # installation. It never overwrites .py, .bat or source assets.
                    if auto and launcher_updates.automatic_updates_allowed(settings_file):
                        def report(phase, done, total):
                            self.online_queue.put(
                                ("launcher_update_progress",
                                 (phase, done, total, release["version"])))
                        pending = launcher_updates.stage_release(
                            release, installed, progress=report,
                            app_dir=install_dir, force_repair=repair)
                        # Discard staged readiness if disabled during transfer.
                        if not launcher_updates.automatic_updates_allowed(settings_file):
                            pending = None
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
        self._refresh_global_game_status()
        self.release_status_var.set("Checking GitHub Releases...")
        if manual:
            self.status_label.configure(text="Checking official GitHub Releases...")
        def worker():
            try:
                metadata = releases.fetch_latest_release(allow_prerelease=True)
                self.online_queue.put(("release_ok", (metadata, manual, request_install)))
            except Exception as exc:
                self.online_queue.put(("release_error", (str(exc), manual)))
        threading.Thread(target=worker, daemon=True,
                         name="CrashForgeReleaseCheck").start()

    def _show_release_check(self, release, manual=False, install_requested=False):
        self.latest_game_release = release
        self._global_release_checked = True
        self._global_release_error = False
        self.release_last_check = time.time()
        self._refresh_global_game_status()
        self._update_primary_game_button()
        # The game NEWS fetch owns game articles independently. Never insert
        # an extra duplicate card during a manual game update check.
        self.github_release_news = []
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
        if not self.game_install_path:
            self.status_label.configure(
                text="Select a game installation folder in Settings before updating.")
            return
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
        confirmed = ask_game_update(
            self, release, local, self.game_install_path,
            icon_path=os.path.join(
                self._forge_base_dir(), "assets", "icons", "cfr_icon.png"))
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
        local_zip = (mod.get("source") == "local" and
                     bool(mod.get("package_path")))
        url = mod.get("download_url")
        sha256 = mod.get("sha256")
        if not sha256 or (not local_zip and not url):
            self.hub_status_label.configure(
                text="A real local ZIP or published HTTPS ZIP with SHA-256 is required.")
            return
        if not services.real_game_status(self.game_install_path)["installed"]:
            self.hub_status_label.configure(text="Select an installed ctr-native.exe game folder first.")
            return
        consent = ask_mod_install(
            self, mod, local=local_zip,
            game_path=self.game_install_path,
            icon_path=os.path.join(
                self._forge_base_dir(), "assets", "icons", "cfr_icon.png"))
        if not consent:
            return
        self.mod_download_busy = True
        self.hub_status_label.configure(
            text="Verifying local ZIP..." if local_zip
            else "Starting verified download...")
        self.set_download_status(percent=0, state="VERIFYING ZIP" if local_zip
                                 else "CONNECTING",
                                 filename=mod["title"], amount="0 MB", time_remaining="")

        def progress(done, total, speed):
            self.online_queue.put(("mod_progress", (done, total, speed)))

        def worker():
            try:
                installer = (services.install_local_mod if local_zip
                             else services.download_install_mod)
                dest = installer(
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

    def _show_play_mode_selector(self, event=None):
        """Right-click always opens the chooser, regardless of saved choice."""
        import tkinter as tk
        if not self.game_install_path:
            self.status_label.configure(text="Choose the game folder in Settings.")
            return
        existing = getattr(self, "_play_mode_window", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        win = tk.Toplevel(self)
        self._play_mode_window = win
        win.title("Crash Forge: Racing - Launch Game")
        win.configure(bg="#0C0F14")
        win.resizable(False, False)
        win.transient(self)
        win.geometry("460x440")
        x = self.winfo_rootx() + max(0,(self.winfo_width()-460)//2)
        y = self.winfo_rooty() + max(0,(self.winfo_height()-440)//2)
        win.geometry(f"+{x}+{y}")
        tk.Frame(win,height=5,bg="#FF6A00").pack(fill="x")
        tk.Label(win,text="LAUNCH GAME",font=("Bahnschrift SemiBold",19),
                 bg="#0C0F14",fg="#FFFFFF").pack(anchor="w",padx=24,pady=(20,2))
        tk.Label(win,text="Choose how to start Crash Forge: Racing",
                 bg="#0C0F14",fg="#A0A7B0").pack(anchor="w",padx=24,pady=(0,14))
        remember=tk.BooleanVar(value=bool(getattr(self,"remember_play_choice",False)))
        def choose(mode):
            if mode == "clean" and not CLEAN_PLAY_PUBLIC_ENABLED:
                self.status_label.configure(text=CLEAN_PLAY_DEVELOPMENT_MESSAGE)
                return
            self.remember_play_choice = bool(remember.get())
            self.preferred_play_mode = mode if self.remember_play_choice else "normal"
            if not self._save_launcher_settings():
                self.status_label.configure(text="Could not save launch preferences.")
            win.destroy()
            self._play_installed_game(mode)
        items=(
            ("normal","PLAY WITH MODS","Start normally with your installed mods."),
            ("clean","PLAY WITHOUT MODS","IN DEVELOPMENT - We're working on it."),
            ("debug","DEBUG MODE","Open the game with a visible console."),
        )
        for mode,title,detail in items:
            disabled = mode == "clean" and not CLEAN_PLAY_PUBLIC_ENABLED
            card_bg = "#14181E" if disabled else "#1A1F27"
            card_cursor = "arrow" if disabled else "hand2"
            card=tk.Frame(win,bg=card_bg,highlightbackground=(
                              "#272C34" if disabled else "#343A43"),
                          highlightthickness=1,cursor=card_cursor)
            card.pack(fill="x",padx=24,pady=4,ipady=5)
            for line,fg,font in ((title,"#8C939B" if disabled else "#FFAD6C",
                                  ("Bahnschrift SemiBold",11)),
                                 (detail,"#777F88" if disabled else "#AEB5BC",
                                  ("Bahnschrift",9))):
                lbl=tk.Label(card,text=line,bg=card_bg,fg=fg,font=font,
                             cursor=card_cursor,anchor="w")
                lbl.pack(fill="x",padx=12,pady=2)
                if not disabled:
                    lbl.bind("<Button-1>",lambda e,m=mode:choose(m))
            if not disabled:
                card.bind("<Button-1>",lambda e,m=mode:choose(m))
        tk.Checkbutton(win,text="Remember my choice",variable=remember,
                       bg="#0C0F14",fg="#DBDEE2",selectcolor="#242A32",
                       activebackground="#0C0F14",activeforeground="#FF9B53",
                       font=("Bahnschrift",10)).pack(anchor="w",padx=23,pady=(10,4))
        tk.Button(win,text="CANCEL",command=win.destroy,bg="#242A32",
                  fg="#F1F1F1",relief="flat",width=15).pack(pady=(4,12))

    def _play_installed_game(self, mode="normal"):
        """Launch only from the explicit Settings folder, with visible errors."""
        if mode == "clean" and not CLEAN_PLAY_PUBLIC_ENABLED:
            self.status_label.configure(text=CLEAN_PLAY_DEVELOPMENT_MESSAGE)
            return
        if getattr(self, "game_update_busy", False):
            self.status_label.configure(
                text="Wait for the game update to finish before playing.")
            return
        issue = game_launch.launch_issue(self.game_install_path)
        if issue:
            self.status_label.configure(text="PLAY BLOCKED: " + issue)
            self.set_download_status(
                percent=0, state="GAME DATA NEEDED", filename=issue,
                amount=self.game_install_path or "No game folder selected",
                time_remaining="Installation folder unchanged")
            messagebox.showwarning(
                "Crash Forge: Racing - Play",
                issue + "\n\nThe launcher will not search for, copy or replace original disc files.",
                parent=self)
            return

        state = services.real_game_status(self.game_install_path)
        if not state["installed"]:
            self.status_label.configure(text="Cannot play: ctr-native.exe is missing.")
            self._refresh_real_install_ui()
            return
        new_version = available_game_update(
            self.game_install_path, getattr(self, "latest_game_release", None))
        if new_version and not self._confirm_play_older_game(new_version):
            self.status_label.configure(
                text="Game launch cancelled; no files or versions were changed.")
            return
        try:
            iso_integrity.start_background_check(self.game_install_path, "play")
        except Exception:
            pass
        if mode == "clean" and not game_launch.supports_native_no_mods(state["exe_path"]):
            # The previous 5s subprocess capability probe was itself a game
            # launch on older builds, then forcibly killed it on timeout.
            # Never execute an unknown EXE to discover whether it can launch.
            self.status_label.configure(
                text="PLAY WITHOUT MODS needs a compatible native game release.")
            return
        try:
            hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" and mode != "debug" else 0
            process = subprocess.Popen(
                [state["exe_path"]] + (["--no-mods"] if mode == "clean" else []),
                cwd=self.game_install_path,
                creationflags=hidden, stdin=subprocess.DEVNULL,
                stdout=None if mode == "debug" else subprocess.DEVNULL,
                stderr=None if mode == "debug" else subprocess.DEVNULL)
            self.status_label.configure(text="Starting Crash Forge: Racing...")
            # Popen succeeds even when the executable immediately fails.
            # Check once on the UI thread without blocking the launcher.
            self.after(1200, lambda p=process: self._report_game_launch(p))
        except OSError as exc:
            self.status_label.configure(text="Could not start the game: " + str(exc))
            messagebox.showerror("Crash Forge: Racing - Play",
                                 "Windows could not launch ctr-native.exe:\n" + str(exc),
                                 parent=self)

    def _report_game_launch(self, process):
        try:
            exit_code = process.poll()
        except (OSError, ValueError):
            return
        if exit_code is None:
            self.status_label.configure(text="Crash Forge: Racing is running.")
        else:
            self.status_label.configure(
                text="Game closed immediately (exit code " + str(exit_code) +
                     "). Check the original disc and game files.")
            messagebox.showwarning(
                "Crash Forge: Racing - Launch failed",
                "The game exited immediately (code " + str(exit_code) +
                "). Verify assets/ctr-u.bin and the selected game installation.",
                parent=self)

    def _check_game_update(self):
        """UPDATE always checks GitHub Releases; install requires explicit consent."""
        self._request_release_check(manual=True, request_install=True)

    def _check_local_game_files(self):
        """REPAIR prepares root mods/, never requires obsolete assets/mods/."""
        if self.game_update_busy:
            self.status_label.configure(
                text="Wait for the verified GitHub game update to finish.")
            return
        repair = game_launch.repair_local_files(self.game_install_path)
        good = bool(repair.get("ok"))
        detail = str(repair.get("detail") or "Game file check failed.")
        self.set_download_status(
            percent=(50 if repair.get("missing_disc") else 100) if good else 0,
            state="LOCAL REPAIR" if good else "REPAIR NEEDS ATTENTION",
            filename=detail,
            amount=self.game_install_path or "Select a game folder",
            time_remaining="No personal mods, saves or disc data replaced")
        self.status_label.configure(text=detail)