"""Mouse and keyboard input for Roblox. Windows only (run with Windows Python).

Roblox must be in front for every single event; the moment it is not, nothing more is sent. Releases (button up,
key up) are the one exception: they are always sent so nothing is left held down.

click() sends a click wherever it is told. Callers must get the point from screens.find_* only, which return a
point on the right screen and nothing else; never click trade or payment buttons. Teleport and buy only in `main.py --snipe` (scanner/windows/snipe.py).
"""
import ctypes
import sys
import time

from scanner.windows import screen

MOVE, LEFT_DOWN, LEFT_UP, WHEEL = 0x0001, 0x0002, 0x0004, 0x0800  # mouse_event flags
KEY_UP, SHIFT, CONTROL, BACKSPACE, V, DELETE = 0x0002, 0x10, 0x11, 0x08, 0x56, 0x2E  # keybd_event flag, virtual keys
NOTCH = 120

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.VkKeyScanW.restype = ctypes.c_short  # a SHORT: -1 means "no such key"


def _send(hwnd: int, event, *args) -> bool:
    if not screen.is_focused(hwnd):
        return False
    event(*args)
    return True


def _run(hwnd: int, steps) -> bool:
    for event, *args in steps:
        if not _send(hwnd, event, *args):
            return False
        time.sleep(0.015)
    return True


def _inside(hwnd: int, x: int, y: int) -> bool:
    """Is the screen point inside the Roblox game area? Anything outside is another window or the title bar."""
    left, top, w, h = screen.client_rect(hwnd)
    return left <= x < left + w and top <= y < top + h


def _hover(x: int, y: int) -> list:
    # Roblox reads raw input: SetCursorPos alone is not a hover and the wheel/click is ignored; a real 1 px move is.
    return [(user32.SetCursorPos, int(x), int(y)),  # int(): ctypes rejects numpy ints (card boxes are numpy)
            (user32.mouse_event, MOVE, 1, 0, 0, 0), (user32.mouse_event, MOVE, -1, 0, 0, 0)]


def scroll(hwnd: int, x: int, y: int, notches: int) -> bool:
    """Hover screen point (x, y) and turn the wheel; notches > 0 scrolls down. False if focus was lost."""
    wheel = -NOTCH if notches > 0 else NOTCH
    if not _inside(hwnd, x, y):
        return False
    return _run(hwnd, _hover(x, y) + [(user32.mouse_event, WHEEL, 0, 0, wheel, 0)] * abs(notches))


def click(hwnd: int, x: int, y: int, hover: float = 0) -> bool:
    """Left-click screen point (x, y), resting `hover` s on it first. False, sending nothing, if the point is outside
    the game area; False if focus was lost before the button went down."""
    if not _inside(hwnd, x, y):
        return False
    if not _run(hwnd, _hover(x, y)):
        return False
    if hover:
        time.sleep(hover)
    if not _send(hwnd, user32.mouse_event, LEFT_DOWN, 0, 0, 0, 0):
        return False
    try:
        time.sleep(0.03)
    finally:  # always, even on Ctrl+C: a button must never stay down
        user32.mouse_event(LEFT_UP, 0, 0, 0, 0)
    return True


def _tap(hwnd: int, key: int, shift: bool = False) -> bool:
    """Press and release one key (with Shift if asked). False if focus was lost; whatever went down comes up."""
    scan = user32.MapVirtualKeyW(key, 0)
    try:
        ok = (not shift or _send(hwnd, user32.keybd_event, SHIFT, 0, 0, 0)) and _send(hwnd, user32.keybd_event, key, scan, 0, 0)
    finally:  # always, even on Ctrl+C: nothing is left held down
        user32.keybd_event(key, scan, KEY_UP, 0)
        if shift:
            user32.keybd_event(SHIFT, 0, KEY_UP, 0)
    return ok


def type_text(hwnd: int, text: str) -> bool:
    """Type text one key at a time into whatever has keyboard focus. False if focus was lost or a character
    has no key; keys already down are always released."""
    for ch in text:
        vk = user32.VkKeyScanW(ord(ch))
        if vk == -1 or vk & 0x600:  # no key, or one that needs Ctrl/Alt (AltGr layouts): never type a wrong character
            return False
        if not _tap(hwnd, vk & 0xFF, bool(vk & 0x100)):
            return False
    return True


def _set_clipboard(text: str) -> bool:
    """Put `text` on the clipboard (replacing what was there). False if another program has it locked."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GlobalAlloc.restype, k32.GlobalAlloc.argtypes = ctypes.c_void_p, [ctypes.c_uint, ctypes.c_size_t]
    k32.GlobalLock.restype, k32.GlobalLock.argtypes = ctypes.c_void_p, [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype, user32.SetClipboardData.argtypes = ctypes.c_void_p, [ctypes.c_uint, ctypes.c_void_p]
    for _ in range(10):  # the clipboard can be busy for a moment
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return False
    try:
        user32.EmptyClipboard()
        data = (text + "\0").encode("utf-16-le")
        handle = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ptr = k32.GlobalLock(handle) if handle else None
        if not ptr:
            return False
        ctypes.memmove(ptr, data, len(data))
        k32.GlobalUnlock(handle)
        if user32.SetClipboardData(13, handle):  # CF_UNICODETEXT; the clipboard owns the memory now
            return True
        k32.GlobalFree.argtypes = [ctypes.c_void_p]
        k32.GlobalFree(handle)  # it was not taken, so it is still ours
        return False
    finally:
        user32.CloseClipboard()


def paste_text(hwnd: int, text: str) -> bool:
    """Copy `text` to the clipboard and press Ctrl+V: the whole text arrives at once. False if the clipboard was
    busy or focus was lost before the paste; Ctrl is always released."""
    if not _set_clipboard(text):
        return False
    try:
        return _send(hwnd, user32.keybd_event, CONTROL, 0, 0, 0) and _tap(hwnd, V)
    finally:
        user32.keybd_event(CONTROL, 0, KEY_UP, 0)


def backspace(hwnd: int, times: int) -> bool:
    """Press Backspace `times` times. It deletes in a focused text box and does nothing in the game itself."""
    return all(_tap(hwnd, BACKSPACE) for _ in range(times))


def clear_box(hwnd: int, times: int) -> bool:
    """Empty the text box that has focus: Backspace deletes left of the cursor and Delete right of it (a click leaves the
    cursor wherever it landed, and Roblox ignores End). Both do nothing in the game itself."""
    return backspace(hwnd, times) and all(_tap(hwnd, DELETE) for _ in range(times))


def hold_key(hwnd: int, key: int, seconds: float) -> bool:
    """Hold one key down for `seconds` (walking with W/S, the hold-E prompts). False, and the key comes up at once,
    if Roblox loses focus while it is held; the key always comes up."""
    scan = user32.MapVirtualKeyW(key, 0)
    try:
        if not _send(hwnd, user32.keybd_event, key, scan, 0, 0):
            return False
        end = time.time() + seconds
        while time.time() < end:
            if not screen.is_focused(hwnd):
                return False
            time.sleep(0.05)
        return True
    finally:  # always, even on Ctrl+C: nothing is left held down
        user32.keybd_event(key, scan, KEY_UP, 0)
