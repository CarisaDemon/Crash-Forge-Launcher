import os
import sys
import webbrowser
import json
import textwrap
import threading
import queue
import ctypes
import subprocess
from datetime import datetime
from forge_tcl_bootstrap import prepare_frozen_tcl
prepare_frozen_tcl()
import tkinter as tk
from tkinter import font as tkfont, filedialog, messagebox
from forge_live_ui import ForgeLiveMixin
import forge_services as services
import forge_mod_metadata as modmeta
import forge_releases as releases
import forge_launcher_updates as launcher_updates
import forge_news_history as news_history
import forge_game_news as game_news
import forge_editor_registry as editor_registry
import forge_editor_geometry as editor_geometry
import forge_editor_config as editor_config
import forge_mod_manager as mod_manager
import forge_account_badge as account_badge
from forge_dialogs import ask_mod_install, preview_newer_version
from forge_account_client import (AccountClient, AccountError,
    AccountSessionExpired, AccountServiceUnavailable)
from forge_account_ui import open_account_dialog

try:
    from PIL import Image, ImageTk, ImageOps
except ImportError:
    Image = None
    ImageTk = None
    ImageOps = None

BASE_DIR = (os.path.dirname(os.path.abspath(sys.executable))
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
BUTTON_DIR = os.path.join(BASE_DIR, "assets", "buttons")
ART_DIR = os.path.join(BASE_DIR, "assets", "art")
VERSION_FILE = os.path.join(BASE_DIR, "launcher_version.txt")
COMMUNITY_CATALOG_FILE = os.path.join(BASE_DIR, "community_catalog.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "launcher_settings.json")
OGG_TOOL_PATH = os.environ.get("CFR_OGG_TOOL_PATH", "")
CSEQ_TOOL_PATH = os.environ.get("CFR_CSEQ_TOOL_PATH", "")
BASE_WIDTH = 1280
BASE_HEIGHT = 820
FORGE_HUB_WEB_URL = "https://carisademon.github.io/Crash-Forge-Racing/forge-hub/"

try:
    with open(VERSION_FILE, "r", encoding="utf-8") as _vf:
        APP_VERSION = _vf.read().strip() or "0.2.0"
except OSError:
    APP_VERSION = "0.2.0"

COLORS = {
    "bg": "#08090B",
    "panel": "#101217",
    "panel2": "#15181E",
    "line": "#2A2F36",
    "line_hot": "#6A2A08",
    "orange": "#FF6A00",
    "amber": "#FFB000",
    "text": "#F2F2EF",
    "muted": "#8D929A",
    "dark": "#050608",
    "success": "#56C47A",
}

def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % rgb

def mix(a, b, t):
    ar, ag, ab = hex_to_rgb(a)
    br, bg, bb = hex_to_rgb(b)
    return rgb_to_hex((
        int(ar + (br - ar) * t),
        int(ag + (bg - ag) * t),
        int(ab + (bb - ab) * t),
    ))

class ForgeButton(tk.Canvas):
    WIDTH = 248
    HEIGHT = 78

    def __init__(self, master, text, asset_name, command=None, accent=False, **kwargs):
        super().__init__(
            master,
            width=self.WIDTH,
            height=self.HEIGHT,
            bg=COLORS["panel"],
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            **kwargs
        )
        self.text = text
        self.asset_name = asset_name
        self.command = command
        self.accent = accent
        self.state = "normal"
        self.disabled = False
        self.ui_scale = 1.0
        self.images = {}
        self._load_images()
        self.bind("<Enter>", lambda e: self.set_state("hover") if not self.disabled else None)
        self.bind("<Leave>", lambda e: self.set_state("normal"))
        self.bind("<ButtonPress-1>", lambda e: self.set_state("pressed"))
        self.bind("<ButtonRelease-1>", self._release)
        self.render()

    def _load_images(self):
        for state in ("normal", "hover", "pressed"):
            path = os.path.join(BUTTON_DIR, f"{self.asset_name}_{state}.png")
            if os.path.exists(path):
                try:
                    self.images[state] = tk.PhotoImage(file=path)
                except tk.TclError:
                    pass

    def _release(self, event):
        width = self.WIDTH * self.ui_scale
        height = self.HEIGHT * self.ui_scale
        inside = 0 <= event.x <= width and 0 <= event.y <= height
        self.set_state("hover" if inside else "normal")
        if inside and not self.disabled and self.command:
            self.command()

    def set_label(self, label):
        if self.text != label:
            self.text = str(label)
            self.render()

    def set_disabled(self, disabled):
        disabled = bool(disabled)
        if self.disabled != disabled:
            self.disabled = disabled
            self.state = "normal"
            self.configure(cursor="arrow" if disabled else "hand2")
            self.render()

    def set_accent(self, enabled):
        """Switch the existing forged orange/grey artwork, not the button itself."""
        enabled = bool(enabled)
        if self.accent != enabled:
            self.accent = enabled
            self.render()

    def set_ui_scale(self, scale):
        scale = max(0.50, min(1.18, float(scale)))
        if abs(scale - self.ui_scale) < 0.01:
            return
        self.ui_scale = scale
        self.render()

    def set_state(self, state):
        self.state = state
        self.render()

    def _plate_points(self, inset=0):
        w = self.WIDTH
        h = self.HEIGHT
        c = 11 + inset
        return (
            10 + inset, inset,
            w - 10 - inset, inset,
            w - inset, c,
            w - inset, h - c,
            w - 10 - inset, h - inset,
            10 + inset, h - inset,
            inset, h - c,
            inset, c,
        )

    def _screw(self, x, y, bright=False):
        rim = "#9A6A45" if bright else "#4A4D51"
        face = "#211E1C" if bright else "#1A1C20"
        self.create_oval(x-5, y-5, x+5, y+5, fill="#08090B", outline="#050505", width=1)
        self.create_oval(x-3.4, y-3.4, x+3.4, y+3.4, fill=face, outline=rim, width=1)
        self.create_line(x-2.2, y+1.2, x+2.2, y-1.2, fill="#050505", width=1)

    def _draw_play_icon(self, glow):
        if glow:
            self.create_polygon(43, 23, 43, 55, 72, 39, fill="#6F2700", outline="")
            self.create_polygon(46, 26, 46, 52, 69, 39, fill="#FF7A00", outline="#FFB545")
        else:
            self.create_polygon(46, 26, 46, 52, 69, 39, fill="#8D8F91", outline="#C7C8C8")

    def _draw_update_icon(self, glow):
        # Angular twin-arrow refresh icon: cleaner than Tk arcs at this size.
        col = "#FF8A19" if glow else "#C4C5C5"
        shadow = "#6A2704" if glow else "#53575C"
        dark = "#121418"

        top = (
            38, 34, 38, 28, 46, 21, 56, 18,
            66, 20, 73, 25, 68, 31, 63, 27,
            56, 25, 50, 27, 46, 31, 46, 34,
            53, 34, 43, 43, 33, 34
        )
        bottom = (
            76, 43, 76, 49, 68, 56, 58, 59,
            48, 57, 41, 52, 46, 46, 51, 50,
            58, 52, 64, 50, 68, 46, 68, 43,
            61, 43, 71, 34, 81, 43
        )

        # small shadow offset gives the forged/embossed look
        self.create_polygon(tuple(v + (1 if i % 2 == 0 else 2) for i, v in enumerate(top)),
                            fill=shadow, outline="")
        self.create_polygon(tuple(v + (1 if i % 2 == 0 else 2) for i, v in enumerate(bottom)),
                            fill=shadow, outline="")
        self.create_polygon(top, fill=col, outline=dark, width=1)
        self.create_polygon(bottom, fill=col, outline=dark, width=1)

        # metallic highlight on each arrow
        hi = "#FFE1B8" if glow else "#F1F1EF"
        self.create_line(47, 23, 56, 20, 65, 22, fill=hi, width=1)
        self.create_line(67, 54, 58, 57, 49, 55, fill=hi, width=1)

    def _draw_repair_icon(self, glow):
        col = "#FF8A19" if glow else "#C2C3C2"
        dark = "#5C2506" if glow else "#4F5256"
        self.create_line(43, 56, 67, 32, fill=dark, width=12, capstyle="round")
        self.create_line(43, 56, 67, 32, fill=col, width=7, capstyle="round")
        self.create_oval(37, 50, 49, 62, fill=col, outline=dark, width=2)
        self.create_oval(40.5, 53.5, 45.5, 58.5, fill="#15171A", outline="")
        self.create_polygon(
            62, 31, 64, 20, 69, 17, 72, 26, 80, 24, 80, 31,
            72, 38, fill=col, outline=dark, width=1
        )
        self.create_polygon(68, 21, 71, 29, 78, 27, 74, 34, 67, 33,
                            fill="#15171A", outline="")

    def _draw_mods_icon(self, glow):
        col = "#FF8A19" if glow else "#C0C1C1"
        shadow = "#5B2200" if glow else "#55585D"
        # cube top
        self.create_polygon(40, 27, 57, 18, 76, 28, 58, 38,
                            fill="", outline=shadow, width=5)
        self.create_polygon(40, 27, 57, 18, 76, 28, 58, 38,
                            fill="#14161A", outline=col, width=2)
        # left / right faces
        self.create_polygon(40, 27, 58, 38, 58, 59, 40, 48,
                            fill="#17191D", outline=col, width=2)
        self.create_polygon(58, 38, 76, 28, 76, 49, 58, 59,
                            fill="#0F1114", outline=col, width=2)
        self.create_line(49, 32, 67, 23, fill=col, width=2)
        self.create_line(58, 39, 58, 58, fill=col, width=2)

    def _draw_icon(self, glow):
        if self.asset_name == "play":
            self._draw_play_icon(glow)
        elif self.asset_name == "update":
            self._draw_update_icon(glow)
        elif self.asset_name == "repair":
            self._draw_repair_icon(glow)
        elif self.asset_name == "mods":
            self._draw_mods_icon(glow)

    def render(self):
        self.delete("all")
        img = self.images.get(self.state) or self.images.get("normal")
        if img and not self.disabled:
            self.create_image(self.WIDTH // 2, self.HEIGHT // 2, image=img)
            return

        hot = (self.accent or self.state in ("hover", "pressed")) and not self.disabled

        if self.accent:
            if self.state == "pressed":
                face = "#2A1208"
                edge = "#FF6A00"
                glow = "#5A2105"
                text = "#F4E8DC"
            elif self.state == "hover":
                face = "#4A1B07"
                edge = "#FFB02E"
                glow = "#A83B00"
                text = "#FFF5E8"
            else:
                face = "#351507"
                edge = "#FF6A00"
                glow = "#7A2900"
                text = "#FFF1E0"
        else:
            if self.state == "pressed":
                face = "#101216"
                edge = "#B64A11"
                glow = "#351608"
                text = "#D5D6D4"
            elif self.state == "hover":
                face = "#1D2026"
                edge = "#FF6A00"
                glow = "#6D2600"
                text = "#FFFFFF"
            else:
                face = "#171A1F"
                edge = "#4A4F56"
                glow = "#2A1208"
                text = "#D9DAD8"

        if self.disabled:
            face, edge, glow, text = "#111316", "#3A3F45", "#121417", "#707780"

        # deep shadow and orange underglow
        self.create_polygon(self._plate_points(0), fill="#060708", outline="")
        if hot:
            self.create_polygon(self._plate_points(1), fill=glow, outline="")
        else:
            # subtle forge glow along the left and lower edge
            self.create_line(6, 16, 6, 61, fill="#5C2207", width=3)
            self.create_line(14, 73, 226, 73, fill="#4A1A05", width=2)

        # outer forged frame
        self.create_polygon(self._plate_points(4), fill="#0C0D10", outline=edge, width=2)
        self.create_polygon(self._plate_points(8), fill=face, outline="#2B2E33", width=1)

        # bevel highlights and scratches
        self.create_line(22, 13, 220, 13, fill=mix(edge, "#FFFFFF", 0.28), width=1)
        self.create_line(18, 17, 92, 17, fill="#5D6065" if not hot else "#A34713", width=1)
        self.create_line(19, 62, 213, 62, fill="#090A0C", width=2)
        self.create_line(88, 29, 166, 29, fill="#21242A", width=1)
        self.create_line(111, 49, 206, 49, fill="#111318", width=1)

        # rivets / screws
        self._screw(17, 16, hot)
        self._screw(231, 16, hot)
        self._screw(17, 62, hot)
        self._screw(231, 62, hot)

        # icon and separator
        self._draw_icon(hot)
        self.create_line(91, 20, 91, 58, fill="#2A2D31", width=1)

        # label
        y = 40 if self.state != "pressed" else 42
        self.create_text(
            108, y,
            text=self.text,
            anchor="w",
            fill=text,
            font=("Bahnschrift SemiBold", max(12, int(round(19 * self.ui_scale)))),
        )

        # small hot-metal edge on the right
        if hot:
            self.create_line(239, 24, 239, 54, fill="#FF8A18", width=2)

        if abs(self.ui_scale - 1.0) > 0.001:
            self.scale("all", 0, 0, self.ui_scale, self.ui_scale)

        self.configure(
            width=max(1, int(round(self.WIDTH * self.ui_scale))),
            height=max(1, int(round(self.HEIGHT * self.ui_scale))),
        )

class Launcher(ForgeLiveMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Crash Forge: Racing Launcher v{APP_VERSION}")
        self.geometry("1280x820")
        self.minsize(760, 520)
        self.configure(bg=COLORS["bg"])
        self._is_maximized = False
        self._restore_geometry = None
        self.ui_scale = 1.0
        self._responsive_job = None
        self._settings_user_expanded = None
        self._active_dashboard_tab = "INSTALLATION"
        self._dashboard_layout_state = None
        self._right_card_layout_state = None
        self._resize_origin = None
        self._button_layout_scale = 1.0
        self.account_client = AccountClient()
        self._account_dialog = None
        self._account_badge_profile = self.account_client.cached_profile()
        self._account_badge_connected = False
        self._account_badge_pending = bool(self.account_client.signed_in)
        self._account_badge_problem = None
        self._account_badge_busy = False
        self._account_badge_retry_failures = 0
        self._account_badge_generation = 0
        self._account_badge_queue = queue.Queue()
        self._account_badge_avatar_url = ""
        self._account_badge_avatar_photo = None
        self._account_popup = None

        # Keep our custom frame, but register this window as a real Windows app
        # so it appears in the taskbar and Alt+Tab.
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "CrashForge.Racing.Launcher"
            )
        except Exception:
            pass

        self._app_icon = None
        self._load_app_icon()
        self._launcher_background = None
        self._launcher_background_source = None
        self._launcher_background_size = (0, 0)
        self._background_resize_job = None
        self._fondo_canvases = []
        self._load_launcher_background()

        self.overrideredirect(True)
        self._drag_x = 0
        self._drag_y = 0
        self._center()
        self._build()
        self._post_init_live()
        self.bind("<Configure>", self._on_root_configure, add="+")
        self.bind("<Configure>", self._account_badge_reposition_popup, add="+")
        self.bind("<Button-1>", self._account_badge_parent_click, add="+")
        self.after(40, self._refresh_launcher_background)
        self.after(120, self._apply_responsive_layout)
        self.after(200, self._account_badge_refresh_async)
        self.after(220, self._account_badge_poll)
        self.after(120000, self._account_badge_periodic)

        # Tk marks borderless windows as tool windows on Windows. Fix the
        # extended style after the native HWND exists.
        self.after(80, self._enable_windows_appwindow)

    def _load_app_icon(self):
        png_path = os.path.join(BASE_DIR, "assets", "icons", "cfr_icon.png")
        if not os.path.exists(png_path):
            png_path = os.path.join(BASE_DIR, "assets", "CFR ICON.png")

        self._native_icon_path = os.path.join(
            BASE_DIR, "assets", "icons", "cfr_icon.ico"
        )

        if os.path.exists(png_path):
            try:
                self._app_icon = tk.PhotoImage(file=png_path)
                self.iconphoto(True, self._app_icon)
            except tk.TclError:
                self._app_icon = None

        if os.path.exists(self._native_icon_path):
            try:
                self.iconbitmap(default=self._native_icon_path)
            except tk.TclError:
                pass

    def _load_launcher_background(self):
        background_path = os.path.join(BASE_DIR, "assets", "Fondo.png")
        if not os.path.exists(background_path):
            background_path = os.path.join(BASE_DIR, "assets", "Fondo_launcher.png")

        self._launcher_background_path = background_path

        if not os.path.exists(background_path):
            self._launcher_background = None
            self._launcher_background_source = None
            return

        if Image is not None and ImageTk is not None:
            try:
                self._launcher_background_source = Image.open(background_path).convert("RGB")
                # Create a harmless initial image; it is resized to the actual
                # launcher dimensions immediately after the UI is built.
                initial = self._launcher_background_source.resize(
                    (BASE_WIDTH, BASE_HEIGHT),
                    Image.Resampling.LANCZOS,
                )
                self._launcher_background = ImageTk.PhotoImage(initial)
                self._launcher_background_size = (BASE_WIDTH, BASE_HEIGHT)
                return
            except Exception:
                self._launcher_background_source = None

        try:
            self._launcher_background = tk.PhotoImage(file=background_path)
        except tk.TclError:
            self._launcher_background = None

    def _refresh_launcher_background(self):
        self._background_resize_job = None

        if self._launcher_background_source is None or ImageTk is None:
            # Fallback path when Pillow is unavailable.
            for canvas in list(getattr(self, "_fondo_canvases", [])):
                try:
                    self._paint_fondo_canvas(canvas)
                except Exception:
                    pass
            if hasattr(self, "_header_canvas"):
                self._paint_floating_header()
            if hasattr(self, "hero_canvas"):
                self._paint_hero()
            return

        try:
            width = max(1, int(self.winfo_width()))
            height = max(1, int(self.winfo_height()))
        except Exception:
            return

        target = (width, height)
        if target != self._launcher_background_size:
            try:
                # Exact fit: the complete workshop image remains visible at
                # every launcher size instead of being cropped off-screen.
                resized = self._launcher_background_source.resize(
                    target,
                    Image.Resampling.LANCZOS,
                )
                self._launcher_background = ImageTk.PhotoImage(resized)
                self._launcher_background_size = target
            except Exception:
                return

        for canvas in list(getattr(self, "_fondo_canvases", [])):
            try:
                if canvas.winfo_exists():
                    self._paint_fondo_canvas(canvas)
            except Exception:
                pass

        if hasattr(self, "_header_canvas"):
            try:
                self._paint_floating_header()
            except Exception:
                pass

        if hasattr(self, "hero_canvas"):
            try:
                self._paint_hero()
            except Exception:
                pass

    def _draw_fondo_image(self, canvas, tag):
        if self._launcher_background is None:
            return False

        try:
            gx = canvas.winfo_rootx() - self.winfo_rootx()
            gy = canvas.winfo_rooty() - self.winfo_rooty()
        except Exception:
            gx = 0
            gy = 0

        canvas.create_image(
            -gx,
            -gy,
            image=self._launcher_background,
            anchor="nw",
            tags=tag,
        )
        return True

    def _paint_fondo_canvas(self, canvas):
        canvas.delete("bg")
        w = max(canvas.winfo_width(), 1)
        h = max(canvas.winfo_height(), 1)

        if not self._draw_fondo_image(canvas, "bg"):
            canvas.create_rectangle(
                0, 0, w, h,
                fill="#090B0E",
                outline="",
                tags="bg",
            )

    def _enable_windows_appwindow(self):
        if os.name != "nt":
            return
        try:
            self.update_idletasks()
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000

            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            user32.SetWindowLongW.restype = ctypes.c_long

            tk_hwnd = ctypes.c_void_p(self.winfo_id())
            hwnd = user32.GetParent(tk_hwnd)
            if not hwnd:
                hwnd = tk_hwnd.value

            exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            exstyle = (exstyle & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)

            # Force the CF:R icon onto the native Windows window. This avoids
            # Windows falling back to the python.exe feather in taskbar/Alt+Tab.
            icon_path = getattr(self, "_native_icon_path", "")
            if icon_path and os.path.exists(icon_path):
                IMAGE_ICON = 1
                LR_LOADFROMFILE = 0x0010
                WM_SETICON = 0x0080
                ICON_SMALL = 0
                ICON_BIG = 1

                user32.LoadImageW.argtypes = [
                    ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                    ctypes.c_int, ctypes.c_int, ctypes.c_uint
                ]
                user32.LoadImageW.restype = ctypes.c_void_p
                user32.SendMessageW.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint,
                    ctypes.c_size_t, ctypes.c_void_p
                ]
                user32.SendMessageW.restype = ctypes.c_ssize_t

                self._hicon_big = user32.LoadImageW(
                    None, icon_path, IMAGE_ICON, 64, 64, LR_LOADFROMFILE
                )
                self._hicon_small = user32.LoadImageW(
                    None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE
                )

                if self._hicon_big:
                    user32.SendMessageW(
                        hwnd, WM_SETICON, ICON_BIG,
                        ctypes.c_void_p(self._hicon_big)
                    )
                if self._hicon_small:
                    user32.SendMessageW(
                        hwnd, WM_SETICON, ICON_SMALL,
                        ctypes.c_void_p(self._hicon_small)
                    )

            # Refresh the shell registration once; visual custom frame stays.
            self.withdraw()
            self.after(20, self._show_after_appwindow_fix)
        except Exception as exc:
            print("Taskbar style warning:", exc)

    def _show_after_appwindow_fix(self):
        self.deiconify()
        self.lift()

    def _center(self):
        # Fit the actual monitor work area (taskbar excluded). Never open the
        # borderless launcher partly below the screen on 720p/compact displays.
        self.update_idletasks()
        workarea = self._current_monitor_workarea()
        if workarea is None:
            workarea = (0, 0, self.winfo_screenwidth(),
                        max(500, self.winfo_screenheight() - 45))
        left, top, available_w, available_h = workarea
        safe_w = max(640, available_w - 18)
        safe_h = max(450, available_h - 18)
        self.minsize(min(760, safe_w), min(520, safe_h))
        width = min(BASE_WIDTH, safe_w)
        height = min(BASE_HEIGHT, safe_h)
        x = left + max(0, (available_w - width) // 2)
        y = top + max(0, (available_h - height) // 2)
        self.geometry(editor_geometry.tk_absolute_geometry(width, height, x, y))

    def _on_root_configure(self, event):
        if event.widget is not self:
            return

        if self._responsive_job is not None:
            try:
                self.after_cancel(self._responsive_job)
            except Exception:
                pass
        self._responsive_job = self.after(35, self._apply_responsive_layout)

        if self._background_resize_job is not None:
            try:
                self.after_cancel(self._background_resize_job)
            except Exception:
                pass
        self._background_resize_job = self.after(
            55, self._refresh_launcher_background
        )

    def _font_tuple(self, base, scale):
        family, size, weight, slant, underline, overstrike = base
        sign = -1 if size < 0 else 1
        new_size = sign * max(6, int(round(abs(size) * scale)))
        styles = []
        if weight == "bold":
            styles.append("bold")
        if slant == "italic":
            styles.append("italic")
        if underline:
            styles.append("underline")
        if overstrike:
            styles.append("overstrike")
        if styles:
            return (family, new_size, " ".join(styles))
        return (family, new_size)

    def _scale_widget_fonts(self, widget, scale):
        if isinstance(widget, ForgeButton):
            widget.set_ui_scale(getattr(self, "_button_layout_scale", scale))
            return

        try:
            keys = widget.keys()
        except Exception:
            keys = ()

        if "font" in keys:
            try:
                if not hasattr(widget, "_responsive_font_base"):
                    actual = tkfont.Font(font=widget.cget("font")).actual()
                    widget._responsive_font_base = (
                        actual.get("family", "TkDefaultFont"),
                        int(actual.get("size", 9)),
                        actual.get("weight", "normal"),
                        actual.get("slant", "roman"),
                        int(actual.get("underline", 0)),
                        int(actual.get("overstrike", 0)),
                    )
                widget.configure(
                    font=self._font_tuple(widget._responsive_font_base, scale)
                )
            except Exception:
                pass

        dynamic_canvas = widget in (
            getattr(self, "hero_canvas", None),
            getattr(self, "download_progress", None),
        )
        if isinstance(widget, tk.Canvas) and not dynamic_canvas:
            try:
                if not hasattr(widget, "_responsive_canvas_fonts"):
                    widget._responsive_canvas_fonts = {}
                bases = widget._responsive_canvas_fonts
                for item in widget.find_all():
                    if widget.type(item) != "text":
                        continue
                    try:
                        font_spec = widget.itemcget(item, "font")
                        if not font_spec:
                            continue
                        if item not in bases:
                            actual = tkfont.Font(font=font_spec).actual()
                            bases[item] = (
                                actual.get("family", "TkDefaultFont"),
                                int(actual.get("size", 9)),
                                actual.get("weight", "normal"),
                                actual.get("slant", "roman"),
                                int(actual.get("underline", 0)),
                                int(actual.get("overstrike", 0)),
                            )
                        widget.itemconfigure(
                            item, font=self._font_tuple(bases[item], scale)
                        )
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            for child in widget.winfo_children():
                self._scale_widget_fonts(child, scale)
        except Exception:
            pass

    def _apply_responsive_layout(self):
        self._responsive_job = None
        try:
            self.update_idletasks()
            width = max(1, self.winfo_width())
            height = max(1, self.winfo_height())
        except tk.TclError:
            return
        if width <= 1 or height <= 1:
            return

        aspect = width / float(height)
        short = height < 690
        tiny = height < 585
        compact = height < 780
        scale = min(width / BASE_WIDTH, height / BASE_HEIGHT)

        # Keep News, Installation, and Settings responsive. Update notes
        # are now displayed beside the artwork in the hero, not as a
        # separate, competing CHANGELOG panel.
        wide_dashboard_target = 210 if short else (235 if compact else 270)
        wide_min_top = 405 if short else (450 if compact else 490)
        wide_top = max(wide_min_top,
                       min(int(round(542 * max(0.64, scale))),
                           height - wide_dashboard_target))
        wide_top = min(wide_top, max(1, height - 172))
        estimated_lower_height = height - wide_top - 14
        tabbed = (
            width < 1180
            or (width < 1410 and aspect < 1.47)
            or estimated_lower_height < 330)
        font_scale = max(0.82, min(1.28, scale))

        if tabbed:
            min_top = 345 if tiny else (370 if short else 397)
            natural_top = int(min(542 * max(0.58, scale),
                                  height * (0.59 if height >= 740 else 0.57)))
            top_height = max(min_top, natural_top)
            top_height = min(top_height, height - 156)
        else:
            dashboard_target = 210 if short else (235 if compact else 270)
            min_top = 405 if short else (450 if compact else 490)
            top_height = max(min_top, min(int(round(542 * max(0.64, scale))),
                                          height - dashboard_target))
            top_height = min(top_height, max(1, height - 172))

        # Button geometry and text scaling are separate: large, readable text
        # can survive inside a compact dashboard without losing the 4 buttons.
        button_scale = min(max(0.58, scale), 1.18)
        if top_height < 460:
            button_scale = min(button_scale, max(0.50, (top_height - 182) / 312))
        side_pad = 10 if tabbed else (15 if compact else 20)
        sidebar_width = max(205 if tabbed else 231,
                            int(round(292 * button_scale)))
        news_width = min(438, max(220, int(round(width * 0.315))))
        right_width = min(370, max(320, int(round(width * 0.245))))

        # Settings must be usable, not just a 42px header. In compact
        # mode it gets its own full-width tab; in three-column mode it
        # defaults open because there is room for both right-hand cards.
        settings_expanded = (
            (tabbed and self._active_dashboard_tab == "SETTINGS") or
            (not tabbed and self._settings_user_expanded is not False))
        settings_height = 255 if short else (267 if compact else 280)

        try:
            self._sync_dashboard_layout(tabbed)
            self.top_section.configure(height=max(1, top_height))
            self.sidebar.configure(width=sidebar_width)
            self.news_panel.configure(width=news_width)
            self.right_panel.configure(width=right_width)
            self.main.pack_configure(
                padx=(8, 8) if tabbed else (14, 14),
                pady=(10, 5) if tabbed else (14, 8))
            self.lower_dashboard.pack_configure(
                padx=(8, 8) if tabbed else (12, 14),
                pady=(0, 7) if tabbed else (0, 12))
            self.sidebar_header.pack_configure(padx=side_pad, pady=(84, 2))

            self._button_layout_scale = button_scale
            for i, button in enumerate(self.sidebar_buttons):
                button.set_ui_scale(button_scale)
                button.pack_configure(
                    padx=side_pad,
                    pady=(0, 0) if tiny else ((1, 2) if i == 0 else
                                              (2 if compact else 4)))
            self.sidebar_separator.pack_configure(
                padx=side_pad, pady=(1, 1) if tiny else
                ((3, 3) if compact else (6, 6)))
            self.sidebar_status_card.pack_configure(
                padx=side_pad, pady=(0, 0 if tiny else (2 if compact else 4)))
            self.status_label.configure(
                wraplength=max(130, sidebar_width - side_pad * 2 - 8),
                height=1 if short else 0)
            if tiny:
                self.status_label.pack_forget()
            elif not self.status_label.winfo_manager():
                self.status_label.pack(anchor="w", padx=side_pad + 2, pady=(0, 0))
            else:
                self.status_label.pack_configure(padx=side_pad + 2)

            self.settings_panel.configure(
                height=(max(255, settings_height)
                        if tabbed and self._active_dashboard_tab == "SETTINGS"
                        else settings_height if settings_expanded else 42))
            if settings_expanded:
                if not self.settings_body.winfo_manager():
                    self.settings_body.pack(fill="x", padx=14)
            elif self.settings_body.winfo_manager():
                self.settings_body.pack_forget()
            self.settings_chevron.configure(
                text="⌄" if settings_expanded else "›")
            self._arrange_right_cards(tabbed)
            if short and not (tabbed and self._active_dashboard_tab == "SETTINGS"):
                self.settings_hint.pack_forget()
            elif not self.settings_hint.winfo_manager():
                self.settings_hint.pack(fill="x", pady=(5, 0))
            self._settings_expanded = settings_expanded

            # Progress/status may occupy one entire tab on compact screens.
            self.install_header.pack_configure(
                padx=12 if tabbed else 18,
                pady=(6, 3) if tabbed else (14, 8))
            self.install_separator.pack_configure(
                padx=12 if tabbed else 18)
            self.download_progress.pack_configure(
                padx=12 if tabbed else 18,
                pady=(3, 0) if tabbed else (9, 1))
            self.install_file_row.pack_configure(
                padx=14 if tabbed else 20,
                pady=(0, 0) if tabbed else (2, 0))
            self.install_stats_row.pack_configure(
                padx=14 if tabbed else 20,
                pady=(0, 0) if tabbed else (3, 11))
            if compact or (tabbed and height < 930):
                self.install_details.pack_forget()
            elif not self.install_details.winfo_manager():
                self.install_details.pack(
                    fill="both", expand=True, padx=18, pady=(0, 14))
            self.download_progress.configure(
                height=(36 if tiny else 45) if tabbed else
                (45 if short else 53 if compact else 74))

            install_width = (width - 54 if tabbed else
                             width - news_width - right_width - 64)
            self.download_file_label.configure(
                wraplength=max(140, install_width - 45), height=1)
            self.download_amount_label.configure(
                wraplength=max(130, install_width - 160), height=1)
            path_width = (
                width - 90 if tabbed and self._active_dashboard_tab == "SETTINGS"
                else right_width)
            self.install_path_label.configure(
                text=self._compact_install_path(
                    self.game_install_path,
                    max(15, (path_width - 120) // 6)))
            if hasattr(self, "hub_upload_shell"):
                ratio = 0.94 if width < 1050 else (0.85 if width < 1180 else 0.70)
                vertical = 0.95 if height < 710 else (0.91 if height < 850 else 0.87)
                self.hub_upload_shell.place_configure(
                    relwidth=ratio, relheight=vertical)
                self.hub_upload_note.configure(
                    wraplength=max(250, int(width * ratio)-65))
            self._resize_news_content()
        except (AttributeError, tk.TclError) as exc:
            print("Adaptive layout warning:", exc)
            return

        if (abs(font_scale - self.ui_scale) >= 0.01 or
                not getattr(self, "_responsive_done", False)):
            self.ui_scale = font_scale
            self._responsive_done = True
            self._scale_widget_fonts(self, font_scale)
        self._draw_download_progress()
        self._paint_hero()

    def _select_dashboard_tab(self, tab):
        if tab not in ("NEWS", "INSTALLATION", "SETTINGS"):
            return
        if tab == "SETTINGS" and self.winfo_height() < 640:
            # On very short windows a compact, resizable settings dialog
            # keeps both the install path and GitHub version options visible.
            self._open_compact_settings()
            return
        self._active_dashboard_tab = tab
        self._sync_dashboard_layout(True)
        self._apply_responsive_layout()
        if tab == "NEWS":
            # Reading NEWS acknowledges the orange NEW marker, not an update.
            self._acknowledge_game_news()

    def _arrange_right_cards(self, tabbed):
        """Keep Settings usable as the only right-hand dashboard card."""
        presentation = "settings-tab" if tabbed else "settings-rail"
        if getattr(self, "_right_card_layout_state", None) == presentation:
            return
        self.settings_panel.pack_forget()
        self.settings_panel.pack(side="top", fill="both", expand=True)
        self._right_card_layout_state = presentation

    def _sync_dashboard_layout(self, tabbed):
        desired = ("tabs" if tabbed else "columns",
                   self._active_dashboard_tab if tabbed else "")
        if self._dashboard_layout_state != desired:
            for widget in (self.dashboard_tabs, self.news_panel,
                           self.install_panel, self.right_panel):
                widget.pack_forget()
            if tabbed:
                self.dashboard_tabs.pack(
                    side="top", fill="x", pady=(0, 5))
                panes = {
                    "NEWS": self.news_panel,
                    "INSTALLATION": self.install_panel,
                    "SETTINGS": self.right_panel}
                active = panes.get(self._active_dashboard_tab,
                                   self.install_panel)
                active.pack(side="top", fill="both", expand=True)
            else:
                self.news_panel.pack(side="left", fill="both")
                self.right_panel.pack(side="right", fill="both",
                                      padx=(7, 0))
                self.install_panel.pack(
                    side="left", fill="both", expand=True, padx=(14, 7))
            self._dashboard_layout_state = desired

        for tab, label in self._dashboard_buttons.items():
            selected = tab == self._active_dashboard_tab and tabbed
            label.configure(
                bg="#3A1C0B" if selected else "#11151A",
                fg="#FFAA58" if selected else "#C0C3C6",
                highlightbackground=COLORS["orange"] if selected else "#343941")

    def _compact_install_path(self, path, limit):
        path = str(path)
        if len(path) <= limit:
            return path
        if limit < 12:
            return path[:max(1, limit - 3)] + "..."
        # Keep the drive/root and the actual selected folder visible.
        lead = max(5, (limit - 3) // 2)
        tail = max(4, limit - 3 - lead)
        return path[:lead] + "..." + path[-tail:]

    def _resize_news_content(self):
        canvas = getattr(self, "news_canvas", None)
        if canvas is None:
            return
        available = max(120, int(canvas.winfo_width()) - 34)
        for row in self.news_rows.winfo_children():
            for child in row.winfo_children():
                for label in child.winfo_children():
                    if isinstance(label, tk.Label) and label.cget("wraplength"):
                        label.configure(wraplength=available)
        canvas.configure(scrollregion=canvas.bbox("all"))
        def bind_recursive(widget):
            widget.bind("<MouseWheel>", self._scroll_news)
            for sub in widget.winfo_children():
                bind_recursive(sub)
        bind_recursive(self.news_rows)

    def _scroll_news(self, event):
        steps = int(-event.delta / 120)
        if steps == 0:
            steps = -1 if event.delta > 0 else 1
        self.news_canvas.yview_scroll(steps, "units")
        return "break"

    def _toggle_settings_panel(self, event=None):
        if self._dashboard_layout_state and self._dashboard_layout_state[0] == "tabs":
            self._select_dashboard_tab("SETTINGS")
            return
        self._settings_user_expanded = not getattr(
            self, "_settings_expanded", False)
        self._apply_responsive_layout()

    def _open_compact_settings(self):
        current = getattr(self, "_compact_settings_window", None)
        try:
            if current is not None and current.winfo_exists():
                current.lift()
                return
        except tk.TclError:
            pass

        win = tk.Toplevel(self)
        self._compact_settings_window = win
        win.title("Crash Forge: Racing - Settings")
        win.configure(bg="#0D1014")
        win.resizable(True, True)
        workarea = self._current_monitor_workarea()
        if workarea is None:
            workarea = (0, 0, self.winfo_screenwidth(),
                        self.winfo_screenheight())
        left, top, work_w, work_h = workarea
        w = min(570, max(400, work_w - 40))
        h = min(415, max(300, work_h - 40))
        x = min(max(left, self.winfo_rootx() + (self.winfo_width() - w) // 2),
                left + work_w - w)
        y = min(max(top, self.winfo_rooty() + (self.winfo_height() - h) // 2),
                top + work_h - h)
        win.geometry(editor_geometry.tk_absolute_geometry(w, h, x, y))
        win.transient(self)

        topbar = tk.Frame(win, bg="#171A20", height=50)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Frame(topbar, bg=COLORS["orange"], width=4).pack(side="left", fill="y")
        tk.Label(topbar, text="SETTINGS  /  INSTALL LOCATION",
                 font=("Bahnschrift SemiBold", 13), bg="#171A20",
                 fg="#F0F0ED").pack(side="left", padx=17, pady=12)

        content = tk.Frame(win, bg="#0D1014")
        content.pack(fill="both", expand=True, padx=18, pady=15)
        tk.Label(content, text="CURRENT GAME FOLDER", bg="#0D1014",
                 fg=COLORS["orange"],
                 font=("Bahnschrift SemiBold", 8)).pack(anchor="w")
        self._compact_settings_path_label = tk.Label(
            content, text=self.game_install_path or "SELECT GAME FOLDER", bg="#171A20",
            fg="#D8DAD8", justify="left", anchor="w",
            font=("Bahnschrift", 9), wraplength=max(260, w - 76),
            padx=10, pady=10)
        self._compact_settings_path_label.pack(fill="x", pady=(8, 12))
        actions = tk.Frame(content, bg="#0D1014")
        actions.pack(fill="x")
        for text, command in (
                ("OPEN FOLDER", self._open_game_location),
                ("BROWSE", self._choose_game_install_location),
                ("CLOSE", win.destroy)):
            tk.Button(
                actions, text=text, command=command, cursor="hand2",
                bg="#532000" if text == "BROWSE" else "#191D23",
                fg="#F1F0EB", activebackground="#743008",
                activeforeground="#FFFFFF", relief="flat",
                font=("Bahnschrift SemiBold", 9), padx=12, pady=8,
            ).pack(side="left", padx=(0, 10))
        # Keep GAME UPDATE on the large sidebar button. This compact page
        # controls the LAUNCHER updater only.
        self._add_launcher_update_settings_controls(content, compact=True)
        win.protocol("WM_DELETE_WINDOW", win.destroy)


    def _attach_fondo_background(self, parent):
        canvas = tk.Canvas(
            parent,
            bg="#090B0E",
            highlightthickness=0,
            bd=0,
        )
        canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        canvas.tk.call("lower", canvas._w)

        self._fondo_canvases.append(canvas)

        canvas.bind(
            "<Configure>",
            lambda e, c=canvas: self._paint_fondo_canvas(c),
        )
        self.after(20, lambda c=canvas: self._paint_fondo_canvas(c))
        return canvas

    def _build(self):
        self.shell = tk.Frame(self, bg=COLORS["bg"], highlightbackground="#282C33", highlightthickness=1)
        self.shell.pack(fill="both", expand=True)

        body = tk.Frame(self.shell, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)
        self._body_background = self._attach_fondo_background(body)

        # Top section: narrow button rail + large hero.
        # The lower section is independent, so NEWS can be wider without
        # stretching PLAY / UPDATE / REPAIR / MODS.
        self.top_section = tk.Frame(body, bg=COLORS["bg"], height=542)
        self.top_section.pack(fill="x")
        self.top_section.pack_propagate(False)
        self._top_section_background = self._attach_fondo_background(self.top_section)

        self.sidebar = tk.Frame(self.top_section, bg=COLORS["panel"], width=292)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self._sidebar()

        self.main = tk.Frame(self.top_section, bg=COLORS["bg"])
        self.main.pack(side="left", fill="both", expand=True, padx=(14, 14), pady=(14, 8))
        self._main_content()

        # Bottom dashboard row: independent widths, like the original concept.
        self.lower_dashboard = tk.Frame(body, bg=COLORS["bg"])
        self.lower_dashboard.pack(fill="both", expand=True, padx=(12, 14), pady=(0, 12))
        self.lower_dashboard.pack_propagate(False)
        self._lower_dashboard_background = self._attach_fondo_background(self.lower_dashboard)

        # Breakpoint navigation: cards become full-width, independently
        # scrollable views rather than three unreadable 4:3 columns.
        self.dashboard_tabs = tk.Frame(
            self.lower_dashboard, bg="#0B0E12", height=34)
        self.dashboard_tabs.pack_propagate(False)
        self._dashboard_buttons = {}
        for title in ("NEWS", "INSTALLATION", "SETTINGS"):
            label = tk.Label(
                self.dashboard_tabs, text=title,
                bg="#11151A", fg="#C0C3C6", cursor="hand2",
                highlightbackground="#343941", highlightthickness=1,
                font=("Bahnschrift SemiBold", 9),
                padx=12, pady=5)
            label.pack(side="left", padx=(0, 6))
            label.bind("<Button-1>", lambda e, key=title:
                       self._select_dashboard_tab(key))
            self._dashboard_buttons[title] = label

        self.news_panel = tk.Frame(
            self.lower_dashboard,
            bg=COLORS["panel"],
            width=420,
            highlightbackground="#2B3037",
            highlightthickness=1,
        )
        self.news_panel.pack(side="left", fill="both")
        self.news_panel.pack_propagate(False)
        self._news(self.news_panel)

        self.install_panel = tk.Frame(
            self.lower_dashboard,
            bg="#0C0E11",
            highlightbackground="#2B3037",
            highlightthickness=1,
        )
        # Pack the flexible middle AFTER the Settings rail so controls
        # remain usable and NEWS can keep its independent scrollable history.
        self._installation_panel(self.install_panel)

        self.right_panel = tk.Frame(self.lower_dashboard, bg=COLORS["bg"], width=300)
        self.right_panel.pack(side="right", fill="both", padx=(7, 0))
        self.right_panel.pack_propagate(False)
        self._right_panel_background = self._attach_fondo_background(self.right_panel)
        self._right_cards(self.right_panel)
        self.install_panel.pack(side="left", fill="both", expand=True, padx=(14, 7))

        self._build_forge_hub_overlay()
        self._topbar()
        self._build_resize_grips()

    def _topbar(self):
        # There is no visual title bar. This canvas is only a transparent-style
        # header layer over the workshop artwork so branding and window controls
        # can float directly on the background.
        top = tk.Canvas(
            self.shell,
            height=82,
            bg="#090B0E",
            highlightthickness=0,
            bd=0,
        )
        top.place(x=0, y=0, relwidth=1.0, height=82)
        # Canvas.lift() means "raise canvas item" in Tkinter; use Tk's
        # window-level raise command so this truly floats above sibling widgets.
        top.tk.call("raise", top._w)
        self._header_canvas = top

        top.bind("<Button-1>", self._drag_start)
        top.bind("<B1-Motion>", self._drag_move)
        top.bind("<Double-Button-1>", lambda e: self._toggle_maximize())
        top.bind("<Button-1>", self._account_badge_parent_click, add="+")
        top.bind("<Configure>", self._paint_floating_header)

        # Initial paint after geometry has settled.
        self.after(20, self._paint_floating_header)

    def _paint_floating_header(self, event=None):
        top = getattr(self, "_header_canvas", None)
        if top is None:
            return

        top.delete("all")
        width = max(top.winfo_width(), 1)
        height = max(top.winfo_height(), 1)

        # Workshop artwork continues through the top without any title-bar plate.
        # It is globally scaled to the current launcher size.
        if not self._draw_fondo_image(top, "header"):
            top.create_rectangle(
                0, 0, width, height,
                fill="#090B0E",
                outline="",
                tags="header",
            )

        # Branding floats directly on the artwork.
        if self._app_icon is not None:
            top.create_image(
                42, 41,
                image=self._app_icon,
                tags=("header", "drag_area"),
            )
        else:
            top.create_polygon(
                18, 17, 50, 17, 63, 30, 63, 57, 31, 57, 18, 44,
                fill="#20242B",
                outline=COLORS["orange"],
                tags=("header", "drag_area"),
            )
            top.create_text(
                41, 38,
                text="CF:R",
                fill=COLORS["amber"],
                font=("Bahnschrift SemiBold", 12),
                tags=("header", "drag_area"),
            )

        top.create_text(
            80, 30,
            text="CRASH FORGE",
            anchor="w",
            fill="#F5F3EE",
            font=("Bahnschrift SemiBold", 21),
            tags=("header", "drag_area"),
        )
        top.create_text(
            80, 54,
            text="RACING  /  WINDOWS LAUNCHER",
            anchor="w",
            fill=COLORS["orange"],
            font=("Bahnschrift SemiBold", 8),
            tags=("header", "drag_area"),
        )

        # Floating EDITOR entry. It is part of the header overlay but does not
        # create a separate title bar or consume layout height.
        editor_x1 = 302
        editor_y1 = 24
        editor_x2 = 400
        editor_y2 = 59
        top.create_rectangle(
            editor_x1, editor_y1, editor_x2, editor_y2,
            fill="#0B0E12",
            outline="#5C6269",
            width=1,
            tags=("header", "editor_button", "editor_button_frame"),
        )
        top.create_rectangle(
            editor_x1, editor_y1, editor_x1 + 3, editor_y2,
            fill=COLORS["orange"],
            outline="",
            tags=("header", "editor_button"),
        )
        top.create_text(
            (editor_x1 + editor_x2) / 2 + 2,
            (editor_y1 + editor_y2) / 2,
            text="EDITOR",
            fill="#E8E8E4",
            font=("Bahnschrift SemiBold", 9),
            tags=("header", "editor_button"),
        )
        top.tag_bind(
            "editor_button", "<Enter>",
            lambda e: top.itemconfigure(
                "editor_button_frame", outline=COLORS["orange"]
            )
        )
        top.tag_bind(
            "editor_button", "<Leave>",
            lambda e: top.itemconfigure(
                "editor_button_frame", outline="#5C6269"
            )
        )
        top.tag_bind(
            "editor_button", "<Button-1>",
            lambda e: self._show_editor_selector(),
        )

        # External community web shortcut, visibly next to EDITOR.
        # The existing MODS button continues to open the launcher-native hub.
        if width >= 920:
            hub_x1 = editor_x2 + 12
            hub_x2 = hub_x1 + 114
            top.create_rectangle(
                hub_x1, editor_y1, hub_x2, editor_y2,
                fill="#0B0E12", outline="#5C6269", width=1,
                tags=("header", "forge_hub_button", "forge_hub_frame"),
            )
            top.create_rectangle(
                hub_x1, editor_y1, hub_x1 + 3, editor_y2,
                fill=COLORS["orange"], outline="",
                tags=("header", "forge_hub_button"),
            )
            top.create_text(
                (hub_x1 + hub_x2) / 2 + 2,
                (editor_y1 + editor_y2) / 2,
                text="FORGE HUB", fill="#E8E8E4",
                font=("Bahnschrift SemiBold", 9),
                tags=("header", "forge_hub_button"),
            )
            top.tag_bind(
                "forge_hub_button", "<Enter>",
                lambda e: top.itemconfigure(
                    "forge_hub_frame", outline=COLORS["orange"]
                )
            )
            top.tag_bind(
                "forge_hub_button", "<Leave>",
                lambda e: top.itemconfigure(
                    "forge_hub_frame", outline="#5C6269"
                )
            )
            top.tag_bind(
                "forge_hub_button", "<Button-1>",
                lambda e: self._open_forge_hub_website(),
            )

        # Version text floats independently; move below the buttons in
        # compact windows to avoid covering the web shortcut.

        controls_right = width - 18
        if width >= 1200:
            version_x, version_y, version_font = controls_right - 170, 41, 9
        else:
            version_x, version_y, version_font = controls_right - 8, 70, 8
        top.create_text(
            version_x, version_y,
            text=f"LAUNCHER  v{APP_VERSION}",
            anchor="e",
            fill="#B7BBC0",
            font=("Bahnschrift", version_font),
            tags=("header", "drag_area"),
        )

        # Window controls are pure canvas glyphs: no combined frame and no
        # permanent rectangle behind them.
        x_close = controls_right - 16
        x_max = x_close - 42
        x_min = x_max - 42
        y = 40

        top.create_text(
            x_min, y,
            text="—",
            fill="#C5C8CC",
            font=("Segoe UI", 13),
            tags=("header", "win_min"),
        )
        top.create_text(
            x_max, y,
            text="□",
            fill="#C5C8CC",
            font=("Segoe UI", 12),
            tags=("header", "win_max"),
        )
        top.create_text(
            x_close, y,
            text="×",
            fill="#E0E1E2",
            font=("Segoe UI", 18),
            tags=("header", "win_close"),
        )

        # Hover only changes the glyph color, keeping the controls floating.
        top.tag_bind(
            "win_min", "<Enter>",
            lambda e: top.itemconfigure("win_min", fill="#FFFFFF")
        )
        top.tag_bind(
            "win_min", "<Leave>",
            lambda e: top.itemconfigure("win_min", fill="#C5C8CC")
        )
        top.tag_bind(
            "win_max", "<Enter>",
            lambda e: top.itemconfigure("win_max", fill="#FFFFFF")
        )
        top.tag_bind(
            "win_max", "<Leave>",
            lambda e: top.itemconfigure("win_max", fill="#C5C8CC")
        )
        top.tag_bind(
            "win_close", "<Enter>",
            lambda e: top.itemconfigure("win_close", fill="#FF6A5A")
        )
        top.tag_bind(
            "win_close", "<Leave>",
            lambda e: top.itemconfigure("win_close", fill="#E0E1E2")
        )

        top.tag_bind(
            "win_min", "<Button-1>",
            lambda e: self._minimize_window()
        )
        top.tag_bind(
            "win_max", "<Button-1>",
            lambda e: self._toggle_maximize()
        )
        top.tag_bind(
            "win_close", "<Button-1>",
            lambda e: self.destroy()
        )
        self._draw_account_badge(top, width)

    def _draw_account_badge(self, top, width):
        """Native Tk account chip. Guest always has a drawn person silhouette."""
        layout = account_badge.header_layout(width)
        x1, x2 = layout["left"], layout["right"]
        y1, y2 = layout["top"], layout["bottom"]
        active = self.account_client.signed_in
        state = account_badge.account_label(
            self._account_badge_profile,
            connected=self._account_badge_connected,
            signed_in=active,
            pending=self._account_badge_pending,
            problem=self._account_badge_problem,
        )
        tag = ("header", "forge_account_chip")
        top.create_rectangle(x1, y1, x2, y2, fill="#10151B",
                             outline="#B95D15", width=1, tags=tag)
        top.create_line(x1 + 2, y2 - 1, x2 - 2, y2 - 1,
                        fill="#442A1C", tags=tag)
        cx, cy = x1 + 28, 38
        photo = self._account_badge_avatar_photo
        if photo is not None and state["avatar_url"] == self._account_badge_avatar_url:
            top.create_image(cx, cy, image=photo, tags=tag)
        else:
            # Built-in Guest portrait. Never a blank circle; no image files.
            top.create_oval(cx - 22, cy - 22, cx + 22, cy + 22,
                            fill="#1C252B", outline="#C66B25",
                            width=2, tags=tag)
            top.create_oval(cx - 7, cy - 14, cx + 7, cy,
                            fill="#E9B079", outline="", tags=tag)
            top.create_oval(cx - 15, cy + 3, cx + 15, cy + 20,
                            fill="#E9B079", outline="", tags=tag)
        name = state["name"]
        if len(name) > 15:
            name = name[:14] + "..."
        top.create_text(x1 + 61, 31, text=name, anchor="w",
                        font=("Bahnschrift SemiBold", 11),
                        fill="#F1EFEB", tags=tag)
        status_color = "#46D577" if state["online"] else "#747E87"
        top.create_oval(x1 + 62, 47, x1 + 71, 56, outline="",
                        fill=status_color, tags=tag)
        top.create_text(x1 + 77, 52, text=state["status"], anchor="w",
                        font=("Bahnschrift", 9),
                        fill=status_color if state["online"] else "#B5B8BC",
                        tags=tag)
        # Dropdown caret
        top.create_line(x2 - 18, 34, x2 - 13, 39, x2 - 8, 34,
                        fill="#E6C1A0", width=2, tags=tag)
        top.tag_bind("forge_account_chip", "<Enter>",
                     lambda e: top.itemconfigure("forge_account_chip_border",
                                                 outline=COLORS["orange"]))
        # Only the rectangle gets the hover border, not the avatar's oval.
        top.addtag_withtag("forge_account_chip_border",
                           top.find_withtag("forge_account_chip")[0])
        top.tag_bind("forge_account_chip", "<Leave>",
                     lambda e: top.itemconfigure("forge_account_chip_border",
                                                 outline="#B95D15"))
        top.tag_bind("forge_account_chip", "<Button-1>",
                     self._account_badge_menu)

    def _account_badge_popup_xy(self, width, height):
        """Compute the dropdown position in virtual multi-monitor coordinates."""
        canvas = getattr(self, "_header_canvas", None)
        canvas_width = max(
            canvas.winfo_width() if canvas is not None else 1,
            self.winfo_width(),
        )
        layout = account_badge.header_layout(canvas_width)
        parent_x, parent_y = self.winfo_rootx(), self.winfo_rooty()
        anchor_x = parent_x + (layout["left"] + layout["right"]) // 2
        anchor_y = parent_y + (layout["top"] + layout["bottom"]) // 2
        work_area = account_badge.monitor_work_area_at(
            anchor_x, anchor_y,
            fallback=(0, 0, self.winfo_screenwidth(), self.winfo_screenheight()),
        )
        return account_badge.account_popup_position(
            parent_x, parent_y, layout, width, height, work_area)

    def _account_badge_reposition_popup(self, event=None):
        """Keep the open dropdown anchored when moving/resizing the launcher."""
        if event is not None and event.widget is not self:
            return
        popup = getattr(self, "_account_popup", None)
        if popup is None:
            return
        try:
            if not popup.winfo_exists():
                return
            width = max(194, popup.winfo_width())
            height = max(65, popup.winfo_height())
            x, y = self._account_badge_popup_xy(width, height)
            if (popup.winfo_rootx(), popup.winfo_rooty()) != (x, y):
                popup.geometry(editor_geometry.tk_absolute_geometry(width, height, x, y))
        except tk.TclError:
            self._account_popup = None

    def _account_badge_menu(self, event):
        """Industrial-orange dropdown, never a modal or native white-edged Menu."""
        current = getattr(self, "_account_popup", None)
        if current is not None:
            try:
                if current.winfo_exists():
                    self._close_account_badge_menu()
                    return
            except tk.TclError:
                pass
        signed_in = bool(self.account_client.signed_in)
        actions = {
            "LOG IN": self._open_account_dialog,
            "MY ACCOUNT": self._open_account_dialog,
            "OPEN FORGE HUB": self._open_forge_hub_website,
            "SIGN OUT": self._account_badge_sign_out,
        }
        items = account_badge.account_menu_items(signed_in)
        width = 194
        row_height = 34
        separator_height = 9 if signed_in else 0
        height = 4 + len(items) * row_height + separator_height
        canvas = getattr(self, "_header_canvas", None)
        canvas_width = max(canvas.winfo_width(), self.winfo_width())
        layout = account_badge.header_layout(canvas_width)
        x, y = self._account_badge_popup_xy(width, height)

        popup = tk.Toplevel(self)
        self._account_popup = popup
        popup.withdraw()
        popup.overrideredirect(True)
        popup.configure(bg=COLORS["orange"])
        popup.resizable(False, False)
        popup.transient(self)
        popup.geometry(editor_geometry.tk_absolute_geometry(width, height, x, y))

        # This border is entirely drawn with Tk widgets; no Windows-native
        # popup menu outline, so the white system border cannot come back.
        outer = tk.Frame(popup, bg=COLORS["orange"], bd=0)
        outer.pack(fill="both", expand=True, padx=0, pady=0)
        panel = tk.Frame(outer, bg="#11161C", bd=0)
        panel.pack(fill="both", expand=True, padx=2, pady=2)

        for label in items:
            if label == "SIGN OUT":
                separator = tk.Frame(panel, bg="#99440D", height=1)
                separator.pack(fill="x", padx=11, pady=(4, 4))
            item = tk.Label(
                panel, text=label, bg="#11161C", fg="#F3F1ED",
                font=("Bahnschrift SemiBold", 9), anchor="w",
                padx=17, pady=0, bd=0, relief="flat", height=2,
                cursor="hand2",
            )
            item.pack(fill="x", expand=True)
            item.bind("<Enter>", lambda e, widget=item:
                      widget.configure(bg="#8F3505", fg="#FFFFFF"))
            item.bind("<Leave>", lambda e, widget=item:
                      widget.configure(bg="#11161C", fg="#F3F1ED"))
            item.bind("<Button-1>", lambda e, action=actions[label]:
                      self._account_badge_invoke(action))

        # Fit actual DPI-scaled label heights instead of clipping bottom
        # actions on monitors using Windows text scaling.
        popup.update_idletasks()
        real_height = max(height, popup.winfo_reqheight())
        if real_height != height:
            x, y = self._account_badge_popup_xy(width, real_height)
            popup.geometry(editor_geometry.tk_absolute_geometry(width, real_height, x, y))
        popup.bind("<Escape>", self._close_account_badge_menu)
        popup.bind("<FocusOut>", self._account_badge_focus_out)
        popup.deiconify()
        popup.lift()
        # No grab_set and no hidden modal window: the launcher stays usable.
        popup.after(30, self._account_badge_focus_popup)

    def _account_badge_focus_popup(self):
        popup = getattr(self, "_account_popup", None)
        if popup is None:
            return
        try:
            if popup.winfo_exists():
                popup.focus_set()
        except tk.TclError:
            pass

    def _account_badge_focus_out(self, _event=None):
        # Avoid immediate close when Windows briefly changes focus while
        # creating a borderless popup. Dismiss only when focus really leaves.
        popup = getattr(self, "_account_popup", None)
        if popup is None:
            return
        try:
            popup.after(120, self._account_badge_dismiss_if_unfocused)
        except tk.TclError:
            pass

    def _account_badge_dismiss_if_unfocused(self):
        popup = getattr(self, "_account_popup", None)
        if popup is None:
            return
        try:
            focus = self.focus_get()
            if focus is None or focus is not popup and str(focus).startswith(str(popup)) is False:
                self._close_account_badge_menu()
        except tk.TclError:
            self._close_account_badge_menu()

    def _account_badge_invoke(self, action):
        self._close_account_badge_menu()
        action()

    def _close_account_badge_menu(self, _event=None):
        popup = getattr(self, "_account_popup", None)
        self._account_popup = None
        if popup is not None:
            try:
                if popup.winfo_exists():
                    popup.destroy()
            except tk.TclError:
                pass

    def _account_badge_parent_click(self, event):
        """A click elsewhere in the launcher closes the non-modal dropdown."""
        popup = getattr(self, "_account_popup", None)
        if popup is None:
            return
        if event.widget is self._header_canvas:
            layout = account_badge.header_layout(self._header_canvas.winfo_width())
            if (layout["left"] <= event.x <= layout["right"] and
                    layout["top"] <= event.y <= layout["bottom"]):
                return
        self._close_account_badge_menu()

    def _account_badge_clear(self):
        self._account_badge_profile = {}
        self._account_badge_connected = False
        self._account_badge_pending = False
        self._account_badge_problem = None
        self._account_badge_busy = False
        self._account_badge_retry_failures = 0
        self._account_badge_avatar_url = ""
        self._account_badge_avatar_photo = None
        self._paint_floating_header()

    def _account_badge_sign_out(self):
        self._account_badge_generation += 1  # Invalidate pending network jobs.
        self._account_badge_clear()
        generation = self._account_badge_generation
        def worker():
            try:
                self.account_client.sign_out()
            finally:
                self._account_badge_queue.put(("signed_out", None, generation))
        threading.Thread(target=worker, daemon=True,
                         name="ForgeBadgeSignOut").start()

    def _account_badge_changed(self):
        """Trust the validated dialog result; invalidate older pending checks."""
        self._account_badge_generation += 1
        self._account_badge_busy = False
        self._account_badge_retry_failures = 0
        self._account_badge_profile = self.account_client.cached_profile()
        self._account_badge_connected = bool(self.account_client.signed_in)
        self._account_badge_problem = None
        self._account_badge_pending = False
        self._paint_floating_header()

    def _account_badge_refresh_async(self):
        """Single nonblocking request, with safe retry on temporary failures."""
        if not self.account_client.signed_in:
            self._account_badge_clear()
            return
        if self._account_badge_busy:
            return
        self._account_badge_generation += 1
        generation = self._account_badge_generation
        self._account_badge_busy = True
        self._account_badge_pending = True
        self._paint_floating_header()

        def worker():
            try:
                profile = self.account_client.profile()
                result = (profile, True, None)
            except AccountSessionExpired:
                result = (None, False, "expired")
            except AccountServiceUnavailable as exc:
                problem = "busy" if "too many attempts" in str(exc).lower() else "connection"
                result = (None, False, problem)
            except AccountError:
                result = (None, False, "account")
            except Exception:
                result = (None, False, "connection")
            self._account_badge_queue.put(("profile", result, generation))
        threading.Thread(target=worker, daemon=True,
                         name="ForgeBadgeProfileCheck").start()

    def _account_badge_periodic(self):
        self._account_badge_refresh_async()
        self.after(120000, self._account_badge_periodic)

    def _account_badge_poll(self):
        """Tk widgets and PhotoImage are created on the Tk/main thread only."""
        while True:
            try:
                kind, payload, generation = self._account_badge_queue.get_nowait()
            except queue.Empty:
                break
            if generation != self._account_badge_generation:
                continue
            if kind == "profile":
                profile, connected, problem = payload
                self._account_badge_busy = False
                self._account_badge_pending = False
                if profile is not None:
                    self._account_badge_profile = profile
                self._account_badge_connected = bool(connected)
                self._account_badge_problem = problem
                if connected:
                    self._account_badge_retry_failures = 0
                elif problem == "connection" and self.account_client.signed_in:
                    # Exponential backoff; stale scheduled timers become
                    # no-ops on new requests or account changes.
                    self._account_badge_retry_failures = min(
                        5, self._account_badge_retry_failures + 1)
                    delay_ms = min(180000, 25000 * (
                        2 ** (self._account_badge_retry_failures - 1)))
                    self.after(delay_ms, lambda epoch=generation:
                               self._account_badge_refresh_async()
                               if (self._account_badge_generation == epoch
                                   and self.account_client.signed_in) else None)
                url = account_badge.github_avatar_url(
                    self._account_badge_profile.get("avatar_url"))
                if not url:
                    self._account_badge_avatar_url = ""
                    self._account_badge_avatar_photo = None
                elif url != self._account_badge_avatar_url:
                    self._account_badge_avatar_url = url
                    self._account_badge_avatar_photo = None
                    def fetch(avatar_url=url, epoch=generation):
                        try:
                            data = account_badge.fetch_github_avatar(avatar_url)
                        except Exception:
                            data = None
                        self._account_badge_queue.put(
                            ("avatar", (avatar_url, data), epoch))
                    threading.Thread(target=fetch, daemon=True,
                                     name="ForgeBadgeAvatar").start()
                self._paint_floating_header()
            elif kind == "avatar":
                url, data = payload
                if url == self._account_badge_avatar_url and data and ImageTk:
                    try:
                        self._account_badge_avatar_photo = ImageTk.PhotoImage(
                            account_badge.avatar_photo(data, size=44))
                    except Exception:
                        self._account_badge_avatar_photo = None
                    self._paint_floating_header()
            elif kind == "signed_out":
                self._account_badge_clear()
        self.after(200, self._account_badge_poll)

    def _open_account_dialog(self):
        existing = getattr(self, "_account_dialog", None)
        if existing is not None:
            try:
                if existing.window.winfo_exists():
                    existing.window.lift()
                    return
            except Exception:
                pass
        try:
            self._account_dialog = open_account_dialog(
                self, self.account_client,
                on_change=self._account_badge_changed,
            )
        except Exception as exc:
            # A failed optional account dialog must never lock PLAY, MODS,
            # the window-close controls, or the rest of the launcher.
            self._account_dialog = None
            self.status_label.configure(
                text=("Account window could not open: " + str(exc))[:200])

    def _open_forge_hub_website(self):
        """Open the official Forge Hub website without leaving the launcher."""
        try:
            if sys.platform.startswith("win") and hasattr(os, "startfile"):
                os.startfile(FORGE_HUB_WEB_URL)
            elif not webbrowser.open(FORGE_HUB_WEB_URL, new=2):
                raise OSError("No browser is configured")
            self.status_label.configure(text="Opening Forge Hub in your browser...")
        except (OSError, ValueError, RuntimeError):
            self.status_label.configure(
                text="Could not open Forge Hub. Check your default browser."
            )

    def _close_editor_selector(self):
        window = getattr(self, "_editor_window", None)
        if window is not None:
            try:
                if window.winfo_exists():
                    window.destroy()
            except Exception:
                pass
        self._editor_window = None

    def _launch_editor_tool(self, path):
        if path and os.path.basename(str(path)).casefold() == "crashforgemodpackager.exe":
            # A login is required even to open the exporter, not just upload.
            # The EXE performs its own server validation to block direct runs.
            if (not self.account_client.signed_in or
                    self._account_badge_problem == "expired"):
                self.status_label.configure(
                    text="Sign in to Forge Hub in My Account to use Mod Packager.")
                self._close_editor_selector()
                self._open_account_dialog()
                return
        if not path or not os.path.exists(path):
            status = getattr(self, "_editor_status_label", None)
            if status is not None:
                status.configure(
                    text="Tool not found. Check the configured path.",
                    fg="#FF7A61",
                )
            return

        self._close_editor_selector()

        try:
            if os.name == "nt" and str(path).lower().endswith(".exe"):
                env = os.environ.copy()
                # The game path selected in Launcher Settings is authoritative
                # even if an update is currently installing the executable.
                # Remove any inherited stale overrides before passing it on.
                env.pop("CFR_GAME_PATH", None)
                env["CFR_LAUNCHER_SETTINGS"] = os.path.abspath(SETTINGS_FILE)
                game = str(getattr(self, "game_install_path", "") or "").strip()
                if game:
                    env["CFR_GAME_PATH"] = game
                # Pick monitor by LAUNCHER location, not the process desktop's
                # primary display. Negative virtual coordinates are supported.
                workarea = self._current_monitor_workarea()
                monitor = editor_geometry.workarea_to_env(workarea)
                if monitor:
                    env[editor_geometry.ENV_NAME] = monitor
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 0
                subprocess.Popen(
                    [path], cwd=os.path.dirname(os.path.abspath(path)),
                    env=env, creationflags=subprocess.CREATE_NO_WINDOW,
                    startupinfo=startup,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                os.startfile(path)
            self.status_label.configure(
                text=f"Editor tool opened: {os.path.basename(path)}"
            )
        except Exception:
            self.status_label.configure(
                text="Could not open the selected editor tool."
            )

    def _show_editor_selector(self):
        current = getattr(self, "_editor_window", None)
        if current is not None:
            try:
                if current.winfo_exists():
                    current.lift()
                    current.focus_force()
                    return
            except Exception:
                pass

        # Create without displaying on the primary monitor first. The selector
        # must stay with THIS launcher even on left/above-primary displays.
        self.update_idletasks()
        monitor = self._current_monitor_workarea()
        win = tk.Toplevel(self)
        win.withdraw()
        self._editor_window = win
        win.title("Crash Forge: Editor")
        win.configure(bg="#090B0E")
        win.resizable(False, False)
        win.overrideredirect(True)

        width = min(900, monitor[2]) if monitor else 900
        height = min(700, monitor[3]) if monitor else 700
        if monitor:
            left, top, work_w, work_h = monitor
            geometry = editor_geometry.select_window_geometry(
                width, height,
                (self.winfo_rootx(), self.winfo_rooty(),
                 self.winfo_width(), self.winfo_height()),
                (left, top, left + work_w, top + work_h),
            )
            win.geometry(geometry)
            x = min(max(self.winfo_rootx() + (self.winfo_width() - width) // 2, left),
                    left + work_w - width)
            y = min(max(self.winfo_rooty() + (self.winfo_height() - height) // 2, top),
                    top + work_h - height)
        else:
            x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
            y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
            win.geometry(editor_geometry.tk_absolute_geometry(width, height, x, y))

        canvas = tk.Canvas(
            win,
            width=width,
            height=height,
            bg="#090B0E",
            highlightthickness=1,
            highlightbackground="#3B4149",
            bd=0,
        )
        canvas.pack(fill="both", expand=True)

        self._editor_background_photo = None
        if self._launcher_background_source is not None and ImageTk is not None:
            try:
                bg = self._launcher_background_source.resize(
                    (width, height),
                    Image.Resampling.LANCZOS,
                )
                self._editor_background_photo = ImageTk.PhotoImage(bg)
                canvas.create_image(
                    0, 0,
                    image=self._editor_background_photo,
                    anchor="nw",
                )
            except Exception:
                pass
        elif self._launcher_background is not None:
            canvas.create_image(
                0, 0,
                image=self._launcher_background,
                anchor="nw",
            )

        # Forge-style left dark plate over the workshop.
        canvas.create_polygon(
            0, 0,
            580, 0,
            505, height,
            0, height,
            fill="#07090C",
            stipple="gray50",
            outline="",
        )

        canvas.create_line(
            0, 78, width, 78,
            fill="#4B5159",
            width=1,
        )
        canvas.create_line(
            0, 78, 320, 78,
            fill=COLORS["orange"],
            width=2,
        )

        if self._app_icon is not None:
            canvas.create_image(42, 39, image=self._app_icon)

        canvas.create_text(
            82, 28,
            text="CRASH FORGE  //  EDITOR",
            anchor="w",
            fill="#F4F3EF",
            font=("Bahnschrift SemiBold", 18),
        )
        canvas.create_text(
            82, 53,
            text="SELECT A TOOL",
            anchor="w",
            fill=COLORS["orange"],
            font=("Bahnschrift SemiBold", 8),
        )

        close_x = width - 28
        canvas.create_text(
            close_x, 36,
            text="×",
            fill="#E2E3E4",
            font=("Segoe UI", 20),
            tags="editor_close",
        )
        canvas.tag_bind(
            "editor_close", "<Enter>",
            lambda e: canvas.itemconfigure("editor_close", fill="#FF705D"),
        )
        canvas.tag_bind(
            "editor_close", "<Leave>",
            lambda e: canvas.itemconfigure("editor_close", fill="#E2E3E4"),
        )
        canvas.tag_bind(
            "editor_close", "<Button-1>",
            lambda e: self._close_editor_selector(),
        )

        # Entire empty header zone can drag the selector window.
        drag = {"x": 0, "y": 0}

        def begin_drag(event):
            drag["x"] = event.x_root - win.winfo_x()
            drag["y"] = event.y_root - win.winfo_y()

        def do_drag(event):
            win.geometry(editor_geometry.tk_absolute_position(
                event.x_root - drag["x"], event.y_root - drag["y"]))

        canvas.bind("<Button-1>", begin_drag)
        canvas.bind("<B1-Motion>", do_drag)

        canvas.create_text(
            44, 112,
            text="CHOOSE WHAT YOU WANT TO EDIT",
            anchor="w",
            fill="#D8DAD7",
            font=("Bahnschrift SemiBold", 12),
        )
        canvas.create_text(
            44, 139,
            text=(
                "Launch one of the Crash Forge creation tools. "
                "The launcher stays open in the background."
            ),
            anchor="w",
            fill="#969CA3",
            font=("Bahnschrift", 9),
        )

        cards_host = tk.Frame(win, bg="#0A0D10")
        host_width = min(820, width - 32)
        host_height = min(432, max(305, height - 230))
        canvas.create_window(
            width // 2,
            172 + host_height // 2,
            width=host_width,
            height=host_height,
            window=cards_host,
            anchor="center",
        )
        cards_host.grid_columnconfigure(0, weight=1, uniform="tool")
        cards_host.grid_columnconfigure(1, weight=1, uniform="tool")
        cards_host.grid_rowconfigure(0, weight=1, uniform="toolrow")
        cards_host.grid_rowconfigure(1, weight=1, uniform="toolrow")

        def make_tool_card(row, col, index, title, subtitle, detail,
                           action=None, disabled=False):
            edge = "#343A42" if disabled else "#4A5058"
            card = tk.Frame(
                cards_host,
                bg="#0E1115",
                highlightbackground=edge,
                highlightthickness=1,
                width=(host_width - 24) // 2,
                height=(host_height - 22) // 2,
            )
            card.grid(row=row, column=col, sticky="nsew", padx=6, pady=5)
            card.grid_propagate(False)

            stripe = tk.Frame(
                card,
                bg="#4E545B" if disabled else COLORS["orange"],
                height=4,
            )
            stripe.pack(fill="x")

            icon = tk.Canvas(
                card,
                width=62,
                height=62,
                bg="#0E1115",
                highlightthickness=0,
                bd=0,
            )
            icon.pack(pady=(5, 1))

            icon_col = "#5C6269" if disabled else "#D7D9D7"
            hot_col = "#676D74" if disabled else COLORS["orange"]

            if index == 0:
                # OGG / waveform + note.
                icon.create_line(
                    8, 37, 16, 27, 23, 43, 31, 22, 39, 39, 47, 29, 55, 36,
                    fill=icon_col,
                    width=2,
                    smooth=True,
                )
                icon.create_oval(38, 14, 48, 24, outline=hot_col, width=2)
                icon.create_line(47, 15, 47, 39, fill=hot_col, width=2)
                icon.create_oval(40, 35, 48, 43, fill=hot_col, outline="")
            elif index == 1:
                # MIDI / step notes.
                for xx, yy in ((10, 37), (25, 27), (40, 18)):
                    icon.create_rectangle(
                        xx, yy, xx + 11, yy + 8,
                        outline=hot_col,
                        width=2,
                    )
                    icon.create_line(
                        xx + 10, yy,
                        xx + 10, yy - 17,
                        fill=icon_col,
                        width=2,
                    )
            elif index == 2:
                # Model / wire cube.
                icon.create_polygon(
                    12, 23, 31, 13, 50, 23, 31, 34,
                    fill="",
                    outline=icon_col,
                    width=2,
                )
                icon.create_polygon(
                    12, 23, 31, 34, 31, 54, 12, 43,
                    fill="",
                    outline=icon_col,
                    width=2,
                )
                icon.create_polygon(
                    31, 34, 50, 23, 50, 43, 31, 54,
                    fill="",
                    outline=icon_col,
                    width=2,
                )

            else:
                # Mod Packager / exported modular ZIP.
                icon.create_rectangle(11, 16, 51, 46, outline=hot_col, width=2)
                icon.create_line(11, 16, 30, 7, 51, 16, fill=icon_col, width=2)
                icon.create_line(30, 7, 30, 34, fill=icon_col, width=2)
                icon.create_text(31, 52, text="ZIP", fill=hot_col,
                                 font=("Bahnschrift SemiBold", 9))

            tk.Label(
                card,
                text=title,
                bg="#0E1115",
                fg="#70767D" if disabled else "#F0F1ED",
                font=("Bahnschrift SemiBold", 12),
            ).pack()

            tk.Label(
                card,
                text=subtitle,
                bg="#0E1115",
                fg="#5E646B" if disabled else COLORS["orange"],
                font=("Bahnschrift SemiBold", 8),
            ).pack(pady=(2, 10))

            tk.Label(
                card,
                text=detail,
                bg="#0E1115",
                fg="#666C73" if disabled else "#93989F",
                font=("Bahnschrift", 8),
                wraplength=max(220, (host_width - 55)//2),
                justify="center",
            ).pack(padx=12)

            button_text = "TOOL NOT INSTALLED" if disabled else "OPEN TOOL"
            button = tk.Label(
                card,
                text=button_text,
                bg="#111419" if disabled else "#391707",
                fg="#5E646B" if disabled else "#FFF1E4",
                highlightbackground="#282D33" if disabled else COLORS["orange"],
                highlightthickness=1,
                font=("Bahnschrift SemiBold", 8),
                padx=14,
                pady=7,
                cursor="arrow" if disabled else "hand2",
            )
            button.pack(side="bottom", pady=7)

            if not disabled and action is not None:
                widgets = [card, icon, button]
                for child in card.winfo_children():
                    widgets.append(child)

                def enter(event=None):
                    card.configure(highlightbackground=COLORS["orange"])
                    button.configure(bg="#5A2208")

                def leave(event=None):
                    card.configure(highlightbackground="#4A5058")
                    button.configure(bg="#391707")

                for widget in widgets:
                    try:
                        widget.bind("<Enter>", enter)
                        widget.bind("<Leave>", leave)
                        widget.bind("<Button-1>", lambda e, fn=action: fn())
                        widget.configure(cursor="hand2")
                    except Exception:
                        pass

        # Always resolve the shipped Windows EXEs first, independently of
        # the game path. All editors receive the game's path via env/settings.
        tool_paths = {
            "ogg": editor_registry.editor_executable(
                "ogg", BASE_DIR,
                override=OGG_TOOL_PATH,
                runtime_dir=getattr(sys, "_MEIPASS", None),
            ),
            "cseq": editor_registry.editor_executable(
                "cseq", BASE_DIR,
                override=CSEQ_TOOL_PATH,
                runtime_dir=getattr(sys, "_MEIPASS", None),
            ),
            "model": editor_registry.editor_executable(
                "model", BASE_DIR,
                runtime_dir=getattr(sys, "_MEIPASS", None),
            ),
            "modpackager": editor_registry.editor_executable(
                "modpackager", BASE_DIR,
                runtime_dir=getattr(sys, "_MEIPASS", None),
            ),
        }
        make_tool_card(
            0, 0, 0,
            "OGG MUSIC",
            ".OGG TOOLKIT",
            "Prepare and manage external OGG music for Crash Forge: Racing.",
            action=lambda: self._launch_editor_tool(tool_paths["ogg"]),
            disabled=not bool(tool_paths["ogg"]),
        )
        make_tool_card(
            0, 1, 1,
            "CSEQ / MIDI",
            ".MIDI TOOLKIT",
            "Import MIDI, assign CTR instruments or SF2 presets and build CSEQ packages.",
            action=lambda: self._launch_editor_tool(tool_paths["cseq"]),
            disabled=not bool(tool_paths["cseq"]),
        )
        make_tool_card(
            1, 0, 2,
            "MODEL IMPORTER",
            "CHARACTERS / KARTS / WHEELS / TRACKS",
            "Import characters, modular karts, wheels and native .LEV/.VRM tracks.",
            action=lambda: self._launch_editor_tool(tool_paths["model"]),
            disabled=not bool(tool_paths["model"]),
        )
        make_tool_card(
            1, 1, 3,
            "MOD PACKAGER",
            "CHARACTERS / KARTS / WHEELS / TRACKS",
            "Build, validate and export native ZIP mods for Forge Hub.",
            action=lambda: self._launch_editor_tool(tool_paths["modpackager"]),
            disabled=not bool(tool_paths["modpackager"]),
        )

        self._editor_status_label = tk.Label(
            win,
            text="Select a tool to continue.",
            bg="#090B0E",
            fg="#747A81",
            font=("Bahnschrift", 8),
        )
        canvas.create_window(
            44, height - 24,
            window=self._editor_status_label,
            anchor="w",
        )

        win.protocol("WM_DELETE_WINDOW", self._close_editor_selector)
        win.deiconify()
        win.lift()
        # Tk may relocate borderless Toplevels to display 1 while mapping.
        # Reinforce the exact signed Win32 virtual-desktop position twice.
        editor_geometry.enforce_native_window_position(win, x, y, width, height)
        win.after(70, lambda: editor_geometry.enforce_native_window_position(
            win, x, y, width, height))
        win.after(220, lambda: editor_geometry.enforce_native_window_position(
            win, x, y, width, height))
        win.focus_set()

    def _get_native_hwnd(self):
        if os.name != "nt":
            return None
        try:
            self.update_idletasks()
            user32 = ctypes.windll.user32
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            tk_hwnd = ctypes.c_void_p(self.winfo_id())
            hwnd = user32.GetParent(tk_hwnd)
            return hwnd or tk_hwnd.value
        except Exception:
            return None

    def _minimize_window(self):
        if os.name == "nt":
            hwnd = self._get_native_hwnd()
            if hwnd:
                try:
                    SW_MINIMIZE = 6
                    ctypes.windll.user32.ShowWindow(
                        ctypes.c_void_p(hwnd), SW_MINIMIZE
                    )
                    return
                except Exception:
                    pass
        self.iconify()

    def _current_monitor_workarea(self):
        """Monitor containing the *visible launcher coordinates*, not its
        transient HWND. The taskbar icon fix can temporarily reparent/hide
        the window; MonitorFromWindow may then fail and incorrectly send
        FIT TO WINDOW to the primary display.
        """
        if os.name != "nt":
            return None
        try:
            # Tk root coordinates remain stable even while Windows changes
            # the borderless wrapper HWND for taskbar integration.
            center_x = self.winfo_rootx() + max(1, self.winfo_width()) // 2
            center_y = self.winfo_rooty() + max(1, self.winfo_height()) // 2
            left, top, right, bottom = account_badge.monitor_work_area_at(
                center_x, center_y,
                fallback=(0, 0, self.winfo_screenwidth(),
                          self.winfo_screenheight()),
            )
            width, height = right - left, bottom - top
            if width <= 0 or height <= 0:
                return None
            return (left, top, width, height)
        except (AttributeError, OSError, ValueError, tk.TclError):
            return None

    def _toggle_maximize(self):
        if self._is_maximized:
            if self._restore_geometry:
                self.geometry(self._restore_geometry)
            self._is_maximized = False
            self._raise_resize_grips()
            if hasattr(self, "max_button"):
                self.max_button.configure(text="□")
            return

        self.update_idletasks()
        self._restore_geometry = self.geometry()

        workarea = self._current_monitor_workarea()
        if workarea is not None:
            x, y, width, height = workarea
            self.geometry(editor_geometry.tk_absolute_geometry(width, height, x, y))
        else:
            # Very old Windows builds or temporary display API failures:
            # fit around the current window instead of jumping to (0,0).
            x, y = self.winfo_rootx(), self.winfo_rooty()
            self.geometry(editor_geometry.tk_absolute_geometry(
                self.winfo_screenwidth(), self.winfo_screenheight(), x, y))

        self._is_maximized = True
        self._raise_resize_grips()
        if hasattr(self, "max_button"):
            self.max_button.configure(text="❐")

    def _drag_start(self, event):
        if self._is_maximized:
            return
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        if self._is_maximized:
            return
        px = int(event.x_root - self._drag_x)
        py = int(event.y_root - self._drag_y)
        self.geometry(editor_geometry.tk_absolute_position(px, py))

    def _build_resize_grips(self):
        # Tk's borderless override removes native Windows resizing. Eight
        # slim edge/corner zones restore mouse-driven free-aspect resizing.
        edge = 6
        corner = 13
        grips = (
            ("n", "sb_v_double_arrow",
             {"relwidth": 1, "height": edge, "x": 0, "y": 0}),
            ("s", "sb_v_double_arrow",
             {"relwidth": 1, "height": edge, "x": 0, "rely": 1, "y": -edge}),
            ("w", "sb_h_double_arrow",
             {"relheight": 1, "width": edge, "x": 0, "y": 0}),
            ("e", "sb_h_double_arrow",
             {"relheight": 1, "width": edge, "relx": 1, "x": -edge, "y": 0}),
            ("nw", "size_nw_se",
             {"width": corner, "height": corner, "x": 0, "y": 0}),
            ("ne", "size_ne_sw",
             {"width": corner, "height": corner, "relx": 1, "x": -corner, "y": 0}),
            ("sw", "size_ne_sw",
             {"width": corner, "height": corner, "rely": 1, "x": 0, "y": -corner}),
            ("se", "size_nw_se",
             {"width": corner, "height": corner, "relx": 1, "rely": 1,
              "x": -corner, "y": -corner}),
        )
        self._resize_grips = []
        for name, cursor, placement in grips:
            try:
                widget = tk.Frame(
                    self.shell, bg="#1C2026", cursor=cursor, bd=0)
            except tk.TclError:
                widget = tk.Frame(
                    self.shell, bg="#1C2026", cursor="cross", bd=0)
            widget.place(**placement)
            widget.bind("<ButtonPress-1>",
                        lambda e, side=name: self._begin_resize(e, side))
            widget.bind("<B1-Motion>", self._resize_drag)
            widget.bind("<ButtonRelease-1>", self._finish_resize)
            self._resize_grips.append((widget, placement))

    def _raise_resize_grips(self):
        for widget, placement in getattr(self, "_resize_grips", []):
            if self._is_maximized:
                widget.place_forget()
            else:
                if not widget.winfo_manager():
                    widget.place(**placement)
                widget.lift()

    def _begin_resize(self, event, edge):
        if self._is_maximized:
            return
        self._resize_origin = (
            int(event.x_root), int(event.y_root),
            int(self.winfo_x()), int(self.winfo_y()),
            int(self.winfo_width()), int(self.winfo_height()),
            edge)

    def _resize_drag(self, event):
        origin = self._resize_origin
        if origin is None or self._is_maximized:
            return
        sx, sy, left, top, width, height, edge = origin
        dx = int(event.x_root) - sx
        dy = int(event.y_root) - sy
        minimum_w, minimum_h = self.minsize()
        if "w" in edge:
            left += dx
            width -= dx
        if "e" in edge:
            width += dx
        if "n" in edge:
            top += dy
            height -= dy
        if "s" in edge:
            height += dy
        if width < minimum_w:
            if "w" in edge:
                left -= (minimum_w - width)
            width = minimum_w
        if height < minimum_h:
            if "n" in edge:
                top -= (minimum_h - height)
            height = minimum_h
        self.geometry(editor_geometry.tk_absolute_geometry(
            width, height, left, top))

    def _finish_resize(self, event=None):
        self._resize_origin = None

    def _sidebar(self):
        head = tk.Frame(self.sidebar, bg=COLORS["panel"], height=40)
        head.pack(fill="x", padx=20, pady=(84, 2))
        self.sidebar_header = head
        tk.Label(head, text="MAIN", bg=COLORS["panel"], fg="#676C74",
                 font=("Bahnschrift SemiBold", 9)).pack(side="left")

        self.sidebar_buttons = [
            ForgeButton(self.sidebar, "PLAY", "play", self._primary_game_action, accent=True),
            ForgeButton(self.sidebar, "UPDATE", "update", self._check_game_update),
            ForgeButton(self.sidebar, "REPAIR", "repair", self._check_local_game_files),
            ForgeButton(self.sidebar, "MODS", "mods", self._show_forge_hub),
        ]
        for idx, button in enumerate(self.sidebar_buttons):
            button.pack(padx=20, pady=(1, 4) if idx == 0 else 4)

        self.sidebar_separator = tk.Frame(self.sidebar, bg="#242930", height=1)
        self.sidebar_separator.pack(fill="x", padx=20, pady=(6, 6))

        status_card = tk.Frame(
            self.sidebar,
            bg="#101318",
            highlightbackground="#2E333A",
            highlightthickness=1,
        )
        status_card.pack(fill="x", padx=20, pady=(0, 4))
        self.sidebar_status_card = status_card

        tk.Frame(status_card, bg=COLORS["orange"], width=3).pack(side="left", fill="y")

        status_copy = tk.Frame(status_card, bg="#101318")
        status_copy.pack(side="left", fill="both", expand=True, padx=10, pady=6)

        tk.Label(
            status_copy,
            text="BUILD STATUS",
            bg="#101318",
            fg="#6E747C",
            font=("Bahnschrift SemiBold", 7),
        ).pack(anchor="w")

        ready_row = tk.Frame(status_copy, bg="#101318")
        ready_row.pack(fill="x", pady=(2, 0))

        self.build_indicator = tk.Label(
            ready_row,
            text="●",
            bg="#101318",
            fg=COLORS["success"],
            font=("Segoe UI", 9),
        )
        self.build_indicator.pack(side="left")

        self.build_state_label = tk.Label(
            ready_row,
            text="NOT INSTALLED",
            bg="#101318",
            fg="#D7D9D6",
            font=("Bahnschrift SemiBold", 9),
        )
        self.build_state_label.pack(side="left", padx=(6, 0))

        self.status_label = tk.Label(
            self.sidebar,
            text="",
            bg=COLORS["panel"],
            fg="#656A72",
            justify="left",
            wraplength=238,
            font=("Bahnschrift", 8),
        )
        self.status_label.pack(anchor="w", padx=22, pady=(1, 0))

        # Shared updater state. The visual panel now lives in the main lower-left area.
        self.download_percent = tk.DoubleVar(value=0.0)
        self.download_state_var = tk.StringVar(value="IDLE")
        self.download_file_var = tk.StringVar(value="Checking local installation...")
        self.download_amount_var = tk.StringVar(value="No transfer active")
        self.download_time_var = tk.StringVar(value="")

    def _compact_news(self, parent):
        card = tk.Frame(
            parent,
            bg="#0C0E11",
            highlightbackground="#3A3F46",
            highlightthickness=1,
        )
        card.pack(side="bottom", fill="x", padx=12, pady=(8, 12))

        header = tk.Frame(card, bg="#111318")
        header.pack(fill="x", padx=8, pady=(7, 5))

        icon = tk.Canvas(header, width=20, height=20, bg="#111318",
                         highlightthickness=0, bd=0)
        icon.pack(side="left")
        icon.create_rectangle(4, 3, 16, 17, fill="#171A1F",
                              outline=COLORS["orange"], width=1)
        icon.create_line(7, 7, 14, 7, fill=COLORS["orange"], width=2)
        icon.create_line(7, 11, 14, 11, fill="#676C73", width=1)
        icon.create_line(7, 14, 12, 14, fill="#676C73", width=1)

        tk.Label(
            header, text="NEWS",
            bg="#111318", fg=COLORS["text"],
            font=("Bahnschrift SemiBold", 10)
        ).pack(side="left", padx=(6, 0))

        more = tk.Label(
            header, text="View All  →",
            bg="#111318", fg="#858A91",
            font=("Bahnschrift", 8), cursor="hand2"
        )
        more.pack(side="right")
        more.bind("<Enter>", lambda e: more.configure(fg=COLORS["orange"]))
        more.bind("<Leave>", lambda e: more.configure(fg="#858A91"))

        items = ((f"LAUNCHER v{APP_VERSION}", "Local build notes"),)

        for idx, (title, detail) in enumerate(items):
            row = tk.Frame(card, bg="#0F1216")
            row.pack(fill="x", padx=8, pady=(0, 5))

            thumb = tk.Canvas(
                row, width=58, height=38,
                bg="#090B0E",
                highlightbackground="#2F343B",
                highlightthickness=1,
                bd=0
            )
            thumb.pack(side="left", padx=(0, 7))
            thumb.create_polygon(0, 38, 24, 14, 58, 38, fill="#181B20", outline="")
            thumb.create_polygon(22, 38, 43, 9, 58, 38, fill="#30190B", outline="")
            thumb.create_line(4, 33, 54, 33, fill="#5A250A", width=1)
            if idx == 2:
                thumb.create_oval(36, 11, 50, 25, outline=COLORS["orange"], width=1)

            copy = tk.Frame(row, bg="#0F1216")
            copy.pack(side="left", fill="both", expand=True, pady=3)
            tk.Label(
                copy, text=title,
                bg="#0F1216", fg="#D7D8D5",
                font=("Bahnschrift SemiBold", 7),
                anchor="w"
            ).pack(anchor="w")
            tk.Label(
                copy, text=detail,
                bg="#0F1216", fg="#7E838A",
                font=("Bahnschrift", 8),
                anchor="w"
            ).pack(anchor="w")

    def _draw_download_progress(self, event=None):
        c = self.download_progress
        c.delete("all")
        w = max(c.winfo_width(), 90)
        pct = max(0.0, min(100.0, float(self.download_percent.get())))
        s = getattr(self, "ui_scale", 1.0)

        left = max(3, int(round(3 * s)))
        right = w - max(74, int(round(74 * s)))
        top = max(12, int(round(15 * s)))
        bottom = max(top + 24, int(round(49 * s)))

        c.create_rectangle(left, top, right, bottom,
                           fill="#070809", outline="#5A5F66", width=1)
        c.create_rectangle(left + 4, top + 4, right - 4, bottom - 4,
                           fill="#101216", outline="#22262C", width=1)

        fill_right = left + 5 + (right - left - 10) * (pct / 100.0)
        if pct > 0:
            c.create_rectangle(left + 5, top + 5, fill_right, bottom - 5,
                               fill="#E65400", outline="")
            c.create_rectangle(left + 6, top + 6, fill_right - 1, top + 11,
                               fill="#FFB000", outline="")
            c.create_line(fill_right, top + 6, fill_right, bottom - 6,
                          fill="#FFD36D", width=2)

        c.create_text(
            w - max(5, int(round(5 * s))),
            int(round((top + bottom) / 2)),
            text=f"{pct:.0f}%",
            anchor="e",
            fill="#F2F2EF",
            font=("Bahnschrift SemiBold", max(13, int(round(18 * s)))),
        )

    def set_download_status(self, percent=None, state=None, filename=None,
                            amount=None, time_remaining=None, visible=True):
        """UI hook for the future updater."""
        if percent is not None:
            self.download_percent.set(float(percent))
        if state is not None:
            self.download_state_var.set(str(state))
        if filename is not None:
            self.download_file_var.set(str(filename))
        if amount is not None:
            self.download_amount_var.set(str(amount))
        if time_remaining is not None:
            self.download_time_var.set(str(time_remaining))

        if hasattr(self, "download_card") and not visible:
            # Dashboard geometry is owned by _sync_dashboard_layout.
            # A background status update must never re-pack Installation
            # on top of NEWS / SETTINGS in the compact tab layout.
            self.download_card.pack_forget()
            self._dashboard_layout_state = None

        if hasattr(self, "download_progress"):
            self._draw_download_progress()

    def _main_content(self):
        self.hero_canvas = tk.Canvas(
            self.main,
            bg="#090B0E",
            highlightbackground="#343941",
            highlightthickness=1
        )
        self.hero_canvas.pack(fill="both", expand=True)
        self.hero_canvas.bind("<Configure>", self._paint_hero)

    def _installation_panel(self, parent):
        self.download_card = parent

        top = tk.Frame(parent, bg="#111318")
        top.pack(fill="x", padx=18, pady=(14, 8))
        self.install_header = top

        icon = tk.Canvas(top, width=27, height=27, bg="#111318",
                         highlightthickness=0, bd=0)
        icon.pack(side="left")
        icon.create_rectangle(3, 3, 24, 24, fill="#171A1F", outline="#373C43")
        icon.create_line(13, 6, 13, 16, fill="#D1D2CF", width=2)
        icon.create_polygon(8, 13, 13, 19, 18, 13, fill="#D1D2CF", outline="")
        icon.create_line(7, 21, 19, 21, fill="#777C82", width=2)

        tk.Label(
            top, text="INSTALLATION STATUS",
            bg="#111318", fg=COLORS["text"],
            font=("Bahnschrift SemiBold", 11)
        ).pack(side="left", padx=(8, 0))

        self.download_state_label = tk.Label(
            top,
            textvariable=self.download_state_var,
            bg="#111318",
            fg="#8F949B",
            font=("Bahnschrift", 9),
        )
        self.download_state_label.pack(side="right")

        separator = tk.Frame(parent, height=1, bg="#252A30")
        self.install_separator = separator
        separator.pack(fill="x", padx=18)

        self.download_progress = tk.Canvas(
            parent,
            height=74,
            bg="#0C0E11",
            highlightthickness=0,
            bd=0,
        )
        self.download_progress.pack(fill="x", padx=18, pady=(9, 1))
        self.download_progress.bind("<Configure>", self._draw_download_progress)

        file_row = tk.Frame(parent, bg="#0C0E11")
        self.install_file_row = file_row
        file_row.pack(fill="x", padx=20, pady=(2, 0))
        self.download_file_label = tk.Label(
            file_row, textvariable=self.download_file_var, bg="#0C0E11",
            fg="#8A8F96", anchor="w", justify="left", height=1,
            font=("Bahnschrift", 9))
        self.download_file_label.pack(side="left", fill="x", expand=True)

        stats = tk.Frame(parent, bg="#0C0E11")
        self.install_stats_row = stats
        stats.pack(fill="x", padx=20, pady=(3, 11))
        self.download_amount_label = tk.Label(
            stats, textvariable=self.download_amount_var,
            bg="#0C0E11", fg="#777C83", anchor="w", height=1,
            font=("Bahnschrift", 9))
        self.download_amount_label.pack(side="left", fill="x", expand=True)
        tk.Label(
            stats,
            textvariable=self.download_time_var,
            bg="#0C0E11",
            fg="#93979D",
            anchor="e",
            font=("Bahnschrift", 9),
        ).pack(side="right")

        details = tk.Frame(parent, bg="#101318")
        self.install_details = details
        details.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        tk.Frame(details, bg=COLORS["orange"], width=3).pack(side="left", fill="y")
        copy = tk.Frame(details, bg="#101318")
        copy.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        tk.Label(
            copy, text="LIVE INSTALLATION",
            bg="#101318", fg="#D7D8D5",
            font=("Bahnschrift SemiBold", 8),
            anchor="w"
        ).pack(anchor="w")
        tk.Label(
            copy,
            text="Actual local-file status; progress updates only during a verified download.",
            bg="#101318",
            fg="#767B82",
            wraplength=430,
            justify="left",
            font=("Bahnschrift", 8),
            anchor="w"
        ).pack(anchor="w", pady=(3, 0))


    def _featured_news_update(self):
        """Choose the newest real publication from TWO independent products."""
        launch = getattr(self, "launcher_news_history", None)
        if not launch:
            launch = news_history.local_publications(BASE_DIR)
        all_news = game_news.combined_news(
            launch, getattr(self, "game_news_history", []))
        return all_news[0] if all_news else None

    def _paint_hero(self, event=None):
        """Feature the newest game OR launcher release by publication instant."""
        c = event.widget if event is not None else getattr(self, "hero_canvas", None)
        if c is None:
            return
        c.delete("hero")
        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)
        s = getattr(self, "ui_scale", 1.0)
        featured = self._featured_news_update()
        is_game = bool(featured and featured.get("source") == "GAME")

        if not self._draw_fondo_image(c, "hero"):
            c.create_rectangle(0, 0, w, h,
                               fill="#0B0D10", outline="", tags="hero")

        # Per-version illustration, fully visible even in 4:3 windows.
        # Until artwork for a given release arrives, use garage art, not
        # a screenshot belonging to a different announcement.
        art_x = min(w - 205, max(250, int(round(w * 0.42))))
        art_y = 81 if h >= 310 else 41
        art_w = max(1, w - art_x - 19)
        art_h = max(1, h - art_y - 49)
        if art_w >= 170 and art_h >= 75:
            c.create_rectangle(art_x-4, art_y-4,
                               art_x+art_w+4, art_y+art_h+4,
                               fill="#0C0F14", outline="#4B5057",
                               width=1, tags="hero")
            if Image is not None and ImageTk is not None:
                # The game has its own release feed; never use an image
                # belonging to a *launcher version* for a game announcement.
                release_version = featured["version"] if featured else APP_VERSION
                image_path = (
                    news_history.garage_fallback(BASE_DIR) if is_game else
                    (news_history.artwork_file(BASE_DIR, release_version)
                     or news_history.garage_fallback(BASE_DIR))
                )
                try:
                    source_key = (
                        image_path,
                        os.stat(image_path).st_mtime_ns if image_path else -1,
                    )
                    if getattr(self, "_hero_art_key", None) != source_key:
                        self._hero_art_key = source_key
                        self._hero_update_source = (
                            Image.open(image_path).convert("RGB")
                            if image_path else None
                        )
                        self._hero_update_bounds = None
                    if self._hero_update_source is not None:
                        bounds = (art_w, art_h)
                        if self._hero_update_bounds != bounds:
                            fitted = ImageOps.contain(
                                self._hero_update_source, bounds,
                                method=Image.Resampling.LANCZOS)
                            self._hero_update_photo = ImageTk.PhotoImage(fitted)
                            self._hero_update_bounds = bounds
                        c.create_image(art_x + art_w//2, art_y + art_h//2,
                                       image=self._hero_update_photo,
                                       anchor="center", tags="hero")
                except (OSError, ValueError, tk.TclError):
                    pass
            c.create_rectangle(art_x-4, art_y-4,
                               art_x+art_w+4, art_y+art_h+4,
                               outline="#484C53", width=1, tags="hero")

        # Opaque copy plate separates small readable text from the photo.
        left_w = max(280, min(w-110, art_x+9))
        c.create_polygon(0, 0, left_w, 0, left_w-18, h, 0, h,
                         fill="#080A0E", outline="", tags="hero")
        c.create_rectangle(8, 8, w-8, h-8,
                           outline="#343941", width=1, tags="hero")
        c.create_line(8, 8, min(w-8, 275), 8,
                      fill=COLORS["orange"], width=2, tags="hero")

        if featured:
            release = featured.get("display_version") or "v" + featured["version"]
            highlights = featured.get("notes", [])[:5]
        else:
            release, highlights = services.real_launcher_changelog(
                BASE_DIR, limit=3)
            release = release or ("v" + APP_VERSION)

        x = 33 if w >= 700 else 23
        copy_width = max(180, left_w - x - 38)
        c.create_rectangle(x, 34, x+5, 49,
                           fill=COLORS["orange"], outline="", tags="hero")
        c.create_text(x+16, 42,
                      text=("LATEST GAME  /  " if is_game else
                            "LATEST LAUNCHER  /  ") + release.upper(),
                      fill="#F5A660", anchor="w",
                      font=("Bahnschrift SemiBold", max(8, int(round(10*s)))),
                      tags="hero")

        title_size = max(19, int(round((25 if w >= 720 else 21)*s)))
        version_shown = featured["version"] if featured else APP_VERSION
        hero_title = ("GAME UPDATE" if is_game else
                      "MODEL IMPORTER 1.8" if version_shown == "0.3.38" else
                      "FORGE HUB" if version_shown == "0.3.37" else "WHAT'S NEW")
        c.create_text(x, 85,
                      text=hero_title, anchor="w", fill="#F4F2ED",
                      font=("Bahnschrift SemiBold", title_size), tags="hero")
        c.create_text(x, 119, text=("CRASH FORGE: RACING" if is_game
                                    else "CRASH FORGE LAUNCHER"),
                      anchor="w", fill=COLORS["orange"],
                      font=("Bahnschrift SemiBold",
                            max(11, int(round(14*s)))), tags="hero")

        # The homepage is the changelog summary: keep it beside the
        # accompanying image. The full append-only history stays in NEWS.
        row_y = 158 if h >= 315 else 139
        bottom_y = h - 53
        limit = 5 if h >= 470 else (4 if h >= 390 else
                                  (3 if h >= 340 else (2 if h >= 285 else 1)))
        char_width = max(24, min(50, int(copy_width / max(5.7, 6.1*s))))
        for note in highlights[:limit]:
            rows = textwrap.wrap(str(note), width=char_width,
                                 break_long_words=False, break_on_hyphens=False)
            if not rows:
                continue
            rows = rows[:2]
            text_height = max(17, 14 * len(rows))
            if row_y + text_height > bottom_y:
                break
            c.create_oval(x, row_y+5, x+5, row_y+10,
                          fill=COLORS["orange"], outline="", tags="hero")
            c.create_text(x+14, row_y, text="\n".join(rows),
                          anchor="nw", fill="#DBDEE1",
                          font=("Bahnschrift", max(8, int(round(9*s)))),
                          justify="left", tags="hero")
            row_y += text_height + (11 if h < 390 else 13)

        # Installed status remains legible above the picture, without
        # covering its content or colliding with the release text.
        if w >= 720 and h >= 300:
            badge_w = max(168, int(round(202*s)))
            bx = max(left_w+15, w - badge_w - 17)
            by = 14
            c.create_rectangle(bx, by, bx+badge_w, by+53,
                               fill="#0A0D11", outline="#3A4047",
                               width=1, tags="hero")
            c.create_rectangle(bx, by, bx+4, by+53,
                               fill=COLORS["orange"], outline="", tags="hero")
            installed = services.real_game_status(
                getattr(self, "game_install_path",
                        services.DEFAULT_GAME_PATH))["installed"]
            c.create_text(bx+13, by+15, anchor="w",
                          text="GAME INSTALLATION", fill="#81878E",
                          font=("Bahnschrift SemiBold", max(7,int(round(8*s)))),
                          tags="hero")
            c.create_text(bx+13, by+35, anchor="w",
                          text="INSTALLED" if installed else "NOT INSTALLED",
                          fill="#F2F2EF",
                          font=("Bahnschrift SemiBold",
                                max(12,int(round(14*s)))), tags="hero")
            c.create_oval(bx+badge_w-24, by+24,
                          bx+badge_w-15, by+33,
                          fill=(COLORS["success"] if installed
                                else COLORS["muted"]),
                          outline="", tags="hero")

        footer_y = h-36
        c.create_line(x, footer_y, min(x+270, w-22), footer_y,
                      fill="#4A4F56", width=1, tags="hero")
        c.create_line(x, footer_y, min(x+105, w-22), footer_y,
                      fill=COLORS["orange"], width=2, tags="hero")
        c.create_text(x, footer_y+13, anchor="w",
                      text="MORE DETAILS IN NEWS  ↓",
                      fill="#A7ADB4",
                      font=("Bahnschrift SemiBold", max(7,int(round(8*s)))),
                      tags="hero")
        c.tag_lower("hero")

    def _news(self, parent):
        header = tk.Frame(parent, bg=COLORS["panel"])
        header.pack(fill="x", padx=14, pady=(12, 7))
        tk.Label(header, text="NEWS", bg=COLORS["panel"],
                 fg=COLORS["text"], font=("Bahnschrift SemiBold", 11)
                 ).pack(side="left")
        link = tk.Label(header, text="VIEW ALL",
                        bg=COLORS["panel"], fg="#A6A9AD",
                        font=("Bahnschrift", 8), cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: self._open_all_news())
        self.news_game_indicator = tk.Label(
            header, text="", bg=COLORS["panel"],
            fg="#FF983C", cursor="hand2",
            font=("Bahnschrift SemiBold", 8))
        self.news_game_indicator.pack(side="right", padx=(0, 10))
        self.news_game_indicator.bind("<Button-1>",
                                      self._acknowledge_game_news)

        container = tk.Frame(parent, bg=COLORS["panel"])
        container.pack(fill="both", expand=True, padx=10, pady=(0, 9))
        self.news_canvas = tk.Canvas(
            container, bg=COLORS["panel"], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(
            container, orient="vertical", command=self.news_canvas.yview,
            bg="#20252C", troughcolor="#0F1217",
            activebackground=COLORS["orange"], width=9,
            relief="flat", bd=0)
        self.news_canvas.configure(yscrollcommand=scrollbar.set)
        self.news_canvas.bind("<MouseWheel>", self._scroll_news)
        scrollbar.pack(side="right", fill="y")
        self.news_canvas.pack(side="left", fill="both", expand=True)
        self.news_rows = tk.Frame(self.news_canvas, bg=COLORS["panel"])
        window_id = self.news_canvas.create_window(
            (0, 0), window=self.news_rows, anchor="nw")
        self.news_rows.bind("<Configure>", lambda e:
            self.news_canvas.configure(scrollregion=self.news_canvas.bbox("all")))
        self.news_canvas.bind("<Configure>", lambda e:
            (self.news_canvas.itemconfigure(window_id, width=e.width),
             self._resize_news_content()))

    def _right_cards(self, parent):
        self.settings_panel = tk.Frame(
            parent, bg="#0F1115",
            highlightbackground="#2B3037", highlightthickness=1)
        self.settings_panel.pack(side="top", fill="both", expand=True)
        self.settings_panel.pack_propagate(False)
        self._settings_card(self.settings_panel)

    def _load_launcher_settings(self):
        # Never auto-search for a CTR executable or silently rewrite a
        # previously selected folder. A missing setting stays unset.
        data = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                data = {}

        self._launcher_settings_data = dict(data)
        frequency = str(data.get("release_check_frequency", "Daily"))
        self.release_check_frequency = (
            frequency if frequency in releases.CHECK_CHOICES else "Daily"
        )
        self.release_last_result = str(data.get("release_last_result", "") or "")[:140]
        self.launcher_auto_update = data.get("launcher_auto_update", True) is not False
        try:
            self.launcher_last_check = max(0.0, float(data.get("launcher_last_check", 0)))
        except (ValueError, TypeError, OverflowError):
            self.launcher_last_check = 0.0
        self.launcher_last_result = str(data.get("launcher_last_result", "") or "")[:140]
        try:
            self.release_last_check = max(0.0, float(data.get("release_last_check", 0)))
        except (ValueError, TypeError, OverflowError):
            self.release_last_check = 0.0
        chosen = data.get("game_install_path", "")
        # Preserve the exact explicitly chosen path even when the game is
        # temporarily absent, moved or its executable has not been installed.
        self.game_install_path = chosen if isinstance(chosen, str) else ""
        if os.path.isfile(SETTINGS_FILE):
            # Enables separately opened tool EXEs to find the same installation
            # without probing arbitrary local game folders.
            editor_config.save_launcher_selection(
                SETTINGS_FILE, self.game_install_path)
        return data

    def _save_launcher_settings(self):
        data = dict(getattr(self, "_launcher_settings_data", {}) or {})
        data.update({
            "game_install_path": getattr(self, "game_install_path", ""),
            "release_check_frequency": getattr(self, "release_check_frequency", "Daily"),
            "release_last_check": getattr(self, "release_last_check", 0.0),
            "release_last_result": getattr(self, "release_last_result", "")[:140],
            "launcher_auto_update": bool(getattr(self, "launcher_auto_update", True)),
            "launcher_last_check": getattr(self, "launcher_last_check", 0.0),
            "launcher_last_result": getattr(self, "launcher_last_result", "")[:140],
        })
        try:
            tmp = SETTINGS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, SETTINGS_FILE)
            self._launcher_settings_data = data
            # Best-effort mirror (contains no account/session information).
            editor_config.save_launcher_selection(
                SETTINGS_FILE, str(self.game_install_path or ""))
            return True
        except OSError:
            return False

    def _refresh_install_location_ui(self):
        path = getattr(self, "game_install_path", "")
        display = path if path else "SELECT GAME FOLDER"

        if hasattr(self, "install_path_label"):
            rail_width = (self.right_panel.winfo_width() if hasattr(self, "right_panel")
                          else 290)
            self.install_path_label.configure(
                text=(self._compact_install_path(path, max(15, (rail_width - 120) // 6))
                      if path else display))
        popup = getattr(self, "_compact_settings_path_label", None)
        if popup is not None:
            try:
                if popup.winfo_exists():
                    popup.configure(text=display)
            except tk.TclError:
                pass

        exe_path = os.path.join(path, "ctr-native.exe") if path else ""
        installed = bool(exe_path) and os.path.isfile(exe_path)
        folder_exists = bool(path) and os.path.isdir(path)

        if not path:
            status_text = "NO GAME FOLDER SELECTED"
            status_color = "#A0A5AB"
        elif installed:
            status_text = "INSTALLED"
            status_color = COLORS["success"]
        elif folder_exists:
            status_text = "TARGET LOCATION"
            status_color = "#D49A4A"
        else:
            status_text = "LOCATION NOT CREATED YET"
            status_color = "#777D85"

        if hasattr(self, "install_path_status"):
            self.install_path_status.configure(
                text=status_text,
                fg=status_color,
            )

    def _settings_card(self, parent):
        self._load_launcher_settings()
        self.release_check_var = tk.StringVar(value=self.release_check_frequency)
        self.release_status_var = tk.StringVar(
            value=getattr(self, "release_last_result", "") or "GitHub Releases: not checked")
        self.launcher_auto_update_var = tk.BooleanVar(value=self.launcher_auto_update)
        self.launcher_update_status_var = tk.StringVar(
            value=self.launcher_last_result or "Launcher updates: not checked")

        header = tk.Frame(parent, bg="#0F1115")
        header.pack(fill="x", padx=14, pady=(9, 5))
        self.settings_header = header

        gear = tk.Canvas(
            header,
            width=22,
            height=22,
            bg="#0F1115",
            highlightthickness=0,
            bd=0,
        )
        gear.pack(side="left")
        gear.create_oval(4, 4, 18, 18, outline=COLORS["orange"], width=3)
        gear.create_oval(9, 9, 13, 13, fill="#0F1115", outline="")
        for x1, y1, x2, y2 in (
            (10, 0, 12, 5),
            (10, 17, 12, 22),
            (0, 10, 5, 12),
            (17, 10, 22, 12),
        ):
            gear.create_rectangle(
                x1, y1, x2, y2,
                fill=COLORS["orange"],
                outline="",
            )

        tk.Label(
            header,
            text="SETTINGS",
            bg="#0F1115",
            fg=COLORS["text"],
            font=("Bahnschrift SemiBold", 10),
        ).pack(side="left", padx=(6, 0))

        self.settings_chevron = tk.Label(
            header, text="›", bg="#0F1115", fg="#9A9EA4",
            font=("Segoe UI", 14), cursor="hand2")
        self.settings_chevron.pack(side="right")
        for widget in [header, *header.winfo_children()]:
            widget.bind("<Button-1>", self._toggle_settings_panel)
            widget.configure(cursor="hand2")

        body = tk.Frame(parent, bg="#0F1115")
        self.settings_body = body
        body.pack(fill="x", padx=14)

        title_row = tk.Frame(body, bg="#0F1115")
        title_row.pack(fill="x")

        tk.Label(
            title_row,
            text="Install Location",
            bg="#0F1115",
            fg="#7D8289",
            font=("Bahnschrift", 8),
        ).pack(side="left")

        self.install_path_status = tk.Label(
            title_row,
            text="",
            bg="#0F1115",
            fg="#777D85",
            font=("Bahnschrift SemiBold", 7),
        )
        self.install_path_status.pack(side="right")

        path_row = tk.Frame(body, bg="#0F1115")
        path_row.pack(fill="x", pady=(4, 0))

        path_box = tk.Frame(
            path_row,
            bg="#15181D",
            highlightbackground="#33383F",
            highlightthickness=1,
        )
        path_box.pack(side="left", fill="x", expand=True)

        self.install_path_label = tk.Label(
            path_box,
            text=self.game_install_path or "SELECT GAME FOLDER",
            bg="#15181D",
            fg="#A8ABB0",
            font=("Bahnschrift", 7),
            anchor="w",
            cursor="hand2",
        )
        self.install_path_label.pack(
            side="left", fill="x", expand=True,
            padx=(7, 5), pady=6,
        )

        self.install_path_label.bind(
            "<Button-1>",
            self._open_game_location,
        )
        self.install_path_label.bind(
            "<Enter>",
            lambda e: self.install_path_label.configure(
                fg=COLORS["orange"]
            ),
        )
        self.install_path_label.bind(
            "<Leave>",
            lambda e: self.install_path_label.configure(
                fg="#A8ABB0"
            ),
        )

        browse = tk.Label(
            path_row,
            text="BROWSE",
            bg="#181B20",
            fg="#F3F1EC",
            highlightbackground="#3A3F47",
            highlightthickness=1,
            font=("Bahnschrift SemiBold", 8),
            padx=10,
            pady=6,
            cursor="hand2",
        )
        browse.pack(side="right", padx=(7, 0))
        self.install_browse_button = browse
        browse.bind(
            "<Enter>",
            lambda e: browse.configure(
                bg="#252A31",
                highlightbackground=COLORS["orange"],
            ),
        )
        browse.bind(
            "<Leave>",
            lambda e: browse.configure(
                bg="#181B20",
                highlightbackground="#3A3F47",
            ),
        )
        browse.bind(
            "<Button-1>",
            self._choose_game_install_location,
        )

        hint = tk.Label(
            body,
            text="Click the path to open it, or BROWSE to choose where Crash Forge: Racing will be installed.",
            bg="#0F1115",
            fg="#5F646B",
            font=("Bahnschrift", 7),
            anchor="w",
            justify="left",
        )
        hint.pack(fill="x", pady=(5, 0))
        self.settings_hint = hint

        # Game updates belong exclusively to the large sidebar UPDATE button.
        # Settings is reserved for the launcher's OWN automatic updater.
        self._add_launcher_update_settings_controls(body)
        self._refresh_install_location_ui()

    def _add_release_settings_controls(self, parent, compact=False):
        """Release check cadence; no silent downloads or game process changes."""
        background = "#0D1014" if compact else "#0F1115"
        section = tk.Frame(parent, bg=background)
        section.pack(fill="x", pady=(10, 3))
        tk.Label(
            section, text="GITHUB RELEASES  /  CHECK VERSIONS",
            bg=background, fg="#C18D67",
            font=("Bahnschrift SemiBold", 8), anchor="w",
        ).pack(fill="x", pady=(0, 4))
        controls = tk.Frame(section, bg=background)
        controls.pack(fill="x")
        picker = tk.Menubutton(
            controls, textvariable=self.release_check_var,
            bg="#1A2027", fg="#E9E4DB",
            activebackground="#2B323A", activeforeground="#FFFFFF",
            font=("Bahnschrift SemiBold", 8), relief="flat",
            padx=9, pady=6, anchor="w",
        )
        menu = tk.Menu(
            picker, tearoff=False, bg="#161B20", fg="#EAE3DB",
            activebackground="#693008", activeforeground="#FFFFFF",
        )
        for frequency in releases.CHECK_CHOICES:
            menu.add_command(
                label=frequency,
                command=lambda value=frequency: self._set_release_check_frequency(value),
            )
        picker.configure(menu=menu)
        picker.pack(fill="x")
        action_row = tk.Frame(section, bg=background)
        action_row.pack(fill="x", pady=(5, 0))
        for title, handler in (
            ("CHECK", self._check_versions_from_settings),
            ("GITHUB", self._open_github_releases),
        ):
            tk.Button(
                action_row, text=title, command=handler, cursor="hand2",
                bg="#42210F" if title == "CHECK" else "#191D23",
                fg="#EAE6E0", relief="flat", padx=7, pady=6,
                font=("Bahnschrift SemiBold", 7),
            ).pack(side="left", fill="x", expand=True, padx=(0, 5))
        tk.Label(
            section, textvariable=self.release_status_var,
            bg=background, fg="#9CAAB2",
            font=("Bahnschrift", 8), anchor="w", justify="left",
            wraplength=465 if compact else 275,
        ).pack(fill="x", pady=(4, 0))
        return section

    def _add_launcher_update_settings_controls(self, parent, compact=False):
        """Own launcher updates are independent from game Releases checks."""
        background = "#0D1014" if compact else "#0F1115"
        panel = tk.Frame(parent, bg=background)
        panel.pack(fill="x", pady=(8, 0))
        label = tk.Checkbutton(
            panel, text="AUTO-UPDATE LAUNCHER",
            variable=self.launcher_auto_update_var,
            command=self._toggle_launcher_auto_update,
            bg=background, fg="#FFB478", selectcolor="#29313B",
            activebackground=background, activeforeground="#FFFFFF",
            font=("Bahnschrift SemiBold", 8), anchor="w",
            highlightthickness=0,
        )
        label.pack(side="left", fill="x", expand=True)
        tk.Button(
            panel, text="CHECK", cursor="hand2", relief="flat",
            command=self._check_launcher_updates_now,
            bg="#35200F", fg="#E9E3DB",
            font=("Bahnschrift SemiBold", 7),
            padx=7, pady=4,
        ).pack(side="right")
        tk.Button(
            panel, text="VERIFY FILES", cursor="hand2", relief="flat",
            command=self._verify_launcher_files_now,
            bg="#242830", fg="#F4D9C1",
            font=("Bahnschrift SemiBold", 7), padx=7, pady=4,
        ).pack(side="right", padx=(0, 6))
        tk.Label(
            parent, textvariable=self.launcher_update_status_var,
            bg=background, fg="#A8B2BD",
            font=("Bahnschrift", 8), anchor="w",
            justify="left", wraplength=465 if compact else 275,
        ).pack(fill="x", pady=(3, 0))
        restart_ready = self._launcher_restart_required()
        restart = tk.Button(
            parent, text="RESTART TO UPDATE LAUNCHER",
            cursor="hand2" if restart_ready else "arrow",
            command=self._restart_into_updated_launcher,
            bg="#4F270F" if restart_ready else "#242830",
            fg="#FFE6CC" if restart_ready else "#88909B",
            disabledforeground="#88909B",
            activebackground="#713710", activeforeground="#FFFFFF",
            relief="flat", font=("Bahnschrift SemiBold", 8),
            padx=9, pady=5,
            state="normal" if restart_ready else "disabled",
        )
        restart.pack(fill="x", pady=(4, 0))
        buttons = getattr(self, "_launcher_restart_buttons", None)
        if buttons is None:
            self._launcher_restart_buttons = []
        self._launcher_restart_buttons.append(restart)
        return panel

    def _launcher_restart_required(self):
        """Only a verified, staged, newer launcher release needs a restart."""
        if not (getattr(self, "launcher_auto_update", False) and
                getattr(self, "launcher_update_ready", None)):
            return False
        pending = launcher_updates.pending_update()
        if not pending or pending["version"] != self.launcher_update_ready["version"]:
            return False
        if launcher_updates.is_portable_build():
            install_dir = self._forge_base_dir()
        else:
            install_dir = launcher_updates.portable_target_for_source(
                self._forge_base_dir())
        return launcher_updates.pending_update_required(
            pending, install_dir)

    def _set_restart_buttons_enabled(self, enabled):
        ready = bool(enabled) and self._launcher_restart_required()
        for button in getattr(self, "_launcher_restart_buttons", []):
            try:
                if button.winfo_exists():
                    button.configure(
                        state="normal" if ready else "disabled",
                        bg="#4F270F" if ready else "#242830",
                        fg="#FFE6CC" if ready else "#88909B",
                        cursor="hand2" if ready else "arrow",
                    )
            except tk.TclError:
                pass

    def _restart_into_updated_launcher(self):
        """User action: close gracefully, then start the new GUI EXE."""
        if not self._launcher_restart_required():
            return
        if getattr(self, "game_update_busy", False) or getattr(self, "mod_download_busy", False):
            self.launcher_update_status_var.set(
                "Wait for the active transfer before restarting.")
            return
        if not getattr(self, "launcher_auto_update", True):
            self.launcher_update_status_var.set(
                "Enable launcher auto-update before restarting.")
            return
        self.destroy()

    def _toggle_launcher_auto_update(self):
        self.launcher_auto_update = bool(self.launcher_auto_update_var.get())
        self._save_launcher_settings()
        self._set_restart_buttons_enabled(
            self.launcher_auto_update and
            bool(getattr(self, "launcher_update_ready", None)))
        self.launcher_update_status_var.set(
            "Auto-update enabled: applies after closing the launcher."
            if self.launcher_auto_update else
            "Auto-update paused. You can still check for releases."
        )
        if self.launcher_auto_update and getattr(self, "launcher_update_busy", False) is False:
            self.after(100, lambda: self._request_launcher_update_check(manual=True))

    def _check_launcher_updates_now(self):
        self._request_launcher_update_check(manual=True)

    def _verify_launcher_files_now(self):
        self._check_launcher_integrity(manual=True)

    def _set_release_check_frequency(self, choice):
        if choice not in releases.CHECK_CHOICES:
            return
        self.release_check_frequency = choice
        self.release_check_var.set(choice)
        if not self._save_launcher_settings():
            self.status_label.configure(text="Could not save GitHub update-check preference.")
            return
        self.release_status_var.set("Update checks: " + choice +
                                    " (downloads always require confirmation)")
        if choice not in ("Manual only", "On launch"):
            self.after(100, lambda: self._request_release_check(
                manual=False, request_install=False))

    def _check_versions_from_settings(self):
        self._request_release_check(manual=True, request_install=False)

    def _open_github_releases(self):
        import webbrowser
        webbrowser.open(releases.RELEASES_URL)

    def _choose_game_install_location(self, event=None):
        if getattr(self, "game_update_busy", False) or getattr(self, "mod_download_busy", False):
            self.status_label.configure(
                text="Wait for the verified transfer to finish before changing the game folder.")
            return
        current = getattr(
            self,
            "game_install_path",
            services.DEFAULT_GAME_PATH,
        )
        initial = current if os.path.isdir(current) else os.path.dirname(current)
        if not initial or not os.path.isdir(initial):
            initial = BASE_DIR

        try:
            selected = filedialog.askdirectory(
                parent=self,
                title="Choose Crash Forge: Racing install location",
                initialdir=initial,
                mustexist=False,
            )
        except TypeError:
            selected = filedialog.askdirectory(
                parent=self,
                title="Choose Crash Forge: Racing install location",
                initialdir=initial,
            )

        selected = str(selected or "").strip()
        if not selected:
            return

        old_path = self.game_install_path
        self.game_install_path = os.path.normpath(selected)
        if not self._save_launcher_settings():
            # Never pretend a new path has been chosen if the preference
            # couldn't be written. Keep the last successfully saved folder.
            self.game_install_path = old_path
            self.status_label.configure(
                text="Could not save folder selection; previous game folder retained."
            )
            self._refresh_install_location_ui()
            return
        self.status_label.configure(
            text=f"Game folder saved: {self.game_install_path}"
        )
        self._refresh_install_location_ui()
        self._refresh_real_install_ui()
        # Offline BIN fingerprinting is silent and cannot prevent PLAY.
        try:
            iso_integrity.start_background_check(self.game_install_path, "folder_changed")
        except Exception:
            pass  # Silent, nonblocking offline-only diagnostics.

    def _open_game_location(self, event=None):
        path = getattr(
            self,
            "game_install_path",
            services.DEFAULT_GAME_PATH,
        )
        try:
            if os.path.isdir(path):
                os.startfile(path)
            else:
                self.status_label.configure(
                    text="That install location does not exist yet. Use BROWSE to choose another folder."
                )
        except Exception:
            self.status_label.configure(
                text="Could not open the install location."
            )


    # ------------------------------------------------------------------
    # Forge Hub / Community Mods
    # ------------------------------------------------------------------

    def _default_community_catalog(self):
        return []

    def _load_community_catalog(self):
        if hasattr(self, "community_catalog"):
            return self.community_catalog

        data = None
        if os.path.exists(COMMUNITY_CATALOG_FILE):
            try:
                with open(COMMUNITY_CATALOG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                data = None

        if data is None:
            data = self._default_community_catalog()
            try:
                with open(COMMUNITY_CATALOG_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except OSError:
                pass

        # Filter the original mock preview entries, but keep genuine user uploads.
        data = [item for item in data if isinstance(item, dict)
                and not (str(item.get("id", "")).endswith("_preview")
                         and str(item.get("author", "")).lower() == "local preview")]
        self.community_catalog = data
        return data

    def _save_community_catalog(self):
        try:
            with open(COMMUNITY_CATALOG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.community_catalog, f, indent=2, ensure_ascii=False)
            return True
        except OSError:
            return False

    def _hub_button(self, parent, text, command, accent=False, width=None, enabled=True):
        if enabled:
            bg = "#532000" if accent else "#181B20"
            hover = "#773000" if accent else "#252A31"
            edge = COLORS["orange"] if accent else "#3A3F47"
            fg = "#F3F1EC"
            cursor = "hand2"
        else:
            bg = "#111318"
            hover = bg
            edge = "#292D33"
            fg = "#5B6067"
            cursor = "arrow"

        label = tk.Label(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            highlightbackground=edge,
            highlightthickness=1,
            font=("Bahnschrift SemiBold", 9),
            padx=12,
            pady=7,
            cursor=cursor,
            width=width,
        )
        if enabled:
            label.bind("<Enter>", lambda e: label.configure(bg=hover))
            label.bind("<Leave>", lambda e: label.configure(bg=bg))
            label.bind("<Button-1>", lambda e: command())
        return label

    def _is_local_community_mod(self, mod):
        source = str(mod.get("source", "")).strip().lower()
        package = str(mod.get("package_path", "")).strip()
        author = str(mod.get("author", "")).strip().lower()
        if source == "local":
            return True
        if package and os.path.exists(package):
            return True
        return author == "local preview"

    def _version_key(self, value):
        numbers = []
        token = ""
        for ch in str(value or "0"):
            if ch.isdigit():
                token += ch
            elif token:
                numbers.append(int(token))
                token = ""
        if token:
            numbers.append(int(token))
        numbers = (numbers + [0, 0, 0, 0])[:4]
        return tuple(numbers)


    def _hub_install_state(self, mod):
        local = mod.get("_installed")
        source = str(mod.get("source", ""))
        pkg = str(mod.get("package_path", ""))
        if local:
            installed_version = (str(local.get("version") or "")
                                 or self._local_record_version(mod))
            downloadable = (
                (source == "local" and pkg.lower().endswith(".zip")
                 and os.path.isfile(pkg) and bool(mod.get("sha256"))) or
                (source == "online" and bool(mod.get("download_url") and
                                             mod.get("sha256"))))
            if (downloadable and self._version_key(mod.get("version")) >
                    self._version_key(installed_version)):
                return ("UPDATE", True)
            return ("INSTALLED", False)
        if source == "installed":
            return ("NO PACKAGE", False)
        if source == "local":
            return ("INSTALL ZIP", bool(pkg.lower().endswith(".zip") and
                                        os.path.isfile(pkg) and mod.get("sha256")))
        if not mod.get("download_url") or not mod.get("sha256"):
            return ("NO PACKAGE", False)
        return ("INSTALL", True)

    def _toggle_hide_local_mods(self):
        """Hide unpublished local ZIPs/folders in the browser, without deleting."""
        active = self.hub_hide_local_var.get()
        self.hub_hide_local_button.configure(
            text="HIDE LOCAL  ON" if active else "HIDE LOCAL",
            bg="#4A1C06" if active else "#15191E",
            fg="#FFFFFF" if active else "#A9ADB2",
        )
        self._render_hub_cards()

    def _toggle_installed_only(self):
        active = self.hub_installed_only_var.get()
        self.hub_installed_button.configure(
            text="INSTALLED ONLY  ✓" if active else "INSTALLED ONLY",
            bg="#4A1C06" if active else "#15191E",
            fg="#FFFFFF" if active else "#A9ADB2",
            highlightbackground=COLORS["orange"] if active else "#343A42",
        )
        self._render_hub_cards()

    def _toggle_installed_mod(self, mod):
        """Write the game's REAL native enabled INI, not a launcher-only flag."""
        if getattr(self, "mod_download_busy", False) or getattr(self, "game_update_busy", False):
            self.hub_status_label.configure(
                text="Wait for the current game/mod installation to finish.")
            return
        current = mod.get("_installed") or {}
        if not current.get("manageable"):
            self.hub_status_label.configure(
                text="This mod needs a valid native INI before it can be managed.")
            return
        try:
            changed = mod_manager.set_enabled(
                self.game_install_path, current["type"], current["id"],
                not current["enabled"])
        except (mod_manager.ModManagerError, OSError) as error:
            self.hub_status_label.configure(text="Mod Manager: " + str(error)[:150])
            return
        self._close_mod_details()
        self._render_hub_cards()
        message = "ENABLED" if changed["enabled"] else "DISABLED"
        if changed["type"] == "Track":
            message += " (track registration in the game is still pending)"
        else:
            message += " — restart the game to apply"
        self.hub_status_label.configure(
            text=current["title"] + " " + message + ".")
    def _build_forge_hub_overlay(self):
        self.hub_overlay = tk.Frame(
            self.shell,
            bg="#090B0E",
            highlightbackground="#30353C",
            highlightthickness=1,
        )

        header = tk.Frame(self.hub_overlay, bg="#0D0F13", height=72)
        header.pack(fill="x")
        header.pack_propagate(False)

        back = self._hub_button(header, "‹  BACK", self._hide_forge_hub)
        back.pack(side="left", padx=(18, 12), pady=18)

        title_box = tk.Frame(header, bg="#0D0F13")
        title_box.pack(side="left", pady=12)
        tk.Label(
            title_box,
            text="FORGE HUB  /  MOD MANAGER",
            bg="#0D0F13",
            fg="#F2F2EF",
            font=("Bahnschrift SemiBold", 18),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="COMMUNITY MODS  /  CHARACTERS • KARTS • WHEELS • MAPS • MODPACKS",
            bg="#0D0F13",
            fg=COLORS["orange"],
            font=("Bahnschrift SemiBold", 8),
        ).pack(anchor="w", pady=(1, 0))

        upload = self._hub_button(
            header, "＋  ADD LOCAL", self._open_hub_upload, accent=True
        )
        upload.pack(side="right", padx=18, pady=18)

        controls = tk.Frame(self.hub_overlay, bg="#101318")
        controls.pack(fill="x", padx=18, pady=(14, 8))

        search_box = tk.Frame(
            controls,
            bg="#15191E",
            highlightbackground="#343A42",
            highlightthickness=1,
        )
        search_box.pack(side="top", fill="x", padx=(0, 8), pady=(0, 8))
        search_icon = tk.Canvas(
            search_box,
            width=28,
            height=28,
            bg="#15191E",
            highlightthickness=0,
            bd=0,
        )
        search_icon.pack(side="left", padx=(7, 1), pady=3)
        search_icon.create_oval(
            6, 5, 18, 17,
            outline="#A6ABB2",
            width=2,
        )
        search_icon.create_line(
            17, 16, 23, 22,
            fill=COLORS["orange"],
            width=3,
            capstyle="round",
        )

        self.hub_search_var = tk.StringVar()
        self.hub_search_entry = tk.Entry(
            search_box,
            textvariable=self.hub_search_var,
            bg="#15191E",
            fg="#E8E9E5",
            insertbackground=COLORS["orange"],
            relief="flat",
            bd=0,
            font=("Bahnschrift", 10),
        )
        self.hub_search_entry.pack(side="left", fill="x", expand=True, padx=(4, 8), pady=8)
        self.hub_search_entry.bind("<KeyRelease>", lambda e: self._render_hub_cards())
        self.hub_search_entry.bind("<Return>", lambda e: self._run_hub_search())

        self.hub_search_button = self._hub_button(
            search_box,
            "SEARCH",
            self._run_hub_search,
            accent=True,
        )
        self.hub_search_button.pack(side="right", padx=(5, 5), pady=4)

        # Search above the filters avoids clipping on smaller screens.
        filter_row = tk.Frame(controls, bg="#101318")
        filter_row.pack(fill="x", pady=(0, 2))
        self.hub_type_var = tk.StringVar(value="All")
        self.hub_filter_buttons = {}
        for label, value in (
            ("ALL", "All"),
            ("CHARACTERS", "Character"),
            ("KARTS", "Kart"),
            ("WHEELS", "Wheels"),
            ("MAPS", "Track"),
            ("MODPACKS", "Modpack"),
        ):
            button = tk.Label(
                filter_row,
                text=label,
                bg="#15191E",
                fg="#A9ADB2",
                highlightbackground="#343A42",
                highlightthickness=1,
                font=("Bahnschrift SemiBold", 8),
                padx=9,
                pady=8,
                cursor="hand2",
            )
            button.pack(side="left", padx=(0, 5))
            button.bind("<Button-1>", lambda e, v=value: self._set_hub_type(v))
            self.hub_filter_buttons[value] = button

        sort_box = tk.Frame(
            filter_row,
            bg="#15191E",
            highlightbackground="#343A42",
            highlightthickness=1,
        )
        sort_box.pack(side="right", padx=(8, 0))
        tk.Label(
            sort_box,
            text="SORT",
            bg="#15191E",
            fg="#676D75",
            font=("Bahnschrift SemiBold", 7),
        ).pack(side="left", padx=(8, 3))

        self.hub_sort_var = tk.StringVar(value="Newest")
        sort_button = tk.Menubutton(
            sort_box,
            textvariable=self.hub_sort_var,
            bg="#15191E",
            fg="#E1E2DE",
            activebackground="#22272D",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            font=("Bahnschrift SemiBold", 8),
            cursor="hand2",
            padx=8,
            pady=6,
        )
        menu = tk.Menu(
            sort_button,
            tearoff=False,
            bg="#15191E",
            fg="#E1E2DE",
            activebackground="#5C2505",
            activeforeground="#FFFFFF",
            bd=0,
        )
        for option in ("Newest", "Most Downloaded", "Most Liked", "Name"):
            menu.add_command(
                label=option,
                command=lambda v=option: self._set_hub_sort(v),
            )
        sort_button.configure(menu=menu)
        sort_button.pack(side="left")

        # Installed is an independent filter, so e.g. WHEELS + INSTALLED
        # works together without crowding the 4:3 category filter row.
        manager_row = tk.Frame(controls, bg="#101318")
        manager_row.pack(fill="x", pady=(4, 5))
        self.hub_installed_only_var = tk.BooleanVar(value=False)
        self.hub_installed_button = tk.Checkbutton(
            manager_row, text="INSTALLED ONLY",
            variable=self.hub_installed_only_var,
            command=self._toggle_installed_only,
            indicatoron=False,
            bg="#15191E", fg="#A9ADB2",
            activebackground="#4A1C06", activeforeground="#FFFFFF",
            selectcolor="#4A1C06",
            highlightbackground="#343A42", highlightthickness=1,
            relief="flat", bd=0,
            font=("Bahnschrift SemiBold", 8), padx=11, pady=5,
            cursor="hand2",
        )
        self.hub_installed_button.pack(side="left", padx=(0, 7))
        self.hub_hide_local_var = tk.BooleanVar(value=False)
        self.hub_hide_local_button = tk.Checkbutton(
            manager_row, text="HIDE LOCAL",
            variable=self.hub_hide_local_var,
            command=self._toggle_hide_local_mods,
            indicatoron=False,
            bg="#15191E", fg="#A9ADB2",
            activebackground="#4A1C06", activeforeground="#FFFFFF",
            selectcolor="#4A1C06",
            highlightbackground="#343A42", highlightthickness=1,
            relief="flat", bd=0, font=("Bahnschrift SemiBold", 8),
            padx=9, pady=5, cursor="hand2",
        )
        self.hub_hide_local_button.pack(side="left", padx=(0, 8))
        self.hub_installed_summary = tk.Label(
            manager_row,
            text="MOD MANAGER  /  SCANNING NATIVE FOLDERS",
            bg="#101318", fg="#9198A1",
            font=("Bahnschrift SemiBold", 8),
        )
        self.hub_installed_summary.pack(side="left")
        music_filter = self._hub_button(
            manager_row, "MUSIC", lambda: self._set_hub_type("Music"),
            width=6
        )
        music_filter.pack(side="right")

        info = tk.Frame(self.hub_overlay, bg="#090B0E")
        info.pack(fill="x", padx=20, pady=(2, 7))
        self.hub_count_label = tk.Label(
            info,
            text="0 MODS",
            bg="#090B0E",
            fg="#A3A7AD",
            font=("Bahnschrift SemiBold", 8),
        )
        self.hub_count_label.pack(side="left")
        self.hub_source_label = tk.Label(
            info, text="PUBLIC FEED NOT CONFIGURED (SOURCE)",
            bg="#090B0E", fg="#9B9FA6", cursor="hand2",
            font=("Bahnschrift SemiBold", 8))
        self.hub_source_label.pack(side="right")
        self.hub_source_label.bind("<Button-1>", lambda e: self._configure_feed_source())
        self._hub_button(info, "REFRESH", self._reload_live_source).pack(side="right", padx=12)

        list_shell = tk.Frame(self.hub_overlay, bg="#090B0E")
        list_shell.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        self.hub_canvas = tk.Canvas(
            list_shell,
            bg="#090B0E",
            highlightthickness=0,
            bd=0,
        )
        self.hub_canvas.pack(side="left", fill="both", expand=True)

        self.hub_scrollbar = tk.Scrollbar(
            list_shell,
            orient="vertical",
            command=self.hub_canvas.yview,
            bg="#1D2127",
            troughcolor="#0B0D10",
            activebackground=COLORS["orange"],
            relief="flat",
            bd=0,
            width=10,
        )
        self.hub_scrollbar.pack(side="right", fill="y")
        self.hub_canvas.configure(yscrollcommand=self.hub_scrollbar.set)

        self.hub_cards_frame = tk.Frame(self.hub_canvas, bg="#090B0E")
        self.hub_cards_window = self.hub_canvas.create_window(
            (0, 0),
            window=self.hub_cards_frame,
            anchor="nw",
        )

        self.hub_cards_frame.bind(
            "<Configure>",
            lambda e: self.hub_canvas.configure(
                scrollregion=self.hub_canvas.bbox("all")
            ),
        )
        self.hub_canvas.bind(
            "<Configure>",
            self._on_hub_canvas_resize,
        )
        # Wheel scrolling must work over the whole Forge Hub, not only
        # when the pointer is directly over the canvas.
        self.bind_all("<MouseWheel>", self._on_hub_mousewheel, add="+")

        footer = tk.Frame(self.hub_overlay, bg="#0D0F13", height=36)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        self.hub_status_label = tk.Label(
            footer,
            text="Local mods available. Select SOURCE to connect your public Forge catalog.",
            bg="#0D0F13",
            fg="#747A82",
            font=("Bahnschrift", 8),
        )
        self.hub_status_label.pack(side="left", padx=18, pady=9)
        tk.Label(
            footer,
            text="FORGE HUB  /  COMMUNITY",
            bg="#0D0F13",
            fg="#4F545B",
            font=("Bahnschrift SemiBold", 7),
        ).pack(side="right", padx=18, pady=9)

        self._build_hub_upload_overlay()
        self._update_hub_filter_visuals()

    def _show_forge_hub(self):
        self._load_community_catalog()
        self.hub_overlay.place(
            x=0,
            y=78,
            relwidth=1.0,
            relheight=1.0,
            height=-78,
        )
        self.hub_overlay.lift()
        self._raise_resize_grips()
        self._render_hub_cards()
        try:
            self.hub_search_entry.focus_set()
        except Exception:
            pass

    def _hide_forge_hub(self):
        if hasattr(self, "hub_details_overlay") and self.hub_details_overlay.winfo_ismapped():
            self._close_mod_details()
            return
        if hasattr(self, "hub_upload_overlay") and self.hub_upload_overlay.winfo_ismapped():
            self._close_hub_upload()
            return
        self.hub_overlay.place_forget()

    def _run_hub_search(self):
        query = self.hub_search_var.get().strip()
        self._render_hub_cards()
        if query:
            count = len(self._hub_filtered_catalog())
            self.hub_status_label.configure(
                text=f'Search "{query}" • {count} result{"s" if count != 1 else ""}.'
            )
        else:
            self.hub_status_label.configure(
                text=self.online_status + " - showing available public and local mods."
            )

    def _set_hub_type(self, value):
        self.hub_type_var.set(value)
        self._update_hub_filter_visuals()
        self._render_hub_cards()

    def _set_hub_sort(self, value):
        self.hub_sort_var.set(value)
        self._render_hub_cards()

    def _update_hub_filter_visuals(self):
        current = self.hub_type_var.get()
        for value, button in self.hub_filter_buttons.items():
            if value == current:
                button.configure(
                    bg="#4A1C06",
                    fg="#FFFFFF",
                    highlightbackground=COLORS["orange"],
                )
            else:
                button.configure(
                    bg="#15191E",
                    fg="#A9ADB2",
                    highlightbackground="#343A42",
                )

    def _on_hub_mousewheel(self, event):
        if not hasattr(self, "hub_overlay") or not self.hub_overlay.winfo_ismapped():
            return

        # Only hijack the wheel when the pointer is somewhere inside Forge Hub.
        widget = getattr(event, "widget", None)
        inside_hub = False
        while widget is not None:
            if widget is self.hub_overlay:
                inside_hub = True
                break
            widget = getattr(widget, "master", None)

        if not inside_hub:
            return

        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return "break"

        steps = -1 if delta > 0 else 1
        # A couple of units per notch feels much less sluggish on the mod grid.
        self.hub_canvas.yview_scroll(steps * 3, "units")
        return "break"

    def _on_hub_canvas_resize(self, event):
        self.hub_canvas.itemconfigure(self.hub_cards_window, width=event.width)
        if getattr(self, "_hub_resize_job", None) is not None:
            try:
                self.after_cancel(self._hub_resize_job)
            except Exception:
                pass
        self._hub_resize_job = self.after(80, self._render_hub_cards)

    def _hub_filtered_catalog(self):
        # Physical native folders are authoritative: the launcher can be
        # reinstalled without forgetting any enabled or disabled game mods.
        installed = mod_manager.scan_installed(self.game_install_path)
        by_key = {(row["type"], row["id"]): row for row in installed}
        self._hub_local_index = by_key
        if hasattr(self, "hub_installed_summary"):
            enabled = sum(row["enabled"] is True for row in installed)
            disabled = sum(row["enabled"] is False for row in installed)
            needs_ini = sum(not row["manageable"] for row in installed)
            self.hub_installed_summary.configure(
                text=f"{len(installed)} INSTALLED  /  {enabled} ON  /  "
                     f"{disabled} OFF  /  {needs_ini} NEED INI")

        catalog = list(getattr(self, "remote_mods", [])) + list(
            self._load_community_catalog())
        joined = {}
        # Local items keep their own known title/version while catalog data
        # supplies download URLs and public metadata for online items.
        for item in catalog:
            key = (str(item.get("type","")),str(item.get("id","")))
            if key[0] not in mod_manager.CATEGORIES or not key[1]:
                continue
            if key not in joined or item.get("source") == "online":
                joined[key] = dict(item)
        for key, entry in by_key.items():
            if key not in joined:
                joined[key] = dict(entry)
            joined[key]["_installed"] = entry
        data = list(joined.values())
        if (getattr(self, "hub_hide_local_var", None)
                and self.hub_hide_local_var.get()):
            data = [mod for mod in data if not mod_manager.locally_sourced(mod)]
        if getattr(self, "hub_installed_only_var", None) and self.hub_installed_only_var.get():
            data = [item for item in data if item.get("_installed")]

        query = self.hub_search_var.get().strip().lower()
        if query:
            data = [
                item for item in data
                if query in str(item.get("title", "")).lower()
                or query in str(item.get("id", "")).lower()
                or query in str(item.get("author", "")).lower()
                or query in str(item.get("description", "")).lower()
                or query in str(item.get("type", "")).lower()
                or query in modmeta.summary(item).lower()
            ]
        mod_type = self.hub_type_var.get()
        if mod_type != "All":
            data = [item for item in data if item.get("type") == mod_type]
        sort_mode = self.hub_sort_var.get()
        if sort_mode == "Most Downloaded":
            data.sort(key=lambda x: int(x.get("downloads") or 0), reverse=True)
        elif sort_mode == "Most Liked":
            data.sort(key=lambda x: int(x.get("likes") or 0), reverse=True)
        elif sort_mode == "Name":
            data.sort(key=lambda x: str(x.get("title","")).lower())
        else:
            data.sort(key=lambda x: str(x.get("created_at","")),reverse=True)
        return data

    def _render_hub_cards(self):
        if not hasattr(self, "hub_cards_frame"):
            return

        self._hub_resize_job = None
        for child in self.hub_cards_frame.winfo_children():
            child.destroy()

        data = self._hub_filtered_catalog()
        self.hub_count_label.configure(text=f"{len(data)} MODS")

        try:
            width = self.hub_canvas.winfo_width()
        except Exception:
            width = 1200

        if width >= 1500:
            columns = 4
        elif width >= 980:
            columns = 3
        else:
            columns = 2

        for col in range(columns):
            self.hub_cards_frame.grid_columnconfigure(col, weight=1, uniform="hub")

        if not data:
            empty = tk.Frame(
                self.hub_cards_frame,
                bg="#101318",
                highlightbackground="#2D3239",
                highlightthickness=1,
            )
            empty.grid(row=0, column=0, columnspan=columns, sticky="nsew", padx=7, pady=7)
            tk.Label(
                empty,
                text="NO MODS FOUND",
                bg="#101318",
                fg="#D5D6D3",
                font=("Bahnschrift SemiBold", 13),
            ).pack(pady=(34, 5))
            tk.Label(
                empty,
                text="Try another search, category, or local/installed filter.",
                bg="#101318",
                fg="#727880",
                font=("Bahnschrift", 9),
            ).pack(pady=(0, 34))
            return

        for index, mod in enumerate(data):
            row = index // columns
            col = index % columns
            card = self._create_hub_card(self.hub_cards_frame, mod)
            card.grid(
                row=row,
                column=col,
                sticky="nsew",
                padx=7,
                pady=7,
            )

    def _create_hub_card(self, parent, mod):
        s = max(0.92, min(1.20, getattr(self, "ui_scale", 1.0)))
        card = tk.Frame(
            parent,
            bg="#101318",
            highlightbackground="#30353C",
            highlightthickness=1,
        )

        preview = tk.Canvas(
            card,
            height=max(86, int(round(98 * s))),
            bg="#0B0D10",
            highlightthickness=0,
            bd=0,
        )
        preview.pack(fill="x")
        preview.bind(
            "<Configure>",
            lambda e, c=preview, m=mod: self._paint_hub_preview(c, m, e.width, e.height),
        )

        body = tk.Frame(card, bg="#101318")
        body.pack(fill="both", expand=True, padx=12, pady=10)

        title_row = tk.Frame(body, bg="#101318")
        title_row.pack(fill="x")
        tk.Label(
            title_row,
            text=mod_manager.display_mod_name(mod),
            bg="#101318",
            fg="#F0F0EC",
            font=("Bahnschrift SemiBold", max(10, int(round(12 * s)))),
            anchor="w",
        ).pack(side="left")
        tk.Label(
            title_row,
            text=f"v{mod.get('version', '1.0')}",
            bg="#101318",
            fg="#70767E",
            font=("Bahnschrift", max(7, int(round(8 * s)))),
        ).pack(side="right")

        tk.Label(
            body,
            text=f"by {mod.get('author', 'Unknown')}",
            bg="#101318",
            fg="#767C84",
            font=("Bahnschrift", max(7, int(round(8 * s)))),
            anchor="w",
        ).pack(anchor="w", pady=(2, 6))

        tk.Label(
            body,
            text=str(mod.get("description", "")),
            bg="#101318",
            fg="#9A9FA6",
            font=("Bahnschrift", max(7, int(round(8 * s)))),
            justify="left",
            anchor="w",
            wraplength=max(230, int(round(300 * s))),
        ).pack(fill="x", anchor="w")
        tk.Label(
            body,
            text=modmeta.summary(mod),
            bg="#101318",
            fg="#EAA877",
            font=("Bahnschrift SemiBold", 8),
            anchor="w",
            justify="left",
            wraplength=max(230, int(round(300 * s))),
        ).pack(fill="x", anchor="w", pady=(7, 0))

        stats = tk.Frame(body, bg="#101318")
        stats.pack(fill="x", pady=(9, 8))
        type_label = tk.Label(
            stats,
            text=str(mod.get("type", "Mod")).upper(),
            bg="#2A160C",
            fg=COLORS["orange"],
            font=("Bahnschrift SemiBold", 7),
            padx=6,
            pady=2,
        )
        type_label.pack(side="left")
        stats_text = "    ".join(
            f"{symbol} {mod[key]:,}" for key, symbol in
            (("downloads", "↓"), ("likes", "♥"))
            if isinstance(mod.get(key), int)) or "UNREPORTED"
        tk.Label(
            stats,
            text=stats_text,
            bg="#101318",
            fg="#747A81",
            font=("Bahnschrift", 7),
        ).pack(side="right")

        installed = mod.get("_installed")
        if installed:
            state = ("STAGED" if installed["type"] == "Track" else
                     installed.get("status", "INSTALLED"))
            tk.Label(
                body, text="●  " + state,
                bg="#101318",
                fg="#59C98F" if installed.get("enabled") else "#ECA47D",
                font=("Bahnschrift SemiBold", 8),
                anchor="w",
            ).pack(fill="x", pady=(0, 6))
        buttons = tk.Frame(body, bg="#101318")
        buttons.pack(fill="x")

        install_text, install_enabled = self._hub_install_state(mod)
        if install_enabled or not installed:
            self._hub_button(
                buttons,
                install_text,
                lambda m=mod: self._install_community_mod(m),
                accent=install_enabled, enabled=install_enabled,
            ).pack(side="left", padx=(0, 5))
        if installed:
            self._hub_button(
                buttons,
                ("DISABLE" if installed["enabled"] else "ENABLE")
                if installed["manageable"] else "NEEDS INI",
                lambda m=mod: self._toggle_installed_mod(m),
                accent=bool(installed["manageable"] and not installed["enabled"]),
                enabled=bool(installed["manageable"]),
            ).pack(side="left", padx=(0, 4))
        self._hub_button(
            buttons, "DETAILS", lambda m=mod: self._show_mod_details(m),
        ).pack(side="right")

        return card

    def _paint_hub_preview(self, canvas, mod, width, height):
        canvas.delete("all")
        width = max(width, 1)
        height = max(height, 1)

        canvas.create_rectangle(0, 0, width, height, fill="#0B0D10", outline="")
        canvas.create_polygon(
            0, height,
            width * 0.42, height * 0.28,
            width * 0.76, height,
            fill="#14171C",
            outline="",
        )
        canvas.create_polygon(
            width * 0.52, height,
            width * 0.78, height * 0.14,
            width, height * 0.28,
            width, height,
            fill="#2A1308",
            outline="",
        )
        canvas.create_line(0, height - 4, width, height - 4, fill="#6B2807", width=2)

        mod_type = mod.get("type", "Mod")
        cx = width * 0.18
        cy = height * 0.50
        col = "#D9DAD6"
        dim = "#5D636B"
        orange = COLORS["orange"]

        if mod_type == "Character":
            # Cleaner profile badge: head + shoulders + small forge accent.
            canvas.create_oval(
                cx - 14, cy - 27, cx + 14, cy + 1,
                fill="#12151A", outline=col, width=2
            )
            canvas.create_arc(
                cx - 28, cy - 1, cx + 28, cy + 43,
                start=0, extent=180,
                style="arc", outline=col, width=2
            )
            canvas.create_line(
                cx - 20, cy + 18, cx - 27, cy + 32,
                fill=col, width=2
            )
            canvas.create_line(
                cx + 20, cy + 18, cx + 27, cy + 32,
                fill=col, width=2
            )
            canvas.create_line(
                cx - 11, cy + 4, cx + 11, cy + 4,
                fill=dim, width=2
            )
            canvas.create_polygon(
                cx - 4, cy + 3,
                cx + 4, cy + 3,
                cx, cy + 10,
                fill=orange, outline=""
            )

        elif mod_type == "Kart":
            # Use the user's actual sketch as the kart preview icon.
            icon_path = os.path.join(ART_DIR, "kart_sketch_icon.png")
            try:
                if not hasattr(self, "_kart_sketch_icon") or self._kart_sketch_icon is None:
                    self._kart_sketch_icon = tk.PhotoImage(file=icon_path)
                canvas.create_image(
                    width * 0.19,
                    height * 0.54,
                    image=self._kart_sketch_icon,
                    anchor="center",
                )
            except Exception:
                # Fallback if the asset cannot be loaded.
                canvas.create_line(
                    cx - 30, cy + 12, cx + 28, cy + 12,
                    fill=col, width=3
                )
                canvas.create_oval(
                    cx - 34, cy + 4, cx - 14, cy + 24,
                    outline=col, width=2
                )
                canvas.create_oval(
                    cx + 14, cy + 4, cx + 34, cy + 24,
                    outline=col, width=2
                )
        elif mod_type == "Wheels":
            # Tire/rim icon with actual spokes and an orange forged hub.
            r = 27
            canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill="#0E1115", outline=col, width=3
            )
            canvas.create_oval(
                cx - 19, cy - 19, cx + 19, cy + 19,
                outline=dim, width=2
            )
            canvas.create_oval(
                cx - 6, cy - 6, cx + 6, cy + 6,
                fill="#111419", outline=orange, width=2
            )
            for dx, dy in (
                (0, -18), (13, -13), (18, 0), (13, 13),
                (0, 18), (-13, 13), (-18, 0), (-13, -13)
            ):
                canvas.create_line(
                    cx, cy, cx + dx, cy + dy,
                    fill="#8B9096", width=2
                )
            canvas.create_oval(
                cx - 2, cy - 2, cx + 2, cy + 2,
                fill=orange, outline=""
            )
            canvas.create_arc(
                cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4,
                start=205, extent=110,
                style="arc", outline="#FFFFFF", width=1
            )

        elif mod_type == "Modpack":
            for dx, dy in ((-21,-13),(-5,-4),(11,5)):
                canvas.create_rectangle(cx+dx-16,cy+dy-11,cx+dx+16,cy+dy+11,outline=col,width=2)
                canvas.create_line(cx+dx-10,cy+dy,cx+dx+8,cy+dy,fill=orange,width=2)

        elif mod_type == "Track":
            # Stylized road circuit inside a map frame, no external assets needed.
            canvas.create_rectangle(
                cx - 31, cy - 24, cx + 31, cy + 25, outline=dim, width=2
            )
            canvas.create_line(
                cx - 18, cy + 14, cx - 20, cy - 12, cx - 3, cy - 18,
                cx + 18, cy - 10, cx + 14, cy + 12, cx - 3, cy + 15,
                cx - 18, cy + 14, fill=col, width=4, smooth=True
            )
            canvas.create_oval(
                cx - 22, cy + 10, cx - 14, cy + 18,
                fill=orange, outline=""
            )
            canvas.create_line(
                cx + 19, cy - 12, cx + 19, cy - 32, fill=orange, width=2
            )
            canvas.create_polygon(
                cx + 20, cy - 32, cx + 35, cy - 25, cx + 20, cy - 18,
                fill=orange, outline=""
            )

        canvas.create_text(
            width - 12,
            12,
            text=mod_type.upper(),
            anchor="ne",
            fill=orange,
            font=("Bahnschrift SemiBold", 8),
        )


    def _install_community_mod(self, mod):
        self._download_public_mod(mod)

    def _close_mod_details(self):
        if hasattr(self, "hub_details_overlay"):
            self.hub_details_overlay.place_forget()

    def _show_mod_details(self, mod):
        if hasattr(self, "hub_details_overlay"):
            try:
                self.hub_details_overlay.destroy()
            except Exception:
                pass

        installed = mod.get("_installed")
        local = self._is_local_community_mod(mod) or bool(installed)
        package = str(mod.get("package_path", "")).strip()
        source_text = "INSTALLED MODULE" if installed else (
            "LOCAL ZIP" if local else "COMMUNITY MOD")

        overlay = tk.Frame(
            self.hub_overlay,
            bg="#090B0E",
            highlightbackground="#343A42",
            highlightthickness=1,
        )
        self.hub_details_overlay = overlay
        overlay.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.58, relheight=0.66)
        overlay.lift()

        header = tk.Frame(overlay, bg="#0D0F13", height=62)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="MOD DETAILS",
            bg="#0D0F13",
            fg="#F0F0EC",
            font=("Bahnschrift SemiBold", 15),
        ).pack(side="left", padx=18, pady=17)

        self._hub_button(
            header, "×  CLOSE", self._close_mod_details
        ).pack(side="right", padx=14, pady=13)

        body = tk.Frame(overlay, bg="#101318")
        body.pack(fill="both", expand=True, padx=20, pady=18)

        title_row = tk.Frame(body, bg="#101318")
        title_row.pack(fill="x")

        tk.Label(
            title_row,
            text=mod_manager.display_mod_name(mod),
            bg="#101318",
            fg="#FFFFFF",
            font=("Bahnschrift SemiBold", 20),
            anchor="w",
        ).pack(side="left")

        tk.Label(
            title_row,
            text=f"v{mod.get('version', '1.0')}",
            bg="#101318",
            fg=COLORS["orange"],
            font=("Bahnschrift SemiBold", 11),
        ).pack(side="right")

        tk.Label(
            body,
            text=f"{source_text}  •  {str(mod.get('type', 'Mod')).upper()}  •  by {mod.get('author', 'Unknown')}",
            bg="#101318",
            fg="#858B93",
            font=("Bahnschrift SemiBold", 9),
            anchor="w",
        ).pack(fill="x", pady=(4, 18))

        tk.Label(
            body,
            text=str(mod.get("description", "")) or "No description provided.",
            bg="#101318",
            fg="#C4C7CB",
            font=("Bahnschrift", 10),
            justify="left",
            anchor="nw",
            wraplength=650,
        ).pack(fill="x", anchor="w", pady=(0, 18))

        info = tk.Frame(
            body,
            bg="#0C0F13",
            highlightbackground="#2D3239",
            highlightthickness=1,
        )
        info.pack(fill="x")

        rows = [
            ("TYPE", str(mod.get("type", "Mod"))),
            ("VERSION", str(mod.get("version", "1.0"))),
            ("AUTHOR", str(mod.get("author", "Unknown"))),
            ("STATUS", installed.get("status", "INSTALLED") if installed
             else "LOCAL ZIP" if local else "ONLINE CATALOG"),
            ("MOD ID", str(mod.get("id", ""))),
            ("WEB ID", str(installed.get("source_id") or
                          mod.get("public_id") or mod.get("id", ""))
             if (installed and installed.get("origin") == "forge_hub")
             or mod.get("source") == "online" else "LOCAL / UNPUBLISHED"),
            ("DOWNLOADS", f"{mod['downloads']:,}" if mod.get("downloads") is not None else "Unreported"),
            ("LIKES", f"{mod['likes']:,}" if mod.get("likes") is not None else "Unreported"),
        ]
        rows.insert(1, ("CLASS / DESIGN", modmeta.summary(mod)))
        if package:
            rows.append(("PACKAGE", package))
        if installed:
            rows.append(("FOLDER", str(installed.get("path", ""))))
            rows.append(("NATIVE INI", "enabled = " +
                         ("true" if installed.get("enabled") else "false")
                         if installed["manageable"] else
                         "MISSING / INVALID"))
            if installed["type"] == "Track":
                rows.append(("TRACK", "Staged only; game registration pending"))

        for label_text, value_text in rows:
            row = tk.Frame(info, bg="#0C0F13")
            row.pack(fill="x", padx=12, pady=5)
            tk.Label(
                row,
                text=label_text,
                bg="#0C0F13",
                fg="#6F757D",
                font=("Bahnschrift SemiBold", 8),
                width=13,
                anchor="w",
            ).pack(side="left")
            tk.Label(
                row,
                text=value_text,
                bg="#0C0F13",
                fg="#D8DADD",
                font=("Bahnschrift", 8),
                anchor="w",
                justify="left",
                wraplength=520,
            ).pack(side="left", fill="x", expand=True)

        footer = tk.Frame(body, bg="#101318")
        footer.pack(fill="x", pady=(16, 0))

        if installed:
            self._hub_button(
                footer,
                ("DISABLE MOD" if installed["enabled"] else "ENABLE MOD")
                if installed["manageable"] else "NEEDS NATIVE INI",
                lambda m=mod: self._toggle_installed_mod(m),
                accent=bool(installed["manageable"] and not installed["enabled"]),
                enabled=bool(installed["manageable"]),
            ).pack(side="left", padx=(0, 7))
        install_text, install_enabled = self._hub_install_state(mod)
        if install_enabled:
            self._hub_button(
                footer, install_text, lambda m=mod: self._install_community_mod(m),
                accent=True,
            ).pack(side="left", padx=(0, 8))

        if (package and os.path.exists(package)) or installed:
            def open_package_location():
                try:
                    target = (installed["path"] if installed else
                              package if os.path.isdir(package)
                              else os.path.dirname(package))
                    if target and os.path.isdir(target):
                        os.startfile(target)
                except Exception:
                    self.hub_status_label.configure(text="Could not open the local mod location.")

            self._hub_button(
                footer, "OPEN LOCATION", open_package_location
            ).pack(side="left")

        self.hub_status_label.configure(
            text=f"Viewing details for {mod.get('title')}."
        )

    def _build_hub_upload_overlay(self):
        self.hub_upload_overlay = tk.Frame(
            self.hub_overlay,
            bg="#090B0E",
            highlightbackground="#343A42",
            highlightthickness=1,
        )

        shell = tk.Frame(
            self.hub_upload_overlay,
            bg="#101318",
            highlightbackground="#3A4048",
            highlightthickness=1,
        )
        self.hub_upload_shell = shell
        shell.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.70, relheight=0.87)

        header = tk.Frame(shell, bg="#0D0F13", height=62)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="ADD LOCAL MOD",
            bg="#0D0F13",
            fg="#F0F0EC",
            font=("Bahnschrift SemiBold", 15),
        ).pack(side="left", padx=18, pady=(13, 0), anchor="n")
        close = self._hub_button(header, "×  CLOSE", self._close_hub_upload)
        close.pack(side="right", padx=14, pady=13)

        note = tk.Label(
            shell,
            text="LOCAL ONLY: adds a package on this PC. Public sharing requires a configured submission page.",
            bg="#2A160C",
            fg="#E5A56F",
            font=("Bahnschrift", 8),
            justify="left",
            anchor="w",
            padx=12,
            pady=8,
        )
        self.hub_upload_note = note
        note.pack(fill="x", padx=18, pady=(9, 7))

        # Pack footer FIRST, so SAVE / SUBMIT cannot be pushed off-screen.
        self.hub_upload_button_bar = tk.Frame(shell, bg="#101318")
        self.hub_upload_button_bar.pack(
            side="bottom", fill="x", padx=14, pady=(4, 9))

        # Grid form remains a normal Frame, but lives in a vertical Canvas.
        # A 4:3 screen can scroll the fields without hiding submit actions.
        form_shell = tk.Frame(shell, bg="#101318")
        form_shell.pack(fill="both", expand=True, padx=(14, 10), pady=(0, 5))
        viewport = tk.Canvas(
            form_shell, bg="#101318", bd=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(
            form_shell, orient="vertical", command=viewport.yview,
            bg="#20252C", troughcolor="#0F1217",
            activebackground=COLORS["orange"], bd=0, width=10)
        scrollbar.pack(side="right", fill="y")
        viewport.pack(side="left", fill="both", expand=True)
        viewport.configure(yscrollcommand=scrollbar.set)
        self.hub_upload_form_canvas = viewport

        form = tk.Frame(viewport, bg="#101318")
        form_window = viewport.create_window((0, 0), window=form, anchor="nw")
        form.grid_columnconfigure(1, weight=1)
        form.bind("<Configure>", lambda e:
                  viewport.configure(scrollregion=viewport.bbox("all")))
        viewport.bind("<Configure>", lambda e:
                      viewport.itemconfigure(form_window, width=e.width))

        self.upload_title_var = tk.StringVar()
        self.upload_author_var = tk.StringVar(value="Player")
        self.upload_type_var = tk.StringVar(value="Character")
        self.upload_meta_var = tk.StringVar(value="Balanced")
        self.upload_version_var = tk.StringVar(value="1.0")
        self.upload_package_var = tk.StringVar()

        def add_field(row, label, variable):
            tk.Label(
                form,
                text=label,
                bg="#101318",
                fg="#858A91",
                font=("Bahnschrift SemiBold", 8),
                anchor="w",
            ).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            entry = tk.Entry(
                form,
                textvariable=variable,
                bg="#15191E",
                fg="#E4E5E1",
                insertbackground=COLORS["orange"],
                relief="flat",
                highlightbackground="#343A42",
                highlightthickness=1,
                font=("Bahnschrift", 9),
            )
            entry.grid(row=row, column=1, sticky="ew", pady=6, ipady=7)
            return entry

        add_field(0, "MOD NAME", self.upload_title_var)
        add_field(1, "AUTHOR", self.upload_author_var)

        tk.Label(
            form,
            text="TYPE",
            bg="#101318",
            fg="#858A91",
            font=("Bahnschrift SemiBold", 8),
        ).grid(row=2, column=0, sticky="w", padx=(0, 12), pady=6)

        type_menu_button = tk.Menubutton(
            form,
            textvariable=self.upload_type_var,
            bg="#15191E",
            fg="#E4E5E1",
            activebackground="#242930",
            activeforeground="#FFFFFF",
            relief="flat",
            highlightbackground="#343A42",
            highlightthickness=1,
            font=("Bahnschrift SemiBold", 9),
            anchor="w",
            padx=8,
            pady=8,
        )
        type_menu = tk.Menu(
            type_menu_button,
            tearoff=False,
            bg="#15191E",
            fg="#E4E5E1",
            activebackground="#5B2405",
            activeforeground="#FFFFFF",
        )
        for value, label in (
            ("Character", "Character"),
            ("Kart", "Kart"),
            ("Wheels", "Wheels"),
            ("Track", "Map / Track"),
            ("Modpack", "Modpack / Bundle"),
        ):
            type_menu.add_command(
                label=label,
                command=lambda v=value: self._set_local_hub_mod_type(v),
            )
        type_menu_button.configure(menu=type_menu)
        type_menu_button.grid(row=2, column=1, sticky="ew", pady=6)

        add_field(3, "VERSION", self.upload_version_var)

        tk.Label(
            form,
            text="PACKAGE",
            bg="#101318",
            fg="#858A91",
            font=("Bahnschrift SemiBold", 8),
        ).grid(row=4, column=0, sticky="w", padx=(0, 12), pady=6)

        package_row = tk.Frame(form, bg="#101318")
        package_row.grid(row=4, column=1, sticky="ew", pady=6)
        package_row.grid_columnconfigure(0, weight=1)
        package_entry = tk.Entry(
            package_row,
            textvariable=self.upload_package_var,
            bg="#15191E",
            fg="#E4E5E1",
            insertbackground=COLORS["orange"],
            relief="flat",
            highlightbackground="#343A42",
            highlightthickness=1,
            font=("Bahnschrift", 9),
        )
        package_entry.grid(row=0, column=0, sticky="ew", ipady=7)
        browse = self._hub_button(package_row, "BROWSE…", self._browse_hub_package)
        browse.grid(row=0, column=1, padx=(8, 0))

        tk.Label(
            form,
            text="DESCRIPTION",
            bg="#101318",
            fg="#858A91",
            font=("Bahnschrift SemiBold", 8),
        ).grid(row=5, column=0, sticky="nw", padx=(0, 12), pady=6)

        self.upload_description = tk.Text(
            form,
            height=5,
            bg="#15191E",
            fg="#E4E5E1",
            insertbackground=COLORS["orange"],
            relief="flat",
            highlightbackground="#343A42",
            highlightthickness=1,
            font=("Bahnschrift", 9),
            wrap="word",
        )
        self.upload_description.grid(row=5, column=1, sticky="nsew", pady=6)

        self.upload_meta_label = tk.Label(
            form, text="STATS CLASS", bg="#101318", fg="#858A91",
            font=("Bahnschrift SemiBold", 8), anchor="w",
        )
        self.upload_meta_label.grid(row=6, column=0, sticky="w", padx=(0, 12), pady=4)
        self.upload_meta_button = tk.Menubutton(
            form, textvariable=self.upload_meta_var,
            bg="#15191E", fg="#E4E5E1", activebackground="#242930",
            activeforeground="#FFFFFF", relief="flat", highlightbackground="#343A42",
            highlightthickness=1, font=("Bahnschrift SemiBold", 9),
            anchor="w", padx=8, pady=6,
        )
        self.upload_meta_menu = tk.Menu(
            self.upload_meta_button, tearoff=False, bg="#15191E", fg="#E4E5E1",
            activebackground="#5B2405", activeforeground="#FFFFFF",
        )
        self.upload_meta_button.configure(menu=self.upload_meta_menu)
        self.upload_meta_button.grid(row=6, column=1, sticky="ew", pady=4)

        # A single three-choice kart selector replaces the confusing
        # drive/wheels combination. Legacy stored values stay compatible.
        self._sync_local_hub_mod_meta()

        buttons = self.hub_upload_button_bar
        self.upload_status_label = tk.Label(
            buttons,
            text="",
            bg="#101318",
            fg="#C56E35",
            font=("Bahnschrift", 8),
        )
        self.upload_status_label.pack(side="left")
        self._hub_button(buttons, "SUBMIT PUBLIC", self._publish_local_mod).pack(side="left", padx=(8, 0))
        self._hub_button(
            buttons,
            "SAVE LOCAL MOD",
            self._submit_hub_upload,
            accent=True,
        ).pack(side="right")

        def bind_scroll(widget):
            if not isinstance(widget, tk.Text):
                widget.bind("<MouseWheel>", self._scroll_hub_upload)
            for child in widget.winfo_children():
                bind_scroll(child)
        viewport.bind("<MouseWheel>", self._scroll_hub_upload)
        bind_scroll(form)

    def _scroll_hub_upload(self, event):
        amount = int(-event.delta / 120)
        if not amount:
            amount = -1 if event.delta > 0 else 1
        self.hub_upload_form_canvas.yview_scroll(amount, "units")
        return "break"

    def _set_local_hub_mod_type(self, category):
        self.upload_type_var.set(category)
        self._sync_local_hub_mod_meta()

    def _sync_local_hub_mod_meta(self):
        category = self.upload_type_var.get()
        options = {
            "Character": ("STATS CLASS", modmeta.RACER_CLASSES),
            "Track": ("MAP TYPE", modmeta.MAP_KINDS),
            "Kart": ("KART TYPE", modmeta.KART_TYPE_LABELS),
        }.get(category)
        if options is None:
            self.upload_meta_button.grid_remove()
            self.upload_meta_label.grid_remove()
        else:
            label, choices = options
            self.upload_meta_label.configure(text=label)
            self.upload_meta_label.grid()
            self.upload_meta_button.grid()
            self.upload_meta_menu.delete(0, "end")
            for choice in choices:
                self.upload_meta_menu.add_command(
                    label=choice, command=lambda c=choice: self._choose_local_hub_meta(c))
            if self.upload_meta_var.get() not in choices:
                self.upload_meta_var.set(choices[0])

    def _choose_local_hub_meta(self, value):
        self.upload_meta_var.set(value)
        self._sync_local_hub_mod_meta()

    def _open_hub_upload(self):
        self.upload_status_label.configure(text="")
        self.upload_title_var.set("")
        self.upload_type_var.set("Character")
        self.upload_meta_var.set("Balanced")
        self._sync_local_hub_mod_meta()
        self.upload_version_var.set("1.0")
        self.upload_package_var.set("")
        self.upload_description.delete("1.0", "end")
        self.hub_upload_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.hub_upload_overlay.lift()

    def _close_hub_upload(self):
        self.hub_upload_overlay.place_forget()

    def _browse_hub_package(self):
        path = filedialog.askopenfilename(
            title="Select Crash Forge mod package",
            filetypes=(
                ("Crash Forge mod ZIP", "*.zip"),
                ("All files", "*.*"),
            ),
        )
        if path:
            self.upload_package_var.set(path)

    def _submit_hub_upload(self):
        title = self.upload_title_var.get().strip()
        author = self.upload_author_var.get().strip()
        mod_type = self.upload_type_var.get().strip()
        version = self.upload_version_var.get().strip() or "1.0"
        package = self.upload_package_var.get().strip()
        description = self.upload_description.get("1.0", "end").strip()

        if not title:
            self.upload_status_label.configure(text="A mod name is required.")
            return
        if not author:
            self.upload_status_label.configure(text="An author name is required.")
            return
        if mod_type not in modmeta.MOD_TYPES:
            self.upload_status_label.configure(text="Choose a valid mod type.")
            return
        if not package or not os.path.isfile(package) or not package.lower().endswith(".zip"):
            self.upload_status_label.configure(text="Choose a local .zip file.")
            return
        try:
            identity = mod_manager.inspect_local_zip(package, mod_type)
            if os.path.getsize(package) > services.MAX_MOD_BYTES:
                raise mod_manager.ModManagerError("ZIP is too large")
            import hashlib
            digest = hashlib.sha256()
            with open(package, "rb") as stream:
                for chunk in iter(lambda: stream.read(262144), b""):
                    digest.update(chunk)
        except (mod_manager.ModManagerError, OSError) as error:
            self.upload_status_label.configure(text="Invalid mod ZIP: " + str(error)[:150])
            return

        raw_metadata = {}
        if mod_type == "Character":
            raw_metadata["racer_class"] = self.upload_meta_var.get()
        elif mod_type == "Track":
            raw_metadata["map_kind"] = self.upload_meta_var.get()
        elif mod_type == "Kart":
            try:
                raw_metadata.update(modmeta.kart_type_fields(self.upload_meta_var.get()))
            except modmeta.ModMetadataError as exc:
                self.upload_status_label.configure(text=str(exc))
                return
        try:
            metadata = modmeta.normalize(mod_type, raw_metadata, strict=True)
        except modmeta.ModMetadataError as exc:
            self.upload_status_label.configure(text=str(exc))
            return

        catalog = self._load_community_catalog()
        now = datetime.now()
        mod = {
            "id": identity["id"],
            "title": title,
            "author": author,
            "type": mod_type,
            "version": version,
            "downloads": None,
            "likes": None,
            "created_at": now.isoformat(timespec="seconds"),
            "description": description or f"{mod_type} mod for Crash Forge: Racing.",
            "package_path": package,
            "sha256": digest.hexdigest(),
            "source": "local",
        }
        mod.update(metadata)
        # One stable ID per native category, not an endlessly duplicated
        # timestamp ID every time the same local ZIP is added.
        catalog[:] = [
            old for old in catalog
            if (old.get("type"), old.get("id")) != (mod_type, mod["id"])
        ]
        catalog.append(mod)

        if not self._save_community_catalog():
            self.upload_status_label.configure(text="Could not save the local catalog.")
            return

        self._close_hub_upload()

        # Put the newly uploaded mod directly into the search results so the
        # uploader can immediately confirm that it is visible in Forge Hub.
        self.hub_type_var.set("All")
        self.hub_sort_var.set("Newest")
        self.hub_search_var.set(title)
        self._update_hub_filter_visuals()
        self._run_hub_search()

        try:
            self.hub_search_entry.icursor("end")
            self.hub_search_entry.focus_set()
        except Exception:
            pass

        self.hub_status_label.configure(
            text=f"{title} saved locally; this does not publish it online."
        )

    def destroy(self):
        """Apply a verified EXE update only after this window closes.

        Portable users are updated in place; developer/.bat users get a
        SEPARATE portable EXE. In both cases the updater relaunches the new
        graphical EXE without invoking cmd.exe, a BAT or the Python console.
        """
        if not getattr(self, "_launcher_shutdown_started", False):
            self._launcher_shutdown_started = True
            if (getattr(self, "launcher_auto_update", False)
                    and getattr(self, "launcher_update_ready", None)):
                try:
                    portable = launcher_updates.is_portable_build()
                    target = (BASE_DIR if portable else
                              launcher_updates.portable_target_for_source(BASE_DIR))
                    launcher_updates.launch_update_after_exit(
                        target, os.getpid(),
                        source_migration=not portable,
                        source_dir=None if portable else BASE_DIR)
                except Exception as exc:
                    try:
                        state = launcher_updates.state_root()
                        state.mkdir(parents=True, exist_ok=True)
                        (state / "updater-result.txt").write_text(
                            "Updater could not start: " + str(exc)[:330],
                            encoding="utf-8")
                    except OSError:
                        pass
        return super().destroy()

    def _not_ready(self):
        self.status_label.configure(text="Button action not connected yet.")

if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        # Portable Windows bundle smoke test. Never creates a window,
        # starts the game, accesses GitHub or changes user settings.
        required = [
            os.path.join(BASE_DIR, "assets", "Fondo.png"),
            os.path.join(BASE_DIR, "assets", "icons", "cfr_icon.png"),
            os.path.join(BASE_DIR, "launcher_version.txt"),
        ]
        if getattr(sys, "frozen", False):
            required.append(os.path.join(BASE_DIR, launcher_updates.UPDATER_EXE))
        invalid = any(not os.path.isfile(item) for item in required)
        raise SystemExit(1 if invalid else 0)
    if sys.argv[1:] == ["--tk-self-test"]:
        # Actually initialize and dispose Tcl/Tk; --self-test alone only
        # checked file presence and could miss broken init.tcl on another PC.
        # No news feeds, account calls, update downloads or user settings.
        root = None
        try:
            root = tk.Tk()
            root.withdraw()
            root.update_idletasks()
            actual = str(root.tk.call("info", "library"))
            expected = os.environ.get("TCL_LIBRARY")
            if expected and os.path.normcase(os.path.normpath(actual)) != (
                    os.path.normcase(os.path.normpath(expected))):
                raise RuntimeError("Tk selected an unexpected Tcl directory")
        finally:
            if root is not None:
                root.destroy()
        raise SystemExit(0)
    # Screenshot preview mode never polls remote feeds, stages downloads, or
    # self-updates.  It is a separate test instance; never mutate the user's
    # existing installed launcher.
    preview_mode = sys.argv[1:] in (
        ["--preview-new-version"],
        ["--preview-mod-install"],
        ["--preview-dialogs"],
    )
    if preview_mode:
        os.environ["CFR_SCREENSHOT_PREVIEW"] = "1"
    app = Launcher()
    if preview_mode:
        app.launcher_auto_update = False
    if sys.argv[1:] == ["--preview-new-version"]:
        app.after(700, lambda: preview_newer_version(
            app, icon_path=os.path.join(
                BASE_DIR, "assets", "icons", "cfr_icon.png")))
    elif sys.argv[1:] in (["--preview-mod-install"], ["--preview-dialogs"]):
        def _preview_install():
            follow_up = None
            if sys.argv[1:] == ["--preview-dialogs"]:
                follow_up = lambda: preview_newer_version(
                    app, icon_path=os.path.join(
                        BASE_DIR, "assets", "icons", "cfr_icon.png"))
            ask_mod_install(
                app, {
                    "title": "Team Bandicoot Kart (CNK)",
                    "author": "Carisa_Demon",
                    "id": "forge-2634caf465b548e182d728c4339d378c",
                }, local=False, preview=True,
                icon_path=os.path.join(
                    BASE_DIR, "assets", "icons", "cfr_icon.png"),
                on_close=follow_up)
        app.after(700, _preview_install)
    app.mainloop()
