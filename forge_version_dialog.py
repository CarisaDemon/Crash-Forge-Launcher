"""Branded, wallpaper-free game-version warning for Crash Forge Launcher.

Future online compatibility may use the same verified-release state. The
warning NEVER updates the game or blocks playing without the user's choice.
"""
import os
import tkinter as tk


def ask_play_outdated(parent, context, icon_path=None):
    """Show a modal English confirmation; True only for PLAY ANYWAY."""
    if not isinstance(context, dict) or not context.get("available"):
        return True

    colors = {
        "bg": "#090B0E", "panel": "#12151A", "steel": "#1B2027",
        "edge": "#343B43", "orange": "#FF6A00", "amber": "#FFB349",
        "white": "#F4F1EA", "muted": "#A5ADB6",
    }
    win = tk.Toplevel(parent)
    win.title("Crash Forge: Racing - Version Warning")
    win.configure(bg=colors["bg"])
    win.resizable(False, False)
    win.transient(parent)

    width, height = 545, 328
    try:
        current_w = int(parent.winfo_width())
        current_x = int(parent.winfo_rootx())
        current_y = int(parent.winfo_rooty())
        current_h = int(parent.winfo_height())
        screen_w = int(parent.winfo_screenwidth())
        screen_h = int(parent.winfo_screenheight())
        width = min(width, max(350, screen_w - 55))
        height = min(height, max(288, screen_h - 85))
        x = max(0, min(screen_w - width, current_x + (current_w - width) // 2))
        y = max(0, min(screen_h - height, current_y + (current_h - height) // 2))
        win.geometry(f"{width}x{height}+{x}+{y}")
    except (tk.TclError, ValueError, TypeError):
        win.geometry(f"{width}x{height}")

    outer = tk.Frame(
        win, bg=colors["panel"], highlightbackground="#7B350D",
        highlightthickness=2)
    outer.pack(fill="both", expand=True, padx=9, pady=9)
    orange_bar = tk.Frame(outer, bg=colors["orange"], width=4)
    orange_bar.pack(side="left", fill="y")

    inside = tk.Frame(outer, bg=colors["panel"])
    inside.pack(side="left", fill="both", expand=True)
    plate = tk.Canvas(
        inside, height=73, bg=colors["steel"],
        highlightthickness=0, bd=0)
    plate.pack(fill="x")
    plate.create_polygon(
        0, 0, width, 0, width - 14, 73, 0, 73,
        fill=colors["steel"], outline="")
    plate.create_line(18, 63, width - 33, 63,
                      fill=colors["orange"], width=2)
    plate.create_line(18, 60, width - 33, 60,
                      fill="#65300D", width=1)
    for px in (17, width - 43):
        plate.create_oval(px - 3, 8, px + 3, 14,
                          fill="#0B0E12", outline="#6C7078")
    plate.create_polygon(
        24, 26, 37, 4, 50, 26,
        fill="#562908", outline=colors["amber"], width=2)
    plate.create_text(37, 18, text="!",
                      fill=colors["white"],
                      font=("Bahnschrift SemiBold", 12))
    plate.create_text(
        64, 16, text="CRASH FORGE: RACING",
        anchor="w", fill=colors["white"],
        font=("Bahnschrift SemiBold", 10))
    plate.create_text(
        64, 39, text="VERSION WARNING",
        anchor="w", fill=colors["amber"],
        font=("Bahnschrift SemiBold", 15))

    if icon_path and os.path.isfile(icon_path):
        try:
            logo = tk.PhotoImage(file=icon_path)
            factor = max(1, (max(logo.width(), logo.height()) + 39) // 40)
            win._forge_logo = logo.subsample(factor, factor)
            plate.create_image(width - 81, 34, image=win._forge_logo)
        except (OSError, tk.TclError):
            pass

    main = tk.Frame(inside, bg=colors["panel"])
    main.pack(fill="both", expand=True, padx=18, pady=(12, 2))
    headline = ("GAME VERSION COULD NOT BE VERIFIED"
                if context.get("unknown") else
                "A NEWER GAME VERSION IS AVAILABLE")
    tk.Label(
        main, text=headline,
        font=("Bahnschrift SemiBold", 10),
        bg=colors["panel"], fg=colors["white"],
        anchor="w").pack(fill="x")

    if context.get("unknown"):
        explanation = (
            "Your installed version couldn't be verified. "
            "A newer release may be available. Continue anyway?")
    else:
        explanation = (
            "You're about to play an older version. "
            "Do you want to continue without updating?")
    tk.Label(
        main, text=explanation,
        font=("Bahnschrift", 9), bg=colors["panel"],
        fg=colors["muted"], wraplength=max(240, width - 90),
        justify="left", anchor="w",
    ).pack(fill="x", pady=(5, 8))

    versions = tk.Frame(main, bg="#0D1014",
                        highlightbackground=colors["edge"],
                        highlightthickness=1)
    versions.pack(fill="x")
    for title, value, foreground in (
        ("INSTALLED", ("v" + str(context["installed"])
                       if context.get("installed") else "UNKNOWN"), colors["muted"]),
        ("AVAILABLE", "v" + str(context["available"]), colors["amber"]),
    ):
        col = tk.Frame(versions, bg="#0D1014")
        col.pack(side="left", fill="x", expand=True, padx=9, pady=6)
        tk.Label(
            col, text=title, bg="#0D1014", fg="#7B838C",
            anchor="w", font=("Bahnschrift SemiBold", 7)
        ).pack(fill="x")
        tk.Label(
            col, text=value, bg="#0D1014", fg=foreground,
            anchor="w", font=("Bahnschrift SemiBold", 10)
        ).pack(fill="x")

    tk.Label(
        main, text="Future online features may require an updated version.",
        bg=colors["panel"], fg="#7F8790",
        font=("Bahnschrift", 8), justify="left",
        anchor="w", wraplength=max(240, width - 90)
    ).pack(fill="x", pady=(7, 0))

    selected = {"play": False}

    def finish(accepted=False):
        selected["play"] = bool(accepted)
        try:
            win.grab_release()
        except tk.TclError:
            pass
        win.destroy()

    footer = tk.Frame(inside, bg=colors["panel"])
    footer.pack(side="bottom", fill="x", padx=18, pady=(5, 14))
    tk.Button(
        footer, text="CANCEL", command=lambda: finish(False),
        bg="#252B33", fg=colors["white"], relief="flat",
        activebackground="#343D47", activeforeground="#FFFFFF",
        cursor="hand2", font=("Bahnschrift SemiBold", 9),
        padx=12, pady=9
    ).pack(side="left", fill="x", expand=True, padx=(0, 7))
    tk.Button(
        footer, text="PLAY ANYWAY", command=lambda: finish(True),
        bg="#A94404", fg="#FFFFFF", relief="flat",
        activebackground=colors["orange"], activeforeground="#FFFFFF",
        cursor="hand2", font=("Bahnschrift SemiBold", 9),
        padx=12, pady=9
    ).pack(side="left", fill="x", expand=True, padx=(7, 0))

    win.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    win.bind("<Escape>", lambda event: finish(False))
    win.bind("<Return>", lambda event: finish(True))
    win.grab_set()
    win.focus_set()
    parent.wait_window(win)
    return selected["play"]
