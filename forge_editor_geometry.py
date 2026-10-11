"""Portable position hand-off from Crash Forge Launcher to companion GUI editors.

CFR_EDITOR_WORKAREA contains virtual-desktop WORK bounds of the monitor where
the launcher lives: "left,top,right,bottom". All monitors may have NEGATIVE
coordinates. Optional and ignored when launching editors independently.
"""
from __future__ import annotations
import os

ENV_NAME = "CFR_EDITOR_WORKAREA"

def parse_workarea(value):
    if not isinstance(value, str) or any(ord(ch) < 32 for ch in value):
        return None
    parts = value.split(",")
    if len(parts) != 4:
        return None
    try:
        left, top, right, bottom = (int(p.strip()) for p in parts)
    except ValueError:
        return None
    if not (-131072 <= left < right <= 131072
            and -131072 <= top < bottom <= 131072):
        return None
    if right - left > 16384 or bottom - top > 16384:
        return None
    return left, top, right, bottom

def workarea_to_env(area):
    if not area or len(area) != 4:
        return None
    left, top, width, height = (int(v) for v in area)
    result = f"{left},{top},{left+width},{top+height}"
    return result if parse_workarea(result) else None

def initial_geometry(width, height, *, workarea=None, environment=None):
    """Return signed Tk geometry centered on designated monitor, else None."""
    env = environment if environment is not None else os.environ
    area = parse_workarea(workarea if workarea is not None else env.get(ENV_NAME))
    if area is None:
        return None
    left, top, right, bottom = area
    w = min(int(width), right - left)
    h = min(int(height), bottom - top)
    if w < 1 or h < 1:
        return None
    x = left + (right - left - w) // 2
    y = top + (bottom - top - h) // 2
    return f"{w}x{h}{x:+d}{y:+d}"

def select_window_geometry(window_width, window_height, parent_rect, monitor_area):
    """Pick launcher-linked Toplevel position without moving to primary screen."""
    left, top, right, bottom = monitor_area
    px, py, pw, ph = (int(p) for p in parent_rect)
    w = min(int(window_width), max(1, right - left))
    h = min(int(window_height), max(1, bottom - top))
    x = min(max(px + (pw - w) // 2, left), right - w)
    y = min(max(py + (ph - h) // 2, top), bottom - h)
    return f"{w}x{h}{x:+d}{y:+d}"