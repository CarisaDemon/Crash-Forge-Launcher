import os
import re
import json
import shutil
import struct
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from forge_editor_config import (find_game_installation, selected_game_directory,
                                 selected_game_explanation, valid_game_root)
from forge_editor_geometry import initial_geometry
from forge_editor_layout import WindowLayoutMemory
from forge_model_preview import PreviewPane, TextureGallery, texture_sources_from_folder
from forge_offset_guides import (build_offset_markers, read_kart_offset_values,
                                DEFAULT_MOUNT_UNITS_PER_OBJ)
from forge_model_ini_link import (
    find_linked_ini, read_linked_ini, save_linked_ini,
    LinkedIniError, LinkedIniConflict)
from crash_forge_kart_colors import install_colors, scan_palette, KartColorError
from crash_forge_model_imports import import_mod, ImportErrorMod
from crash_forge_native_tracks import install_native_track, inspect_native_track, NativeTrackError, slugify as track_slugify

APP_TITLE = "Crash Forge Model Importer"
APP_VERSION = "1.8.1"
TOOL_DIR = Path(__file__).resolve().parent

def find_source_root():
    for candidate in (TOOL_DIR, *TOOL_DIR.parents):
        if ((candidate / "CMakeLists.txt").is_file() and
                (candidate / "game").is_dir() and
                (candidate / "platform").is_dir()):
            return candidate
    return None

def find_installed_game():
    # The selected Launcher Settings path is authoritative, even while its
    # executable is being updated or temporarily missing.
    selected = selected_game_directory(source_file=__file__)
    return str(selected) if selected else ""

SOURCE_ROOT = find_source_root()
DEFAULT_GAME_ROOT = ""
RETAIL = ["crash", "cortex", "tiny", "coco", "ngin", "dingo", "polar", "pura",
          "pinstripe", "papu", "roo", "joe", "ntropy", "pen", "fake", "oxide"]
ENGINES = ["turn", "accel", "speed", "balanced"]

BG = "#0f141c"
PANEL = "#171e29"
PANEL_2 = "#1d2633"
FIELD = "#101722"
TEXT = "#edf3fb"
MUTED = "#91a1b5"
ACCENT = "#ff6a00"
ACCENT_HOVER = "#ffa34b"
SUCCESS = "#61d991"
WARNING = "#ffd166"
ERROR = "#ff6b78"
BORDER = "#2a3647"

def clean_slug(text):
    text = text.strip().lower().replace(" ", "_")
    text = re.sub(r"[^a-z0-9_]+", "", text)
    return re.sub(r"_+", "_", text).strip("_")[:15]

def parse_obj(path):
    p = Path(path)
    stats = {"v": 0, "vt": 0, "tri": 0, "vertex_colors": 0,
             "materials": set(), "groups": set(), "mtllib": None}
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    xyz = list(map(float, parts[1:4]))
                    stats["v"] += 1
                    if len(parts) >= 7:
                        try:
                            list(map(float, parts[-3:]))
                            stats["vertex_colors"] += 1
                        except ValueError:
                            pass
                    for i, val in enumerate(xyz):
                        mins[i] = min(mins[i], val)
                        maxs[i] = max(maxs[i], val)
            elif line.startswith("vt "):
                stats["vt"] += 1
            elif line.startswith("f "):
                count = len(line.split()) - 1
                if count >= 3:
                    stats["tri"] += count - 2
            elif line.startswith("usemtl "):
                stats["materials"].add(line[7:].strip())
            elif line.startswith(("o ", "g ")):
                stats["groups"].add(line[2:].strip())
            elif line.startswith("mtllib ") and not stats["mtllib"]:
                stats["mtllib"] = line[7:].strip()
    stats["extent"] = tuple(maxs[i] - mins[i] for i in range(3)) if stats["v"] else (0.0, 0.0, 0.0)
    return stats

def locate_mtl(obj_path, mtllib):
    if not mtllib:
        return None
    base = Path(obj_path).parent
    raw = mtllib.strip().strip('"')
    candidates = [base / raw, base / raw.replace("\\", os.sep), base / Path(raw.replace("\\", "/")).name]
    return next((c for c in candidates if c.exists()), None)

def parse_mtl(path):
    materials = 0
    textures = []
    with Path(path).open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("newmtl "):
                materials += 1
            elif line.startswith("map_Kd "):
                textures.append(line[7:].strip().strip('"'))
    return materials, textures

def locate_texture(mtl_path, tex):
    base = Path(mtl_path).parent
    raw = tex.strip().strip('"')
    candidates = [base / raw, base / raw.replace("\\", os.sep), base / Path(raw.replace("\\", "/")).name]
    return next((c for c in candidates if c.exists()), None)

