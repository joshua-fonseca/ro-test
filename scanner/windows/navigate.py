"""Open one skin's results from the collection screen (search, tile, Search Options, green check) and close them.
Windows only. Start with the collection screen open (any text in the search box is cleared first). Run:
    python -m scanner.windows.navigate "Starveil AWP" Sniper   picks the category, searches for the skin and opens its results
    python -m scanner.windows.navigate --close                 closes an open results list
Every click uses a point from screens.find_*, which only returns one on the screen it belongs to; each step waits
for the next screen to show before going on, and anything unexpected stops with nothing more clicked.
"""
import re
import sys
import time

import cv2

from scanner.windows import controller
from scanner.reading import layout
from scanner.windows import screen
from scanner.reading import screens


def wait_for(hwnd: int, state: str, seconds: float):
    """Capture until the screen is `state`; the capture, or None on timeout or if Roblox lost focus."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        img = screen.capture(hwnd)
        if img is None:
            return None
        if screens.classify(img) == state:
            return img
        time.sleep(0.1)
    return None


def _grid_change(a, b) -> float:
    """How much the skin grid differs between two captures (mean pixel difference); 99 if the sizes differ."""
    if a.shape != b.shape:
        return 99.0
    h, w = a.shape[:2]
    grid = (slice(int(0.18 * h), int(0.82 * h)), slice(int(0.28 * w), int(0.84 * w)))
    return float(cv2.absdiff(a[grid], b[grid]).mean())


def _settled(hwnd: int, img, seconds: float = 3):
    """The latest capture once the skin grid has stopped moving (two frames alike), so the slow tile reading is
    not spent on a grid that is still narrowing; whatever the last frame was after `seconds`; None if focus is lost."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        cur = screen.capture(hwnd)
        if cur is None:
            return None
        if _grid_change(cur, img) < 0.5:  # borders animate: a little change is normal
            return cur
        img = cur
        time.sleep(0.05)
    return img


def _click(hwnd: int, point, img, hover: float = 0) -> bool:
    """Click a point found on screenshot `img`. Refused if the window is a different size now (resized or moved
    to another monitor since the screenshot): the same point would land on something else."""
    x0, y0, w, h = screen.client_rect(hwnd)
    if (w, h) != (img.shape[1], img.shape[0]):
        return False
    x, y = x0 + point[0], y0 + point[1]
    return controller.click(hwnd, x, y, hover) if hover else controller.click(hwnd, x, y)


def _text_shows(hwnd: int):
    """(True, img) once the search box shows text, (False, img) if it still does not after about 1 s, (None, None) if
    focus was lost."""
    for _ in range(20):  # the pasted text shows within a few frames
        img = screen.capture(hwnd)
        if img is None:
            return None, None
        if screens.search_has_text(img):
            return True, img
        time.sleep(0.05)
    return False, img


