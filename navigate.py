"""Open one skin's results from the collection screen (search, tile, Search Options, green check) and close them.
Windows only. Start with the collection screen open and the search box EMPTY. Run:
    python navigate.py "Starveil AWP"          searches for the skin and opens its results
    python navigate.py --close                 closes an open results list
Every click uses a point from screens.find_*, which only returns one on the screen it belongs to; each step waits
for the next screen to show before going on, and anything unexpected stops with nothing more clicked.
"""
import sys
import time

import controller
import screen
import screens


def wait_for(hwnd: int, state: str, seconds: float):
    """Capture until the screen is `state`; the capture, or None on timeout or if Roblox lost focus."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        img = screen.capture(hwnd)
        if img is None:
            return None
        if screens.classify(img) == state:
            return img
        time.sleep(0.4)
    return None


def _click(hwnd: int, point, img) -> bool:
    """Click a point found on screenshot `img`. Refused if the window is a different size now (resized or moved
    to another monitor since the screenshot): the same point would land on something else."""
    x0, y0, w, h = screen.client_rect(hwnd)
    if (w, h) != (img.shape[1], img.shape[0]):
        return False
    return controller.click(hwnd, x0 + point[0], y0 + point[1])


def search_for(hwnd: int, skin: str) -> tuple[bool, str]:
    """Click the search box and type the skin name, but only after the text cursor shows in the box: without it
    the letters would reach the game as key presses. The box must be empty (typed text also looks like a cursor)."""
    img = wait_for(hwnd, "collection", 8)  # 8 s: an in-game "X bought Y" banner can cover the screen for ~6 s
    point = None if img is None else screens.find_search_box(img)
    if point is None:
        return False, "no search box on the collection screen"
    if not _click(hwnd, point, img):
        return False, "click not sent (Roblox lost focus, or the window changed size)"
    for _ in range(8):  # the cursor blinks: look for it over about 2 s
        time.sleep(0.25)
        img = screen.capture(hwnd)
        if img is None:
            return False, "Roblox lost focus"
        if screens.search_caret(img):
            break
    else:
        return False, "no text cursor in the search box; typed nothing"
    if not controller.type_text(hwnd, skin):
        return False, "typing stopped (Roblox lost focus, or a character has no key)"
    time.sleep(1.0)  # let the grid narrow: tiles move while it does, so the tile is looked for after this
    return True, ""


def open_results(hwnd: int, skin: str, save=lambda name, img: None):
    """(results screenshot, '') or (None, why it stopped). save(name, img) keeps diagnostics."""
    img = wait_for(hwnd, "collection", 8)
    if img is None:
        return None, "not on the collection screen"
    tile = screens.find_skin_tile(img, skin)
    if tile is None:
        save("no_tile", img)
        return None, f"no single tile labelled {skin!r} in the grid"
    if not _click(hwnd, tile, img):
        return None, "click not sent (Roblox lost focus, or the window changed size)"
    img = wait_for(hwnd, "options", 4)
    if img is None:
        return None, "Search Options did not open after clicking the tile"
    save("options", img)
    if not screens.options_is_for(img, skin):  # a click on a moved tile can open another skin
        return None, f"Search Options is not for {skin!r}"
    check = screens.find_check_button(img)
    if check is None:
        return None, "no green check found in Search Options"
    if not _click(hwnd, check, img):
        return None, "click not sent (Roblox lost focus, or the window changed size)"
    img = wait_for(hwnd, "results", 8)
    if img is None:
        return None, "results list did not open after the green check"
    save("results", img)
    return img, ""


def close_results(hwnd: int) -> bool:
    """Click the red X under the results list and wait for the collection screen. False if it did not work."""
    img = wait_for(hwnd, "results", 8)  # a banner can hide the list for a few seconds
    point = None if img is None else screens.find_close_button(img)
    return point is not None and _click(hwnd, point, img) and wait_for(hwnd, "collection", 4) is not None


def main() -> int:
    import cv2
    from pathlib import Path

    from config import load_config

    close = "--close" in sys.argv
    skin = next((a for a in sys.argv[1:] if not a.startswith("--")), "Starveil AWP")
    hwnd = screen.find_roblox()
    if hwnd is None:
        print("Roblox window not found")
        return 2
    if not screen.is_focused(hwnd):
        print("Click the Roblox title bar within 30 s (not inside the game)...")
        deadline = time.time() + 30
        while not screen.is_focused(hwnd) and time.time() < deadline:
            time.sleep(0.5)
    out = Path(load_config().output_dir) / "probe"
    out.mkdir(parents=True, exist_ok=True)
    if close:
        print("Closing the results: hands off the mouse.")
        ok = close_results(hwnd)
        print("Closed; the collection screen is back" if ok else "Could not close the results (nothing else was clicked)")
        return 0 if ok else 1
    print("Opening the results: hands off the mouse and keyboard.")
    ok, why = search_for(hwnd, skin)
    img = None
    if ok:
        img, why = open_results(hwnd, skin, lambda name, im: cv2.imwrite(str(out / f"nav_{name}.png"), im))
    print(f"Results are open ({screens.classify(img)})" if img is not None else f"Stopped: {why}")
    return 0 if img is not None else 1


if __name__ == "__main__":
    sys.exit(main())
