import os
import re
import json
import shutil
import struct
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from crash_forge_kart_colors import install_colors, KartColorError
from crash_forge_native_tracks import install_native_track, inspect_native_track, NativeTrackError, slugify as track_slugify

APP_TITLE = "Crash Forge Model Importer"
APP_VERSION = "1.7"
TOOL_DIR = Path(__file__).resolve().parent

def find_source_root():
    for candidate in (TOOL_DIR, *TOOL_DIR.parents):
        if ((candidate / "CMakeLists.txt").is_file() and
                (candidate / "game").is_dir() and
                (candidate / "platform").is_dir()):
            return candidate
    return None

def find_installed_game():
    roots = [TOOL_DIR, TOOL_DIR.parent]
    if getattr(sys, "frozen", False):
        binary_dir = Path(sys.executable).resolve().parent
        roots.extend((binary_dir, binary_dir.parent, binary_dir.parent.parent))
    for root in roots:
        settings = root / "launcher_settings.json"
        if settings.is_file():
            try:
                info = json.loads(settings.read_text(encoding="utf-8-sig"))
                path = Path(info.get("game_install_path", ""))
                if (path / "ctr-native.exe").is_file():
                    return str(path)
            except (OSError, ValueError, TypeError):
                pass
    candidate = TOOL_DIR.parent / "Crash Team Racing Compiled Custom Music"
    if (candidate / "ctr-native.exe").is_file():
        return str(candidate)
    return ""

