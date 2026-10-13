"""Central monitor policy for EVERY Tk child window of Crash Forge Launcher.

No per-dialog centering code is required. The owner launcher monitor wins,
including displays left/above primary with negative virtual coordinates.
The policy is installed per launcher Tk interpreter, not for other processes.
"""
from __future__ import annotations

import tkinter as tk
import weakref
from tkinter import commondialog
import forge_editor_geometry as geometry

_active_owner_ref = None
_original_native_show = commondialog.Dialog.show


def choose_position(area, owner, child):
    """Return (width, height, x, y) if child is off the owner's work area."""
    left, top, area_w, area_h = (int(v) for v in area)
    px, py, pw, ph = (int(v) for v in owner)
    x, y, width, height = (int(v) for v in child)
    if area_w < 1 or area_h < 1:
        return None
    requested_width, requested_height = width, height
    width = max(1, min(width, area_w))
    height = max(1, min(height, area_h))
    right, bottom = left + area_w, top + area_h
    if (width == requested_width and height == requested_height
            and left <= x and top <= y and x + width <= right
            and y + height <= bottom):
        return None
    new_x = min(max(left, px + (pw - width) // 2), right - width)
    new_y = min(max(top, py + (ph - height) // 2), bottom - height)
    return width, height, new_x, new_y


class WindowPolicy:
    def __init__(self, owner):
        self.owner = owner
        self._busy = set()
        # All child windows in the same Tcl interpreter are covered, even
        # Toplevels created in other modules, third-party dialogs and popups.
        owner.bind_all("<Map>", self._event, add="+")
        owner.bind_all("<Configure>", self._event, add="+")

    def _event(self, event):
        window = event.widget
        if not isinstance(window, tk.Toplevel):
            return
        if window is self.owner or window.tk is not self.owner.tk:
            return
        self.place(window)

    def place(self, window):
        try:
            if window in self._busy or not window.winfo_exists():
                return
            if window.state() in ("withdrawn", "iconic"):
                return
            area = self.owner._current_monitor_workarea()
            if area is None:
                return
            owner = (self.owner.winfo_rootx(), self.owner.winfo_rooty(),
                     max(1, self.owner.winfo_width()), max(1, self.owner.winfo_height()))
            width = window.winfo_width()
            height = window.winfo_height()
            child = (window.winfo_rootx(), window.winfo_rooty(),
                     width if width > 1 else max(1,window.winfo_reqwidth()),
                     height if height > 1 else max(1,window.winfo_reqheight()))
            target = choose_position(area, owner, child)
            if target is None:
                return
            width, height, x, y = target
            self._busy.add(window)
            try:
                window.geometry(geometry.tk_absolute_geometry(width, height, x, y))
            finally:
                self._busy.discard(window)
        except (AttributeError, tk.TclError, ValueError, RuntimeError):
            # A closing/transient dialog must never break the launcher.
            return


def native_dialog_options(dialog, options, owner):
    """Attach missing parent to native Windows file/message/color dialogs."""
    kwargs = dict(options)
    if (owner is not None and dialog.master is None
            and "parent" not in kwargs and "parent" not in dialog.options):
        try:
            if owner.winfo_exists():
                kwargs["parent"] = owner
        except (AttributeError, tk.TclError):
            pass
    return kwargs


def _native_show(dialog, **options):
    owner = _active_owner_ref() if _active_owner_ref is not None else None
    return _original_native_show(dialog,
        **native_dialog_options(dialog, options, owner))


def install(owner):
    """Invoke once per Launcher(), before building any dialogs."""
    global _active_owner_ref
    existing = getattr(owner, "_forge_window_policy", None)
    if existing is None:
        owner._forge_window_policy = WindowPolicy(owner)
    _active_owner_ref = weakref.ref(owner)
    # Tk Toplevel windows use the <Map>/<Configure> policy above. Native
    # file/message/color pickers cannot receive those Tk map events;
    # parent them once here so Windows opens them on the launcher monitor.
    if commondialog.Dialog.show is not _native_show:
        commondialog.Dialog.show = _native_show
    return owner._forge_window_policy
