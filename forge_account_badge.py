"""Launcher account header: state, safe GitHub avatars and compact layout.

No synthetic/generated artwork: signed-out profiles use a native Tk canvas
silhouette. GitHub images are fetched from the verified GitHub avatar CDN.
"""
from __future__ import annotations

import io
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageOps


GITHUB_AVATAR_HOST = "avatars.githubusercontent.com"
MAX_AVATAR_BYTES = 1_000_000


def header_layout(width):
    """Return a stable profile-card rect and responsive header flags."""
    width = max(760, int(width))
    compact = width < 1200
    right = width - (128 if compact else 337)
    card_width = 186 if compact else 194
    return {
        "left": right - card_width, "right": right,
        "top": 11, "bottom": 66,
        "show_hub_button": width >= 920,
        "compact_version": compact,
    }


def account_menu_items(signed_in):
    """Guest has LOGIN only; account actions require an active session."""
    return (("MY ACCOUNT", "OPEN FORGE HUB", "SIGN OUT") if signed_in
            else ("LOG IN", "OPEN FORGE HUB"))


def monitor_work_area_at(x, y, fallback=(0, 0, 1920, 1080)):
    """Nearest *actual monitor* work area, in desktop-wide screen coordinates.

    Tk's winfo_screenwidth/height report the primary screen on Windows, so
    clamping a floating menu to those values throws it onto the first monitor.
    """
    import os
    if os.name != "nt":
        return tuple(fallback)
    try:
        import ctypes
        from ctypes import wintypes

        class Point(ctypes.Structure):
            _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))

        class MonitorInfo(ctypes.Structure):
            _fields_ = (("cbSize", wintypes.DWORD),
                        ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD))

        api = ctypes.windll.user32
        from_point = api.MonitorFromPoint
        from_point.argtypes = (Point, wintypes.DWORD)
        from_point.restype = wintypes.HANDLE
        handle = from_point(Point(int(x), int(y)), 2)  # MONITOR_DEFAULTTONEAREST
        if not handle:
            return tuple(fallback)

        monitor_info = api.GetMonitorInfoW
        monitor_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
        monitor_info.restype = wintypes.BOOL
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not monitor_info(handle, ctypes.byref(info)):
            return tuple(fallback)
        r = info.rcWork
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except (AttributeError, OSError, ValueError, TypeError):
        return tuple(fallback)


def account_popup_position(parent_x, parent_y, badge_layout,
                           popup_width, popup_height, work_area, *, gap=5):
    """Position dropdown under the profile badge on its own monitor.

    Both input and output are *desktop-wide* coordinates, which may be
    negative for displays located to the left/above the primary monitor.
    """
    left, top, right, bottom = map(int, work_area)
    popup_width = int(popup_width)
    popup_height = int(popup_height)
    desired_x = int(parent_x) + int(badge_layout["right"]) - popup_width
    desired_y = int(parent_y) + int(badge_layout["bottom"]) + gap
    if desired_y + popup_height > bottom - 3:
        desired_y = int(parent_y) + int(badge_layout["top"]) - popup_height - gap
    # Clamp to the owning monitor only, never to the primary monitor.
    x = max(left + 3, min(desired_x, right - popup_width - 3))
    y = max(top + 3, min(desired_y, bottom - popup_height - 3))
    return (x, y)

def account_label(profile, *, connected, signed_in, pending=False):
    """Never show a signed-in user as Guest during a temporary auth outage.

    Session presence and online validation are different states. The last
    validated display name survives launcher restarts without a network fetch.
    """
    profile = profile if isinstance(profile, dict) else {}
    if not signed_in:
        return {"name": "Guest", "status": "Not signed in", "online": False,
                "avatar_url": None}
    name = profile.get("username") or profile.get("display_name") or "My Account"
    return {
        "name": str(name)[:22],
        "status": "Online" if connected else ("Connecting..." if pending else "Offline"),
        "online": bool(connected),
        "avatar_url": github_avatar_url(profile.get("avatar_url")),
    }


def github_avatar_url(value):
    if not isinstance(value, str) or len(value) > 512:
        return None
    try:
        url = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    try:
        port = url.port
    except ValueError:
        return None
    if (url.scheme != "https" or url.hostname != GITHUB_AVATAR_HOST
            or port not in (None, 443) or url.username or url.password
            or url.fragment or not url.path.startswith("/u/")):
        return None
    return value


class NoAvatarRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def fetch_github_avatar(url):
    url = github_avatar_url(url)
    if not url:
        return None
    req = urllib.request.Request(url, headers={
        "User-Agent": "CrashForgeLauncher/0.3 Accounts",
        "Accept": "image/png,image/jpeg,image/webp",
    })
    with urllib.request.build_opener(NoAvatarRedirect()).open(
            req, timeout=7) as response:
        if int(response.headers.get("Content-Length", 0) or 0) > MAX_AVATAR_BYTES:
            return None
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        if content_type not in ("image/png", "image/jpeg", "image/webp"):
            return None
        image_bytes = response.read(MAX_AVATAR_BYTES + 1)
        return image_bytes if len(image_bytes) <= MAX_AVATAR_BYTES else None


def avatar_photo(data, *, size=44):
    """Pillow sprite. Construct ImageTk.PhotoImage ONLY from Tk main thread."""
    with Image.open(io.BytesIO(data)) as source:
        if source.width > 2048 or source.height > 2048:
            raise ValueError("Avatar image is too large")
        avatar = ImageOps.fit(
            source.convert("RGBA"), (size * 3, size * 3),
            method=Image.Resampling.LANCZOS)
    mask = Image.new("L", avatar.size, 0)
    drawer = ImageDraw.Draw(mask)
    drawer.ellipse((0, 0, avatar.width - 1, avatar.height - 1), fill=255)
    avatar.putalpha(mask)
    return avatar.resize((size, size), Image.Resampling.LANCZOS)
