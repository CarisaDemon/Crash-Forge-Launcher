"""Persistent, resizable GUI pane and window positions for Crash Forge editors.

Stores only presentation geometry under LOCALAPPDATA/CrashForgeRacing.
Account credentials, game settings and mod files are never read or changed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tkinter as tk

from forge_editor_geometry import (tk_absolute_geometry,
                                   enforce_native_window_position)


_LAYOUT_ID = re.compile(r"^[a-z0-9_-]{3,56}$")


def layout_file(tool_id, *, environment=None):
    if not _LAYOUT_ID.fullmatch(tool_id):
        raise ValueError("Invalid editor layout ID")
    env = os.environ if environment is None else environment
    local = env.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".crashforge"
    return base / "CrashForgeRacing" / ("editor-layout-" + tool_id + ".json")


def load_layout(file):
    """Treat arbitrary or corrupt JSON as absent, never as executable settings."""
    try:
        p = Path(file)
        if not p.is_file() or p.stat().st_size > 16384:
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != 1:
            return {}
        return data
    except (OSError, ValueError, UnicodeError, TypeError):
        return {}


def clamp_ratio(value, default=.55):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return max(.13, min(.87, float(value)))


def validate_saved_window(value):
    if not isinstance(value, dict):
        return None
    try:
        w, h = int(value["width"]), int(value["height"])
        x, y = int(value["x"]), int(value["y"])
        maximized = value.get("maximized") is True
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    if not (640 <= w <= 12000 and 400 <= h <= 8000 and
            -131072 <= x <= 131072 and -131072 <= y <= 131072):
        return None
    return {"width": w, "height": h, "x": x, "y": y,
            "maximized": maximized}


def _screen_union(window):
    if os.name == "nt":
        try:
            import ctypes
            get = ctypes.windll.user32.GetSystemMetrics
            left, top, w, h = [int(get(i)) for i in (76, 77, 78, 79)]
            if w > 0 and h > 0:
                return left, top, left + w, top + h
        except (OSError, AttributeError, TypeError):
            pass
    return (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())


def visible_on_desktop(window, geometry):
    area = _screen_union(window)
    x = geometry["x"]
    y = geometry["y"]
    w, h = geometry["width"], geometry["height"]
    left, top, right, bottom = area
    # Require at least part of the TITLE BAR and 80px horizontal overlap.
    return x + w > left + 80 and x < right - 80 and y < bottom - 55 and y + 55 > top


class WindowLayoutMemory:
    """Window size/position/maximize and user-adjusted pane dividers."""

    def __init__(self, window, tool_id, *, file=None):
        self.window = window
        self.file = Path(file) if file else layout_file(tool_id)
        self.saved = load_layout(self.file)
        self.panes = {}
        self._initializing = True
        self._normal = validate_saved_window(self.saved.get("window"))
        self._write_job = None
        self._position_job = None
        self._closing = False
        self._extra = {}

    def register_pane(self, name, pane):
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,35}", name):
            raise ValueError("Invalid pane name")
        self.panes[name] = pane
        pane.bind("<ButtonRelease-1>", self._changed, add="+")

    def get_number(self, key, default, low, high):
        value = self.saved.get("extra")
        value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(low, min(high, int(value)))
        return default

    def put_number(self, key, value):
        self._extra[key] = int(value)
        self.schedule_save()

    def start(self):
        saved = validate_saved_window(self.saved.get("window"))
        if saved and visible_on_desktop(self.window, saved):
            self.window.geometry(tk_absolute_geometry(
                saved["width"], saved["height"], saved["x"], saved["y"]))
            # Tk may silently discard the position applied before the native
            # window first maps, especially after a previous editor root
            # closed in this process. Reapply after creation via SetWindowPos.
            if not saved["maximized"]:
                self._position_job = self.window.after(
                    130, lambda: self._restore_saved_window(saved))
        self.window.bind("<Configure>", self._changed, add="+")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        if saved and saved["maximized"]:
            self.window.after(70, lambda: self.window.state("zoomed"))
        self.window.after(220, self.restore_panes)
        self.window.after(600, self._ready)

    def _restore_saved_window(self, saved):
        self._position_job = None
        if self._closing or not self.window.winfo_exists():
            return
        if self.window.state() != "normal":
            return
        if not visible_on_desktop(self.window, saved):
            return
        enforce_native_window_position(
            self.window, saved["x"], saved["y"],
            saved["width"], saved["height"])
        # SetWindowPos dimensions include OS title bar/borders. Tk geometry
        # sizes the CLIENT area; reapply after mapping to avoid losing 16x39.
        self.window.geometry(tk_absolute_geometry(
            saved["width"], saved["height"], saved["x"], saved["y"]))

    def restore_panes(self):
        panes = self.saved.get("panes")
        if not isinstance(panes, dict):
            return
        for name, pane in self.panes.items():
            try:
                if not pane.winfo_ismapped() or len(pane.panes()) < 2:
                    continue
                horizontal = pane.cget("orient") == "horizontal"
                size = pane.winfo_width() if horizontal else pane.winfo_height()
                if size < 100:
                    continue
                ratio = clamp_ratio(panes.get(name), default=.58)
                coord = round(size * ratio)
                pane.sash_place(0, coord if horizontal else 1,
                               1 if horizontal else coord)
            except (tk.TclError, ValueError):
                continue

    def _ready(self):
        self._initializing = False
        if self._normal is None:
            self._remember_normal()

    def _remember_normal(self):
        try:
            if self.window.state() != "normal":
                return
            width, height = self.window.winfo_width(), self.window.winfo_height()
            if width >= 640 and height >= 400:
                self._normal = {
                    "width": width, "height": height,
                    "x": self.window.winfo_x(), "y": self.window.winfo_y(),
                    "maximized": False,
                }
        except tk.TclError:
            pass

    def _changed(self, event):
        if self._initializing or self._closing:
            return
        if getattr(event, "widget", None) is self.window:
            self._remember_normal()
        self.schedule_save()

    def schedule_save(self):
        if self._initializing or self._closing:
            return
        if self._write_job is not None:
            self.window.after_cancel(self._write_job)
        self._write_job = self.window.after(700, self.save)

    def save(self):
        if self._write_job is not None:
            try:
                self.window.after_cancel(self._write_job)
            except tk.TclError:
                pass
        self._write_job = None
        if not self.window.winfo_exists():
            return
        self._remember_normal()
        try:
            maximized = self.window.state() == "zoomed"
        except tk.TclError:
            maximized = False
        normal = self._normal or validate_saved_window(self.saved.get("window"))
        if not normal:
            return
        values = {}
        for key, pane in self.panes.items():
            try:
                if not pane.winfo_ismapped() or len(pane.panes()) < 2:
                    continue
                horizontal = pane.cget("orient") == "horizontal"
                size = pane.winfo_width() if horizontal else pane.winfo_height()
                if size < 80:
                    continue
                point = pane.sash_coord(0)[0 if horizontal else 1]
                values[key] = round(clamp_ratio(point / size), 5)
            except (tk.TclError, ValueError, ZeroDivisionError):
                continue
        old_panes = self.saved.get("panes")
        if isinstance(old_panes, dict):
            for key in self.panes:
                if key not in values and key in old_panes:
                    values[key] = clamp_ratio(old_panes[key])
        old_extra = self.saved.get("extra")
        extra = dict(old_extra) if isinstance(old_extra, dict) else {}
        extra.update(self._extra)
        value = {"schema": 1,
                 "window": {**normal, "maximized": maximized},
                 "panes": values, "extra": extra}
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_name(self.file.name + ".tmp")
            tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
            os.replace(tmp, self.file)
            self.saved = value
        except OSError:
            pass  # Window closing should never fail due to a settings disk error.

    def close(self):
        if self._closing:
            return
        if self._write_job is not None:
            self.window.after_cancel(self._write_job)
        if self._position_job is not None:
            self.window.after_cancel(self._position_job)
            self._position_job = None
        self.save()
        self._closing = True
        self.window.destroy()
