"""Dark Forge Hub account dialog for the native Windows launcher."""
from __future__ import annotations

import queue
import threading
import webbrowser
import tkinter as tk
from forge_account_client import AccountError, AccountSessionExpired, WEB_ACCOUNT

BG = "#0C0F13"
PANEL = "#171C22"
EDGE = "#383E47"
ORANGE = "#FF760C"
WHITE = "#ECECEA"
MUTED = "#A0A7AD"


class AccountDialog:
    def __init__(self, parent, client, on_change=None):
        self.parent = parent
        self.client = client
        self.on_change = on_change or (lambda: None)
        self._queue = queue.Queue()
        self._busy = False
        self._closed = False
        self._pair_check_busy = False
        self.mode = "profile" if client.signed_in else "signin"
        self.status = tk.StringVar(value="Connect your existing Forge Hub account.")
        self.window = tk.Toplevel(parent)
        win = self.window
        # A Windows-managed, non-modal window is essential here: the
        # borderless launcher is not a safe parent for Tk modal grab_set.
        # The previous override-redirect+grab combination could trap all
        # mouse input behind an invisible child window and prevent closing.
        win.withdraw()
        win.title("Crash Forge: Racing - Forge Hub Account")
        win.configure(bg=ORANGE)
        win.resizable(False, False)
        try:
            win.iconphoto(False, parent._app_icon)
        except (AttributeError, tk.TclError, TypeError):
            pass
        width = min(650, max(480, win.winfo_screenwidth() - 35))
        height = min(630, max(430, win.winfo_screenheight() - 65))
        x = max(0, parent.winfo_rootx() + (parent.winfo_width() - width)//2)
        y = max(0, parent.winfo_rooty() + (parent.winfo_height() - height)//2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        outer = tk.Frame(win, bg=BG, highlightbackground=ORANGE,
                         highlightthickness=1)
        outer.pack(fill="both", expand=True, padx=2, pady=2)
        header = tk.Frame(outer, bg="#1B2027", height=76)
        header.pack(fill="x")
        header.pack_propagate(False)
        self._title = tk.Label(
            header, text="CRASH FORGE: RACING   /   ACCOUNT",
            bg="#1B2027", fg=ORANGE, font=("Bahnschrift SemiBold", 15))
        self._title.pack(side="left", padx=20, pady=18)
        tk.Button(header, text="×", command=self.close, cursor="hand2",
                  bg="#1B2027", fg=WHITE, activebackground="#742A09",
                  activeforeground=WHITE, bd=0,
                  font=("Segoe UI", 18)).pack(side="right", padx=15)
        self._drag = None
        for widget in (header, self._title):
            widget.bind("<ButtonPress-1>", self._drag_begin)
            widget.bind("<B1-Motion>", self._drag_move)
        tk.Frame(outer, bg=ORANGE, height=2).pack(fill="x", padx=16)
        bar = tk.Frame(outer, bg=BG)
        bar.pack(fill="x", padx=17, pady=(12, 6))
        self._tab_buttons = {}
        for title, value in (("SIGN IN", "signin"), ("REGISTER", "register"),
                             ("PROFILE", "profile")):
            button = tk.Button(bar, text=title,
                               command=lambda m=value: self._switch(m),
                               relief="flat", bd=0, padx=15, pady=8,
                               cursor="hand2", font=("Bahnschrift SemiBold", 9))
            button.pack(side="left", padx=(0, 7))
            self._tab_buttons[value] = button
        self.content = tk.Frame(outer, bg=BG)
        self.content.pack(fill="both", expand=True, padx=22, pady=4)
        footer = tk.Frame(outer, bg="#11151A")
        footer.pack(fill="x", side="bottom", padx=12, pady=(0, 12))
        tk.Label(footer, textvariable=self.status, bg="#11151A",
                 fg=MUTED, justify="left", anchor="w",
                 font=("Bahnschrift", 9), wraplength=590,
                 padx=10, pady=9).pack(fill="x")
        win.protocol("WM_DELETE_WINDOW", self.close)
        self._render()
        win.deiconify()
        win.lift()
        # Never grab mouse or keyboard. Both parent and Account remain
        # independently closeable even if the account service stalls.
        win.after(125, self._pump)
        if client.signed_in:
            self._run(client.profile, self._signed_in)

    def _drag_begin(self, event):
        self._drag = (event.x_root, event.y_root,
                      self.window.winfo_x(), self.window.winfo_y())

    def _drag_move(self, event):
        if not self._drag:
            return
        sx, sy, wx, wy = self._drag
        self.window.geometry(f"+{wx + event.x_root - sx}+{wy + event.y_root - sy}")

    def _button(self, parent, label, command, *, accent=False, width=0):
        return tk.Button(
            parent, text=label, command=command, cursor="hand2",
            bg="#A63D02" if accent else "#262C33", fg=WHITE,
            activebackground=ORANGE if accent else "#454C55",
            activeforeground=WHITE, relief="flat", bd=0,
            highlightthickness=1, highlightbackground="#9B470E" if accent else EDGE,
            font=("Bahnschrift SemiBold", 9),
            padx=12, pady=11, width=width,
        )

    def _field(self, parent, label, *, secret=False, default=""):
        tk.Label(parent, text=label, bg=BG, fg=MUTED, anchor="w",
                 font=("Bahnschrift SemiBold", 9)).pack(fill="x", pady=(10, 3))
        entry = tk.Entry(parent, bg="#151A20", fg=WHITE,
                         insertbackground=WHITE, selectbackground="#8C3508",
                         show="●" if secret else "", relief="flat", bd=0,
                         font=("Bahnschrift", 11), highlightthickness=1,
                         highlightbackground=EDGE, highlightcolor=ORANGE)
        entry.pack(fill="x", ipady=9)
        if default:
            entry.insert(0, default)
        return entry

    def _paragraph(self, text, color=MUTED):
        tk.Label(self.content, text=text, bg=BG, fg=color, justify="left",
                 anchor="w", font=("Bahnschrift", 10),
                 wraplength=550).pack(fill="x", pady=(5, 10))

    def _switch(self, mode):
        if self._busy:
            return
        self.mode = mode
        self._render()

    def _render(self):
        if self._closed:
            return
        for child in self.content.winfo_children():
            child.destroy()
        for name, button in self._tab_buttons.items():
            active = name == self.mode
            button.configure(
                bg="#67310D" if active else PANEL,
                fg="#FFFFFF" if active else MUTED,
                highlightthickness=0)
        if self.mode == "signin":
            self._render_signin()
        elif self.mode == "register":
            self._render_signup()
        else:
            self._render_profile()

    def _render_signin(self):
        self._paragraph("Use the same Forge Hub identity for your launcher and creator profile.")
        self.login = self._field(self.content, "USERNAME OR EMAIL")
        self.passwd = self._field(self.content, "PASSWORD", secret=True)
        self.passwd.bind("<Return>", lambda _e: self._sign_in())
        actions = tk.Frame(self.content, bg=BG)
        actions.pack(fill="x", pady=(17, 13))
        self._button(actions, "SIGN IN", self._sign_in, accent=True).pack(side="left", padx=(0, 8))
        self._button(actions, "GITHUB / WEB", lambda: self._browser("github")).pack(side="left")
        self._button(self.content, "CONNECT AN EXISTING FORGE HUB ACCOUNT",
                     lambda: self._browser("connect")).pack(anchor="w", pady=(2, 8))
        self._paragraph("GitHub authorization opens your browser. Never enter a GitHub password here.",
                        color="#E6A873")

    def _render_signup(self):
        self._paragraph("Create a Forge Hub account. Email confirmation may be required.")
        self.signup_name = self._field(self.content, "USERNAME (3–24 CHARACTERS)")
        self.signup_mail = self._field(self.content, "EMAIL")
        self.signup_password = self._field(self.content, "PASSWORD (AT LEAST 8 CHARACTERS)",
                                           secret=True)
        self._button(self.content, "CREATE ACCOUNT",
                     self._sign_up, accent=True).pack(anchor="w", pady=16)

    def _render_profile(self):
        if not self.client.signed_in:
            self._paragraph("You aren't signed in yet. Choose SIGN IN or connect through Forge Hub.")
            self._button(self.content, "SIGN IN", lambda: self._switch("signin"),
                         accent=True).pack(anchor="w")
            return
        self._paragraph("Connected accounts use the same identity on the launcher and Forge Hub.",
                        "#E6A873")
        profile = getattr(self, "_last_profile", {})
        for label, value in (
            ("EMAIL", profile.get("email") or "Loading..."),
            ("USERNAME", profile.get("username") or "Not set yet"),
            ("GITHUB", "LINKED" if profile.get("github_linked") else "NOT LINKED"),
        ):
            block = tk.Frame(self.content, bg="#151A20")
            block.pack(fill="x", pady=3)
            tk.Label(block, text=label, bg="#151A20", fg=ORANGE, width=12,
                     anchor="w", font=("Bahnschrift SemiBold", 9),
                     padx=8, pady=8).pack(side="left")
            tk.Label(block, text=value, bg="#151A20", fg=WHITE,
                     anchor="w", font=("Bahnschrift", 9),
                     padx=8, pady=8).pack(side="left", fill="x", expand=True)
        self.new_username = self._field(
            self.content, "ACCOUNT USERNAME",
            default=profile.get("username") or "")
        line = tk.Frame(self.content, bg=BG)
        line.pack(fill="x", pady=(14, 6))
        self._button(line, "SAVE USERNAME", self._save_username, accent=True).pack(
            side="left", padx=(0, 8))
        if not profile.get("github_linked"):
            self._button(line, "LINK GITHUB", lambda: self._browser("link")).pack(
                side="left", padx=(0, 8))
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", pady=(8, 5))
        self._button(row, "FORGE HUB WEBSITE",
                     lambda: webbrowser.open(WEB_ACCOUNT)).pack(side="left", padx=(0, 8))
        self._button(row, "SIGN OUT", self._sign_out).pack(side="left")

    def _run(self, fn, success):
        if self._busy:
            return
        self._busy = True
        self.status.set("Connecting securely to Forge Hub...")

        def task():
            try:
                result = fn()
                self._queue.put(("success", success, result))
            except AccountSessionExpired:
                self._queue.put(("expired", None, "Session expired. Please sign in again."))
            except (AccountError, ValueError, OSError) as exc:
                self._queue.put(("error", None, str(exc)))
            except Exception:
                self._queue.put(("error", None, "Authentication failed unexpectedly"))
        threading.Thread(target=task, daemon=True,
                         name="ForgeLauncherAccount").start()

    def _pump(self):
        if self._closed:
            return
        while True:
            try:
                kind, callback, value = self._queue.get_nowait()
            except queue.Empty:
                break
            if kind == "success":
                self._busy = False
                try:
                    callback(value)
                except Exception:
                    self.status.set("Account result could not be displayed")
            elif kind == "expired":
                # Keep DPAPI credentials untouched. A new sign-in (including
                # GitHub browser pairing) can atomically replace them.
                self._busy = False
                self.mode = "signin"
                self._render()
                self.status.set(value)
            elif kind == "pair":
                self._pair_check_busy = False
                if value:
                    self._signed_in(value)
                else:
                    self.window.after(2400, self._poll_pair)
            elif kind == "pair_error":
                self._pair_check_busy = False
                self.status.set(value)
            else:
                self._busy = False
                self.status.set(value)
        self.window.after(150, self._pump)

    def _signed_in(self, profile):
        self._last_profile = profile
        self.mode = "profile"
        self.status.set("Signed in to Forge Hub.")
        self._render()
        self.on_change()

    def _sign_in(self):
        username, password = self.login.get(), self.passwd.get()
        self.passwd.delete(0, "end")
        self._run(lambda: self.client.sign_in(username, password), self._signed_in)
        password = None

    def _sign_up(self):
        username, email, password = (
            self.signup_name.get(), self.signup_mail.get(),
            self.signup_password.get())
        self.signup_password.delete(0, "end")
        def done(result):
            if result.get("requires_confirmation"):
                self.mode = "signin"
                self._render()
                self.status.set(result.get("message", "Check your email to confirm."))
            else:
                self._run(self.client.profile, self._signed_in)
        self._run(lambda: self.client.sign_up(username, email, password), done)
        password = None

    def _save_username(self):
        name = self.new_username.get()
        self._run(lambda: self.client.save_username(name), self._signed_in)

    def _sign_out(self):
        self._run(self.client.sign_out, self._signed_out)

    def _signed_out(self, _result):
        self._last_profile = {}
        self.mode = "signin"
        self.status.set("Signed out locally. Your Forge Hub mods were not changed.")
        self._render()
        self.on_change()

    def _browser(self, mode):
        self._run(lambda: self.client.begin_browser(mode), self._browser_started)

    def _browser_started(self, result):
        self.status.set(
            "Browser authorization: " + result["code"] +
            " — Confirm this same code on the Forge Hub website.")
        webbrowser.open(result["url"])
        self.window.after(1700, self._poll_pair)

    def _poll_pair(self):
        if self._closed or self._busy or self._pair_check_busy:
            return
        if not self.client._pending:
            return
        self._pair_check_busy = True
        def worker():
            try:
                result = self.client.finish_browser()
                self._queue.put(("pair", None, result))
            except (AccountError, OSError) as exc:
                self._queue.put(("pair_error", None, str(exc)))
        threading.Thread(target=worker, daemon=True,
                         name="ForgeLauncherBrowserLink").start()

    def close(self):
        self._closed = True
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.window.destroy()


def open_account_dialog(parent, client, on_change=None):
    return AccountDialog(parent, client, on_change)