def search_for(hwnd: int, skin: str, save=lambda name, img: None, *, category: str | None = None,
               rarity: str | None = None, filters_on: bool = False) -> tuple[bool, str]:
    """Pick the skin's category (Sniper, Knife...) and rarity (Secret / Limited: names like 'Starry Flip Knife' also
    show their [Rainbow] variants, which are Secret), click the search box, clear any old text, and type the skin
    name, but only after the text cursor shows in the empty box: without it the letters would reach the game as
    key presses."""
    img = wait_for(hwnd, "collection", 8)  # 8 s: an in-game "X bought Y" banner can cover the screen for ~6 s
    if filters_on:  # the last search already picked this category; the rarity is still checked (one look, no click if lit)
        category = None
    if category and img is not None:
        point = layout.point(img, f"category:{category}", lambda: layout.from_sibling(
            img, f"category:{category}", lambda name: screens.find_category_button(img, name.split(":")[1])))
        if point is None:
            save("no_category", img)
            return False, f"no {category!r} button on the collection screen"
        if not _click(hwnd, point, img):
            return False, "click not sent (Roblox lost focus, or the window changed size)"
        clicked_on = img  # the grid before the category changed it
        img = wait_for(hwnd, "collection", 8)  # the search box does not move with the category
        if img is None:
            raw = screen.capture(hwnd)  # what the screen looked like instead
            if raw is not None:
                save("after_category", raw)
    if rarity in ("Secret", "Limited") and img is not None and category:
        for _ in range(10):  # picking a category resets the rarity to All a moment later: look only after the grid changed
            if _grid_change(img, clicked_on) > 2:
                break
            time.sleep(0.05)
            img = screen.capture(hwnd)
            if img is None:
                return False, "Roblox lost focus"
    # shortcut: the rarity buttons have fixed points only, so on a window that is not 16:9 the search runs unfiltered
    point = layout.fixed(img, f"rarity:{rarity}") if rarity in ("Secret", "Limited") and img is not None else None
    if point is not None and not screens.rarity_is_on(img, rarity):
        if not _click(hwnd, point, img):
            return False, f"could not click the {rarity} filter"
        for _ in range(20):  # the button lights up within a few frames
            img = screen.capture(hwnd)
            if img is None:
                return False, "Roblox lost focus"
            if screens.rarity_is_on(img, rarity):
                time.sleep(0.15)  # a late reset by the category click would switch it off again
                img = screen.capture(hwnd)
                if img is not None and screens.rarity_is_on(img, rarity):
                    break
                if img is None:
                    return False, "Roblox lost focus"
            time.sleep(0.05)
        else:
            save("rarity_not_on", img)
            return False, f"the {rarity} filter did not light up"
    point = None if img is None else layout.point(img, "search_box", lambda: screens.find_search_box(img))
    if point is None:
        if img is not None:
            save("no_search_box", img)
        return False, "no search box on the collection screen"
    if not _click(hwnd, point, img):
        return False, "click not sent (Roblox lost focus, or the window changed size)"
    img = screen.capture(hwnd)
    if img is None:
        return False, "Roblox lost focus"
    save("search_clicked", img)
    for _ in range(4):  # left over from the last skin; Backspace is harmless if the box isn't focused yet
        if not screens.search_has_text(img):
            break
        if not controller.clear_box(hwnd, 40):
            return False, "Roblox lost focus"
        for _ in range(6):  # the box shows the deletions a moment later; some keys may also have been missed
            time.sleep(0.05)
            img = screen.capture(hwnd)
            if img is None:
                return False, "Roblox lost focus"
            if not screens.search_has_text(img):
                break
    if screens.search_has_text(img):
        save("search_not_cleared", img)
        return False, "could not clear the search box"
    before = img  # the grid as it was when the box was empty; it changes once the filter applies
    if controller.paste_text(hwnd, skin):  # the whole name at once
        shown, img = _text_shows(hwnd)
        if shown is None:
            return False, "Roblox lost focus"
        if not shown:  # the box was probably not focused yet (seen live: the grid redraws after the Secret filter click)
            save("paste_not_shown", img)  # the box is still empty, so clicking it and pasting once more cannot double the name
            if not _click(hwnd, point, img) or not controller.paste_text(hwnd, skin):
                return False, "the pasted name did not show in the search box"
            shown, img = _text_shows(hwnd)
            if shown is None:
                return False, "Roblox lost focus"
            if not shown:  # typing now could double the name if the paste lands late
                save("paste_not_shown_twice", img)
                return False, "the pasted name did not show in the search box"
    else:  # nothing was pasted (clipboard busy): type it key by key, but only once the box shows its cursor, or the
        # letters would reach the game as key presses (a paste with no focused box does nothing, so it needs no check)
        for _ in range(16):  # the cursor blinks: look for it over about 2 s
            img = screen.capture(hwnd)
            if img is None:
                return False, "Roblox lost focus"
            if screens.search_caret(img):
                break
            time.sleep(0.1)
        else:
            save("search_no_cursor", img)
            return False, "no text cursor in the search box; typed nothing"
        if not controller.type_text(hwnd, skin):
            return False, "typing stopped (Roblox lost focus, or a character has no key)"
    deadline = time.time() + 2
    while time.time() < deadline:
        img = screen.capture(hwnd)
        if img is None:
            return False, "Roblox lost focus"
        if _grid_change(img, before) > 2:
            time.sleep(0.4)  # the one wait that is needed: the searched skin takes a moment to load into the grid
            break
        time.sleep(0.05)
    return True, ""


