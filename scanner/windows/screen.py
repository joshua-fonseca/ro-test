"""Find, size and capture the Roblox window. Windows only (run with Windows Python); sends no game input.

All sizes are real pixels: the process is per-monitor DPI aware, so a 150% monitor is not scaled.
"""
import ctypes
import sys
from ctypes import wintypes

import numpy as np

ASPECT = 16 / 9


def fit_size(work_w: int, work_h: int, frame_w: int, frame_h: int,
             width: int | None = None, height: int | None = None) -> tuple[int, int]:
    """Client size to request. Neither given: largest 16:9 that fits the usable screen area with the frame."""
    if width and height:
        return width, height
    if width:
        return width, round(width / ASPECT)
    if height:
        return round(height * ASPECT), height
    w = min(work_w - frame_w, int((work_h - frame_h) * ASPECT))
    return w, round(w / ASPECT)


if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class _MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    # Done at import so no caller can forget: without it a 150% monitor reports scaled positions.
    # -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2: real pixels on every monitor
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

    def _is_roblox(hwnd: int) -> bool:
        # Class name read from the live game window; the title alone also matches e.g. an Explorer folder "Roblox"
        cls, title = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        user32.GetWindowTextW(hwnd, title, 64)
        return cls.value == "WINDOWSCLIENT" and title.value == "Roblox"

    def find_roblox(prefer: int | None = None) -> int | None:
        """With several Roblox windows open: `prefer` while it is still a Roblox window, else the one in front, else
        the first."""
        if prefer and user32.IsWindow(prefer) and _is_roblox(prefer):
            return prefer
        front = user32.GetForegroundWindow()
        if front and _is_roblox(front):
            return front
        return user32.FindWindowW("WINDOWSCLIENT", "Roblox") or None

    def foreground_title() -> str:
        """Title of the window in front (diagnostics: what took focus from Roblox)."""
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(user32.GetForegroundWindow(), buf, 256)
        return buf.value

    def is_focused(hwnd: int) -> bool:
        return user32.GetForegroundWindow() == hwnd

    def client_rect(hwnd: int) -> tuple[int, int, int, int]:
        """Game area as (left, top, width, height) in screen pixels."""
        r, p = wintypes.RECT(), wintypes.POINT(0, 0)
        user32.GetClientRect(hwnd, ctypes.byref(r))
        user32.ClientToScreen(hwnd, ctypes.byref(p))
        return p.x, p.y, r.right - r.left, r.bottom - r.top

    def resize(hwnd: int, width: int | None = None, height: int | None = None) -> tuple[int, int]:
        """Move the window to its monitor's top-left and size the game area; returns the size Roblox accepted."""
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE: un-maximize so the size can change
        outer, inner = wintypes.RECT(), wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(outer))
        user32.GetClientRect(hwnd, ctypes.byref(inner))
        frame_w = (outer.right - outer.left) - inner.right
        frame_h = (outer.bottom - outer.top) - inner.bottom
        mi = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
        user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
        work = mi.rcWork
        w, h = fit_size(work.right - work.left, work.bottom - work.top, frame_w, frame_h, width, height)
        user32.MoveWindow(hwnd, work.left, work.top, w + frame_w, h + frame_h, True)
        return client_rect(hwnd)[2:]

    def capture(hwnd: int) -> np.ndarray | None:
        """BGR screenshot of the game area (what vision.py expects), or None: pause, don't scan.

        Screen pixels are copied, so a window or pop-up over Roblox would land in the image;
        only capture while Roblox is in front. Minimized means a 0x0 area.
        """
        from PIL import ImageGrab
        x, y, w, h = client_rect(hwnd)
        if not is_focused(hwnd) or w <= 0 or h <= 0:
            return None
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
        return np.asarray(img)[:, :, ::-1].copy()