SOURCE_ROOT = find_source_root()
DEFAULT_GAME_ROOT = str(SOURCE_ROOT) if SOURCE_ROOT else ""
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
        self.minsize(640, 520)
        self.configure(bg=BG)
        self.obj_var = tk.StringVar()
        self.name_var = tk.StringVar(value="My Character")
        self.slug_var = tk.StringVar(value="my_character")
        self.fallback_var = tk.StringVar(value="coco")
        self.engine_var = tk.StringVar(value="accel")
        self.kart_var = tk.StringVar()
        # Optional tool section: customize existing kart mods without
        # replacing OBJ/MTL, seat, wheels, attachments or exhaust offsets.
        candidate = TOOL_DIR.parent / "Crash Team Racing Compiled Custom Music" / "assets" / "mods" / "karts" / "ctr_cinematic_kart"
        palette = TOOL_DIR.parent / "GameCube - Crash Nitro Kart - Characters in Karts - Coco Bandicoot" / "Kart_Color"
        self.kart_mod_dir_var = tk.StringVar(value=str(candidate) if (candidate / "kart.ini").is_file() else "")
        self.kart_color_dir_var = tk.StringVar(value=str(palette) if palette.is_dir() else "")
        self.kart_color_info_var = tk.StringVar(value="Select a kart mod and a palette folder. Blue stays as the original atlas.")
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
        self.own_wheels_var = tk.BooleanVar(value=True)
        self.icon_mode_var = tk.StringVar(value="retail")
        self.retail_icon_var = tk.StringVar(value="coco")
        self.custom_icon_var = tk.StringVar()
        self.scale_var = tk.StringVar(value="1.0")
        self.ox_var = tk.StringVar(value="0.0")
        self.oy_var = tk.StringVar(value="0.0")
        self.oz_var = tk.StringVar(value="0.0")
        self.game_var = tk.StringVar(value=find_installed_game() or DEFAULT_GAME_ROOT)
        self.output_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.last_stats = None
        self.last_dest = None
        self.icon_preview = None
        self._columns_stacked = None
        self._compact_controls = None
        self._setup_style()
        self._build_ui()
        self.game_var.trace_add("write", self._on_game_path_change)
        self._sync_output_path()
        self._update_icon_controls()

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

        source_border, source = self._card(root)
        source_border.pack(fill="x", pady=(0, 12))
        self._section_title(source, "MODEL SOURCE", "Choose the OBJ model used by the custom racer.")
        source_line = ttk.Frame(source, style="Panel.TFrame")
        source_line.pack(fill="x")
        ttk.Entry(source_line, textvariable=self.obj_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(source_line, text="Browse OBJ...", command=self.choose_obj).pack(side="left")

        track_border, tracks = self._card(root)
        track_border.pack(fill="x", pady=(0, 12))
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
        ttk.Entry(line, textvariable=self.track_game_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line, text="Browse...", command=self._choose_track_game).pack(
            side="right")
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
        self._section_title(
            palette, "KART COLOR VARIANTS",
            "Single OBJ and MTL. Auto-detect Blue, Red, Lime, Pink, Blank and more; save to kart.ini.")
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

        columns = ttk.Frame(root)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=1, uniform="main")
        columns.columnconfigure(1, weight=1, uniform="main")
        columns.rowconfigure(0, weight=1)
        left = ttk.Frame(columns)
        right = ttk.Frame(columns)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
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
        ttk.Checkbutton(transform_fields, text="OBJ includes its own wheels  (has_wheels = false)",
                        variable=self.own_wheels_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

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
        self.after_idle(lambda: self._update_responsive_layout(self.winfo_width()))

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
        path = filedialog.askdirectory(
            title="Installed Crash Forge Racing game folder",
            initialdir=self.track_game_var.get().strip() or str(TOOL_DIR.parent))
        if path:
            self.track_game_var.set(path)

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
        initial = self.kart_mod_dir_var.get().strip() or str(TOOL_DIR.parent)
        selected = filedialog.askdirectory(title="Choose existing kart mod (contains kart.ini)",
                                          initialdir=initial)
        if selected:
            self.kart_mod_dir_var.set(selected)
            self._scan_kart_colors()

    def _choose_kart_colors(self):
        selected = filedialog.askdirectory(title="Choose folder with colored textures",
                                          initialdir=self.kart_color_dir_var.get().strip() or str(TOOL_DIR))
        if selected:
            self.kart_color_dir_var.set(selected)
            self._scan_kart_colors()

    def _scan_kart_colors(self):
        try:
            result = install_colors(self.kart_mod_dir_var.get().strip(),
                                    self.kart_color_dir_var.get().strip(), dry_run=True)
            names = ", ".join(name.title() for name in result["variants"])
            note = "Default Blue reused; no duplicate." if result["skipped_duplicate_blue"] else "Default atlas reused."
            self.kart_color_info_var.set(
                f"{len(result['variants'])} colors: {names}. {note} "
                f"{len(result['new_textures'])} new textures to install.")
            self.status_var.set("Kart colors ready")
        except (KartColorError, OSError, UnicodeError) as exc:
            self.kart_color_info_var.set(str(exc))
            self.status_var.set("Color scan needs attention")

    def _apply_kart_colors(self):
        try:
            preview = install_colors(self.kart_mod_dir_var.get().strip(),
                                     self.kart_color_dir_var.get().strip(), dry_run=True)
            if not messagebox.askyesno(APP_TITLE,
                "Update the colors for this kart?\n\n" + preview["kart"] +
                "\n\nIts OBJ, MTL, original blue texture, and attachment offsets stay unchanged."):
                return
            result = install_colors(self.kart_mod_dir_var.get().strip(),
                                    self.kart_color_dir_var.get().strip())
            self.kart_color_info_var.set(
                "INSTALLED: " + ", ".join(name.title() for name in result["variants"]) +
                ". Original geometry preserved; kart.ini backed up.")
            self.status_var.set("Kart colors installed")
            messagebox.showinfo(APP_TITLE,
                                "Kart colors installed successfully.\n\n" +
                                result["kart"] +
                                "\n\nRestart the game to discover the new colors.")
        except (KartColorError, OSError, UnicodeError) as exc:
            self.kart_color_info_var.set(str(exc))
            messagebox.showerror(APP_TITLE, str(exc))

    def _on_content_configure(self, _event=None):
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.scroll_canvas.itemconfigure(self._canvas_window, width=event.width)
        self._update_responsive_layout(event.width)

    def _on_mousewheel(self, event):
        if getattr(self, "report", None) is not None and event.widget is self.report:
            return

        if getattr(event, "num", None) == 4:
            step = -3
        elif getattr(event, "num", None) == 5:
            step = 3
        else:
            delta = getattr(event, "delta", 0)
            if not delta:
                return
            step = -int(delta / 120) * 3
            if step == 0:
                step = -1 if delta > 0 else 1

        if self.scroll_canvas.bbox("all"):
            self.scroll_canvas.yview_scroll(step, "units")

    def _update_responsive_layout(self, width):
        stacked = width < 900
        compact = width < 720

        if stacked != self._columns_stacked:
            self._columns_stacked = stacked
            self._left_column.grid_forget()
            self._right_column.grid_forget()

            if stacked:
                self._columns_frame.columnconfigure(0, weight=1, uniform="")
                self._columns_frame.columnconfigure(1, weight=0, uniform="")
                self._left_column.grid(row=0, column=0, sticky="nsew")
                self._right_column.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
            else:
                self._columns_frame.columnconfigure(0, weight=1, uniform="main")
                self._columns_frame.columnconfigure(1, weight=1, uniform="main")
                self._left_column.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
                self._right_column.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

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
            self.obj_var.set(path)
            if self.slug_var.get() == "my_character":
                self.slug_var.set(clean_slug(Path(path).stem))
            self.analyze()

    def auto_slug(self):
        self.slug_var.set(clean_slug(self.name_var.get()))

    def _game_root_from_value(self, value=None):
        raw = (self.game_var.get() if value is None else value).strip().strip('"')
        if not raw:
            return None

        path = Path(raw).expanduser()

        if path.suffix.lower() == ".exe":
            path = path.parent

        parts = [part.lower() for part in path.parts]
        if len(parts) >= 3 and parts[-3:] == ["assets", "mods", "racers"]:
            path = path.parents[2]
        elif len(parts) >= 2 and parts[-2:] == ["assets", "mods"]:
            path = path.parents[1]
        elif path.name.lower() == "assets":
            path = path.parent

        return path

    def _mods_path_from_game(self, value=None):
        root = self._game_root_from_value(value)
        return (root / "assets" / "mods" / "racers") if root else None

    def _on_game_path_change(self, *_args):
        self._sync_output_path()

    def _sync_output_path(self):
        mods_path = self._mods_path_from_game()
        self.output_var.set(str(mods_path) if mods_path else "")

    def _validated_game_root(self):
        root = self._game_root_from_value()
        if root is None:
            messagebox.showerror(APP_TITLE, "Choose the Crash Forge Racing game folder or ctr_native.exe.")
            return None

        if not root.is_dir():
            messagebox.showerror(APP_TITLE, f"Game folder not found:\n{root}")
            return None

        has_exe = (root / "ctr_native.exe").is_file()
        has_source = ((root / "CMakeLists.txt").is_file() and
                      (root / "game").is_dir() and
                      (root / "platform").is_dir())
        has_assets = (root / "assets").is_dir()

        if not (has_exe or has_source or has_assets):
            messagebox.showerror(
                APP_TITLE,
                "That folder does not look like Crash Forge Racing.\n\n"
                "Choose the folder containing ctr_native.exe, or select ctr_native.exe directly.")
            return None

        return root

    def choose_game_folder(self):
        initial = self._game_root_from_value()
        path = filedialog.askdirectory(
            title="Choose Crash Forge Racing game folder",
            initialdir=str(initial) if initial and initial.exists() else None)
        if path:
            self.game_var.set(path)

    def choose_game_exe(self):
        initial = self._game_root_from_value()
        path = filedialog.askopenfilename(
            title="Choose ctr_native.exe",
            initialdir=str(initial) if initial and initial.exists() else None,
            filetypes=[("Crash Forge Racing", "ctr_native.exe"),
                       ("Executable", "*.exe"),
                       ("All files", "*.*")])
        if path:
            self.game_var.set(path)

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

        if self.own_wheels_var.get():
            required = {"wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr"}
            found = {g.lower() for g in stats["groups"]}
            missing = sorted(required - found)
            if missing:
                warnings.append("Own wheels enabled, but these groups were not found: " +
                                ", ".join(missing) + ". The mod can still be built, but those wheels will not rotate separately.")

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
        out_root = game_root / "assets" / "mods" / "racers"
        out_root.mkdir(parents=True, exist_ok=True)
        self.output_var.set(str(out_root))
        dest = out_root / slug

        if dest.exists():
            if not messagebox.askyesno(APP_TITLE, f"This folder already exists:\n{dest}\n\nReplace its contents?"):
                return
            shutil.rmtree(dest)
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

        has_wheels = "false" if self.own_wheels_var.get() else "true"
        kart_slug = self.kart_var.get().strip()
        kart_line = f"kart = {kart_slug}\n" if kart_slug else ""
        ini = (
            "[character]\n"
            f"name = {self.name_var.get().strip()}\n"
            "enabled = true\n"
            f"fallback_retail = {self.fallback_var.get()}\n"
            f"engine = {self.engine_var.get()}\n"
            f"{kart_line}"
            f"has_wheels = {has_wheels}\n\n"
            "[model]\n"
            f"scale = {scale}\n"
            f"offset_x = {ox}\n"
            f"offset_y = {oy}\n"
            f"offset_z = {oz}\n\n"
            "[assets]\n"
            f"asset_name = {slug}\n"
            f"icon = {icon_value}\n"
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
    App().mainloop()