def open_results(hwnd: int, skin: str, save=lambda name, img: None):
    """(results screenshot, '') or (None, why it stopped). save(name, img) keeps diagnostics.

    After a search the skin is the first tile of the grid, so the tile and the green check are clicked at once from
    known positions. The Search Options name is checked on the screenshot while the results load: if it was another
    skin's results that opened, they are closed again and nothing is scanned.
    """
    img = wait_for(hwnd, "collection", 8)
    if img is None:
        return None, "not on the collection screen"

    def first_tile(img):
        # The slot is always the same on a 16:9 window; the finder (by red shape) can pick the second tile when the
        # first has a rainbow frame and a pale picture (seen: Nocturne Daisho [Rainbow]). The name check below catches
        # a wrong tile either way.
        return layout.fixed(img, "first_tile") or screens.find_first_tile(img)
    tile = first_tile(img)
    for _ in range(2):  # the grid is still narrowing while the name was typed: look again
        if tile is not None:
            break
        img = wait_for(hwnd, "collection", 8)
        img = None if img is None else _settled(hwnd, img)
        tile = None if img is None else first_tile(img)
    if tile is None:
        if img is not None:
            save("no_tile", img)
        return None, f"no single tile labelled {skin!r} in the grid"
    if not _click(hwnd, tile, img):
        return None, "click not sent (Roblox lost focus, or the window changed size)"
    img = wait_for(hwnd, "options", 4)
    if img is None:
        return None, "Search Options did not open after clicking the tile"
    save("options", img)
    check = layout.point(img, "check", lambda: screens.find_check_button(img))
    if check is None:
        return None, "no green check found in Search Options"
    if not _click(hwnd, check, img):
        return None, "click not sent (Roblox lost focus, or the window changed size)"
    right_skin = screens.options_is_for(img, skin)  # read while the results load
    results = wait_for(hwnd, "results", 8)
    if not right_skin:  # the tile was another skin, or its name did not read: close what opened
        save("options_" + re.sub(r"[^a-z0-9]+", "-", skin.lower()).strip("-"), img)  # one file per skin: see which
        back = back_to_collection(hwnd)
        return None, f"Search Options was not for {skin!r}" + ("" if back else " (and could not get back to the grid)")
    if results is None:
        return None, "results list did not open after the green check"
    save("results", results)
    return results, ""


def back_to_collection(hwnd: int) -> bool:
    """Leave whatever Search Options / results screen is open (cancel or close it) and wait for the collection
    screen. True if the collection screen is showing; nothing is clicked on any other screen."""
    img = screen.capture(hwnd)
    if img is None:
        return False
    state = screens.classify(img)
    if state == "collection":
        return True
    if state == "options":
        point = layout.point(img, "options_cancel", lambda: screens.find_options_cancel(img))
    elif state == "results":
        point = layout.point(img, "close_results", lambda: screens.find_close_button(img))
    else:
        return False
    return point is not None and _click(hwnd, point, img) and wait_for(hwnd, "collection", 4) is not None


def close_results(hwnd: int) -> bool:
    """Click the red X under the results list and wait for the collection screen. False if it did not work."""
    img = wait_for(hwnd, "results", 8)  # a banner can hide the list for a few seconds
    point = None if img is None else layout.point(img, "close_results", lambda: screens.find_close_button(img))
    return point is not None and _click(hwnd, point, img) and wait_for(hwnd, "collection", 4) is not None


def main() -> int:
    import cv2
    from pathlib import Path

    from scanner.logic.config import load_config

    close = "--close" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    skin = args[0] if args else "Starveil AWP"
    category = args[1] if len(args) > 1 else None  # optional second word-group: python -m scanner.windows.navigate "Nya Reaper" Knife
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
    save = lambda name, im: cv2.imwrite(str(out / f"nav_{name}.png"), im)  # noqa: E731
    ok, why = search_for(hwnd, skin, save, category=category)
    img = None
    if ok:
        img, why = open_results(hwnd, skin, save)
    print(f"Results are open ({screens.classify(img)})" if img is not None else f"Stopped: {why}")
    return 0 if img is not None else 1


if __name__ == "__main__":
    sys.exit(main())
