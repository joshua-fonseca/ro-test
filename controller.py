"""Mouse input for Roblox: move and wheel only, never a click. Windows only (run with Windows Python).

Roblox must be in front for every single event; the moment it is not, nothing more is sent.
"""
import ctypes
import sys
import time

import screen

MOVE, WHEEL = 0x0001, 0x0800  # mouse_event flags
NOTCH = 120

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)


def _send(hwnd: int, event, *args) -> bool:
    if not screen.is_focused(hwnd):
        return False
    event(*args)
    return True


def scroll(hwnd: int, x: int, y: int, notches: int) -> bool:
    """Hover screen point (x, y) and turn the wheel; notches > 0 scrolls down. False if focus was lost."""
    x, y = int(x), int(y)  # ctypes rejects numpy ints (card boxes are numpy)
    wheel = -NOTCH if notches > 0 else NOTCH
    # Roblox reads raw input: SetCursorPos alone is not a hover and the wheel is ignored; a real 1 px move is.
    steps = [(user32.SetCursorPos, x, y), (user32.mouse_event, MOVE, 1, 0, 0, 0),
             (user32.mouse_event, MOVE, -1, 0, 0, 0)] + [(user32.mouse_event, WHEEL, 0, 0, wheel, 0)] * abs(notches)
    for event, *args in steps:
        if not _send(hwnd, event, *args):
            return False
        time.sleep(0.03)
    return True
