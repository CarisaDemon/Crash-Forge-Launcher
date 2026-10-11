"""Crash Forge styled confirmations for launcher game and Forge Hub actions.

These replace native Windows question-mark dialogs. They do not install,
download or update anything; callers retain exclusive control over actions.
"""
from __future__ import annotations

import os
import re
import tkinter as tk
import forge_mod_manager as mod_manager

_PALETTE = {
    "background": "#090B0E",
    "panel": "#12151A",
    "panel2": "#1C2128",
    "panel3": "#0B0E12",
    "edge": "#404750",
    "orange": "#FF6A00",
    "orange2": "#D75707",
    "ember": "#FFB445",
    "white": "#F4F0E8",
    "muted": "#9DA5AC",
}
_VERSION = re.compile(r"^[a-zA-Z0-9._-]{1,80}$")
_MOD_ID = re.compile(r"^[a-zA-Z0-9_-]{1,72}$")


def _text(value, length=140):
    # Keep remote catalog titles from injecting control characters or
    # smashing a compact popup layout.
    value = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    value = "".join(c for c in value if c.isprintable())
    return value[:length]


def _show_confirmation(
    parent, *, category, heading, subheading, rows, note,
    accept="INSTALL", cancel="CANCEL", icon_path=None, preview=False,
    on_close=None
):
    """Blocking centered confirmation, True only on affirmative click."""
    colors = _PALETTE
    win = tk.Toplevel(parent)
    win.title("Crash Forge: Racing / " + _text(category, 48))
    win.configure(bg=colors["background"])
    win.resizable(False, False)
    win.transient(parent)
    width, height = 600, 386
    try:
        pw, ph = parent.winfo_width(), parent.winfo_height()
        sw, sh = parent.winfo_screenwidth(), parent.winfo_screenheight()
        width = min(width, max(360, sw - 46))
        height = min(height, max(316, sh - 90))
        x = max(0, min(sw - width, parent.winfo_rootx() + (pw - width) // 2))
        y = max(0, min(sh - height, parent.winfo_rooty() + (ph - height) // 2))
        win.geometry(f"{width}x{height}+{x}+{y}")
    except (TypeError, ValueError, tk.TclError):
        win.geometry(f"{width}x{height}")

    # Keep the native close/minimize controls available. A borderless,
    # grabbed Toplevel can become unresponsive to mouse focus on Windows.
    # The interior keeps the same steel/orange Crash Forge look.
    border = tk.Frame(win, bg="#8B390A", padx=2, pady=2)
    border.pack(fill="both", expand=True)
    shell = tk.Frame(border, bg=colors["panel"])
    shell.pack(fill="both", expand=True)
    bar = tk.Frame(shell, bg=colors["orange"], width=4)
    bar.pack(side="left", fill="y")
    body = tk.Frame(shell, bg=colors["panel"])
    body.pack(side="left", fill="both", expand=True)
    header = tk.Canvas(
        body, height=79, bg=colors["panel2"], highlightthickness=0, bd=0
    )
    header.pack(fill="x")

    def paint_header(event=None):
        w = max(100, header.winfo_width())
        header.delete("all")
        header.create_rectangle(0, 0, w, 79, fill=colors["panel2"], outline="")
        header.create_polygon(
            0, 0, w - 14, 0, w, 14, w, 79, 0, 79,
            fill=colors["panel2"], outline="")
        header.create_line(14, 74, w - 14, 74, fill="#6A2B08", width=1)
        header.create_line(14, 76, w - 14, 76, fill=colors["orange"], width=2)
        header.create_polygon(19, 36, 34, 11, 49, 36,
                              fill="#502207", outline=colors["ember"], width=2)
        header.create_polygon(27, 32, 34, 19, 41, 32,
                              fill=colors["orange"], outline="")
        header.create_text(61, 18, text="CRASH FORGE: RACING", anchor="w",
                           fill=colors["white"],
                           font=("Bahnschrift SemiBold", 10))
        header.create_text(61, 45, text=_text(category.upper(), 42),
                           anchor="w", fill=colors["ember"],
                           font=("Bahnschrift SemiBold", 17))
        for sx in (12, w - 14):
            header.create_oval(sx - 2, 8, sx + 2, 12,
                               fill="#08090B", outline="#646C74")

    header.bind("<Configure>", paint_header)

    if icon_path and os.path.isfile(icon_path):
        try:
            icon = tk.PhotoImage(file=icon_path)
            factor = max(1, (max(icon.width(), icon.height()) + 37) // 38)
            win._forge_icon = icon.subsample(factor, factor)
            # Window icon is optional on some versions of Tk/Windows.
            win.iconphoto(True, icon)
        except (OSError, tk.TclError):
            pass

    result = {"accepted": False}

    def finish(accept_it=False):
        result["accepted"] = bool(accept_it) and not preview
        try:
            win.grab_release()
        except tk.TclError:
            pass
        win.destroy()
        if on_close is not None:
            try:
                parent.after(150, on_close)
            except tk.TclError:
                pass

    close = tk.Label(
        header, text="×", bg=colors["panel2"], fg="#D7D4CD",
        font=("Bahnschrift", 18), cursor="hand2")
    close.place(relx=1.0, x=-26, y=4, anchor="ne", width=28, height=29)
    close.bind("<Button-1>", lambda e: finish(False))

    details = tk.Frame(body, bg=colors["panel"], padx=18, pady=13)
    details.pack(fill="both", expand=True)
    tk.Label(
        details, text=_text(heading, 115), bg=colors["panel"],
        fg=colors["white"], font=("Bahnschrift SemiBold", 12),
        justify="left", anchor="w", wraplength=max(250, width - 88)
    ).pack(fill="x", pady=(0, 4))
    tk.Label(
        details, text=_text(subheading, 190), bg=colors["panel"],
        fg=colors["muted"], font=("Bahnschrift", 9),
        justify="left", anchor="w", wraplength=max(250, width - 88)
    ).pack(fill="x", pady=(0, 12))

    fact_panel = tk.Frame(
        details, bg=colors["panel3"], highlightthickness=1,
        highlightbackground=colors["edge"], padx=11, pady=9)
    fact_panel.pack(fill="x")
    for key, value in rows[:3]:
        line = tk.Frame(fact_panel, bg=colors["panel3"])
        line.pack(fill="x", pady=2)
        tk.Label(
            line, text=_text(key.upper(), 16), bg=colors["panel3"],
            fg="#A0A8B0", font=("Bahnschrift SemiBold", 8), width=13,
            anchor="w").pack(side="left")
        tk.Label(
            line, text=_text(value, 100), bg=colors["panel3"],
            fg=colors["ember"] if key.upper() == "DESTINATION" else
               colors["white"], font=("Bahnschrift", 9), anchor="w"
        ).pack(side="left", fill="x", expand=True)

    tk.Label(
        details, text=_text(note, 220), bg=colors["panel"], fg=colors["muted"],
        font=("Bahnschrift", 8), justify="left", anchor="w",
        wraplength=max(250, width - 88)
    ).pack(fill="x", pady=(10, 0))
    if preview:
        tk.Label(
            details, text="DESIGN PREVIEW  ·  NO DOWNLOAD",
            bg=colors["panel"], fg=colors["orange"],
            font=("Bahnschrift SemiBold", 8), anchor="w"
        ).pack(fill="x", pady=(5, 0))

    footer = tk.Frame(body, bg=colors["panel"], padx=18, pady=13)
    footer.pack(side="bottom", fill="x")
    buttons = [
        (cancel, False, "#282E35", "#F3EFE6", "#414951"),
        (accept, True, "#A84305", "#FFFFFF", colors["orange"]),
    ]
    for index, (label, value, bg, fg, hover) in enumerate(buttons):
        b = tk.Button(
            footer, text=label, command=lambda yes=value: finish(yes),
            bg=bg, fg=fg, activebackground=hover,
            activeforeground="#FFFFFF", relief="flat", bd=0,
            cursor="hand2", font=("Bahnschrift SemiBold", 9),
            padx=10, pady=8, takefocus=True)
        b.pack(side="left", fill="x", expand=True,
               padx=(0, 6) if index == 0 else (6, 0))

    win.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    win.bind("<Escape>", lambda event: finish(False))
    if not preview:
        win.bind("<Return>", lambda event: finish(True))
    win.lift()
    win.focus_set()
    if preview:
        # Screenshot dialogs are deliberately non-modal: no Tk grab,
        # no nested wait loop and no action can be accepted.
        return False
    try:
        win.wait_visibility()
        win.grab_set()
    except tk.TclError:
        pass
    parent.wait_window(win)
    return result["accepted"]


def ask_mod_install(parent, mod, local=False, icon_path=None, preview=False,
                    on_close=None, game_path=None):
    """Confirm a Forge Hub mod install with the actual new root-mod path."""
    author = _text(mod.get("author") or "Unknown creator", 85)
    title = _text(mod.get("title") or "Community mod", 100)
    mod_id = _text(mod.get("id") or "", 72)
    folder_name = mod_manager.folder_name_for_title(title)
    if game_path and _MOD_ID.fullmatch(mod_id):
        try:
            folder_name = mod_manager.mod_path(
                game_path, str(mod.get("type") or "Kart"), mod_id,
                title=title, prefer_readable=True).name
        except mod_manager.ModManagerError:
            pass
    destination = "mods/" + folder_name
    return _show_confirmation(
        parent,
        category="INSTALL MOD",
        heading="Install " + title + "?",
        subheading="Creator: " + author,
        rows=[
            ("SOURCE", "LOCAL ZIP" if local else "FORGE HUB CATALOG"),
            ("DESTINATION", destination),
            ("SECURITY", "SHA-256 VERIFIED"),
        ],
        note="Existing version is backed up. Other mods remain untouched.",
        accept="INSTALL MOD", cancel="CANCEL",
        icon_path=icon_path, preview=preview, on_close=on_close,
    )


def ask_game_update(parent, release, installed, folder, icon_path=None):
    """Modern version of the official GitHub release confirmation."""
    asset = release.get("asset") or {}
    version = _text(release.get("version"), 50)
    local = _text(installed or "unknown", 50)
    return _show_confirmation(
        parent,
        category="GAME UPDATE",
        heading="Update Crash Forge: Racing?",
        subheading=f"Installed: {local}    →    Available: v{version}",
        rows=[
            ("RELEASE", "v" + version),
            ("PACKAGE", _text(asset.get("name") or "Windows game ZIP", 80)),
            ("SECURITY", "SHA-256 VERIFIED"),
        ],
        note="Game files are backed up. Mods and saves stay untouched. Close the game before updating.",
        accept="UPDATE GAME", cancel="CANCEL",
        icon_path=icon_path,
    )


def preview_newer_version(parent, icon_path=None):
    """Inert visual-only preview of the new launcher version notification."""
    return _show_confirmation(
        parent,
        category="NEW VERSION",
        heading="Crash Forge Launcher v0.3.42",
        subheading="A newer launcher build is ready for testing.",
        rows=[
            ("INSTALLED", "v0.3.41"),
            ("AVAILABLE", "v0.3.42"),
            ("STATUS", "UPDATE PREVIEW"),
        ],
        note="This preview does not install, replace or download anything.",
        accept="UPDATE LAUNCHER", cancel="CLOSE",
        icon_path=icon_path, preview=True,
    )