def image_dimensions(path):
    try:
        data = Path(path).read_bytes()
        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
            return struct.unpack(">II", data[16:24])
        if data.startswith(b"BM") and len(data) >= 26:
            width = struct.unpack("<i", data[18:22])[0]
            height = abs(struct.unpack("<i", data[22:26])[0])
            return width, height
    except OSError:
        pass
    return None

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}  •  v{APP_VERSION}")
        self.geometry("1060x800")
        editor_geometry = initial_geometry(1060, 800)
        if editor_geometry:
            self.geometry(editor_geometry)
        self.minsize(640, 520)
        self.configure(bg=BG)
        self.active_section = "home"
        self.mod_obj_var = tk.StringVar()
        # Current OBJ <-> same-folder native INI. Editing the form NEVER
        # writes to disk until the explicit Save INI button is pressed.
        self._linked_ini = None
        self._linked_ini_context = None
        self._ini_loading = False
        self._ini_modified = False
        self.linked_ini_status_var = tk.StringVar(
            value="Open an OBJ to detect character.ini, kart.ini or wheels.ini")
        self.mod_name_var = tk.StringVar(value="My Custom Model")
        self.mod_id_var = tk.StringVar(value="my_custom_mod")
        self.mod_scale_var = tk.StringVar(value="1.0")
        self.mod_offsets = {axis: tk.StringVar(value="0.0") for axis in "xyz"}
        self.mod_mounts = {key: tk.StringVar(value="0.0") for key in
                           ["seat_x", "seat_y", "seat_z"] +
                           ["wheel_" + wheel + "_" + axis for wheel in ("fl","fr","rl","rr") for axis in "xyz"]}
        self.mod_exhaust_count_var = tk.StringVar(value="Default")
        self.mod_exhausts = {
            f"exhaust_{n}_{suffix}{axis}": tk.StringVar(value="0.0")
            for n in range(4) for suffix in ("", "rotation_") for axis in "xyz"}
        self.preview_offsets_visible_var = tk.BooleanVar(value=True)
        self.preview_offset_group_var = tk.StringVar(value="All")
        self.preview_fire_var = tk.BooleanVar(value=False)
        self.preview_smoke_var = tk.BooleanVar(value=False)
        self.preview_arrows_var = tk.BooleanVar(value=True)
        self.preview_offset_units_var = tk.StringVar(
            value=str(DEFAULT_MOUNT_UNITS_PER_OBJ))
        self.obj_var = tk.StringVar()
        self.name_var = tk.StringVar(value="My Character")
        self.slug_var = tk.StringVar(value="my_character")
        self.fallback_var = tk.StringVar(value="coco")
        self.engine_var = tk.StringVar(value="accel")
        self.kart_var = tk.StringVar()
        # No hard-coded personal mods, tools, or retired assets/mods paths.
        self.kart_mod_dir_var = tk.StringVar()
        self.kart_color_dir_var = tk.StringVar()
        self.kart_color_info_var = tk.StringVar(
            value="Choose any PNG/BMP skin textures. You can rename every in-game variant.")
        # Paired CTR retail-native track assets. The game loader decides
        # when to activate a package; importing never replaces retail files.
        sample_game = find_installed_game()
        self.track_game_var = tk.StringVar(value=sample_game)
        self.track_lev_var = tk.StringVar()
        self.track_vrm_var = tk.StringVar()
        self.track_name_var = tk.StringVar(value="My Custom Track")
        self.track_slug_var = tk.StringVar(value="my_custom_track")
        self.track_author_var = tk.StringVar()
        self.track_description_var = tk.StringVar()
        self.track_info_var = tk.StringVar(
            value="LEV + VRM only. Import is staged; does not replace Crash Cove or start the game.")
        self.icon_mode_var = tk.StringVar(value="retail")
        self.retail_icon_var = tk.StringVar(value="coco")
        self.custom_icon_var = tk.StringVar()
        self.scale_var = tk.StringVar(value="1.0")
        self.ox_var = tk.StringVar(value="0.0")
        self.oy_var = tk.StringVar(value="0.0")
        self.oz_var = tk.StringVar(value="0.0")
        self.game_var = tk.StringVar(value=find_installed_game())
        self.output_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.last_stats = None
        self.last_dest = None
        self.icon_preview = None
        self._preview_update_job = None
        self._columns_stacked = None
        self._compact_controls = None
        self._set_windows_identity()
        self._setup_style()
        self._build_ui()
        self._install_mousewheel_router()
        self.game_var.trace_add("write", self._on_game_path_change)
        self.mod_exhaust_count_var.trace_add("write", self._refresh_exhaust_controls)
        for value in (self.mod_scale_var, self.scale_var, self.ox_var, self.oy_var,
                      self.oz_var, *self.mod_offsets.values(), *self.mod_mounts.values(),
                      *self.mod_exhausts.values(), self.preview_offsets_visible_var,
                      self.preview_offset_group_var, self.preview_offset_units_var,
                      self.preview_fire_var,self.preview_smoke_var,
                      self.preview_arrows_var):
            value.trace_add("write", self._refresh_offset_guides)
        self._refresh_exhaust_controls()
        tracked=(self.name_var,self.slug_var,self.fallback_var,self.engine_var,
                 self.kart_var,self.scale_var,self.ox_var,self.oy_var,self.oz_var,
                 self.icon_mode_var,self.retail_icon_var,
                 self.custom_icon_var,self.mod_name_var,self.mod_id_var,
                 self.mod_scale_var,self.mod_exhaust_count_var,
                 *self.mod_offsets.values(),*self.mod_mounts.values(),
                 *self.mod_exhausts.values())
        for value in tracked:
            value.trace_add("write",self._update_ini_dirty)
        self.bind("<Control-s>",self._save_ini_shortcut)
        for value in (self.obj_var, self.mod_obj_var, self.track_lev_var):
            value.trace_add("write", self._schedule_model_preview)
        self._sync_output_path()
        self._update_icon_controls()
        self._show_section("home")
        self.layout = WindowLayoutMemory(self, "model-importer")
        self.layout.register_pane("preview_textures", self.preview_split)
        # Character columns use a draggable custom sash, preserving the
        # existing stacked view on small 4:3 windows.
        self._char_ratio = self.layout.get_number("character_columns_percent",50,20,80)
        self.layout.start()
        self.after(320,self._restore_preview_layout)

    def _set_windows_identity(self):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CrashForge.Racing.ModelImporter")
        except (AttributeError, OSError):
            pass
        try:
            icon = self._forge_art_file("icons/cfr_icon.ico")
            if icon is not None:
                self.iconbitmap(str(icon))
        except (OSError, tk.TclError):
            pass
        self._taskbar_photo = None
        logo = self._forge_art_file("icons/cfr_icon.png")
        if logo is not None:
            try:
                from PIL import Image, ImageTk
                self._taskbar_photo = ImageTk.PhotoImage(
                    Image.open(logo).convert("RGBA")
                )
                self.iconphoto(True, self._taskbar_photo)
            except (ImportError, OSError, tk.TclError):
                pass

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel2.TFrame", background=PANEL_2)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 22))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=PANEL, foreground=ACCENT, font=("Segoe UI Semibold", 11))
        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, bordercolor=BORDER, insertcolor=TEXT, padding=7)
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                        arrowcolor=TEXT, bordercolor=BORDER, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", TEXT)])
        style.configure("TRadiobutton", background=PANEL, foreground=TEXT)
        style.map("TRadiobutton", background=[("active", PANEL)], foreground=[("active", TEXT)])
        style.configure("TButton", background=PANEL_2, foreground=TEXT, bordercolor=BORDER, padding=(12, 7))
        style.map("TButton", background=[("active", "#283447")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#161616",
                        bordercolor=ACCENT, font=("Segoe UI Semibold", 10), padding=(16, 9))
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER)])
        style.configure("Ghost.TButton", background=PANEL, foreground=MUTED, bordercolor=BORDER)
        style.configure("TSeparator", background=BORDER)

    def _card(self, parent):
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        inner = ttk.Frame(outer, style="Panel.TFrame", padding=14)
        inner.pack(fill="both", expand=True)
        return outer, inner

    def _section_title(self, parent, title, subtitle=None):
        ttk.Label(parent, text=title, style="Section.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(parent, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        else:
            ttk.Separator(parent).pack(fill="x", pady=(5, 10))

    def _field(self, parent, label, variable, row, widget="entry", values=None):
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        if widget == "combo":
            w = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        else:
            w = ttk.Entry(parent, textvariable=variable)
        w.grid(row=row, column=1, sticky="ew", pady=5)
        parent.columnconfigure(1, weight=1)
        return w

    def _build_ui(self):
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)

        self.scroll_canvas = tk.Canvas(shell, bg=BG, highlightthickness=0, bd=0)
        self.scroll_canvas.pack(side="left", fill="both", expand=True)
        self.page_scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.scroll_canvas.yview)
        self.page_scrollbar.pack(side="right", fill="y")
        self.scroll_canvas.configure(yscrollcommand=self.page_scrollbar.set)

        root = ttk.Frame(self.scroll_canvas, padding=(20, 16))
        self._canvas_window = self.scroll_canvas.create_window((0, 0), window=root, anchor="nw")
        root.bind("<Configure>", self._on_content_configure)
        self.scroll_canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind("<MouseWheel>", self._on_mousewheel, add="+")
        self.bind("<Button-4>", self._on_mousewheel, add="+")
        self.bind("<Button-5>", self._on_mousewheel, add="+")

        self.art_banner = tk.Frame(root, bg=BG, height=148)
        self.art_banner.pack(fill="x", pady=(0,12))
        self.art_banner.pack_propagate(False)
        self.art_banner_image = tk.Label(self.art_banner, bg=BG, bd=0)
        self.art_banner_image.pack(fill="both", expand=True)
        self.art_banner.bind("<Configure>", self._refresh_art_banner)
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 14))
        title_box = ttk.Frame(header)
        title_box.pack(side="left")
        ttk.Label(title_box, text="Crash Forge Model Importer", style="Title.TLabel").pack(anchor="w")
        self.subtitle_label = ttk.Label(
            title_box,
            text="Characters, modular kart colors and native CTR LEV/VRM track packages.",
            style="Subtitle.TLabel",
            justify="left")
        self.subtitle_label.pack(anchor="w", pady=(2, 0))
        status = tk.Label(header, textvariable=self.status_var, bg=PANEL_2, fg=ACCENT,
                          font=("Segoe UI Semibold", 9), padx=12, pady=6)
        status.pack(side="right", anchor="n")
        self._header_frame = header
        self._title_box = title_box
        self._status_label = status

        self._content_root = root
        self.home_frame = ttk.Frame(root)
        self.home_frame.pack(fill="x", pady=(0, 16))
        ttk.Label(self.home_frame, text="WHAT WOULD YOU LIKE TO IMPORT?",
                  style="Title.TLabel").pack(anchor="w", pady=(4, 16))
        self.home_cards = tk.Frame(self.home_frame, bg=BG)
        self.home_cards.pack(fill="x")
        for i, (section, label, detail) in enumerate((
                ("character", "CHARACTER", "Custom racers and character settings"),
                ("kart", "KART", "Modular karts and optional color palettes"),
                ("wheels", "WHEELS", "Independent sets of four rotating wheels"),
                ("tracks", "TRACKS", "Native CTR LEV + VRM packages"))):
            tile = tk.Frame(self.home_cards, bg=PANEL, highlightbackground=BORDER,
                            highlightthickness=1, padx=20, pady=22)
            tile.grid(row=i//2, column=i%2, sticky="nsew", padx=6, pady=6)
            tk.Button(tile, text=label, bg=ACCENT, fg="#151515",
                      activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
                      font=("Segoe UI Semibold", 14),
                      command=lambda section=section: self._show_section(section)).pack(fill="x")
            tk.Label(tile, text=detail, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 10), wraplength=330).pack(pady=(10,0))
        self.home_cards.grid_columnconfigure(0, weight=1)
        self.home_cards.grid_columnconfigure(1, weight=1)
        self.section_navigation = tk.Frame(root, bg=BG)
        self.section_navigation.pack(fill="x", pady=(0, 12))
        for section,label in (("home","HOME"),("character","CHARACTER"),
                              ("kart","KART"),("wheels","WHEELS"),("tracks","TRACKS")):
            tk.Button(self.section_navigation, text=label, bg=PANEL_2, fg=TEXT,
                      activebackground=ACCENT, relief="flat", cursor="hand2",
                      font=("Segoe UI Semibold", 9), padx=13, pady=9,
                      command=lambda section=section: self._show_section(section)).pack(side="left",padx=(0,5))
        self.section_heading = tk.Label(root, text="", bg=BG, fg=ACCENT,
                                        font=("Segoe UI Semibold", 18), anchor="w")
        self.section_heading.pack(fill="x", pady=(0,12))
        source_border, source = self._card(root)
        source_border.pack(fill="x", pady=(0, 12))
        self.char_source_card = source_border
        self._section_title(source, "MODEL SOURCE", "Choose the OBJ model used by the custom racer.")
        source_line = ttk.Frame(source, style="Panel.TFrame")
        source_line.pack(fill="x")
        ttk.Entry(source_line, textvariable=self.obj_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(source_line, text="Browse OBJ...", command=self.choose_obj).pack(side="left")

        track_border, tracks = self._card(root)
        track_border.pack(fill="x", pady=(0, 12))
        self.track_card = track_border
        self._section_title(
            tracks, "CUSTOM TRACKS  /  .LEV + .VRM",
            "Native CTR geometry, collisions and textures only. OBJ/MTL tracks are unsupported.")
        line = ttk.Frame(tracks, style="Panel.TFrame")
        line.pack(fill="x", pady=(4, 2))
        ttk.Label(line, text="Level (.lev)", style="Panel.TLabel",
                  width=15).pack(side="left")
        ttk.Entry(line, textvariable=self.track_lev_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line, text="Browse LEV...", command=self._choose_track_lev).pack(
            side="right")
        line = ttk.Frame(tracks, style="Panel.TFrame")
        line.pack(fill="x", pady=2)
        ttk.Label(line, text="Textures (.vrm)", style="Panel.TLabel",
                  width=15).pack(side="left")
        ttk.Entry(line, textvariable=self.track_vrm_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line, text="Browse VRM...", command=self._choose_track_vrm).pack(
            side="right")
        meta = ttk.Frame(tracks, style="Panel.TFrame")
        meta.pack(fill="x", pady=(6, 0))
        self._field(meta, "Track name", self.track_name_var, 0)
        self._field(meta, "Track ID", self.track_slug_var, 1)
        ttk.Button(meta, text="Auto", command=self._auto_track_slug,
                   style="Ghost.TButton").grid(row=1, column=2, padx=(8, 0))
        self._field(meta, "Author (optional)", self.track_author_var, 2)
        self._field(meta, "Description", self.track_description_var, 3)
        line = ttk.Frame(tracks, style="Panel.TFrame")
        line.pack(fill="x", pady=(7, 3))
        ttk.Label(line, text="Game folder", style="Panel.TLabel",
                  width=15).pack(side="left")
        ttk.Entry(line, textvariable=self.track_game_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Label(line, text="(Launcher Settings)",style="Muted.TLabel").pack(side="right")
        line = ttk.Frame(tracks, style="Panel.TFrame")
        line.pack(fill="x", pady=(6, 2))
        ttk.Button(line, text="Validate Pair", command=self._validate_native_track).pack(
            side="left")
        ttk.Button(line, text="Install Track Package", command=self._install_native_track,
                   style="Accent.TButton").pack(side="right")
        ttk.Label(tracks, textvariable=self.track_info_var, style="Muted.TLabel",
                  wraplength=860, justify="left").pack(fill="x", anchor="w", pady=(5, 0))

        palette_border, palette = self._card(root)
        palette_border.pack(fill="x", pady=(0, 12))
        self.palette_card = palette_border
        self._section_title(
            palette, "KART TEXTURE VARIANTS",
            "One native OBJ/MTL. Find any atlas color or pattern; preview and rename each skin for the game.")
        kart_row = ttk.Frame(palette, style="Panel.TFrame")
        kart_row.pack(fill="x", pady=3)
        ttk.Label(kart_row, text="Existing kart", style="Panel.TLabel", width=16).pack(side="left")
        ttk.Entry(kart_row, textvariable=self.kart_mod_dir_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(kart_row, text="Choose...", command=self._choose_kart_mod).pack(side="right")
        color_row = ttk.Frame(palette, style="Panel.TFrame")
        color_row.pack(fill="x", pady=3)
        ttk.Label(color_row, text="Color textures", style="Panel.TLabel", width=16).pack(side="left")
        ttk.Entry(color_row, textvariable=self.kart_color_dir_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(color_row, text="Choose...", command=self._choose_kart_colors).pack(side="right")
        palette_actions = ttk.Frame(palette, style="Panel.TFrame")
        palette_actions.pack(fill="x", pady=(6, 2))
        ttk.Button(palette_actions, text="Scan Colors",
                   command=self._scan_kart_colors).pack(side="left")
        ttk.Button(palette_actions, text="Apply to Existing Kart",
                   command=self._apply_kart_colors,
                   style="Accent.TButton").pack(side="right")
        ttk.Label(palette, textvariable=self.kart_color_info_var,
                  style="Muted.TLabel", wraplength=860, justify="left").pack(
                      fill="x", anchor="w", pady=(4, 0))
        self.kart_colors_gallery=TextureGallery(
            palette,editable=True,on_preview=self._preview_texture)
        # Hide the otherwise large empty texture gallery until a scan finds
        # variants. This leaves more room for the model viewport on small UI.
        self.kart_colors_gallery.pack_forget()

        columns = ttk.Frame(root)
        columns.pack(fill="both", expand=True)
        self.char_columns = columns
        columns.columnconfigure(0, weight=1, uniform="main")
        columns.columnconfigure(1, weight=0, uniform="")
        columns.columnconfigure(2, weight=1, uniform="main")
        columns.rowconfigure(0, weight=1)
        left = ttk.Frame(columns)
        right = ttk.Frame(columns)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        self._char_sash = tk.Frame(columns,bg=ACCENT,width=9,cursor="sb_h_double_arrow")
        self._char_sash.grid(row=0,column=1,sticky="ns")
        self._char_sash.bind("<B1-Motion>",self._drag_character_column)
        self._char_sash.bind("<ButtonRelease-1>",self._remember_character_column)
        self._columns_frame = columns
        self._left_column = left
        self._right_column = right

        char_border, char = self._card(left)
        char_border.pack(fill="x", pady=(0, 12))
        self._section_title(char, "CHARACTER", "Basic roster and driving settings.")
        char_fields = ttk.Frame(char, style="Panel.TFrame")
        char_fields.pack(fill="x")
        self._field(char_fields, "Display name", self.name_var, 0)
        slug_entry = self._field(char_fields, "Asset name", self.slug_var, 1)
        ttk.Button(char_fields, text="Auto", command=self.auto_slug, style="Ghost.TButton").grid(row=1, column=2, padx=(8, 0))
        self._field(char_fields, "Retail fallback", self.fallback_var, 2, "combo", RETAIL)
        self._field(char_fields, "Engine class", self.engine_var, 3, "combo", ENGINES)
        self._field(char_fields, "Kart asset (optional)", self.kart_var, 4)

        transform_border, transform = self._card(left)
        transform_border.pack(fill="x", pady=(0, 12))
        self._section_title(transform, "MODEL TRANSFORM", "Fine-tune scale and local position without re-exporting.")
        transform_fields = ttk.Frame(transform, style="Panel.TFrame")
        transform_fields.pack(fill="x")
        self._field(transform_fields, "Scale", self.scale_var, 0)
        self._field(transform_fields, "Offset X", self.ox_var, 1)
        self._field(transform_fields, "Offset Y", self.oy_var, 2)
        self._field(transform_fields, "Offset Z", self.oz_var, 3)

        output_border, output = self._card(left)
        output_border.pack(fill="x")
        self._section_title(
            output,
            "GAME INSTALLATION",
            "Choose the game folder or ctr_native.exe. The mods path is detected automatically.")
        game_line = ttk.Frame(output, style="Panel.TFrame")
        game_line.pack(fill="x")
        ttk.Entry(game_line, textvariable=self.game_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(game_line, text="Game Folder...", command=self.choose_game_folder).pack(side="left")
        ttk.Button(game_line, text="ctr_native.exe...", command=self.choose_game_exe).pack(
            side="left", padx=(6, 0))

        mods_line = ttk.Frame(output, style="Panel.TFrame")
        mods_line.pack(fill="x", pady=(8, 0))
        ttk.Label(mods_line, text="Mods path", style="Panel.TLabel", width=14).pack(side="left")
        self.output_entry = ttk.Entry(mods_line, textvariable=self.output_var, state="readonly")
        self.output_entry.pack(side="left", fill="x", expand=True)

        icon_border, icon = self._card(right)
        icon_border.pack(fill="x", pady=(0, 12))
        self._section_title(icon, "ROSTER ICON", "Use a retail portrait or prepare a custom image for the mod.")
        modes = ttk.Frame(icon, style="Panel.TFrame")
        modes.pack(fill="x")
        ttk.Radiobutton(modes, text="Retail icon", variable=self.icon_mode_var, value="retail",
                        command=self._update_icon_controls).pack(side="left", padx=(0, 18))
        ttk.Radiobutton(modes, text="Custom image", variable=self.icon_mode_var, value="custom",
                        command=self._update_icon_controls).pack(side="left")
        retail_line = ttk.Frame(icon, style="Panel.TFrame")
        retail_line.pack(fill="x", pady=(10, 6))
        ttk.Label(retail_line, text="Retail icon", style="Panel.TLabel", width=14).pack(side="left")
        self.retail_icon_combo = ttk.Combobox(retail_line, textvariable=self.retail_icon_var,
                                              values=RETAIL, state="readonly")
        self.retail_icon_combo.pack(side="left", fill="x", expand=True)

        custom_line = ttk.Frame(icon, style="Panel.TFrame")
        custom_line.pack(fill="x", pady=6)
        ttk.Label(custom_line, text="Custom file", style="Panel.TLabel", width=14).pack(side="left")
        self.custom_icon_entry = ttk.Entry(custom_line, textvariable=self.custom_icon_var)
        self.custom_icon_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.custom_icon_button = ttk.Button(custom_line, text="Browse...", command=self.choose_icon)
        self.custom_icon_button.pack(side="left")

        preview_box = tk.Frame(icon, bg=FIELD, highlightbackground=BORDER, highlightthickness=1,
                               width=148, height=148)
        preview_box.pack(fill="x", pady=(10, 8))
        preview_box.pack_propagate(False)
        self.preview_label = tk.Label(preview_box, text="No custom icon selected", bg=FIELD, fg=MUTED,
                                      font=("Segoe UI", 9))
        self.preview_label.pack(expand=True)
        self.icon_note = ttk.Label(
            icon,
            text="Note: Crash Forge Racing stores custom icon paths, but roster rendering may still use the retail fallback until custom icon rendering is wired in.",
            style="Muted.TLabel", wraplength=440, justify="left")
        self.icon_note.pack(anchor="w", pady=(2, 0))

        validation_border, validation = self._card(right)
        validation_border.pack(fill="both", expand=True)
        self._section_title(validation, "VALIDATION", "Checks OBJ limits, materials, textures and wheel groups.")
        report_box = ttk.Frame(validation, style="Panel.TFrame")
        report_box.pack(fill="both", expand=True)
        self.report = tk.Text(report_box, wrap="word", height=13, bg=FIELD, fg=TEXT,
                              insertbackground=TEXT, relief="flat", padx=10, pady=10,
                              font=("Consolas", 9))
        report_scrollbar = ttk.Scrollbar(report_box, orient="vertical", command=self.report.yview)
        self.report.configure(yscrollcommand=report_scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)
        report_scrollbar.pack(side="right", fill="y")
        self.report.tag_configure("ok", foreground=SUCCESS)
        self.report.tag_configure("warn", foreground=WARNING)
        self.report.tag_configure("error", foreground=ERROR)
        self.report.insert("end", "Choose an OBJ model to begin.\n")
        self.report.configure(state="disabled")

        self.mod_card, model = self._card(root)
        self.mod_card.pack(fill="x", pady=(0, 12))
        self._section_title(model, "MODULAR MODEL IMPORT", "Wavefront OBJ + local MTL/textures")
        fields = ttk.Frame(model, style="Panel.TFrame")
        fields.pack(fill="x")
        line = ttk.Frame(model, style="Panel.TFrame")
        line.pack(fill="x", pady=5)
        ttk.Entry(line, textvariable=self.mod_obj_var).pack(side="left", fill="x", expand=True, padx=(0,8))
        ttk.Button(line, text="Browse OBJ...", command=self._choose_mod_obj).pack(side="right")
        self._field(fields, "Display name", self.mod_name_var, 0)
        self._field(fields, "Mod ID", self.mod_id_var, 1)
        self._field(fields, "Scale", self.mod_scale_var, 2)
        for i, axis in enumerate("xyz", 3):
            self._field(fields, "Offset " + axis.upper(), self.mod_offsets[axis], i)
        self.mount_frame = ttk.Frame(model, style="Panel.TFrame")
        self.mount_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(self.mount_frame, text="KART MOUNTS (SEAT / FOUR WHEELS)",
                  style="Section.TLabel").pack(anchor="w")
        mount_fields = ttk.Frame(self.mount_frame, style="Panel.TFrame")
        mount_fields.pack(fill="x")
        for i, (key,var) in enumerate(self.mod_mounts.items()):
            self._field(mount_fields, key.replace("_"," ").title(), var, i)
        # The game accepts up to four exhaust outlets with separate XYZ and
        # orientation. Default retains retail exhaust behavior in existing karts.
        exhaust_row=ttk.Frame(self.mount_frame,style="Panel.TFrame")
        exhaust_row.pack(fill="x",pady=(13,5))
        ttk.Label(exhaust_row,text="EXHAUST OUTLETS",style="Section.TLabel").pack(side="left")
        ttk.Label(exhaust_row,text="Count",style="Panel.TLabel").pack(side="left",padx=(18,6))
        self.exhaust_count_box=ttk.Combobox(
            exhaust_row,textvariable=self.mod_exhaust_count_var,
            values=("Default","0","1","2","3","4"),state="readonly",width=10)
        self.exhaust_count_box.pack(side="left")
        self.exhaust_guide_frames=[]
        for n in range(4):
            panel=ttk.Frame(self.mount_frame,style="Panel.TFrame")
            ttk.Label(panel,text=f"EXHAUST {n+1}  /  POSITION & DIRECTION",
                      style="Section.TLabel").pack(anchor="w",pady=(4,3))
            pairs=ttk.Frame(panel,style="Panel.TFrame")
            pairs.pack(fill="x")
            for column,prefix,title in ((0,"","Position"),(1,"rotation_","Rotation")):
                group=ttk.Frame(pairs,style="Panel.TFrame")
                group.grid(row=0,column=column,sticky="nsew",
                           padx=(0,9) if column==0 else (9,0))
                ttk.Label(group,text=title+" XYZ",style="Muted.TLabel").pack(anchor="w")
                fields=ttk.Frame(group,style="Panel.TFrame")
                fields.pack(fill="x")
                for k,axis in enumerate("xyz"):
                    key=f"exhaust_{n}_{prefix}{axis}"
                    self._field(fields,axis.upper(),self.mod_exhausts[key],k)
            pairs.columnconfigure(0,weight=1)
            pairs.columnconfigure(1,weight=1)
            self.exhaust_guide_frames.append(panel)
        ttk.Label(self.mount_frame,text="Set exhaust count to show its markers and rotation arrows.",
                  style="Muted.TLabel").pack(anchor="w",pady=(3,0))
        # Texture variants live in ONE kart-only section (see palette_card).
        # Do not duplicate the same color folder picker under Import Model.
        ttk.Label(model, text="Use the game installation selected in the Character page.",
                  style="Muted.TLabel").pack(anchor="w", pady=(10,5))
        ttk.Button(model, text="Import Model", command=self._import_mod,
                   style="Accent.TButton").pack(anchor="e", pady=(8,0))
        self.preview_card, visual = self._card(root)
        self.preview_card.pack(fill="x",pady=(0,12))
        self._section_title(visual,"LIVE 3D PREVIEW",
            "Drag the orange separator to resize the textured model and the thumbnails.")
        config_row=ttk.Frame(visual,style="Panel.TFrame")
        config_row.pack(fill="x",pady=(3,7))
        ttk.Label(config_row,textvariable=self.linked_ini_status_var,
                  style="Muted.TLabel",wraplength=590,justify="left").pack(
                      side="left",fill="x",expand=True,padx=(0,8))
        self.reload_linked_ini_button=ttk.Button(
            config_row,text="Reload INI",command=self._reload_linked_ini,
            style="Ghost.TButton",state="disabled")
        self.reload_linked_ini_button.pack(side="right",padx=(5,0))
        self.save_linked_ini_button=ttk.Button(
            config_row,text="Save INI",command=self._save_linked_ini,
            style="Accent.TButton",state="disabled")
        self.save_linked_ini_button.pack(side="right",padx=(5,0))
        guide_row=ttk.Frame(visual,style="Panel.TFrame")
        guide_row.pack(fill="x",pady=(2,5))
        ttk.Checkbutton(guide_row,text="Show offsets",
                        variable=self.preview_offsets_visible_var).pack(side="left")
        ttk.Label(guide_row,text="Markers:",style="Muted.TLabel").pack(
            side="left",padx=(12,3))
        ttk.Combobox(guide_row,textvariable=self.preview_offset_group_var,
                     values=("All","Model","Seat","Wheels","Exhaust"),
                     state="readonly",width=9).pack(side="left")
        ttk.Label(guide_row,text="Native scale: 248.05 CTR / OBJ",
                  style="Muted.TLabel").pack(side="left",padx=(14,4))
        fx_row=ttk.Frame(visual,style="Panel.TFrame")
        fx_row.pack(fill="x",pady=(2,4))
        ttk.Label(fx_row,text="EXHAUST PREVIEW",style="Section.TLabel").pack(
            side="left",padx=(0,12))
        ttk.Checkbutton(fx_row,text="Fire",variable=self.preview_fire_var).pack(
            side="left",padx=(0,12))
        ttk.Checkbutton(fx_row,text="Smoke",variable=self.preview_smoke_var).pack(
            side="left",padx=(0,12))
        ttk.Checkbutton(fx_row,text="Direction arrows",
                        variable=self.preview_arrows_var).pack(side="left")
        ttk.Label(visual,text="CTR turbo: 8 original flame-core frames at maximum size. "
                  "Broken translucent sheet layers hidden in this QA preview. "
                  "Smoke: dustpuff00 with soft transparent edges and native 30Hz motion.",
                  style="Muted.TLabel",wraplength=900).pack(fill="x")
        ttk.Button(visual,text="FRAME OFFSETS",style="Ghost.TButton",
                   command=lambda:self.model_viewer.frame_markers()).pack(
                       anchor="e",pady=(3,1))
        self.preview_split = tk.PanedWindow(
            visual,orient="vertical",bg=ACCENT,bd=0,relief="flat",
            sashwidth=10,sashrelief="flat",showhandle=True,handlesize=13,
            opaqueresize=False,height=510)
        self.preview_split.pack(fill="both",expand=True,pady=(7,0))
        self._model_preview_region=tk.Frame(self.preview_split,bg=PANEL)
        self.preview_split.add(self._model_preview_region,minsize=125,stretch="always")
        self.model_viewer = PreviewPane(self._model_preview_region,width=820,height=345)
        self.model_viewer.pack(fill="both",expand=True)
        self._texture_preview_region=tk.Frame(self.preview_split,bg=PANEL)
        self.preview_split.add(self._texture_preview_region,minsize=90,stretch="always")
        self.preview_textures=TextureGallery(
            self._texture_preview_region,editable=False,
            on_preview=self._preview_texture)
        self.preview_textures.pack(fill="both",expand=True)
        height_row=ttk.Frame(visual,style="Panel.TFrame")
        height_row.pack(fill="x",pady=(7,0))
        ttk.Label(height_row,text="Preview panel height",style="Muted.TLabel").pack(side="left")
        self._preview_height_var=tk.IntVar(value=510)
        self._preview_height_slider=ttk.Scale(
            height_row,from_=320,to=900,orient="horizontal",
            command=self._resize_preview_height)
        self._preview_height_slider.pack(side="left",fill="x",expand=True,padx=(8,10))
        ttk.Label(height_row,text="DRAG TO RESIZE",style="Muted.TLabel").pack(side="right")
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(14, 0))
        self.analyze_button = ttk.Button(actions, text="Analyze / Validate", command=self.analyze)
        self.analyze_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="Open Generated Folder", command=self.open_generated,
                                      state="disabled")
        self.open_button.pack(side="left", padx=(8, 0))
        self.build_button = ttk.Button(actions, text="Build Mod", command=self.build_mod, style="Accent.TButton")
        self.build_button.pack(side="right")
        self._actions_frame = actions
        self._load_forge_background()
        self.after_idle(lambda: self._update_responsive_layout(self.winfo_width()))

    def _restore_preview_layout(self):
        if not self.winfo_exists():
            return
        height=self.layout.get_number("preview_panel_height",510,320,900)
        self.preview_split.configure(height=height)
        self._preview_height_slider.set(height)
        self.layout.restore_panes()
        self._update_responsive_layout(self.scroll_canvas.winfo_width())
        self._apply_character_columns()

    def _resize_preview_height(self,value):
        try:
            height=max(320,min(900,int(float(value))))
        except (TypeError,ValueError):
            return
        self.preview_split.configure(height=height)
        if hasattr(self,"layout"):
            self.layout.put_number("preview_panel_height",height)

    def _drag_character_column(self,event):
        if self._columns_stacked or not hasattr(self,"_char_sash"):
            return
        width=max(1,self._columns_frame.winfo_width())
        x=event.x_root-self._columns_frame.winfo_rootx()
        self._char_ratio=max(20,min(80,round(x*100/width)))
        self._apply_character_columns()

    def _apply_character_columns(self):
        if self._columns_stacked:
            return
        fraction=getattr(self,"_char_ratio",50)
        self._columns_frame.columnconfigure(0,weight=fraction)
        self._columns_frame.columnconfigure(2,weight=100-fraction)

    def _remember_character_column(self,_event=None):
        if hasattr(self,"layout"):
            self.layout.put_number(
                "character_columns_percent",getattr(self,"_char_ratio",50))

    def _refresh_art_banner(self, event=None):
        art = getattr(self, "_forge_bg_source", None)
        if art is None:
            return
        try:
            from PIL import Image, ImageTk, ImageEnhance
            width = max(1, self.art_banner.winfo_width())
            height = max(1, self.art_banner.winfo_height())
            if width < 15 or height < 15:
                return
            scale = max(width / art.width, height / art.height)
            src = art.resize((max(width, int(art.width*scale)),
                              max(height, int(art.height*scale))), Image.Resampling.LANCZOS)
            x=(src.width-width)//2
            y=(src.height-height)//2
            src=src.crop((x,y,x+width,y+height))
            self._forge_banner_photo = ImageTk.PhotoImage(src)
            self.art_banner_image.configure(image=self._forge_banner_photo)
        except (ImportError, OSError, tk.TclError):
            pass

    @staticmethod
    def _forge_art_file(relative):
        """Find garage artwork in both portable EXEs and the local dev tree."""
        paths = []
        bundled_root = getattr(sys, "_MEIPASS", None)
        if bundled_root:
            paths.append(Path(bundled_root) / "assets" / relative)
            paths.append(Path(bundled_root) / "model_importer_art" / relative)
        paths.extend((
            TOOL_DIR.parent / "Crash Forge Launcher" / "assets" / relative,
            TOOL_DIR.parents[1] / "assets" / relative,
            TOOL_DIR / "assets" / relative,
        ))
        return next((p for p in paths if p.is_file()), None)

    def _load_forge_background(self):
        art = self._forge_art_file("Fondo.png")
        try:
            from PIL import Image, ImageTk, ImageEnhance
            if art is None:
                raise OSError("Bundled garage background not available")
            original = Image.open(art).convert("RGB")
            self._forge_bg_source = ImageEnhance.Brightness(original).enhance(0.78)
            self.after_idle(self._refresh_art_banner)
            self._forge_bg = ImageEnhance.Brightness(original).enhance(0.27)
            self._forge_bg_render = None
            self.scroll_canvas.bind("<Configure>", self._paint_background, add="+")
            self._paint_background()
        except (ImportError, OSError, tk.TclError):
            self._forge_bg = None

    def _paint_background(self, _event=None):
        bg = getattr(self, "_forge_bg", None)
        if bg is None:
            return
        from PIL import ImageTk, Image
        width = max(1, self.scroll_canvas.winfo_width())
        height = max(1, self.scroll_canvas.winfo_height())
        if width < 10 or height < 10:
            return
        image = bg.resize((width, height), Image.Resampling.LANCZOS)
        self._forge_bg_render = ImageTk.PhotoImage(image)
        self.scroll_canvas.delete("forge_background")
        self.scroll_canvas.create_image(0, 0, image=self._forge_bg_render,
                                        anchor="nw", tags="forge_background")
        self.scroll_canvas.tag_lower("forge_background")

    def _show_section(self, section):
        if section not in ("home", "character", "kart", "wheels", "tracks"):
            return
        self.active_section = section
        for item in (self.home_frame, self.char_source_card, self.track_card,
                     self.palette_card, self.char_columns, self.mod_card,
                     self.preview_card,self._actions_frame):
            item.pack_forget()
        self.section_heading.configure(text={
            "home":"", "character":"CHARACTER IMPORTER",
            "kart":"KART IMPORTER", "wheels":"WHEELS IMPORTER",
            "tracks":"TRACK IMPORTER"}[section])
        if section == "home":
            self.home_frame.pack(fill="x", pady=(0, 18), after=self.section_heading)
        elif section == "character":
            self.char_source_card.pack(fill="x", pady=(0,12), after=self.section_heading)
            self.char_columns.pack(fill="both", expand=True, after=self.char_source_card)
            self.preview_card.pack(fill="x",pady=(0,12),after=self.char_columns)
            self._actions_frame.pack(fill="x", pady=(14,0), after=self.preview_card)
        elif section == "tracks":
            self.track_card.pack(fill="x", pady=(0,12), after=self.section_heading)
            self.preview_card.pack(fill="x",pady=(0,12),after=self.track_card)
        else:
            self.mod_card.pack(fill="x", pady=(0,12), after=self.section_heading)
            if section == "kart":
                self.mount_frame.pack(fill="x", pady=(10,0))
                self.palette_card.pack(fill="x", pady=(0,12), after=self.mod_card)
                self.preview_card.pack(fill="x",pady=(0,12),after=self.palette_card)
            else:
                self.mount_frame.pack_forget()
                self.preview_card.pack(fill="x",pady=(0,12),after=self.mod_card)
        self._sync_preview_panes(section)
        self._refresh_current_preview()
        if section != "home" and hasattr(self,"layout"):
            self.after(80,self.layout.restore_panes)
        self.scroll_canvas.yview_moveto(0)
        self._on_content_configure()


    @staticmethod
    def _model_from_kart_folder(folder):
        folder=Path(folder)
        models=sorted(folder.glob("*.obj"),key=lambda p:p.name.casefold())
        if not models:
            return None
        ini=folder/"kart.ini"
        if ini.is_file():
            try:
                preferred=read_linked_ini("kart",ini).fields.get("asset_name","")
                for model in models:
                    if model.stem.casefold()==preferred.casefold():
                        return model
            except (OSError,LinkedIniError):
                pass
        return models[0]

    def _ini_values(self):
        kind=self.active_section
        if kind=="character":
            icon=("retail:"+self.retail_icon_var.get()
                  if self.icon_mode_var.get()=="retail" else
                  self.custom_icon_var.get().strip())
            return {
                "name":self.name_var.get(),
                "asset_name":self.slug_var.get(),
                "fallback_retail":self.fallback_var.get(),
                "engine":self.engine_var.get(),
                "kart":self.kart_var.get(),
                "modular_body":(
                    self._linked_ini.fields.get("modular_body","true")
                    if self._linked_ini is not None and
                       self._linked_ini.kind=="character" else "true"),
                "icon":icon,
                "scale":self.scale_var.get(),
                **{"offset_"+a:v.get() for a,v in
                   zip("xyz",(self.ox_var,self.oy_var,self.oz_var))},
            }
        return {
            "name":self.mod_name_var.get(),
            "asset_name":self.mod_id_var.get(),
            "scale":self.mod_scale_var.get(),
            **{"offset_"+a:v.get() for a,v in self.mod_offsets.items()},
            **({**{a:v.get() for a,v in self.mod_mounts.items()},
               **{a:v.get() for a,v in self.mod_exhausts.items()},
               "exhaust_count":self.mod_exhaust_count_var.get()}
               if kind=="kart" else {}),
        }

    def _update_ini_dirty(self,*_):
        if self._ini_loading or not hasattr(self,"save_linked_ini_button"):
            return
        link=self._linked_ini
        if link is None or link.kind!=self.active_section:
            self.save_linked_ini_button.configure(state="disabled")
            self._ini_modified=False
            return
        edited=self._ini_values()
        dirty=any(str(edited.get(k,"")).strip()!=v for k,v in link.fields.items())
        self._ini_modified=dirty
        self.save_linked_ini_button.configure(state="normal" if dirty else "disabled")
        self.linked_ini_status_var.set(
            ("Unsaved changes | " if dirty else "Loaded | ")+
            link.path.name+"  (Save INI updates this file only)")

    def _apply_ini_fields(self,kind,values,obj):
        # All offsets are reset when a new OBJ is selected. Neutral scale is
        # 1.0 instead of 0.0: zero scale is invalid and hides every marker.
        self._ini_loading=True
        try:
            if kind=="character":
                self.name_var.set(values.get("name",obj.stem))
                self.slug_var.set(values.get("asset_name",clean_slug(obj.stem)))
                self.fallback_var.set(values.get("fallback_retail","coco"))
                self.engine_var.set(values.get("engine","accel"))
                self.kart_var.set(values.get("kart",""))
                self.scale_var.set(values.get("scale","1.0"))
                for axis,var in zip("xyz",(self.ox_var,self.oy_var,self.oz_var)):
                    var.set(values.get("offset_"+axis,"0.0"))
                icon=values.get("icon","retail:coco").strip()
                if icon.casefold().startswith("retail:"):
                    self.icon_mode_var.set("retail")
                    self.retail_icon_var.set(icon.split(":",1)[1])
                    self.custom_icon_var.set("")
                else:
                    self.icon_mode_var.set("custom")
                    self.custom_icon_var.set(icon)
                self._update_icon_controls()
            else:
                self.mod_name_var.set(values.get("name",obj.stem))
                self.mod_id_var.set(values.get("asset_name",clean_slug(obj.stem)))
                self.mod_scale_var.set(values.get("scale","1.0"))
                for axis,var in self.mod_offsets.items():
                    var.set(values.get("offset_"+axis,"0.0"))
                for key,var in self.mod_mounts.items():
                    var.set(values.get(key,"0.0"))
                for key,var in self.mod_exhausts.items():
                    var.set(values.get(key,"0.0"))
                self.mod_exhaust_count_var.set(
                    values.get("exhaust_count","0"))
        finally:
            self._ini_loading=False
        self._refresh_offset_guides()

    def _bind_source_ini(self,source,kind,force=False):
        if kind not in ("character","kart","wheels"):
            return
        obj=Path(source).resolve()
        context=(kind,str(obj))
        if not force and self._linked_ini_context==context:
            return
        self._linked_ini_context=context
        self._linked_ini=None
        self._ini_modified=False
        values={}
        found=find_linked_ini(obj,kind)
        try:
            if found and found[0]==kind:
                self._linked_ini=read_linked_ini(*found)
                values=self._linked_ini.fields
                status="Loaded | "+self._linked_ini.path.name
            elif found:
                status=("Found "+found[1].name+
                        " | switch to the "+found[0].title()+" importer")
            else:
                status=("No matching INI | offsets 0.0, scale 1.0 "
                        "(neutral) — Import Model can create a new mod")
        except (OSError,LinkedIniError) as exc:
            status="Could not read linked INI: "+str(exc)
        self._apply_ini_fields(kind,values,obj)
        self.linked_ini_status_var.set(status)
        self.reload_linked_ini_button.configure(
            state="normal" if self._linked_ini else "disabled")
        self.save_linked_ini_button.configure(state="disabled")

    def _reload_linked_ini(self):
        if self._linked_ini is None:
            return
        if self._ini_modified and not messagebox.askyesno(
            APP_TITLE,"Discard unsaved INI changes and reload from disk?"):
            return
        source=(self.obj_var.get() if self.active_section=="character"
                else self.mod_obj_var.get())
        if (not source and self.active_section=="kart" and
                self.kart_mod_dir_var.get().strip()):
            model=self._model_from_kart_folder(
                self.kart_mod_dir_var.get().strip())
            if model:source=str(model)
        if source:
            self._bind_source_ini(source,self.active_section,force=True)
        self.status_var.set("INI reloaded from disk")

    def _save_shortcut_available(self):
        return self._linked_ini is not None and self._linked_ini.kind==self.active_section

    def _save_ini_shortcut(self,_event=None):
        if self._save_shortcut_available():
            self._save_linked_ini()
            return "break"
        return None

    def _save_linked_ini(self):
        if not self._save_shortcut_available():
            return
        link=self._linked_ini
        try:
            backup=save_linked_ini(link,self._ini_values())
            if backup is not None:
                self.status_var.set("INI saved — backup: "+backup.name)
            else:
                self.status_var.set("INI is already up to date")
            self._linked_ini=read_linked_ini(link.kind,link.path)
            self._ini_modified=False
            self._update_ini_dirty()
        except LinkedIniConflict as exc:
            messagebox.showerror(APP_TITLE,
                str(exc)+"\n\nNo data was overwritten. Use Reload INI to inspect the changes.")
            self.status_var.set("INI changed on disk — reload first")
        except (OSError,LinkedIniError) as exc:
            messagebox.showerror(APP_TITLE,"INI not saved: "+str(exc))
            self.status_var.set("INI save failed")

    def _refresh_exhaust_controls(self, *_):
        if not hasattr(self,"exhaust_guide_frames"):
            return
        try:
            count=max(0,min(4,int(self.mod_exhaust_count_var.get())))
        except (TypeError,ValueError):
            count=0
        for i,panel in enumerate(self.exhaust_guide_frames):
            if i<count:
                panel.pack(fill="x",pady=(7,5))
            else:
                panel.pack_forget()
        self._refresh_offset_guides()

    def _refresh_offset_guides(self, *_):
        if not hasattr(self,"model_viewer") or self.active_section=="home":
            return
        section=self.active_section.title()
        if section=="Tracks":
            self.model_viewer.set_markers(())
            self.model_viewer.set_exhaust_preview((),arrows=False)
            return
        if section=="Character":
            offsets={a:v.get() for a,v in zip("xyz",(self.ox_var,self.oy_var,self.oz_var))}
            scale=self.scale_var.get()
            mounts={}
        else:
            offsets={a:v.get() for a,v in self.mod_offsets.items()}
            scale=self.mod_scale_var.get()
            mounts=({**{a:v.get() for a,v in self.mod_mounts.items()},
                     **{a:v.get() for a,v in self.mod_exhausts.items()}}
                    if section=="Kart" else {})
        markers=build_offset_markers(
            section,offsets,scale,mounts,
            exhaust_count=self.mod_exhaust_count_var.get(),
            units_per_obj=self.preview_offset_units_var.get(),
            group=self.preview_offset_group_var.get())
        self.model_viewer.set_markers(
            markers if self.preview_offsets_visible_var.get() else ())
        # Effects and arrows work regardless of which marker group is selected.
        exhaust_markers=build_offset_markers(
            "Kart",offsets,scale,mounts,
            exhaust_count=self.mod_exhaust_count_var.get(),
            units_per_obj=self.preview_offset_units_var.get(),group="Exhaust"
        ) if section=="Kart" else ()
        self.model_viewer.set_exhaust_preview(
            exhaust_markers,fire=section=="Kart" and self.preview_fire_var.get(),
            smoke=section=="Kart" and self.preview_smoke_var.get(),
            arrows=section=="Kart" and self.preview_arrows_var.get())

    def _load_selected_kart_offsets(self, ini_path):
        try:
            values=read_kart_offset_values(ini_path)
        except (OSError,ValueError):
            return
        self.mod_scale_var.set(values["scale"])
        for axis,value in values["model"].items():
            self.mod_offsets[axis].set(value)
        for key,var in self.mod_mounts.items():
            var.set(values["mounts"].get(key,"0.0"))
        for key,var in self.mod_exhausts.items():
            var.set(values["mounts"].get(key,"0.0"))
        self.mod_exhaust_count_var.set(values["exhaust_count"])

    def _sync_preview_panes(self, section):
        # Karts already have their own color gallery. Give the 3D view the
        # full adjustable pane instead of wasting a second empty thumbnail area.
        active = str(self._texture_preview_region) in {str(p) for p in self.preview_split.panes()}
        if section == "kart" and active:
            self.preview_split.forget(self._texture_preview_region)
        elif section in ("character", "wheels", "tracks") and not active:
            self.preview_split.add(self._texture_preview_region,
                                   minsize=90, stretch="always")

    def _schedule_model_preview(self, *_):
        if self._preview_update_job is not None:
            self.after_cancel(self._preview_update_job)
        self._preview_update_job=self.after(300,self._refresh_current_preview)

    def _preview_texture(self,texture):
        if getattr(self,"model_viewer",None) is not None:
            self.model_viewer.set_variant(texture)

    def _refresh_current_preview(self):
        self._preview_update_job=None
        if not hasattr(self,"model_viewer") or self.active_section=="home":
            return
        if self.active_section=="character":
            source=self.obj_var.get().strip()
            category="Character"
        elif self.active_section=="tracks":
            source=self.track_lev_var.get().strip()
            category="Track"
        else:
            source=self.mod_obj_var.get().strip()
            category=self.active_section.title()
            if (self.active_section=="kart" and
                    (not source or not Path(source).is_file()) and
                    self.kart_mod_dir_var.get().strip()):
                model=self._model_from_kart_folder(
                    self.kart_mod_dir_var.get().strip())
                if model:source=str(model)
        if not source or not Path(source).is_file():
            self._linked_ini=None
            self._linked_ini_context=None
            self._ini_modified=False
            self.save_linked_ini_button.configure(state="disabled")
            self.reload_linked_ini_button.configure(state="disabled")
            self.linked_ini_status_var.set(
                "Open a model to load a nearby character.ini, kart.ini or wheels.ini")
            self.model_viewer.scene=None
            self.model_viewer.image.configure(image="",text="Choose a "+(
                "LEV track" if category=="Track" else "native OBJ")+" to preview.")
            self.model_viewer.detail.set("Waiting for source model.")
            self.preview_textures.load([])
            return
        if self.active_section in ("character","kart","wheels"):
            self._bind_source_ini(source,self.active_section)
        else:
            self._linked_ini=None
            self._linked_ini_context=None
            self.save_linked_ini_button.configure(state="disabled")
            self.reload_linked_ini_button.configure(state="disabled")
            self.linked_ini_status_var.set("Tracks use LEV/VRM (no linked model INI)")
        self.model_viewer.load(source,category=category)
        self._refresh_offset_guides()
        if self.active_section=="kart":
            self.preview_textures.pack_forget()
            folder=self.kart_color_dir_var.get().strip()
            if folder and Path(folder).is_dir() and not self.kart_colors_gallery.rows:
                self._scan_kart_colors()
        else:
            self.preview_textures.pack(fill="x",pady=(8,0))
            self.preview_textures.load(texture_sources_from_folder(Path(source).parent))
            self._tag_mousewheel_descendants(self.preview_textures)
        if category=="Track":
            self.model_viewer.detail.set(self.model_viewer.detail.get()+
                " • VRM atlas decoding is not yet available in preview.")

    def _choose_mod_obj(self):
        path = filedialog.askopenfilename(title="Choose modular OBJ",
                  filetypes=[("Wavefront model", "*.obj"), ("All files", "*.*")])
        if path:
            found=find_linked_ini(path,self.active_section)
            if found and found[0]=="character":
                self.obj_var.set(path)
                self._show_section("character")
                self.analyze()
            else:
                self.mod_obj_var.set(path)
                if found and found[0] in ("kart","wheels"):
                    self._show_section(found[0])
                else:
                    self._refresh_current_preview()

    def _import_mod(self):
        kind = self.active_section
        if kind not in ("kart", "wheels"):
            return
        try:
            root = self._validated_game_root()
            if root is None:
                return
            obj = self.mod_obj_var.get().strip()
            slug = self.mod_id_var.get().strip()
            target = root / "mods" / slug
            replacing = target.exists()
            if replacing and not messagebox.askyesno(APP_TITLE,
                    "Replace this existing mod? A backup will be saved.\n\n" + str(target)):
                return
            result = import_mod(obj, root, kind, self.mod_name_var.get(), slug,
                        self.mod_scale_var.get(),
                        {a: v.get() for a,v in self.mod_offsets.items()},
                        ({**{a:v.get() for a,v in self.mod_mounts.items()},
                          **{a:v.get() for a,v in self.mod_exhausts.items()},
                          "exhaust_count":self.mod_exhaust_count_var.get()}
                         if kind=="kart" else {}),
                        None, replace=replacing)
            # New and existing karts use the SAME texture gallery. Texture
            # names from its editable rows become actual [colors] INI keys.
            if kind == "kart" and self.kart_colors_gallery.rows:
                choices=self.kart_colors_gallery.selected_names()
                if choices:
                    install_colors(result["folder"],
                                   self.kart_color_dir_var.get().strip(),
                                   variants=choices)
            self.last_dest = Path(result["folder"])
            self.status_var.set(kind.title() + " imported")
            messagebox.showinfo(APP_TITLE, "Mod installed successfully:\n" + result["folder"])
        except (ImportErrorMod, OSError, ValueError) as exc:
            self.status_var.set("Import failed")
            messagebox.showerror(APP_TITLE, str(exc))

    def _auto_track_slug(self):
        try:
            self.track_slug_var.set(track_slugify(self.track_name_var.get()))
        except NativeTrackError as exc:
            self.track_info_var.set(str(exc))

    def _choose_track_lev(self):
        path = filedialog.askopenfilename(
            title="Choose CTR native .lev level", filetypes=[
                ("CTR LEV", "*.lev"), ("All files", "*.*")])
        if path:
            self.track_lev_var.set(path)
            # Normal CTR asset pairs share the same folder and basename.
            other = Path(path).with_suffix(".vrm")
            if other.is_file() and not self.track_vrm_var.get().strip():
                self.track_vrm_var.set(str(other))
            self._validate_native_track()

    def _choose_track_vrm(self):
        path = filedialog.askopenfilename(
            title="Choose CTR native .vrm textures",
            filetypes=[("CTR VRM", "*.vrm"), ("All files", "*.*")])
        if path:
            self.track_vrm_var.set(path)
            self._validate_native_track()

    def _choose_track_game(self):
        messagebox.showinfo(APP_TITLE,
            "Change the game installation in Crash Forge Launcher > Settings.")

    def _validate_native_track(self):
        try:
            stats = inspect_native_track(
                self.track_lev_var.get().strip(), self.track_vrm_var.get().strip())
            self.track_info_var.set(
                "Pair verified: LEV " + str(stats["lev_size"] // 1024) +
                " KiB, VRM " + str(stats["vrm_size"] // 1024) +
                " KiB. Native file structure checked; gameplay compatibility "
                "still requires the game's track registration.")
            self.status_var.set("Native track pair validated")
        except (NativeTrackError, OSError, UnicodeError) as exc:
            self.track_info_var.set(str(exc))
            self.status_var.set("Invalid LEV/VRM pair")

    def _install_native_track(self):
        try:
            inputs = dict(
                lev_path=self.track_lev_var.get().strip(),
                vrm_path=self.track_vrm_var.get().strip(),
                game_path=self.track_game_var.get().strip(),
                track_name=self.track_name_var.get().strip(),
                track_slug=self.track_slug_var.get().strip(),
                author=self.track_author_var.get().strip(),
                description=self.track_description_var.get().strip())
            preview = install_native_track(**inputs, dry_run=True)
            if not messagebox.askyesno(
                APP_TITLE, "Install native track package?\n\n" +
                preview["name"] + "\n" + preview["target"] +
                "\n\nThe original retail levels will NOT be changed. "
                "Custom-track runtime registration is not yet enabled."):
                return
            result = install_native_track(**inputs)
            self.track_info_var.set(
                "INSTALLED: " + result["target"] +
                ". LEV/VRM hashes verified. Retail levels unchanged. "
                "Awaiting native game track registration.")
            self.status_var.set("Track package prepared")
            messagebox.showinfo(
                APP_TITLE, "Native CTR track package installed.\n\n" +
                result["target"] +
                "\n\nThe game will need a native custom-track registry before "
                "this map can be selected. Crash Cove is unchanged.")
        except (NativeTrackError, OSError, UnicodeError) as exc:
            self.track_info_var.set(str(exc))
            messagebox.showerror(APP_TITLE, str(exc))

    def _choose_kart_mod(self):
        """Choose only an existing kart inside the launcher-selected mods root."""
        root=self._game_root_from_value()
        if root is None:
            messagebox.showerror(APP_TITLE,
                "Select your game installation in Crash Forge Launcher > Settings.")
            return
        mods=root/"mods"
        if not mods.is_dir():
            messagebox.showerror(APP_TITLE, "Game mods folder missing: "+str(mods))
            return
        selected=filedialog.askdirectory(
            title="Existing kart mod inside selected Crash Forge game",
            initialdir=str(mods))
        if not selected:return
        folder=Path(selected).resolve()
        if (not folder.is_relative_to(mods.resolve()) or
                not (folder/"kart.ini").is_file()):
            messagebox.showerror(APP_TITLE,
                "Choose a kart mod inside "+str(mods)+" containing kart.ini.")
            return
        self.kart_mod_dir_var.set(str(folder))
        model=self._model_from_kart_folder(folder)
        if model:
            self.mod_obj_var.set(str(model))
        self._load_selected_kart_offsets(folder/"kart.ini")
        self._refresh_current_preview()
        if self.kart_color_dir_var.get().strip():
            self._scan_kart_colors()

    def _choose_kart_colors(self):
        selected=filedialog.askdirectory(
            title="Choose PNG/BMP kart texture atlases",
            initialdir=self.kart_color_dir_var.get().strip() or
                        str(Path(self.mod_obj_var.get()).parent
                            if self.mod_obj_var.get().strip() else Path.home()))
        if selected:
            self.kart_color_dir_var.set(selected)
            self._scan_kart_colors()

    def _scan_kart_colors(self):
        """Detect ANY atlas filenames. Show previews and editable game names."""
        try:
            folder=self.kart_color_dir_var.get().strip()
            if not folder:
                self.kart_colors_gallery.pack_forget()
                self.kart_color_info_var.set("Choose a PNG/BMP texture folder to add kart colors (optional).")
                return
            textures=scan_palette(folder)
            self.kart_colors_gallery.load(textures)
            self._tag_mousewheel_descendants(self.kart_colors_gallery)
            if textures:
                self.kart_colors_gallery.pack(fill="x",pady=(6,0))
            else:
                self.kart_colors_gallery.pack_forget()
            info=(str(len(textures))+" textures detected. "
                  "Set in-game names beside each thumbnail, tick variants "
                  "to include, then import/apply. Maximum 12 skins including original.")
            kart=self.kart_mod_dir_var.get().strip()
            if kart and (Path(kart)/"kart.ini").is_file():
                obj=sorted(Path(kart).glob("*.obj"))
                if obj:self.model_viewer.load(obj[0],category="Kart")
            self.kart_color_info_var.set(info)
            self.status_var.set("Kart textures detected")
        except (KartColorError, OSError, UnicodeError) as exc:
            self.kart_color_info_var.set(str(exc))
            self.status_var.set("Texture scan needs attention")

    def _apply_kart_colors(self):
        """Apply selected named variants without modifying the native OBJ/MTL."""
        try:
            root=self._validated_game_root()
            if root is None:return
            folder=Path(self.kart_mod_dir_var.get().strip()).resolve()
            if (not folder.is_relative_to((root/"mods").resolve()) or
                    not (folder/"kart.ini").is_file()):
                raise KartColorError("Choose an installed kart inside the selected game mods folder.")
            chosen=self.kart_colors_gallery.selected_names()
            if not chosen:
                raise KartColorError("Scan and select at least one kart skin texture.")
            preview=install_colors(
                folder,self.kart_color_dir_var.get().strip(),
                variants=chosen,dry_run=True)
            names=", ".join(preview["variants"])
            if not messagebox.askyesno(APP_TITLE,
                "Apply texture variants to this kart?\n\n" + names +
                "\n\nOnly selected atlases and kart.ini change. "
                "The original OBJ, MTL and attachment offsets stay untouched."):
                return
            result=install_colors(
                folder,self.kart_color_dir_var.get().strip(),variants=chosen)
            self.kart_color_info_var.set(
                "Installed "+str(len(result["variants"]))+" skin variants: "+
                ", ".join(result["variants"])+". kart.ini backup saved.")
            self.status_var.set("Kart textures installed")
            messagebox.showinfo(APP_TITLE,
                "Textures installed in:\n"+result["kart"]+
                "\n\nRestart the game to load the custom names.")
        except (KartColorError, OSError, UnicodeError, ValueError) as exc:
            self.kart_color_info_var.set(str(exc))
            messagebox.showerror(APP_TITLE,str(exc))

    def _on_content_configure(self, _event=None):
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.scroll_canvas.itemconfigure(self._canvas_window, width=event.width)
        self._update_responsive_layout(event.width)

    def _install_mousewheel_router(self):
        """Process wheel before Tk combobox/text/scrollbar class bindings.

        Tk class defaults otherwise change combobox selections and scroll
        nested widgets instead of the page. The 3D label is bound first and
        stops propagation itself, so exactly one zoom event is generated.
        """
        tag = "CrashForgeImporterPageWheel"
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_class(tag, event, self._on_mousewheel)
        self._tag_mousewheel_descendants(self)

    def _tag_mousewheel_descendants(self, parent):
        tag = "CrashForgeImporterPageWheel"
        tags = parent.bindtags()
        if tag not in tags:
            # After widget-specific bindings (3D zoom), before class bindings
            # that consume wheel events and block the main page-scroller.
            parent.bindtags((tags[0], tag, *tags[1:]))
        for child in parent.winfo_children():
            self._tag_mousewheel_descendants(child)

    @staticmethod
    def _widget_is_descendant(widget, ancestor):
        """True for the 3D image or any child of a given viewport widget."""
        while widget is not None:
            if widget is ancestor:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_mousewheel(self, event):
        """Wheel over 3D model zooms ONLY; wheel everywhere else scrolls page.

        Tk's toplevel wheel binding runs for its child widgets, too. On Windows
        the receiving widget can differ from the widget beneath the pointer,
        so use root mouse coordinates to route the event to exactly one owner.
        """
        preview = getattr(self, "model_viewer", None)
        source = getattr(event, "widget", None)
        target = None
        if hasattr(event, "x_root") and hasattr(event, "y_root"):
            try:
                target = self.winfo_containing(event.x_root, event.y_root)
            except (tk.TclError, TypeError, ValueError):
                pass
        if target is None:
            target = source

        if preview is not None:
            image = preview.image
            viewport = image.master
            # The image binding itself already handles this wheel event.
            if self._widget_is_descendant(source, image):
                return "break"
            if self._widget_is_descendant(target, viewport):
                # The pointer may be on the preview border while Windows
                # delivered the event to a previously focused entry/control.
                if getattr(event, "num", None) in (4, 5):
                    preview._zoom(1.12 if event.num == 4 else 1 / 1.12)
                elif getattr(event, "delta", 0):
                    preview._wheel(event)
                return "break"

        if getattr(event, "num", None) == 4:
            step = -3
        elif getattr(event, "num", None) == 5:
            step = 3
        else:
            delta = getattr(event, "delta", 0)
            if not delta:
                return "break"
            step = -int(delta / 120) * 3
            if step == 0:
                step = -1 if delta > 0 else 1

        if self.scroll_canvas.bbox("all"):
            self.scroll_canvas.yview_scroll(step, "units")
        # Stop Tk's class/all bindings from also changing zoom or selections.
        return "break"

    def _update_responsive_layout(self, width):
        stacked = width < 900
        compact = width < 720

        if stacked != self._columns_stacked:
            self._columns_stacked = stacked
            self._left_column.grid_forget()
            self._right_column.grid_forget()
            self._char_sash.grid_forget()
            if stacked:
                self._columns_frame.columnconfigure(0,weight=1,uniform="")
                self._columns_frame.columnconfigure(1,weight=0,uniform="")
                self._columns_frame.columnconfigure(2,weight=0,uniform="")
                self._left_column.grid(row=0,column=0,sticky="nsew")
                self._right_column.grid(row=1,column=0,sticky="nsew",pady=(12,0))
            else:
                self._columns_frame.columnconfigure(0,weight=50,uniform="main")
                self._columns_frame.columnconfigure(1,weight=0,uniform="")
                self._columns_frame.columnconfigure(2,weight=50,uniform="main")
                self._left_column.grid(row=0,column=0,sticky="nsew",padx=(0,4))
                self._char_sash.grid(row=0,column=1,sticky="ns")
                self._right_column.grid(row=0,column=2,sticky="nsew",padx=(4,0))
                self._apply_character_columns()

        if compact != self._compact_controls:
            self._compact_controls = compact

            self._title_box.pack_forget()
            self._status_label.pack_forget()
            self.analyze_button.pack_forget()
            self.open_button.pack_forget()
            self.build_button.pack_forget()

            if compact:
                self._title_box.pack(fill="x", anchor="w")
                self._status_label.pack(anchor="w", pady=(8, 0))
                self.analyze_button.pack(fill="x")
                self.open_button.pack(fill="x", pady=(6, 0))
                self.build_button.pack(fill="x", pady=(8, 0))
            else:
                self._title_box.pack(side="left")
                self._status_label.pack(side="right", anchor="n")
                self.analyze_button.pack(side="left")
                self.open_button.pack(side="left", padx=(8, 0))
                self.build_button.pack(side="right")

        subtitle_wrap = max(260, width - 150)
        if stacked:
            note_wrap = max(260, width - 120)
        else:
            note_wrap = max(240, (width // 2) - 100)

        self.subtitle_label.configure(wraplength=subtitle_wrap)
        self.icon_note.configure(wraplength=note_wrap)
        self.after_idle(self._on_content_configure)

    def log(self, text, state="normal"):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("end", text)
        if state in ("ok", "warn", "error"):
            self.report.tag_add(state, "1.0", "end")
        self.report.configure(state="disabled")

    def choose_obj(self):
        path = filedialog.askopenfilename(title="Choose OBJ model",
                                          filetypes=[("Wavefront OBJ", "*.obj"), ("All files", "*.*")])
        if path:
            found=find_linked_ini(path,"character")
            if found and found[0] in ("kart","wheels"):
                self.mod_obj_var.set(path)
                self._show_section(found[0])
            else:
                self.obj_var.set(path)
                self._refresh_current_preview()
                self.analyze()

    def auto_slug(self):
        self.slug_var.set(clean_slug(self.name_var.get()))

    def _game_root_from_value(self, value=None):
        # Never probe arbitrary C: paths, source roots or retired assets/mods.
        # All four editors use exactly Launcher Settings.
        return selected_game_directory(source_file=__file__)

    def _mods_path_from_game(self, value=None):
        root = self._game_root_from_value(value)
        return (root / "mods") if root else None

    def _on_game_path_change(self, *_args):
        self._sync_output_path()

    def _sync_output_path(self):
        mods_path = self._mods_path_from_game()
        self.output_var.set(str(mods_path) if mods_path else "")

    def _validated_game_root(self):
        root = self._game_root_from_value()
        if valid_game_root(root) is None:
            messagebox.showerror(APP_TITLE, selected_game_explanation(root)+
                "\n\nChange the selected folder in Launcher > Settings.")
            return None
        return root

    def choose_game_folder(self):
        messagebox.showinfo(APP_TITLE,
            "The game directory is configured in Crash Forge Launcher > Settings.")

    def choose_game_exe(self):
        self.choose_game_folder()

    def choose_icon(self):
        path = filedialog.askopenfilename(title="Choose custom roster icon",
                                          filetypes=[("Supported images", "*.png *.bmp"),
                                                     ("PNG image", "*.png"),
                                                     ("BMP image", "*.bmp"),
                                                     ("All files", "*.*")])
        if path:
            self.custom_icon_var.set(path)
            self._refresh_icon_preview()

    def _update_icon_controls(self):
        custom = self.icon_mode_var.get() == "custom"
        self.retail_icon_combo.configure(state="disabled" if custom else "readonly")
        self.custom_icon_entry.configure(state="normal" if custom else "disabled")
        self.custom_icon_button.configure(state="normal" if custom else "disabled")
        self._refresh_icon_preview()

    def _refresh_icon_preview(self):
        self.icon_preview = None
        self.preview_label.configure(image="", text="")
        if self.icon_mode_var.get() != "custom":
            self.preview_label.configure(text=f"Retail icon: {self.retail_icon_var.get().upper()}", fg=ACCENT)
            return
        path = self.custom_icon_var.get().strip()
        if not path or not Path(path).is_file():
            self.preview_label.configure(text="No custom icon selected", fg=MUTED)
            return
        try:
            if Path(path).suffix.lower() == ".png":
                img = tk.PhotoImage(file=path)
                factor = max(1, (max(img.width(), img.height()) + 119) // 120)
                if factor > 1:
                    img = img.subsample(factor, factor)
                self.icon_preview = img
                self.preview_label.configure(image=img, text="")
            else:
                dims = image_dimensions(path)
                label = f"{Path(path).name}\n{dims[0]} × {dims[1]}" if dims else Path(path).name
                self.preview_label.configure(text=label, fg=TEXT)
        except tk.TclError:
            self.preview_label.configure(text=Path(path).name + "\nPreview unavailable", fg=MUTED)

    def analyze(self):
        obj = self.obj_var.get().strip()
        self.status_var.set("Checking...")
        if not obj or not Path(obj).is_file():
            self.status_var.set("Needs attention")
            self.log("ERROR: Choose a valid OBJ file.", "error")
            return False
        try:
            stats = parse_obj(obj)
        except Exception as exc:
            self.status_var.set("Needs attention")
            self.log(f"ERROR reading OBJ: {exc}", "error")
            return False

        self.last_stats = stats
        problems = []
        warnings = []
        if stats["v"] == 0 or stats["tri"] == 0:
            problems.append("The OBJ does not contain valid geometry.")
        if stats["v"] > 100000:
            problems.append("More than 100000 vertices.")
        if stats["vt"] > 100000:
            problems.append("More than 100000 UV coordinates.")
        if stats["tri"] > 100000:
            problems.append("More than 100000 final triangles.")
        if len(stats["materials"]) > 256:
            problems.append("More than 256 materials.")
        if any(x > 32.0 for x in stats["extent"]):
            problems.append("Model exceeds 32 OBJ units on at least one axis.")

        slug = self.slug_var.get().strip()
        if not re.fullmatch(r"[a-z0-9_]+", slug or ""):
            problems.append("Asset name may only contain a-z, 0-9 and underscore.")
        if len(slug) > 15:
            problems.append("Asset name is longer than 15 characters.")

        kart_slug = self.kart_var.get().strip()
        if kart_slug and not re.fullmatch(r"[A-Za-z0-9_-]+", kart_slug):
            problems.append("Kart asset may only contain letters, numbers, underscore and hyphen.")
        if len(kart_slug) >= 64:
            problems.append("Kart asset is too long (maximum 63 characters).")

        mtl = locate_mtl(obj, stats["mtllib"])
        textures = []
        if stats["mtllib"] and not mtl:
            problems.append(f"MTL referenced by OBJ was not found: {stats['mtllib']}")
        elif mtl:
            material_count, textures = parse_mtl(mtl)
            if material_count > 256:
                problems.append("MTL contains more than 256 materials.")
            for tex in textures:
                located = locate_texture(mtl, tex)
                if not located:
                    problems.append(f"Missing texture: {tex}")
                elif located.suffix.lower() not in (".png", ".bmp"):
                    warnings.append(f"Texture {located.name}: PNG or BMP is recommended.")

        custom_icon = None
        if self.icon_mode_var.get() == "custom":
            custom_icon = Path(self.custom_icon_var.get().strip())
            if not custom_icon.is_file():
                problems.append("Custom icon mode is enabled but no valid image was selected.")
            elif custom_icon.suffix.lower() not in (".png", ".bmp"):
                problems.append("Custom icon must be PNG or BMP.")
            else:
                dims = image_dimensions(custom_icon)
                if dims and dims != (128, 128):
                    warnings.append(f"Custom icon is {dims[0]}x{dims[1]}; 128x128 is recommended.")

        lines = [
            f"OBJ          {obj}",
            f"Vertices     {stats['v']}",
            f"Vertex color {'YES' if stats['vertex_colors'] > 0 else 'NO'}",
            f"UVs          {stats['vt']}",
            f"Triangles    {stats['tri']}",
            f"Materials    {len(stats['materials'])}",
            "Extent XYZ   " + " / ".join(f"{x:.3f}" for x in stats["extent"]),
            f"MTL          {str(mtl) if mtl else '(none)'}",
            f"Textures     {len(textures)}",
            f"Icon         {'custom: ' + custom_icon.name if custom_icon and custom_icon.is_file() else 'retail: ' + self.retail_icon_var.get()}",
            "",
        ]
        if problems:
            lines += ["ERRORS"] + [f"  • {item}" for item in problems]
        else:
            lines.append("VALIDATION PASSED — ready to build.")
        if warnings:
            lines += ["", "WARNINGS"] + [f"  • {item}" for item in warnings]

        if problems:
            self.status_var.set("Needs attention")
            state = "error"
        elif warnings:
            self.status_var.set("Ready with warnings")
            state = "warn"
        else:
            self.status_var.set("Ready to build")
            state = "ok"
        self.log("\n".join(lines), state)
        return not problems

    def build_mod(self):
        if not self.analyze():
            messagebox.showerror(APP_TITLE, "Fix the validation errors before building the mod.")
            return

        game_root = self._validated_game_root()
        if game_root is None:
            return

        slug = self.slug_var.get().strip()
        obj_src = Path(self.obj_var.get().strip())
        out_root = game_root / "mods"
        out_root.mkdir(parents=True, exist_ok=True)
        self.output_var.set(str(out_root))
        dest = out_root / slug

        if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
            messagebox.showerror(APP_TITLE,"Unsafe existing mod folder.")
            return
        if dest.is_dir() and not (dest / "character.ini").is_file():
            messagebox.showerror(APP_TITLE,"Mod ID belongs to another category.")
            return
        if dest.exists():
            if not messagebox.askyesno(APP_TITLE, f"This mod already exists:\n{dest}\n\nReplace it? A backup will be kept."):
                return
            backups = game_root / ".forge_mod_backups" / "character_import"
            backups.mkdir(parents=True,exist_ok=True)
            backup = backups / (slug + "_" + __import__("uuid").uuid4().hex[:10])
            dest.rename(backup)
        dest.mkdir(parents=True, exist_ok=True)

        stats = parse_obj(obj_src)
        mtl_src = locate_mtl(obj_src, stats["mtllib"])
        obj_text = obj_src.read_text(encoding="utf-8", errors="ignore")
        if mtl_src:
            new_lines = []
            replaced = False
            for line in obj_text.splitlines():
                if line.strip().startswith("mtllib ") and not replaced:
                    new_lines.append(f"mtllib {slug}.mtl")
                    replaced = True
                else:
                    new_lines.append(line)
            obj_text = "\n".join(new_lines) + "\n"
        (dest / f"{slug}.obj").write_text(obj_text, encoding="utf-8")

        if mtl_src:
            mtl_lines = []
            for raw in mtl_src.read_text(encoding="utf-8", errors="ignore").splitlines():
                if raw.strip().startswith("map_Kd "):
                    tex_value = raw.strip()[7:].strip().strip('"')
                    tex_src = locate_texture(mtl_src, tex_value)
                    if tex_src:
                        shutil.copy2(tex_src, dest / tex_src.name)
                        mtl_lines.append(f"map_Kd {tex_src.name}")
                    else:
                        mtl_lines.append(raw)
                else:
                    mtl_lines.append(raw)
            (dest / f"{slug}.mtl").write_text("\n".join(mtl_lines) + "\n", encoding="utf-8")
        try:
            scale = float(self.scale_var.get())
            ox = float(self.ox_var.get())
            oy = float(self.oy_var.get())
            oz = float(self.oz_var.get())
        except ValueError:
            shutil.rmtree(dest, ignore_errors=True)
            messagebox.showerror(APP_TITLE, "Scale and offsets must be valid numbers.")
            return

        if self.icon_mode_var.get() == "custom":
            icon_src = Path(self.custom_icon_var.get().strip())
            icon_name = f"{slug}_icon{icon_src.suffix.lower()}"
            shutil.copy2(icon_src, dest / icon_name)
            icon_value = icon_name
        else:
            icon_value = f"retail:{self.retail_icon_var.get()}"

        kart_slug = self.kart_var.get().strip()
        kart_line = f"kart = {kart_slug}\n" if kart_slug else ""
        ini = (
            "[character]\n"
            f"name = {self.name_var.get().strip()}\n"
            "enabled = true\n"
            f"fallback_retail = {self.fallback_var.get()}\n"
            f"engine = {self.engine_var.get()}\n"
            f"{kart_line}"
            "modular_body = true\n\n"
            "[model]\n"
            f"scale = {scale}\n"
            f"offset_x = {ox}\n"
            f"offset_y = {oy}\n"
            f"offset_z = {oz}\n\n"
            "[assets]\n"
            f"asset_name = {slug}\n"
            f"icon = {icon_value}\n\n"
            "[forge_mod]\n"
            f"id = {slug}\n"
            "type = Character\n"
            "source = local\n"
            "version = 1.0\n"
            "enabled = true\n"
        )
        (dest / "character.ini").write_text(ini, encoding="utf-8")

        self.last_dest = dest
        self.open_button.configure(state="normal")
        self.status_var.set("Build complete")
        files = [p.name for p in sorted(dest.iterdir()) if p.is_file()]
        self.log("MOD BUILT SUCCESSFULLY\n\n" + str(dest) + "\n\nFILES\n" +
                 "\n".join(f"  • {name}" for name in files), "ok")
        messagebox.showinfo(APP_TITLE, f"Mod built successfully:\n{dest}")

    def open_generated(self):
        if self.last_dest and self.last_dest.exists():
            os.startfile(self.last_dest)

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        # Portable EXE smoke test; intentionally never opens a window/game.
        from crash_forge_kart_colors import PALETTE, KartColorError
        from crash_forge_native_tracks import SLUG_RE, MAX_LEV
        if len(PALETTE) < 2 or MAX_LEV <= 4096 or SLUG_RE.fullmatch("demo-track") is None:
            raise SystemExit(1)
        raise SystemExit(0)
    if "--retail-fx-self-test" in sys.argv:
        # Verify all eight original 3D frames and all five original smoke
        # textures from the packaged executable, without launching Tk.
        from forge_preview_retail_fx import (
            TURBO_FIRE_SIZE,load_retail_turbo_frames,
            load_retail_smoke_textures)
        from forge_preview_ctr_particle import (
            NATIVE_PARTICLE_LIFE,NATIVE_TICKS_PER_SECOND,
            native_emitter_particles)
        mock=[{"position":(0.,0.,0.),"rotation":(0.,0.,0.),
               "native_model_scale":1.0}]
        alive=native_emitter_particles(mock,1.0)
        ok=(TURBO_FIRE_SIZE==8 and
            len(load_retail_turbo_frames())==8 and
            len(load_retail_smoke_textures())==5 and
            NATIVE_PARTICLE_LIFE==5 and
            NATIVE_TICKS_PER_SECOND==30 and
            len(alive)==5 and alive[0].sprite_index==0 and
            alive[0].scale_fixed==1936 and alive[0].shade_byte==54)
        raise SystemExit(0 if ok else 24)
    if "--gpu-self-test" in sys.argv:
        # Checks the embedded WGL/ModernGL runtime without showing a window.
        try:
            from forge_preview_gpu import GpuPreviewRenderer
            test_renderer=GpuPreviewRenderer()
            test_renderer.release()
        except Exception:
            raise SystemExit(23)
        raise SystemExit(0)
    app=App()
    # Explicit command-line preview for editor QA and community workflows.
    # Never autodetect personal game folders or change a mod's source files.
    if "--preview-kart" in sys.argv:
        try:
            flag=sys.argv.index("--preview-kart")
            folder=Path(sys.argv[flag+1]).resolve()
            if (folder/"kart.ini").is_file():
                app._show_section("kart")
                app.kart_mod_dir_var.set(str(folder))
                model=app._model_from_kart_folder(folder)
                if model:
                    app.mod_obj_var.set(str(model))
                app._load_selected_kart_offsets(folder/"kart.ini")
                app._refresh_current_preview()
                app.after(110,app.model_viewer.frame_markers)
        except (ValueError,IndexError,OSError):
            pass
    app.mainloop()