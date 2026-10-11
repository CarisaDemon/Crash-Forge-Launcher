"""Crash Forge MIDI/CSEQ Tool - early usable GUI.

Current scope:
- inspect/validate MIDI,
- browse the retail global catalog,
- map each melodic channel and used drum note,
- build a structurally valid CSEQ/package to an arbitrary output folder.

It never installs files into the live game automatically.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import threading
import wave
import tkinter as tk
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from forge_editor_config import find_game_installation
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

try:
    import winsound
except ImportError:
    winsound = None

from audio_preview import play_sample_preview, stop_preview
from cseq_encoder import (
    CseqEncodeError,
    MelodicInstrumentZone,
    build_project_with_zones,
    build_simple_retail_project,
    find_loop_start_tick,
)
from gm_names import gm_program_name
from instrument_map import RetailInstrument, RetailDrum, load_retail_catalog
from midi_reader import MidiFile, read_midi, summarize
from package_builder import build_music_package
from track_discovery import (
    discover_custom_tracks, valid_game_root, install_cseq_on_custom_track,
)
from sf2_import import (
    Sf2Error,
    export_zone_temp,
    load_sf2 as load_soundfont,
    make_cseq_drum,
    make_cseq_instrument,
    zone_for_note,
)
from song_preview import (
    ctr_note_pitch,
    pause_song_preview,
    play_rendered_preview,
    play_song_preview,
    song_preview_state,
    stop_song_preview,
)
from validator import validate_midi


# Crash Forge Launcher visual language.
BG = "#08090B"
PANEL = "#101217"
PANEL_2 = "#15181E"
FIELD = "#0C0E11"
TEXT = "#F2F2EF"
MUTED = "#8D929A"
ACCENT = "#FF6A00"
ACCENT_HOVER = "#FF8A19"
AMBER = "#FFB000"
SUCCESS = "#56C47A"
WARNING = "#FFB000"
ERROR = "#FF6B78"
BORDER = "#2A2F36"
LINE_HOT = "#6A2A08"
APP_VERSION = "1.0.15"

# Use assets shipped inside our own EXE, never another installation's files.
_BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
_ASSET_CANDIDATES = (
    _BUNDLE_DIR / "forge_assets",
    Path(__file__).resolve().parents[2] / "assets",
)
FORGE_ASSETS = next((p for p in _ASSET_CANDIDATES
                     if (p / "Fondo.png").is_file()), _ASSET_CANDIDATES[0])
FORGE_BACKGROUND = FORGE_ASSETS / "Fondo.png"
FORGE_ICON_PNG = FORGE_ASSETS / "icons" / "cfr_icon.png"


LEVEL_TARGETS = {
    0: "DINGO_CANYON",
    1: "DRAGON_MINES",
    2: "BLIZZARD_BLUFF",
    3: "CRASH_COVE",
    4: "TIGER_TEMPLE",
    5: "PAPU_PYRAMID",
    6: "ROO_TUBES",
    7: "HOT_AIR_SKYWAY",
    8: "SEWER_SPEEDWAY",
    9: "MYSTERY_CAVES",
    10: "CORTEX_CASTLE",
    11: "N_GIN_LABS",
    12: "POLAR_PASS",
    13: "OXIDE_STATION",
    14: "COCO_PARK",
    15: "TINY_ARENA",
    16: "SLIDE_COLISEUM",
    17: "TURBO_TRACK",
    18: "NITRO_COURT",
    19: "RAMPAGE_RUINS",
    20: "PARKING_LOT",
    21: "SKULL_ROCK",
    22: "THE_NORTH_BOWL",
    23: "ROCKY_ROAD",
    24: "LAB_BASEMENT",
    25: "GEM_STONE_VALLEY",
    26: "N_SANITY_BEACH",
    27: "THE_LOST_RUINS",
    28: "GLACIER_PARK",
    29: "CITADEL_CITY",
    30: "INTRO_RACE_TODAY",
    31: "INTRO_COCO",
    32: "INTRO_TINY",
    33: "INTRO_POLAR",
    34: "INTRO_DINGODILE",
    35: "INTRO_CORTEX",
    36: "INTRO_SPACE",
    37: "INTRO_CRASH",
    38: "INTRO_OXIDE",
    39: "MAIN_MENU_LEVEL",
    40: "ADVENTURE_CHARACTER_SELECT",
    41: "NAUGHTY_DOG_CRATE",
    42: "OXIDE_ENDING",
    43: "OXIDE_TRUE_ENDING",
    44: "CREDITS_LEVEL",
    45: "CREDITS_CRASH",
    46: "CREDITS_TINY",
    47: "CREDITS_COCO",
    48: "CREDITS_N_GIN",
    49: "CREDITS_DINGO",
    50: "CREDITS_POLAR",
    51: "CREDITS_PURA",
    52: "CREDITS_PINSTRIPE",
    53: "CREDITS_PAPU",
    54: "CREDITS_ROO",
    55: "CREDITS_JOE",
    56: "CREDITS_TROPY",
    57: "CREDITS_PENTA",
    58: "CREDITS_FAKE_CRASH",
    59: "CREDITS_OXIDE",
    60: "CREDITS_AMI",
    61: "CREDITS_ISABELLA",
    62: "CREDITS_LIZ",
    63: "CREDITS_MEGUMI",
    64: "SCRAPBOOK",
    # Virtual native-only target. Hangout runs on N. Sanity Beach geometry,
    # but uses this separate music slot so it never steals level_26's theme.
    99: "HANGOUT_HUB",
}


class App(tk.Tk):
    def __init__(self) -> None:
        if os.name == "nt":
            try:
                import ctypes
                f = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
                f.argtypes = [ctypes.c_wchar_p]
                f.restype = ctypes.c_long
                f("CrashForge.Racing.CSEQToolkit")
            except (OSError, AttributeError):
                pass
        super().__init__()
        self.title(f"Crash Forge CSEQ Toolkit  v{APP_VERSION}")
        self.geometry("1200x800")
        self.minsize(920, 620)
        self.configure(bg=BG)
        self._restore_geometry: str | None = None
        self._maximized = False
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._forge_background_resize_job = None
        self._forge_background_size = (0, 0)
        self.overrideredirect(True)
        self._setup_style()
        self._install_forge_background()
        self._build_window_chrome()
        self.bind("<Configure>", self._on_root_configure, add="+")
        self.after(40, self._apply_windows_app_style)
        self.after(70, self._refresh_forge_background)

        icon_path = Path(__file__).parent / "assets" / "cfr_icon.ico"
        if icon_path.is_file():
            try:
                self.iconbitmap(str(icon_path))
            except tk.TclError:
                pass
        self._taskbar_photo = None
        if FORGE_ICON_PNG.is_file() and Image is not None and ImageTk is not None:
            try:
                self._taskbar_photo = ImageTk.PhotoImage(
                    Image.open(FORGE_ICON_PNG).convert("RGBA")
                )
                self.iconphoto(True, self._taskbar_photo)
            except (OSError, tk.TclError):
                pass

        self.current_path: Path | None = None
        self.current_midi: MidiFile | None = None
        self.current_report: dict | None = None
        self.channel_vars: dict[int, tk.StringVar] = {}
        self.channel_transpose_vars: dict[int, tk.IntVar] = {}
        self.drum_vars: dict[int, tk.StringVar] = {}
        self.target_var = tk.StringVar(value="No level override")
        self.game_root_var = tk.StringVar(
            value=str(find_game_installation(source_file=__file__) or "")
        )
        self.custom_track_targets = {}
        self.race_intro_var = tk.BooleanVar(value=False)
        self.race_intro_status_var = tk.StringVar(
            value="Move LOOP START to choose where the repeating section begins"
        )
        self.loop_start_var = tk.DoubleVar(value=0.0)
        self.loop_start_seconds_var = tk.StringVar(value="0.000000")
        self.loop_start_text_var = tk.StringVar(value="Loop start: 0:00.000 / 0:00.000")
        self.preview_position_var = tk.DoubleVar(value=0.0)
        self.preview_position_text_var = tk.StringVar(value="Playback: 0:00.000 / 0:00.000")
        self.preview_loop_var = tk.BooleanVar(value=False)
        self._preview_audio_path: Path | None = None
        self._preview_total_seconds = 0.0
        self._preview_poll_job = None
        self._preview_user_seeking = False
        self._preview_seek_was_playing = False
        self.soundfont = None
        self.sf2_path: Path | None = None
        self.sf2_preset_var = tk.StringVar(value="No SoundFont loaded")
        self.sf2_status_var = tk.StringVar(value="SF2: not loaded")
        self.sf2_presets_by_value: dict[str, object] = {}
        self._last_custom_samples: list[Path] = []

        try:
            self.catalog = load_retail_catalog()
        except Exception as exc:
            self.catalog = None
            messagebox.showwarning(
                "Retail catalog unavailable",
                f"The GUI can inspect MIDI, but building is disabled until the catalog is available.\n\n{exc}",
            )

        hero_border = tk.Frame(self, bg=BORDER)
        hero_border.pack(fill="x", padx=20, pady=(14, 12))
        hero = tk.Frame(hero_border, bg="#0F1216")
        hero.pack(fill="x", padx=1, pady=1)
        tk.Frame(hero, bg=ACCENT, width=4).pack(side="left", fill="y")

        hero_copy = tk.Frame(hero, bg="#0F1216")
        hero_copy.pack(side="left", fill="both", expand=True, padx=16, pady=12)
        tk.Label(
            hero_copy,
            text="CSEQ / MIDI FORGE",
            bg="#0F1216",
            fg="#F4F3EF",
            font=("Bahnschrift SemiBold", 19),
        ).pack(anchor="w")
        tk.Label(
            hero_copy,
            text="BUILD NATIVE CTR MUSIC FROM MIDI, RETAIL HOWL SOUNDS AND SF2 PRESETS",
            bg="#0F1216",
            fg=MUTED,
            font=("Bahnschrift", 9),
        ).pack(anchor="w", pady=(3, 0))

        tk.Label(
            hero,
            text="MUSIC EDITOR",
            bg="#0F1216",
            fg=ACCENT,
            font=("Bahnschrift SemiBold", 9),
            padx=16,
        ).pack(side="right", anchor="n", pady=17)

        controls_border, controls = self._card(self, padding=12)
        controls_border.pack(fill="x", padx=20, pady=(0, 12))

        top = ttk.Frame(controls, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Button(top, text="OPEN MIDI", command=self.open_midi, style="Accent.TButton").pack(side="left")
        ttk.Button(top, text="LOAD SF2", command=self.load_sf2, style="Forge.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Export Report", command=self.export_report).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Stop Audio", command=stop_preview, style="Ghost.TButton").pack(side="left", padx=(8, 0))
        self.file_label = ttk.Label(top, text="No MIDI loaded", style="Muted.TLabel")
        self.file_label.pack(side="left", padx=14)

        ttk.Separator(controls).pack(fill="x", pady=10)

        preview_row = ttk.Frame(controls, style="Panel.TFrame")
        preview_row.pack(fill="x")
        ttk.Label(preview_row, text="RETAIL SOUND AUDITION", style="Section.TLabel").pack(side="left")
        self.global_preview_var = tk.StringVar(value="")
        preview_values: list[str] = []
        if self.catalog is not None:
            preview_values += [
                f"INST {x.global_id:03d} | {self.catalog.instrument_display(x.global_id)} | "
                f"GM {x.midi_program if x.midi_program >= 0 else '-'} | "
                f"transpose {x.midi_pitch:+d} | SPU {x.spu_index:03d}"
                for x in self.catalog.instruments
            ]
            preview_values += [
                f"DRUM {x.global_id:03d} | {self.catalog.drum_display(x.global_id)} | "
                f"GM key {x.midi_key if x.midi_key >= 0 else '-'} | SPU {x.spu_index:03d}"
                for x in self.catalog.drums
            ]
        ttk.Combobox(
            preview_row,
            textvariable=self.global_preview_var,
            values=preview_values,
            state="readonly",
            width=72,
        ).pack(side="left", fill="x", expand=True, padx=(12, 8))
        ttk.Button(
            preview_row,
            text="Audition",
            command=self._preview_global_catalog_value,
            style="Accent.TButton",
        ).pack(side="left")

        # Keep the game installation visible from every tab, not buried only
        # inside Build CSEQ. This is shared with Launcher Settings.
        self.game_bar = ttk.Frame(self, style="Panel.TFrame", padding=(20, 6, 20, 9))
        self.game_bar.pack(fill="x")
        ttk.Label(self.game_bar, text="GAME INSTALLATION",
                  style="Section.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(self.game_bar, textvariable=self.game_root_var,
                  style="Muted.TLabel", width=70).pack(side="left", fill="x", expand=True)
        ttk.Button(self.game_bar, text="BROWSE GAME",
                   command=self._browse_custom_tracks_game).pack(side="right")
        ttk.Button(self.game_bar, text="REFRESH MODS",
                   command=self._refresh_custom_tracks).pack(side="right", padx=(0, 6))

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        self.summary_text = self._text_tab("MIDI")
        self.validation_text = self._text_tab("Validation")
        self.build_tab = self._create_build_tab()
        self.sf2_tab = self._create_sf2_tab()
        self.catalog_text = self._text_tab("Retail Instruments")

        ttk.Label(
            self,
            text=(
                "Audition plays one raw retail sample; Preview Song renders the MIDI with your current assignments. "
                "Live CSEQ packages are loaded from assets/mods/music; Hangout uses the dedicated level_99 target."
            ),
            style="Subtitle.TLabel",
            padding=(20, 0, 20, 12),
        ).pack(fill="x")

        self.load_catalog_text()

    def _install_forge_background(self) -> None:
        self._forge_background_photo = None
        self._forge_background_label = None
        self._forge_background_source = None

        if Image is None or ImageTk is None or not FORGE_BACKGROUND.is_file():
            return

        try:
            self._forge_background_source = Image.open(FORGE_BACKGROUND).convert("RGB")
            initial = self._forge_background_source.resize(
                (1200, 800),
                Image.Resampling.LANCZOS,
            )
            self._forge_background_photo = ImageTk.PhotoImage(initial)
            self._forge_background_size = (1200, 800)
            self._forge_background_label = tk.Label(
                self,
                image=self._forge_background_photo,
                bg=BG,
                bd=0,
                highlightthickness=0,
            )
            self._forge_background_label.place(
                x=0, y=0, relwidth=1, relheight=1
            )
            self._forge_background_label.lower()
        except Exception:
            self._forge_background_photo = None
            self._forge_background_label = None
            self._forge_background_source = None

    def _on_root_configure(self, event) -> None:
        if event.widget is not self:
            return

        if self._forge_background_resize_job is not None:
            try:
                self.after_cancel(self._forge_background_resize_job)
            except Exception:
                pass

        self._forge_background_resize_job = self.after(
            55, self._refresh_forge_background
        )

    def _refresh_forge_background(self) -> None:
        self._forge_background_resize_job = None

        if (
            self._forge_background_source is None
            or ImageTk is None
            or self._forge_background_label is None
        ):
            return

        try:
            width = max(1, int(self.winfo_width()))
            height = max(1, int(self.winfo_height()))
        except Exception:
            return

        target = (width, height)
        if target == self._forge_background_size:
            return

        try:
            resized = self._forge_background_source.resize(
                target,
                Image.Resampling.LANCZOS,
            )
            self._forge_background_photo = ImageTk.PhotoImage(resized)
            self._forge_background_label.configure(
                image=self._forge_background_photo,
                bg=BG,
            )
            self._forge_background_size = target
            self._forge_background_label.place(
                x=0, y=0, relwidth=1, relheight=1
            )
            self._forge_background_label.lower()
        except Exception:
            pass

    def _build_window_chrome(self) -> None:
        bar = tk.Frame(self, bg="#090B0E", height=44)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        tk.Frame(bar, bg=ACCENT, width=3).pack(side="left", fill="y")

        logo_box = tk.Frame(bar, bg="#090B0E", width=44)
        logo_box.pack(side="left", fill="y")
        logo_box.pack_propagate(False)
        self._chrome_icon_photo = None
        if Image is not None and ImageTk is not None and FORGE_ICON_PNG.is_file():
            try:
                logo = Image.open(FORGE_ICON_PNG).convert("RGBA")
                logo.thumbnail((25, 25), Image.Resampling.LANCZOS)
                self._chrome_icon_photo = ImageTk.PhotoImage(logo)
                tk.Label(
                    logo_box,
                    image=self._chrome_icon_photo,
                    bg="#090B0E",
                    bd=0,
                ).pack(expand=True)
            except Exception:
                pass

        title = tk.Label(
            bar,
            text="CRASH FORGE  //  CSEQ TOOLKIT",
            bg="#090B0E",
            fg="#F4F3EF",
            font=("Bahnschrift SemiBold", 11),
            padx=4,
        )
        title.pack(side="left", fill="y")

        version = tk.Label(
            bar,
            text=f"TOOLKIT  v{APP_VERSION}",
            bg="#090B0E",
            fg=ACCENT,
            font=("Bahnschrift SemiBold", 9),
            padx=12,
        )
        version.pack(side="right", fill="y")

        def make_control(text: str, command, danger: bool = False) -> tk.Button:
            btn = tk.Button(
                bar,
                text=text,
                command=command,
                width=4,
                bg="#090B0E",
                fg="#E2E3E4",
                activebackground=("#B73529" if danger else "#20242A"),
                activeforeground="#FFFFFF",
                bd=0,
                relief="flat",
                highlightthickness=0,
                font=("Segoe UI", 11),
                cursor="hand2",
                takefocus=False,
            )
            btn.pack(side="right", fill="y")
            base = "#090B0E"
            hover = "#B73529" if danger else "#20242A"
            btn.bind("<Enter>", lambda _e, b=btn, c=hover: b.configure(bg=c))
            btn.bind("<Leave>", lambda _e, b=btn, c=base: b.configure(bg=c))
            return btn

        make_control("X", self.destroy, danger=True)
        make_control("□", self._toggle_maximize)
        make_control("—", self._minimize_window)

        for widget in (bar, title, logo_box):
            widget.bind("<ButtonPress-1>", self._begin_window_drag)
            widget.bind("<B1-Motion>", self._drag_window)
            widget.bind("<Double-Button-1>", lambda _e: self._toggle_maximize())

        self._chrome_bar = bar

    def _begin_window_drag(self, event) -> None:
        if self._maximized:
            return
        self._drag_offset_x = event.x_root - self.winfo_x()
        self._drag_offset_y = event.y_root - self.winfo_y()

    def _drag_window(self, event) -> None:
        if self._maximized:
            return
        x = event.x_root - self._drag_offset_x
        y = event.y_root - self._drag_offset_y
        self.geometry(f"+{x}+{y}")

    def _current_monitor_workarea(self) -> tuple[int, int, int, int] | None:
        """Return the work area of the monitor containing this window."""
        try:
            import ctypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", ctypes.c_ulong),
                ]

            hwnd = self._native_hwnd()
            if not hwnd:
                return None

            user32 = ctypes.windll.user32
            MONITOR_DEFAULTTONEAREST = 0x00000002
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            if not monitor:
                return None

            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)

            if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return None

            rect = info.rcWork
            return (
                int(rect.left),
                int(rect.top),
                int(rect.right),
                int(rect.bottom),
            )
        except Exception:
            return None

    def _toggle_maximize(self) -> None:
        if self._maximized:
            if self._restore_geometry:
                self.geometry(self._restore_geometry)
            self._maximized = False
            self.after(35, self._refresh_forge_background)
            self.after(45, self._apply_windows_app_style)
            return

        self.update_idletasks()
        self._restore_geometry = self.geometry()

        work = self._current_monitor_workarea()
        if work is not None:
            left, top, right, bottom = work
            width = max(1, right - left)
            height = max(1, bottom - top)
            self.geometry(f"{width}x{height}+{left}+{top}")
        else:
            # Fallback only if the monitor API is unavailable.
            self.geometry(
                f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0"
            )

        self._maximized = True
        self.after(35, self._refresh_forge_background)
        self.after(45, self._apply_windows_app_style)

    def _native_hwnd(self) -> int:
        try:
            import ctypes

            hwnd = int(self.winfo_id())
            root = int(ctypes.windll.user32.GetAncestor(hwnd, 2))
            return root or hwnd
        except Exception:
            return 0

    def _apply_windows_app_style(self) -> None:
        """Keep the borderless Forge window visible in taskbar / Alt+Tab."""
        try:
            import ctypes

            hwnd = self._native_hwnd()
            if not hwnd:
                self.after(120, self._apply_windows_app_style)
                return

            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020

            ex_style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
            ex_style = (ex_style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOSIZE
                | SWP_NOMOVE
                | SWP_NOZORDER
                | SWP_NOACTIVATE
                | SWP_FRAMECHANGED,
            )
        except Exception:
            pass

    def _minimize_window(self) -> None:
        # Tk iconify() cannot reliably minimize an overrideredirect window and
        # toggling overrideredirect causes Windows to recreate it as a
        # WS_EX_TOOLWINDOW (no taskbar button). Minimize the native HWND
        # directly instead, preserving the Forge borderless chrome.
        try:
            import ctypes

            hwnd = self._native_hwnd()
            if hwnd:
                self._apply_windows_app_style()
                ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
                return
        except Exception:
            pass

        # Safe fallback for non-Windows environments.
        try:
            self.iconify()
        except tk.TclError:
            pass

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Bahnschrift", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel2.TFrame", background=PANEL_2)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Bahnschrift", 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Bahnschrift SemiBold", 22))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Bahnschrift", 10))
        style.configure("Version.TLabel", background=BG, foreground=ACCENT, font=("Bahnschrift SemiBold", 10))
        style.configure("Section.TLabel", background=PANEL, foreground=ACCENT, font=("Bahnschrift SemiBold", 11))
        style.configure(
            "TEntry",
            fieldbackground=FIELD,
            foreground=TEXT,
            bordercolor=BORDER,
            insertcolor=TEXT,
            padding=7,
        )
        style.configure(
            "TCombobox",
            fieldbackground=FIELD,
            background=FIELD,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            padding=6,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD)],
            foreground=[("readonly", TEXT)],
        )
        style.configure(
            "TButton",
            background=PANEL_2,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            relief="flat",
            font=("Bahnschrift SemiBold", 9),
            padding=(12, 8),
        )
        style.map(
            "TButton",
            background=[("active", "#1F242B"), ("pressed", "#15181E")],
            bordercolor=[("active", ACCENT), ("pressed", ACCENT)],
            foreground=[("active", "#FFFFFF")],
        )
        style.configure(
            "Accent.TButton",
            background="#371707",
            foreground="#F4F3EF",
            bordercolor=ACCENT,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            relief="flat",
            font=("Bahnschrift SemiBold", 10),
            padding=(16, 9),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#522007"), ("pressed", "#2B1206")],
            bordercolor=[("active", ACCENT_HOVER)],
            foreground=[("active", "#FFFFFF")],
        )
        style.configure(
            "Forge.TButton",
            background="#15181D",
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            relief="flat",
            font=("Bahnschrift SemiBold", 10),
            padding=(14, 8),
        )
        style.map(
            "Forge.TButton",
            background=[("active", "#1F242B"), ("pressed", "#111419")],
            foreground=[("active", "#FFFFFF")],
            bordercolor=[("active", ACCENT), ("pressed", ACCENT_HOVER)],
        )
        style.configure(
            "Ghost.TButton",
            background=PANEL,
            foreground=MUTED,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            relief="flat",
        )
        style.map(
            "Ghost.TButton",
            background=[("active", "#171B20")],
            foreground=[("active", TEXT)],
            bordercolor=[("active", "#555D66")],
        )
        style.configure(
            "TCheckbutton",
            background=PANEL,
            foreground=TEXT,
            indicatorcolor=FIELD,
            bordercolor=BORDER,
            font=("Bahnschrift", 10),
        )
        style.map(
            "TCheckbutton",
            indicatorcolor=[("selected", ACCENT)],
            foreground=[("active", TEXT)],
            background=[("active", PANEL)],
        )
        style.configure("TSeparator", background=BORDER)
        style.configure(
            "TScale",
            background=PANEL,
            troughcolor="#1A1E24",
            bordercolor=BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            sliderrelief="flat",
        )
        style.map(
            "TScale",
            background=[("active", ACCENT_HOVER)],
            troughcolor=[("disabled", "#111419")],
        )
        style.configure(
            "Vertical.TScrollbar",
            background="#20252C",
            troughcolor=FIELD,
            bordercolor=BORDER,
            arrowcolor=MUTED,
            relief="flat",
        )
        style.configure(
            "Horizontal.TScrollbar",
            background="#20252C",
            troughcolor=FIELD,
            bordercolor=BORDER,
            arrowcolor=MUTED,
            relief="flat",
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#343A43")],
            arrowcolor=[("active", TEXT)],
        )
        style.map(
            "Horizontal.TScrollbar",
            background=[("active", "#343A43")],
            arrowcolor=[("active", TEXT)],
        )
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=PANEL_2,
            foreground=MUTED,
            padding=(14, 8),
            bordercolor=BORDER,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL)],
            foreground=[("selected", ACCENT)],
        )

    def _card(self, parent: tk.Misc, padding: int = 12) -> tuple[tk.Frame, ttk.Frame]:
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        inner = ttk.Frame(outer, style="Panel.TFrame", padding=padding)
        inner.pack(fill="both", expand=True)
        return outer, inner

    def _text_tab(self, title: str) -> tk.Text:
        frame = ttk.Frame(self.tabs, style="Panel.TFrame", padding=1)
        self.tabs.add(frame, text=title)
        text = tk.Text(
            frame,
            wrap="none",
            font=("Consolas", 10),
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#34455e",
            selectforeground=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=10,
        )
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        scroll_x = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return text

    def _create_sf2_tab(self) -> ttk.Frame:
        outer = ttk.Frame(self.tabs, style="Panel.TFrame", padding=16)
        self.tabs.add(outer, text="SoundFont 2")

        hero = tk.Frame(
            outer,
            bg="#0F1115",
            highlightbackground=LINE_HOT,
            highlightthickness=1,
        )
        hero.pack(fill="x", pady=(0, 12))
        tk.Frame(hero, bg=ACCENT, width=4).pack(side="left", fill="y")
        hero_copy = tk.Frame(hero, bg="#0F1115")
        hero_copy.pack(side="left", fill="both", expand=True, padx=14, pady=12)
        tk.Label(
            hero_copy,
            text="SOUNDFONT 2 / CUSTOM INSTRUMENT FORGE",
            bg="#0F1115",
            fg=TEXT,
            font=("Bahnschrift SemiBold", 12),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            hero_copy,
            text=(
                "Load an .sf2, choose any preset, and assign it beside CTR retail "
                "instruments. Multisample key zones, root pitch and sample loops "
                "are preserved in the generated native music package."
            ),
            bg="#0F1115",
            fg=MUTED,
            font=("Bahnschrift", 9),
            justify="left",
            wraplength=920,
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        controls = ttk.Frame(outer, style="Panel.TFrame")
        controls.pack(fill="x", pady=(0, 10))
        ttk.Button(
            controls,
            text="LOAD .SF2",
            command=self.load_sf2,
            style="Accent.TButton",
        ).pack(side="left")
        self.sf2_preset_box = ttk.Combobox(
            controls,
            textvariable=self.sf2_preset_var,
            values=[],
            state="readonly",
            width=62,
        )
        self.sf2_preset_box.pack(side="left", fill="x", expand=True, padx=10)
        self.sf2_preset_box.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._update_sf2_details(),
        )
        ttk.Button(
            controls,
            text="AUDITION",
            command=self._audition_selected_sf2,
            style="Forge.TButton",
        ).pack(side="left")

        ttk.Label(
            outer,
            textvariable=self.sf2_status_var,
            style="Muted.TLabel",
            padding=(2, 0, 2, 8),
        ).pack(fill="x")

        details_frame = tk.Frame(
            outer,
            bg=FIELD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        details_frame.pack(fill="both", expand=True)
        self.sf2_details = tk.Text(
            details_frame,
            wrap="none",
            font=("Consolas", 10),
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=12,
        )
        sf2_scroll = ttk.Scrollbar(
            details_frame,
            orient="vertical",
            command=self.sf2_details.yview,
        )
        self.sf2_details.configure(yscrollcommand=sf2_scroll.set)
        self.sf2_details.pack(side="left", fill="both", expand=True)
        sf2_scroll.pack(side="right", fill="y")
        self._set_text(
            self.sf2_details,
            "Load a SoundFont 2 file to inspect presets and key zones.\n",
        )
        return outer

    @staticmethod
    def _is_sf2_value(value: str) -> bool:
        return value.strip().startswith("SF2 |")

    def _selected_sf2_preset(self, value: str):
        preset = self.sf2_presets_by_value.get(value.strip())
        if preset is None:
            raise ValueError("SoundFont preset is not available")
        return preset

    def _sf2_option_values(self) -> list[str]:
        return list(self.sf2_presets_by_value.keys())

    def load_sf2(self) -> None:
        filename = filedialog.askopenfilename(
            title="Load SoundFont 2",
            filetypes=[("SoundFont 2", "*.sf2"), ("All files", "*.*")],
        )
        if not filename:
            return

        old_channels = {ch: var.get() for ch, var in self.channel_vars.items()}
        old_drums = {note: var.get() for note, var in self.drum_vars.items()}

        try:
            sf = load_soundfont(filename)
        except (OSError, Sf2Error, ValueError) as exc:
            messagebox.showerror("SoundFont error", str(exc))
            return

        if not sf.presets:
            messagebox.showerror(
                "SoundFont error",
                "This SF2 contains no playable presets.",
            )
            return

        self.soundfont = sf
        self.sf2_path = Path(filename)
        self.sf2_presets_by_value.clear()
        values: list[str] = []
        for preset in sf.presets:
            value = (
                f"SF2 | B{preset.bank:03d} P{preset.preset:03d} | "
                f"{preset.name} | {len(preset.zones)} zone"
                f"{'s' if len(preset.zones) != 1 else ''}"
            )
            values.append(value)
            self.sf2_presets_by_value[value] = preset

        self.sf2_preset_box.configure(values=values)
        self.sf2_preset_var.set(values[0])
        self.sf2_status_var.set(
            f"Loaded: {self.sf2_path.name}  |  "
            f"{len(sf.presets)} presets  |  {len(sf.samples)} samples"
        )
        self._update_sf2_details()

        if self.current_midi is not None:
            self.rebuild_mapping_ui()
            valid_inst = set(self._instrument_options())
            valid_drum = set(self._drum_options())
            for ch, value in old_channels.items():
                if ch in self.channel_vars and value in valid_inst:
                    self.channel_vars[ch].set(value)
            for note, value in old_drums.items():
                if note in self.drum_vars and value in valid_drum:
                    self.drum_vars[note].set(value)

        self.tabs.select(self.sf2_tab)

    def _update_sf2_details(self) -> None:
        if self.soundfont is None:
            return
        try:
            preset = self._selected_sf2_preset(self.sf2_preset_var.get())
        except ValueError:
            return

        lines = [
            f"SoundFont: {self.soundfont.path}",
            f"Preset: bank {preset.bank}, program {preset.preset} - {preset.name}",
            f"Zones: {len(preset.zones)}",
            "",
            "KEY RANGE    ROOT   TUNE    SAMPLE RATE   LOOP   SAMPLE",
        ]
        for zone in preset.zones:
            sample = self.soundfont.samples[zone.sample_index]
            lines.append(
                f"{zone.key_low:03d}-{zone.key_high:03d}      "
                f"{zone.root_key:03d}   {zone.tune_cents:+5d}c   "
                f"{sample.sample_rate:6d} Hz     "
                f"{'yes' if zone.loop_enabled else 'no ':3s}    "
                f"{sample.name}"
            )
        lines += [
            "",
            "When this preset is assigned to a MIDI channel, Crash Forge keeps",
            "the SF2 key zones instead of stretching one sample across the whole keyboard.",
            "",
            "Percussion presets can also be selected per MIDI drum note.",
        ]
        self._set_text(self.sf2_details, "\n".join(lines) + "\n")

    def _audition_selected_sf2(self) -> None:
        if self.soundfont is None:
            messagebox.showinfo("SoundFont", "Load an SF2 first.")
            return
        try:
            preset = self._selected_sf2_preset(self.sf2_preset_var.get())
            zone = zone_for_note(preset, 60)
            wav = export_zone_temp(self.soundfont, zone, zone.sample_index)
            if winsound is None:
                raise RuntimeError("SF2 audition currently requires Windows")
            winsound.PlaySound(
                str(wav),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except Exception as exc:
            messagebox.showerror("SF2 audition", str(exc))

    def _create_build_tab(self) -> ttk.Frame:
        outer = ttk.Frame(self.tabs, style="Panel.TFrame", padding=12)
        self.tabs.add(outer, text="Build CSEQ")

        info = ttk.Label(
            outer,
            text=(
                "Assign CTR retail sounds or SoundFont 2 presets to each MIDI part. "
                "The generated package can mix both sources; unassigned channels "
                "and drum notes stay silent."
            ),
            wraplength=900,
            padding=8,
            style="Muted.TLabel",
        )
        info.pack(fill="x")

        target_row = ttk.Frame(outer, style="Panel.TFrame", padding=(8, 0, 8, 8))
        target_row.pack(fill="x")
        ttk.Label(target_row, text="REPLACE MUSIC TARGET", style="Section.TLabel").pack(side="left")
        target_values = ["No level override"] + [
            f"level_{level_id:02d} | {name}"
            for level_id, name in LEVEL_TARGETS.items()
        ]
        self.target_combo = ttk.Combobox(
            target_row,
            textvariable=self.target_var,
            values=target_values,
            state="readonly",
            width=42,
        )
        self.target_combo.pack(side="left", padx=(8, 0))
        self.target_combo.bind("<Button-1>", lambda event: self._refresh_custom_tracks())
        game_row = ttk.Frame(outer, style="Panel.TFrame", padding=(8, 0, 8, 8))
        game_row.pack(fill="x")
        ttk.Label(game_row, text="GAME", style="Section.TLabel").pack(side="left")
        ttk.Label(game_row, textvariable=self.game_root_var,
                  width=66, style="Muted.TLabel").pack(side="left", padx=(9, 0))
        ttk.Button(game_row, text="BROWSE GAME",
                   command=self._browse_custom_tracks_game).pack(side="left", padx=(8, 0))
        ttk.Button(game_row, text="REFRESH TRACKS",
                   command=self._refresh_custom_tracks).pack(side="left", padx=(6, 0))
        self._refresh_custom_tracks()
        ttk.Label(
            target_row,
            text="Written to music.ini; external CSEQ loading is active in Crash Forge Racing.",
            style="Muted.TLabel",
        ).pack(side="left", padx=(8, 0))

        intro_row = ttk.Frame(outer, style="Panel.TFrame", padding=(8, 0, 8, 4))
        intro_row.pack(fill="x")
        self.race_intro_check = ttk.Checkbutton(
            intro_row,
            text="RACE INTRO / ONE-SHOT LEAD-IN",
            variable=self.race_intro_var,
        )
        self.race_intro_check.pack(side="left")
        ttk.Label(
            intro_row,
            textvariable=self.race_intro_status_var,
            style="Muted.TLabel",
        ).pack(side="left", padx=(12, 0))
        ttk.Label(
            intro_row,
            text="Marker optional; use the LOOP START slider or type exact seconds below.",
            style="Muted.TLabel",
        ).pack(side="right")

        playback_row = ttk.Frame(outer, style="Panel.TFrame", padding=(8, 0, 8, 6))
        playback_row.pack(fill="x")
        ttk.Label(playback_row, text="PLAYBACK", style="Section.TLabel").pack(side="left")
        self.preview_position_scale = ttk.Scale(
            playback_row,
            from_=0,
            to=1,
            orient="horizontal",
            variable=self.preview_position_var,
            command=self._on_preview_position_slider,
            state="disabled",
        )
        self.preview_position_scale.pack(side="left", fill="x", expand=True, padx=(12, 12))
        self.preview_position_scale.bind("<ButtonPress-1>", self._preview_seek_begin, add="+")
        self.preview_position_scale.bind("<ButtonRelease-1>", self._preview_seek_end, add="+")
        ttk.Label(
            playback_row,
            textvariable=self.preview_position_text_var,
            style="Muted.TLabel",
            width=34,
        ).pack(side="right")

        loop_row = ttk.Frame(outer, style="Panel.TFrame", padding=(8, 0, 8, 8))
        loop_row.pack(fill="x")
        ttk.Label(loop_row, text="LOOP START", style="Section.TLabel").pack(side="left")
        self.loop_start_scale = ttk.Scale(
            loop_row,
            from_=0,
            to=1,
            orient="horizontal",
            variable=self.loop_start_var,
            command=self._on_loop_slider,
            state="disabled",
        )
        self.loop_start_scale.pack(side="left", fill="x", expand=True, padx=(12, 10))

        exact_box = ttk.Frame(loop_row, style="Panel.TFrame")
        exact_box.pack(side="left", padx=(0, 10))
        ttk.Label(
            exact_box,
            text="SECONDS",
            style="Muted.TLabel",
        ).pack(side="left", padx=(0, 6))
        self.loop_start_seconds_entry = ttk.Entry(
            exact_box,
            textvariable=self.loop_start_seconds_var,
            width=12,
            justify="right",
            state="disabled",
        )
        self.loop_start_seconds_entry.pack(side="left")
        self.loop_start_seconds_entry.bind(
            "<Return>",
            self._apply_loop_seconds_entry,
            add="+",
        )
        self.loop_start_seconds_entry.bind(
            "<FocusOut>",
            self._apply_loop_seconds_entry,
            add="+",
        )

        ttk.Label(
            loop_row,
            textvariable=self.loop_start_text_var,
            style="Muted.TLabel",
            width=46,
        ).pack(side="right")

        buttons = ttk.Frame(outer, style="Panel.TFrame", padding=(8, 0, 8, 8))
        buttons.pack(fill="x")
        self.preview_song_button = ttk.Button(
            buttons,
            text="Render",
            command=self.preview_song,
            state="disabled",
            style="Accent.TButton",
        )
        self.preview_song_button.pack(side="left")

        self.play_preview_button = ttk.Button(
            buttons,
            text="Play",
            command=self.play_preview_transport,
            state="disabled",
            style="Forge.TButton",
        )
        self.play_preview_button.pack(side="left", padx=(8, 0))
        self.pause_preview_button = ttk.Button(
            buttons,
            text="Pause",
            command=self.pause_preview_transport,
            state="disabled",
            style="Ghost.TButton",
        )
        self.pause_preview_button.pack(side="left", padx=(6, 0))
        self.loop_preview_button = ttk.Button(
            buttons,
            text="Loop: OFF",
            command=self.toggle_preview_loop,
            state="disabled",
            style="Ghost.TButton",
        )
        self.loop_preview_button.pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Stop",
            command=self.stop_preview_transport,
            style="Ghost.TButton",
        ).pack(side="left", padx=(6, 16))
        self.build_cseq_button = ttk.Button(
            buttons,
            text="Build .cseq...",
            command=self.save_cseq,
            state="disabled",
            style="Accent.TButton",
        )
        self.build_cseq_button.pack(side="left")
        self.build_package_button = ttk.Button(
            buttons,
            text="Build Music Package...",
            command=self.save_package,
            state="disabled",
            style="Accent.TButton",
        )
        self.build_package_button.pack(side="left", padx=(8, 0))

        holder = ttk.Frame(outer, style="Panel.TFrame")
        holder.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.build_canvas = tk.Canvas(holder, bg=PANEL, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=self.build_canvas.yview)
        self.mapping_frame = ttk.Frame(self.build_canvas, style="Panel.TFrame")
        self.mapping_frame.bind(
            "<Configure>",
            lambda _e: self.build_canvas.configure(scrollregion=self.build_canvas.bbox("all")),
        )
        self.build_canvas.create_window((0, 0), window=self.mapping_frame, anchor="nw")
        self.build_canvas.configure(yscrollcommand=scrollbar.set)
        self.build_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.build_canvas.bind("<MouseWheel>", self._on_mapping_mousewheel, add="+")
        holder.bind("<MouseWheel>", self._on_mapping_mousewheel, add="+")

        ttk.Label(self.mapping_frame, text="Open a MIDI to create mappings.", padding=8).grid(
            row=0, column=0, sticky="w"
        )
        return outer

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _tick_to_seconds(self, tick: int) -> float:
        midi = self.current_midi
        if midi is None or midi.ticks_per_quarter <= 0:
            return 0.0
        target = max(0, int(tick))
        tempo_us = 500000
        last_tick = 0
        seconds = 0.0
        tempos = sorted(
            (e for e in midi.events if e.kind == "tempo" and e.a),
            key=lambda e: (e.tick, e.track, e.order),
        )
        for event in tempos:
            event_tick = int(event.tick)
            if event_tick > target:
                break
            if event_tick > last_tick:
                seconds += (
                    (event_tick - last_tick)
                    * tempo_us
                    / (1_000_000.0 * float(midi.ticks_per_quarter))
                )
                last_tick = event_tick
            tempo_us = int(event.a or tempo_us)
        if target > last_tick:
            seconds += (
                (target - last_tick)
                * tempo_us
                / (1_000_000.0 * float(midi.ticks_per_quarter))
            )
        return max(0.0, seconds)

    def _seconds_to_tick(self, seconds: float) -> int:
        midi = self.current_midi
        if midi is None or midi.ticks_per_quarter <= 0:
            return 0

        target_seconds = max(0.0, float(seconds))
        last_song_tick = max((int(e.tick) for e in midi.events), default=0)
        tempo_us = 500000
        last_tick = 0
        elapsed = 0.0
        tempos = sorted(
            (e for e in midi.events if e.kind == "tempo" and e.a),
            key=lambda e: (e.tick, e.track, e.order),
        )

        for event in tempos:
            event_tick = max(last_tick, int(event.tick))
            segment_seconds = (
                (event_tick - last_tick)
                * tempo_us
                / (1_000_000.0 * float(midi.ticks_per_quarter))
            )
            if target_seconds <= elapsed + segment_seconds:
                remaining = target_seconds - elapsed
                tick = last_tick + int(round(
                    remaining
                    * 1_000_000.0
                    * float(midi.ticks_per_quarter)
                    / float(tempo_us)
                ))
                return max(0, min(last_song_tick, tick))
            elapsed += segment_seconds
            last_tick = event_tick
            tempo_us = int(event.a or tempo_us)

        remaining = max(0.0, target_seconds - elapsed)
        tick = last_tick + int(round(
            remaining
            * 1_000_000.0
            * float(midi.ticks_per_quarter)
            / float(tempo_us)
        ))
        return max(0, min(last_song_tick, tick))

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        minutes = int(seconds // 60)
        rest = seconds - (minutes * 60)
        return f"{minutes}:{rest:06.3f}"

    def _apply_loop_seconds_entry(self, _event=None) -> None:
        if self.current_midi is None:
            return

        raw = self.loop_start_seconds_var.get().strip().replace(",", ".")
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            self.bell()
            self.loop_start_seconds_var.set(
                f"{float(self.loop_start_var.get()):.6f}"
            )
            return

        last_tick = max(
            (int(e.tick) for e in self.current_midi.events),
            default=0,
        )
        total_seconds = self._tick_to_seconds(last_tick)
        seconds = max(0.0, min(total_seconds, seconds))

        self.loop_start_var.set(seconds)
        self._on_loop_slider(seconds)

    def _on_loop_slider(self, value: str | float) -> None:
        if self.current_midi is None:
            return

        last_tick = max((int(e.tick) for e in self.current_midi.events), default=0)
        total_seconds = self._tick_to_seconds(last_tick)
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            seconds = 0.0
        seconds = max(0.0, min(total_seconds, seconds))

        if abs(float(self.loop_start_var.get()) - seconds) > 0.0005:
            self.loop_start_var.set(seconds)

        self.loop_start_seconds_var.set(f"{seconds:.6f}")

        tick = self._seconds_to_tick(seconds)
        self.loop_start_text_var.set(
            f"Loop start: {self._format_seconds(seconds)} / "
            f"{self._format_seconds(total_seconds)}  |  tick {tick}"
        )
        if seconds > 0.001:
            self.race_intro_var.set(True)
            self.race_intro_status_var.set(
                "Manual loop start active - playback loop returns here"
            )
        else:
            self.race_intro_status_var.set(
                "Loop starts at song beginning unless you move the slider"
            )

    def _update_preview_position_display(self, seconds: float) -> None:
        total = max(0.0, float(self._preview_total_seconds))
        seconds = max(0.0, min(total, float(seconds))) if total > 0.0 else 0.0
        self.preview_position_text_var.set(
            f"Playback: {self._format_seconds(seconds)} / {self._format_seconds(total)}"
        )

    def _on_preview_position_slider(self, value: str | float) -> None:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            seconds = 0.0
        total = max(0.0, float(self._preview_total_seconds))
        seconds = max(0.0, min(total, seconds)) if total > 0.0 else 0.0
        if abs(float(self.preview_position_var.get()) - seconds) > 0.0005:
            self.preview_position_var.set(seconds)
        self._update_preview_position_display(seconds)

    def _preview_seek_begin(self, _event=None) -> None:
        if self._preview_audio_path is None:
            return
        mode, _position_ms, _length_ms = song_preview_state()
        self._preview_user_seeking = True
        self._preview_seek_was_playing = mode == "playing"
        if self._preview_seek_was_playing:
            try:
                pause_song_preview()
            except Exception:
                self._preview_seek_was_playing = False

    def _preview_seek_end(self, _event=None) -> None:
        if self._preview_audio_path is None:
            self._preview_user_seeking = False
            self._preview_seek_was_playing = False
            return

        seconds = max(0.0, float(self.preview_position_var.get()))
        start_ms = int(round(seconds * 1000.0))
        was_playing = self._preview_seek_was_playing
        self._preview_user_seeking = False
        self._preview_seek_was_playing = False

        try:
            if was_playing:
                play_rendered_preview(self._preview_audio_path, start_ms=start_ms)
                self._schedule_preview_poll()
            else:
                mode, _position_ms, _length_ms = song_preview_state()
                if mode == "paused":
                    # Leave audio silent, but make the next Play start from the
                    # newly selected playback position instead of the old pause point.
                    stop_song_preview()
        except Exception as exc:
            messagebox.showerror("Preview transport", str(exc))

    def play_preview_transport(self) -> None:
        if self._preview_audio_path is None or not self._preview_audio_path.is_file():
            messagebox.showinfo("Preview transport", "Render the song first.")
            return
        try:
            mode, _position_ms, _length_ms = song_preview_state()
            if mode == "paused" and not self._preview_user_seeking:
                play_rendered_preview(self._preview_audio_path)
            else:
                start_ms = int(round(
                    max(0.0, float(self.preview_position_var.get())) * 1000.0
                ))
                play_rendered_preview(self._preview_audio_path, start_ms=start_ms)
            self._schedule_preview_poll()
        except Exception as exc:
            messagebox.showerror("Preview transport", str(exc))

    def pause_preview_transport(self) -> None:
        try:
            pause_song_preview()
            mode, position_ms, _length_ms = song_preview_state()
            if mode == "paused":
                seconds = max(0.0, position_ms / 1000.0)
                self.preview_position_var.set(seconds)
                self._update_preview_position_display(seconds)
        except Exception as exc:
            messagebox.showerror("Preview transport", str(exc))

    def stop_preview_transport(self) -> None:
        stop_song_preview()
        if self._preview_poll_job is not None:
            try:
                self.after_cancel(self._preview_poll_job)
            except tk.TclError:
                pass
            self._preview_poll_job = None
        self._preview_user_seeking = False
        self._preview_seek_was_playing = False
        self.preview_position_var.set(0.0)
        self._update_preview_position_display(0.0)

    def _preview_rendered(self, path: str | Path) -> None:
        self._preview_audio_path = Path(path)
        try:
            with wave.open(str(self._preview_audio_path), "rb") as wav:
                rate = max(1, int(wav.getframerate()))
                self._preview_total_seconds = wav.getnframes() / float(rate)
        except (OSError, wave.Error):
            self._preview_total_seconds = 0.0

        self.preview_position_var.set(0.0)
        self._update_preview_position_display(0.0)
        self.preview_position_scale.configure(
            to=max(0.001, self._preview_total_seconds),
            state="normal",
        )
        self.play_preview_button.configure(state="normal")
        self.pause_preview_button.configure(state="normal")
        self.loop_preview_button.configure(state="normal")

    def toggle_preview_loop(self) -> None:
        enabled = not bool(self.preview_loop_var.get())
        self.preview_loop_var.set(enabled)
        self.loop_preview_button.configure(text=f"Loop: {'ON' if enabled else 'OFF'}")
        mode, _position_ms, _length_ms = song_preview_state()
        if mode == "playing":
            self._schedule_preview_poll()

    def _schedule_preview_poll(self) -> None:
        if self._preview_poll_job is None:
            self._preview_poll_job = self.after(100, self._poll_preview_audio)

    def _poll_preview_audio(self) -> None:
        self._preview_poll_job = None
        mode, position_ms, length_ms = song_preview_state()

        if not self._preview_user_seeking and length_ms > 0:
            seconds = max(0.0, position_ms / 1000.0)
            self.preview_position_var.set(seconds)
            self._update_preview_position_display(seconds)

        if (
            self.preview_loop_var.get()
            and self._preview_audio_path is not None
            and length_ms > 0
            and mode == "stopped"
            and position_ms >= max(0, length_ms - 180)
        ):
            start_ms = int(round(max(0.0, float(self.loop_start_var.get())) * 1000.0))
            start_ms = max(0, min(max(0, length_ms - 1), start_ms))
            try:
                play_rendered_preview(self._preview_audio_path, start_ms=start_ms)
                seconds = start_ms / 1000.0
                self.preview_position_var.set(seconds)
                self._update_preview_position_display(seconds)
                mode = "playing"
            except Exception:
                mode = "closed"

        if (
            mode == "stopped"
            and length_ms > 0
            and position_ms >= max(0, length_ms - 180)
            and not self.preview_loop_var.get()
            and not self._preview_user_seeking
        ):
            seconds = min(self._preview_total_seconds, length_ms / 1000.0)
            self.preview_position_var.set(seconds)
            self._update_preview_position_display(seconds)

        if mode == "playing":
            self._schedule_preview_poll()

    def _on_mapping_mousewheel(self, event) -> str:
        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return "break"
        steps = -int(delta / 120)
        if steps == 0:
            steps = -1 if delta > 0 else 1
        self.build_canvas.yview_scroll(steps * 3, "units")
        return "break"

    def _bind_mapping_mousewheel(self, widget) -> None:
        try:
            widget.bind("<MouseWheel>", self._on_mapping_mousewheel, add="+")
        except tk.TclError:
            return
        for child in widget.winfo_children():
            self._bind_mapping_mousewheel(child)

    def _change_channel_transpose(self, channel: int, delta: int) -> None:
        var = self.channel_transpose_vars.get(channel)
        if var is None:
            return
        value = max(-24, min(24, int(var.get()) + int(delta)))
        var.set(value)

    def _midi_with_channel_transpose(self) -> MidiFile:
        if self.current_midi is None:
            raise ValueError("open a MIDI first")

        transpose = {
            int(ch): int(var.get())
            for ch, var in self.channel_transpose_vars.items()
            if int(var.get()) != 0
        }
        if not transpose:
            return self.current_midi

        events = []
        for event in self.current_midi.events:
            shift = transpose.get(int(event.channel)) if event.channel is not None else None
            if (
                shift
                and event.channel != 9
                and event.kind in ("note_on", "note_off")
                and event.a is not None
            ):
                note = int(event.a) + int(shift)
                if not 0 <= note <= 127:
                    raise ValueError(
                        f"Channel {int(event.channel) + 1}: transpose {shift:+d} st "
                        f"moves MIDI note {int(event.a)} outside 0..127."
                    )
                events.append(replace(event, a=note))
            else:
                events.append(event)

        return replace(self.current_midi, events=events)

    def open_midi(self) -> None:
        filename = filedialog.askopenfilename(
            title="Open MIDI",
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            midi = read_midi(filename)
            summary = summarize(midi)
            validation = validate_midi(midi).to_dict()
        except Exception as exc:
            messagebox.showerror("MIDI error", str(exc))
            return

        self.current_path = Path(filename)
        self.current_midi = midi
        self.current_report = {"midi": summary, "validation": validation}
        self.file_label.configure(text=self.current_path.name)

        stop_song_preview()
        self._preview_audio_path = None
        self._preview_total_seconds = 0.0
        self.preview_position_var.set(0.0)
        self.preview_position_text_var.set("Playback: 0:00.000 / 0:00.000")
        self.preview_position_scale.configure(to=1, state="disabled")
        self.preview_loop_var.set(False)
        self.loop_preview_button.configure(text="Loop: OFF")
        self.play_preview_button.configure(state="disabled")
        self.pause_preview_button.configure(state="disabled")
        self.loop_preview_button.configure(state="disabled")

        last_tick = max(0, int(summary["last_tick"]))
        total_seconds = self._tick_to_seconds(last_tick)
        self.loop_start_scale.configure(
            to=max(0.001, total_seconds),
            state="normal",
        )
        self.loop_start_seconds_entry.configure(state="normal")

        loop_start_tick = find_loop_start_tick(midi)
        if loop_start_tick is not None:
            loop_start_seconds = self._tick_to_seconds(loop_start_tick)
            self.loop_start_var.set(loop_start_seconds)
            self._on_loop_slider(loop_start_seconds)
            self.race_intro_status_var.set(
                f"CFR_LOOP_START detected at {self._format_seconds(loop_start_seconds)}; "
                "move the slider to override it"
            )
            self.race_intro_var.set(loop_start_tick > 0)
        else:
            self.loop_start_var.set(0.0)
            self._on_loop_slider(0.0)
            self.race_intro_status_var.set(
                "No marker exported by FL Studio; choose the loop start by time"
            )
            self.race_intro_var.set(False)

        lines = [
            f"File: {self.current_path}",
            f"Type: {summary['format']}",
            f"Tracks: {summary['tracks']}",
            f"TPQN: {summary['ticks_per_quarter']}",
            f"Events: {summary['events']}",
            f"Last tick: {summary['last_tick']}",
            "",
            "Channels:",
        ]
        for ch in summary["channels"]:
            role = "DRUMS" if ch == 9 else "MELODIC"
            programs = summary["programs"].get(ch, [])
            lines.append(f"  {ch + 1:02d}  {role:<7} programs={programs}")
        lines += ["", "Tempo:"]
        for tempo in summary["tempos"]:
            bpm = tempo["bpm"]
            lines.append(
                f"  tick {tempo['tick']}: {bpm:.3f} BPM" if bpm is not None
                else f"  tick {tempo['tick']}: invalid"
            )
        if not summary["tempos"]:
            lines.append("  (none)")
        if summary["markers"]:
            lines += ["", "Markers:"]
            for marker in summary["markers"]:
                lines.append(f"  tick {marker['tick']}: {marker['text']}")

        self._set_text(self.summary_text, "\n".join(lines) + "\n")

        vlines = [
            f"Peak polyphony: {validation['peak_polyphony']} voices",
            f"Peak tick: {validation['peak_polyphony_tick']}",
            "",
        ]
        if not validation["issues"]:
            vlines.append("No validation issues.")
        for issue in validation["issues"]:
            vlines.append(f"[{issue['severity'].upper()}] {issue['code']}: {issue['message']}")
        self._set_text(self.validation_text, "\n".join(vlines) + "\n")

        self.rebuild_mapping_ui()
        self.tabs.select(self.build_tab)

    def export_report(self) -> None:
        if self.current_report is None:
            messagebox.showinfo("Crash Forge MIDI Tool", "Open a MIDI first.")
            return
        filename = filedialog.asksaveasfilename(
            title="Export report",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not filename:
            return
        Path(filename).write_text(json.dumps(self.current_report, indent=2) + "\n", encoding="utf-8")

    def _instrument_options(self) -> list[str]:
        if self.catalog is None:
            return []
        retail = [
            f"{x.global_id:03d} | {self.catalog.instrument_display(x.global_id)} | "
            f"GM {x.midi_program if x.midi_program >= 0 else '-'} | "
            f"transpose {x.midi_pitch:+d} | SPU {x.spu_index:03d}"
            for x in self.catalog.instruments
        ]
        percussion = [
            f"DRUM {x.global_id:03d} | {self.catalog.drum_display(x.global_id)} | "
            f"GM key {x.midi_key if x.midi_key >= 0 else '-'} | "
            f"SPU {x.spu_index:03d} | melodic-use"
            for x in self.catalog.drums
        ]
        return (
            ["(None / Unassigned)"]
            + retail
            + percussion
            + self._sf2_option_values()
        )

    def _drum_options(self) -> list[str]:
        if self.catalog is None:
            return []
        retail = [
            f"{x.global_id:03d} | {self.catalog.drum_display(x.global_id)} | "
            f"GM key {x.midi_key if x.midi_key >= 0 else '-'} | SPU {x.spu_index:03d}"
            for x in self.catalog.drums
        ]
        return ["(None / Unassigned)"] + retail + self._sf2_option_values()

    @staticmethod
    def _is_unassigned(value: str) -> bool:
        return not value.strip() or value.strip() == "(None / Unassigned)"

    @staticmethod
    def _is_retail_drum_melodic_value(value: str) -> bool:
        return value.strip().upper().startswith("DRUM ")

    @staticmethod
    def _selected_global_id(value: str) -> int:
        if App._is_unassigned(value):
            raise ValueError("the mapping is unassigned")
        head = value.split("|", 1)[0].strip()
        if head.upper().startswith("DRUM "):
            return int(head.split(None, 1)[1])
        return int(head)

    @staticmethod
    def _drum_as_melodic_instrument(item: RetailDrum) -> RetailInstrument:
        # Short/drum metadata has no ADSR pair, so use the same safe envelope
        # used for imported melodic SF2 samples. Keep the real retail sample,
        # volume and drum playback pitch.
        return RetailInstrument(
            global_id=0x30000 + int(item.global_id),
            spu_index=int(item.spu_index),
            volume=int(item.volume),
            base_pitch=max(1, int(item.pitch)),
            ad=-32513,
            sr=8129,
            title=f"{item.label} (Percussion)",
            sample_name=item.sample_name,
            midi_program=-1,
            midi_pitch=0,
        )

    def _preview_global_catalog_value(self) -> None:
        if self.catalog is None:
            return
        value = self.global_preview_var.get().strip()
        if not value:
            return
        try:
            head = value.split("|", 1)[0].strip().split()
            kind = head[0]
            gid = int(head[1])
            if kind == "INST":
                item = next(x for x in self.catalog.instruments if x.global_id == gid)
                play_sample_preview(
                    item.spu_index,
                    ctr_note_pitch(item.base_pitch, 60 - item.midi_pitch),
                )
            else:
                item = next(x for x in self.catalog.drums if x.global_id == gid)
                play_sample_preview(item.spu_index, item.pitch)
        except Exception as exc:
            messagebox.showerror("Retail sample preview", str(exc))

    def _preview_sf2_value(self, value: str, midi_note: int = 60) -> None:
        if self.soundfont is None:
            raise ValueError("Load the SoundFont first")
        preset = self._selected_sf2_preset(value)
        zone = zone_for_note(preset, midi_note)
        wav = export_zone_temp(self.soundfont, zone, zone.sample_index)
        if winsound is None:
            raise RuntimeError("SF2 audition currently requires Windows")
        winsound.PlaySound(
            str(wav),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )

    def _preview_instrument_value(self, value: str, semitones: int = 0) -> None:
        if self.catalog is None or self._is_unassigned(value):
            return
        try:
            midi_note = max(0, min(127, 60 + int(semitones)))
            if self._is_sf2_value(value):
                self._preview_sf2_value(value, midi_note)
                return
            gid = self._selected_global_id(value)
            if self._is_retail_drum_melodic_value(value):
                drum = next(
                    x for x in self.catalog.drums
                    if x.global_id == gid
                )
                semitones = midi_note - 60
                pitch = int(round(
                    max(1, drum.pitch) * (2.0 ** (semitones / 12.0))
                ))
                play_sample_preview(
                    drum.spu_index,
                    max(1, min(0xFFFF, pitch)),
                )
            else:
                item = next(
                    x for x in self.catalog.instruments
                    if x.global_id == gid
                )
                play_sample_preview(
                    item.spu_index,
                    ctr_note_pitch(
                        item.base_pitch,
                        midi_note - item.midi_pitch,
                    ),
                )
        except Exception as exc:
            messagebox.showerror("Instrument preview", str(exc))

    def _preview_drum_value(self, value: str, midi_note: int = 60) -> None:
        if self.catalog is None or self._is_unassigned(value):
            return
        try:
            if self._is_sf2_value(value):
                self._preview_sf2_value(value, midi_note)
                return
            gid = self._selected_global_id(value)
            item = next(x for x in self.catalog.drums if x.global_id == gid)
            play_sample_preview(item.spu_index, item.pitch)
        except Exception as exc:
            messagebox.showerror("Drum preview", str(exc))

    def rebuild_mapping_ui(self) -> None:
        for child in self.mapping_frame.winfo_children():
            child.destroy()
        self.channel_vars.clear()
        self.channel_transpose_vars.clear()
        self.drum_vars.clear()

        if self.current_midi is None or self.catalog is None:
            ttk.Label(
                self.mapping_frame,
                text="Open a MIDI and make sure the retail catalog is available.",
                padding=8,
            ).grid(row=0, column=0, sticky="w")
            self.preview_song_button.configure(state="disabled")
            self.play_preview_button.configure(state="disabled")
            self.pause_preview_button.configure(state="disabled")
            self.loop_preview_button.configure(state="disabled")
            self.build_cseq_button.configure(state="disabled")
            self.build_package_button.configure(state="disabled")
            self._bind_mapping_mousewheel(self.mapping_frame)
            return

        midi = self.current_midi
        melodic_channels = sorted({
            int(e.channel)
            for e in midi.events
            if e.channel is not None and e.channel != 9 and e.kind == "note_on"
        })
        drum_notes = sorted({
            int(e.a)
            for e in midi.events
            if e.channel == 9 and e.kind == "note_on" and e.a is not None
        })

        row = 0
        ttk.Label(self.mapping_frame, text="Melodic channels", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(4, 6)
        )
        row += 1

        inst_options = self._instrument_options()
        for ch in melodic_channels:
            programs = sorted({
                int(e.a)
                for e in midi.events
                if e.channel == ch and e.kind == "program_change" and e.a is not None
            })
            source_programs = programs or [0]
            source_names = ", ".join(
                f"{program}: {gm_program_name(program)}"
                for program in source_programs
            )
            ttk.Label(
                self.mapping_frame,
                text=f"Channel {ch + 1}  |  MIDI source: {source_names}",
            ).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=2)
            var = tk.StringVar(value="(None / Unassigned)")
            box = ttk.Combobox(
                self.mapping_frame,
                textvariable=var,
                values=inst_options,
                state="readonly",
                width=54,
            )
            box.grid(row=row, column=1, sticky="ew", pady=2)
            tone_var = tk.IntVar(value=0)
            self.channel_transpose_vars[ch] = tone_var

            ttk.Button(
                self.mapping_frame,
                text="Audition",
                command=lambda v=var, c=ch: self._preview_instrument_value(
                    v.get(),
                    self.channel_transpose_vars[c].get(),
                ),
            ).grid(row=row, column=2, padx=(8, 0), pady=2)

            tone_box = ttk.Frame(self.mapping_frame, style="Panel.TFrame")
            tone_box.grid(row=row, column=3, padx=(10, 0), pady=2, sticky="e")
            ttk.Button(
                tone_box,
                text="-",
                width=3,
                command=lambda c=ch: self._change_channel_transpose(c, -1),
            ).pack(side="left")
            ttk.Label(
                tone_box,
                textvariable=tone_var,
                width=3,
                anchor="center",
            ).pack(side="left", padx=(4, 1))
            ttk.Label(
                tone_box,
                text="st",
                style="Muted.TLabel",
            ).pack(side="left", padx=(0, 4))
            ttk.Button(
                tone_box,
                text="+",
                width=3,
                command=lambda c=ch: self._change_channel_transpose(c, 1),
            ).pack(side="left")

            self.channel_vars[ch] = var
            row += 1

        if not melodic_channels:
            ttk.Label(self.mapping_frame, text="(none)").grid(row=row, column=0, sticky="w")
            row += 1

        ttk.Separator(self.mapping_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=4, sticky="ew", pady=10
        )
        row += 1
        ttk.Label(
            self.mapping_frame,
            text="Channel 10 / drums used by this MIDI",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=row, column=0, columnspan=4, sticky="w", pady=(0, 6))
        row += 1

        drum_options = self._drum_options()
        for note in drum_notes:
            ttk.Label(self.mapping_frame, text=f"MIDI drum note {note}").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=2
            )
            var = tk.StringVar(value="(None / Unassigned)")
            box = ttk.Combobox(
                self.mapping_frame,
                textvariable=var,
                values=drum_options,
                state="readonly",
                width=54,
            )
            box.grid(row=row, column=1, sticky="ew", pady=2)
            ttk.Button(
                self.mapping_frame,
                text="Audition",
                command=lambda v=var, n=note: self._preview_drum_value(v.get(), n),
            ).grid(row=row, column=2, padx=(8, 0), pady=2)
            self.drum_vars[note] = var
            row += 1

        if not drum_notes:
            ttk.Label(self.mapping_frame, text="(none)").grid(row=row, column=0, sticky="w")
            row += 1

        self.mapping_frame.columnconfigure(1, weight=1)
        self.preview_song_button.configure(state="normal")
        has_render = self._preview_audio_path is not None and self._preview_audio_path.is_file()
        self.play_preview_button.configure(state="normal" if has_render else "disabled")
        self.pause_preview_button.configure(state="normal" if has_render else "disabled")
        self.loop_preview_button.configure(state="normal" if has_render else "disabled")
        self.build_cseq_button.configure(state="normal")
        self.build_package_button.configure(state="normal")
        self._bind_mapping_mousewheel(self.mapping_frame)

    def _preview_maps(self):
        if self.catalog is None:
            return {}, {}
        inst_by_id = {x.global_id: x for x in self.catalog.instruments}
        drum_by_id = {x.global_id: x for x in self.catalog.drums}

        channel_map = {}
        for ch, var in self.channel_vars.items():
            value = var.get().strip()
            if self._is_unassigned(value):
                continue
            if self._is_sf2_value(value):
                if self.soundfont is None:
                    raise ValueError("Load the SoundFont used by this preview")
                channel_map[ch] = self._selected_sf2_preset(value)
                continue
            gid = self._selected_global_id(value)
            if self._is_retail_drum_melodic_value(value):
                channel_map[ch] = self._drum_as_melodic_instrument(
                    drum_by_id[gid]
                )
            else:
                channel_map[ch] = inst_by_id[gid]

        drum_map = {}
        for note, var in self.drum_vars.items():
            value = var.get().strip()
            if self._is_unassigned(value):
                continue
            if self._is_sf2_value(value):
                if self.soundfont is None:
                    raise ValueError("Load the SoundFont used by this preview")
                drum_map[note] = self._selected_sf2_preset(value)
                continue
            drum_map[note] = drum_by_id[self._selected_global_id(value)]

        return channel_map, drum_map

    def preview_song(self) -> None:
        if self.current_midi is None or self.catalog is None:
            messagebox.showinfo("Song Preview", "Open a MIDI first.")
            return

        try:
            channel_map, drum_map = self._preview_maps()
            midi = self._midi_with_channel_transpose()
        except Exception as exc:
            messagebox.showerror("Song Preview", str(exc))
            return

        if not channel_map and not drum_map:
            messagebox.showinfo(
                "Song Preview",
                "Assign at least one instrument or drum first. "
                "Unassigned channels are skipped during preview.",
            )
            return

        self.preview_song_button.configure(state="disabled", text="Rendering...")
        stop_preview()
        stop_song_preview()
        if self._preview_poll_job is not None:
            try:
                self.after_cancel(self._preview_poll_job)
            except tk.TclError:
                pass
            self._preview_poll_job = None
        self._preview_audio_path = None
        self._preview_total_seconds = 0.0
        self.preview_position_var.set(0.0)
        self.preview_position_text_var.set("Playback: 0:00.000 / 0:00.000")
        self.preview_position_scale.configure(to=1, state="disabled")
        self.play_preview_button.configure(state="disabled")
        self.pause_preview_button.configure(state="disabled")
        self.loop_preview_button.configure(state="disabled")

        soundfont = self.soundfont

        def worker() -> None:
            try:
                out = play_song_preview(
                    midi,
                    channel_map,
                    drum_map,
                    soundfont=soundfont,
                    autoplay=False,
                )
                self.after(0, lambda p=out: self._preview_rendered(p))
            except Exception as exc:
                self.after(
                    0,
                    lambda e=exc: messagebox.showerror("Song Preview", str(e)),
                )
            finally:
                self.after(
                    0,
                    lambda: self.preview_song_button.configure(
                        state="normal",
                        text="Render",
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _build_cseq(self) -> bytes:
        if self.current_midi is None or self.catalog is None:
            raise ValueError("open a MIDI first")

        source_midi = self._midi_with_channel_transpose()
        report = validate_midi(source_midi)
        errors = [x.message for x in report.issues if x.severity == "error"]
        if errors:
            raise ValueError("\n".join(errors))

        loop_start_tick = None
        if self.race_intro_var.get():
            loop_start_seconds = max(0.0, float(self.loop_start_var.get()))
            loop_start_tick = self._seconds_to_tick(loop_start_seconds)
            song_end_tick = max((int(e.tick) for e in source_midi.events), default=0)
            if loop_start_seconds <= 0.001 or loop_start_tick <= 0:
                raise ValueError(
                    "Race Intro is enabled, but LOOP START is still at the beginning. "
                    "Move the LOOP START slider to where the repeating section should begin."
                )
            if loop_start_tick >= song_end_tick:
                raise ValueError(
                    "LOOP START must be before the end of the MIDI."
                )

        inst_by_id = {x.global_id: x for x in self.catalog.instruments}
        drum_by_id = {x.global_id: x for x in self.catalog.drums}

        channel_zones: dict[int, list[MelodicInstrumentZone]] = {}
        drum_map: dict[int, object] = {}
        custom_samples: list[Path] = []
        sample_slots: dict[tuple[int, bool], int] = {}

        def sample_slot_for(zone) -> int:
            if self.soundfont is None:
                raise ValueError("Load the SoundFont used by this mapping")
            key = (int(zone.sample_index), bool(zone.loop_enabled))
            slot = sample_slots.get(key)
            if slot is not None:
                return slot
            slot = len(custom_samples)
            if slot >= 256:
                raise ValueError(
                    "This project uses more than 256 unique custom SF2 samples."
                )
            wav = export_zone_temp(self.soundfont, zone, slot)
            sample_slots[key] = slot
            custom_samples.append(wav)
            return slot

        for ch, var in self.channel_vars.items():
            value = var.get().strip()
            if self._is_unassigned(value):
                continue

            if self._is_sf2_value(value):
                if self.soundfont is None:
                    raise ValueError("The selected SF2 is no longer loaded")
                preset = self._selected_sf2_preset(value)
                zones: list[MelodicInstrumentZone] = []
                for sf_zone in preset.zones:
                    slot = sample_slot_for(sf_zone)
                    inst = make_cseq_instrument(
                        self.soundfont,
                        sf_zone,
                        slot,
                    )
                    zones.append(
                        MelodicInstrumentZone(
                            instrument=inst,
                            key_low=sf_zone.key_low,
                            key_high=sf_zone.key_high,
                            midi_pitch=inst.midi_pitch,
                        )
                    )
                if zones:
                    channel_zones[ch] = zones
                continue

            gid = self._selected_global_id(value)
            if self._is_retail_drum_melodic_value(value):
                item = self._drum_as_melodic_instrument(drum_by_id[gid])
            else:
                item = inst_by_id[gid]
            channel_zones[ch] = [
                MelodicInstrumentZone(
                    instrument=item,
                    key_low=0,
                    key_high=127,
                    midi_pitch=item.midi_pitch,
                )
            ]

        for note, var in self.drum_vars.items():
            value = var.get().strip()
            if self._is_unassigned(value):
                continue

            if self._is_sf2_value(value):
                if self.soundfont is None:
                    raise ValueError("The selected SF2 is no longer loaded")
                preset = self._selected_sf2_preset(value)
                sf_zone = zone_for_note(preset, note)
                slot = sample_slot_for(sf_zone)
                drum_map[note] = make_cseq_drum(
                    self.soundfont,
                    sf_zone,
                    slot,
                    note,
                )
                continue

            drum_map[note] = drum_by_id[self._selected_global_id(value)]

        if not channel_zones and not drum_map:
            raise ValueError("Assign at least one instrument or drum first.")

        self._last_custom_samples = custom_samples
        return build_project_with_zones(
            source_midi,
            channel_zones,
            drum_map,
            loop_start_tick=loop_start_tick,
        )

    def save_cseq(self) -> None:
        try:
            cseq = self._build_cseq()
        except (ValueError, CseqEncodeError) as exc:
            messagebox.showerror("Cannot build CSEQ", str(exc))
            return

        default_name = (
            self.current_path.stem + ".cseq"
            if self.current_path is not None
            else "track.cseq"
        )
        filename = filedialog.asksaveasfilename(
            title="Save CSEQ",
            initialfile=default_name,
            defaultextension=".cseq",
            filetypes=[("Crash Forge CSEQ", "*.cseq"), ("All files", "*.*")],
        )
        if not filename:
            return
        Path(filename).write_bytes(cseq)
        messagebox.showinfo("CSEQ built", f"Wrote {len(cseq)} bytes.\n\n{filename}")

    def _browse_custom_tracks_game(self) -> None:
        initial = self.game_root_var.get()
        chosen = filedialog.askdirectory(
            title="Select Crash Forge: Racing game folder",
            initialdir=initial if Path(initial).is_dir() else None
        )
        if chosen:
            root = valid_game_root(chosen)
            if root is None:
                messagebox.showerror("Game not found",
                                     "Select the folder containing ctr-native.exe or ctr_native.exe.")
                return
            self.game_root_var.set(str(root))
            self._refresh_custom_tracks()

    def _refresh_custom_tracks(self) -> None:
        if not hasattr(self, "target_combo"):
            return
        tracks = discover_custom_tracks(self.game_root_var.get())
        self.custom_track_targets = {track.target_label: track for track in tracks}
        values = ["No level override"] + [
            f"level_{level_id:02d} | {name}"
            for level_id, name in LEVEL_TARGETS.items()
        ] + list(self.custom_track_targets)
        self.target_combo.configure(values=values)
        if self.target_var.get() not in values:
            self.target_var.set("No level override")

    def save_package(self) -> None:
        try:
            cseq = self._build_cseq()
        except (ValueError, CseqEncodeError) as exc:
            messagebox.showerror("Cannot build package", str(exc))
            return

        chosen_custom = self.custom_track_targets.get(self.target_var.get())
        if chosen_custom:
            available = discover_custom_tracks(self.game_root_var.get())
            found = next((item for item in available
                          if item.directory == chosen_custom.directory), None)
            if found is None:
                messagebox.showerror("Custom track unavailable",
                                     "This track is no longer installed or enabled. Refresh the list.")
                return
            if (found.directory / "track.cseq").is_file() and not messagebox.askyesno(
                "Replace track music", f"Replace the existing music in {found.name}?"
            ):
                return
            try:
                path = install_cseq_on_custom_track(
                    found, cseq, self._last_custom_samples
                )
            except (OSError, ValueError) as exc:
                messagebox.showerror("Cannot install track music", str(exc))
                return
            messagebox.showinfo(
                "Custom track music installed",
                f"{found.name}\n\n{path}\n\nNo retail track music was changed.",
            )
            return

        parent = filedialog.askdirectory(
            title="Choose package output root (live game: assets/mods/music)"
        )
        if not parent:
            return

        parent_path = Path(parent)
        redirected_from_music_custom = False
        if (
            parent_path.name.lower() == "music_custom"
            and parent_path.parent.name.lower() == "assets"
        ):
            parent_path = parent_path.parent / "mods" / "music"
            parent_path.mkdir(parents=True, exist_ok=True)
            redirected_from_music_custom = True

        default_slug = (
            self.current_path.stem.lower().replace(" ", "_")
            if self.current_path is not None
            else "custom_track"
        )
        slug = simpledialog.askstring("Music slug", "Stable music slug:", initialvalue=default_slug)
        if not slug:
            return
        name = simpledialog.askstring(
            "Display name",
            "Track display name:",
            initialvalue=self.current_path.stem if self.current_path else slug,
        )
        if name is None:
            return
        author = simpledialog.askstring("Author", "Author:", initialvalue="")
        if author is None:
            return

        target_value = self.target_var.get().strip()
        target = ""
        if target_value and target_value != "No level override":
            target = target_value.split("|", 1)[0].strip()

        try:
            package = build_music_package(
                parent_path,
                slug,
                name,
                author,
                cseq,
                target=target,
                custom_samples=self._last_custom_samples,
                race_intro=self.race_intro_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("Cannot build package", str(exc))
            return

        location_note = ""
        if redirected_from_music_custom:
            location_note = (
                "\n\nMUSIC_CUSTOM is reserved for OGG replacements. "
                "This CSEQ package was redirected to assets/mods/music."
            )

        messagebox.showinfo(
            "Music package built",
            f"Package created:\n\n{package}{location_note}",
        )

    def load_catalog_text(self) -> None:
        if self.catalog is None:
            self._set_text(self.catalog_text, "Retail catalog unavailable.\n")
            return

        lines = [
            f"Global melodic definitions: {len(self.catalog.instruments)}",
            f"Global drum definitions: {len(self.catalog.drums)}",
            "Instrument names come from CTR-tools CSEQ metadata; exact sample labels come from samplenames.txt.",
            f"Retail local->global mappings: {len(self.catalog.local_map)}",
            "",
            "MELODIC",
        ]
        for x in self.catalog.instruments:
            lines.append(
                f"{x.global_id:03d}  {self.catalog.instrument_display(x.global_id)}  | "
                f"GM={x.midi_program if x.midi_program >= 0 else '-'}  "
                f"transpose={x.midi_pitch:+d}  SPU={x.spu_index:03d}  "
                f"vol={x.volume:3d}  basePitch={x.base_pitch:5d}  "
                f"AD=0x{x.ad & 0xffff:04x} SR=0x{x.sr & 0xffff:04x}"
            )
        lines += [
            "",
            "Semantic names and MIDI transpose values above are the CTR-tools retail metadata used for MIDI export.",
            "Use Audition to hear one retail sound at middle C, or Preview Song to hear the MIDI arrangement.",
            "",
            "DRUMS",
        ]
        for x in self.catalog.drums:
            lines.append(
                f"{x.global_id:03d}  {self.catalog.drum_display(x.global_id)}  | "
                f"GMkey={x.midi_key if x.midi_key >= 0 else '-'}  "
                f"SPU={x.spu_index:03d}  vol={x.volume:3d}  pitch={x.pitch:5d}"
            )
        self._set_text(self.catalog_text, "\n".join(lines) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        # Test the frozen editor independently: no GUI, no Python install.
        assert FORGE_BACKGROUND.is_file(), "Bundled CSEQ background missing"
        assert FORGE_ICON_PNG.is_file(), "Bundled CSEQ icon image missing"
        assert (_BUNDLE_DIR / "assets" / "cfr_icon.ico").is_file(), (
            "Bundled CSEQ taskbar icon missing"
        )
        raise SystemExit(0)
    App().mainloop()