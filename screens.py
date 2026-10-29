"""Which Roblox screen is showing, and where its buttons are. Pure vision on a BGR screenshot: no Windows calls.

Every finder returns a click point only on the screen it belongs to, and None anywhere else. That is the safety
rule for navigation: the green check in Search Options looks like the green Teleport buttons in the results
list, so a point is never returned unless classify() has first confirmed the right screen.
"""
import cv2
import numpy as np
import pytesseract

import vision  # sets the Tesseract path on Windows

Point = tuple[int, int]
_SEARCH_BAR = np.array([68, 67, 67])  # grey of the collection search box, BGR


def modal_box(img: np.ndarray) -> tuple[int, int, int, int] | None:
    """Biggest area of modal background colour, as (left, top, width, height)."""
    bg = (np.abs(img.astype(int) - vision._BG).max(2) <= 2).astype(np.uint8)
    bg = cv2.morphologyEx(bg, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(bg)
    if n < 2:
        return None
    x, y, w, h, _ = stats[1 + np.argmax(stats[1:, 4])]
    return int(x), int(y), int(w), int(h)


def _components(mask: np.ndarray, min_area: int):
    n, _, stats, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    return [(stats[i], cen[i]) for i in range(1, n) if stats[i, 4] >= min_area]


def _search_bar(img: np.ndarray) -> tuple[int, int, int, int] | None:
    """The grey search bar as (left, top, width, height); None if there is none."""
    h, w = img.shape[:2]
    y0 = int(0.75 * h)
    strip = img[y0:, :int(0.7 * w)]
    mask = (np.abs(strip.astype(int) - _SEARCH_BAR).max(2) <= 8).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 25), np.uint8))
    bars = [(s, c) for s, c in _components(mask, 10000) if s[2] >= 0.15 * w]
    if not bars:
        return None
    s, _ = max(bars, key=lambda b: b[0][4])
    return int(s[0]), int(s[1]) + y0, int(s[2]), int(s[3])


def _search_box(img: np.ndarray) -> Point | None:
    bar = _search_bar(img)
    return None if bar is None else (bar[0] + bar[2] // 2, bar[1] + bar[3] // 2)


def search_caret(img: np.ndarray) -> bool:
    """True if the blinking text cursor shows at the left of the empty search box (it blinks: check a few frames).

    Only meaningful before anything is typed; typed text is white too.
    """
    bar = _search_bar(img)
    if bar is None:
        return False
    x, y, w, h = bar
    region = img[max(0, y - 25):y + h + 25, x:x + int(0.35 * w)]
    return bool(((region.min(2) > 200).sum(0) >= 10).any())  # a thin bright vertical line; stray pixels give <= 3


def search_has_text(img: np.ndarray) -> bool:
    """True if something is typed in the search box. Text is white: an empty box shows grey 'Search ...' and at
    most the thin cursor (under 50 bright pixels in the live frames); 'Starveil AWP' gives over 1,600."""
    bar = _search_bar(img)
    if bar is None:
        return False
    x, y, w, h = bar
    region = img[max(0, y - 25):y + h + 25, x:x + w]
    return int((region.min(2) > 200).sum()) > 200


def classify(img: np.ndarray) -> str:
    """'options' (Search Options box), 'results' (listing list), 'collection' (skin grid) or 'unknown'."""
    box = modal_box(img)
    if box is None:
        return "unknown"
    x, y, w, h = box
    band = img[y:y + int(0.7 * h), x:x + w]
    grey = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    grey = cv2.resize(grey, None, fx=2000 / band.shape[1], fy=2000 / band.shape[1])
    text = pytesseract.image_to_string(255 - cv2.threshold(grey, 170, 255, cv2.THRESH_BINARY)[1], config="--psm 6")
    text = " ".join(text.split()).casefold()
    if "search options" in text:
        return "options"
    if "records found" in text:
        return "results"
    return "collection" if _search_box(img) else "unknown"


def find_search_box(img: np.ndarray) -> Point | None:
    """Centre of the collection screen's search box (a wide grey bar under the grid, left side)."""
    return _search_box(img) if classify(img) == "collection" else None


def find_check_button(img: np.ndarray) -> Point | None:
    """Green check in Search Options: the button that shows the results. None on any other screen."""
    if classify(img) != "options":
        return None
    x, y, w, h = modal_box(img)
    box = img[y:y + h, x:x + w].astype(int)
    green = (box[..., 1] > 140) & (box[..., 2] < 120) & (box[..., 0] < 120)
    found = [(s, c) for s, c in _components(green, int(0.001 * w * h)) if s[2] > s[3]]  # a wide button, not a thin line
    if len(found) != 1:  # exactly one green button exists here; anything else is not the screen we think
        return None
    return x + int(found[0][1][0]), y + int(found[0][1][1])


def find_close_button(img: np.ndarray) -> Point | None:
    """Red X at the bottom of the results list. None on any other screen."""
    if classify(img) != "results":
        return None
    x, y, w, h = modal_box(img)
    box = img[y:y + h, x:x + w].astype(int)
    red = (box[..., 2] > 150) & (box[..., 1] < 60) & (box[..., 0] < 60)
    found = [(s, c) for s, c in _components(red, int(0.0007 * w * h))
             if s[2] > s[3] and s[1] > 0.8 * h and abs(c[0] - w / 2) < 0.1 * w]  # bottom centre of the modal
    if len(found) != 1:
        return None
    return x + int(found[0][1][0]), y + int(found[0][1][1])


def _letters(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _tiles_named(img: np.ndarray, name: str, box: tuple[int, int, int, int]) -> list[Point]:
    """Centres (whole-image coordinates) of the red skin tiles inside box = (x0, y0, x1, y1) whose label reads
    exactly `name`. A doubtful read is not a hit: a wrong skin must never be opened."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    region = img[y0:y1, x0:x1]
    red = ((region[..., 2].astype(int) > 90) & (region[..., 1] < 45) & (region[..., 0] < 45)).astype(np.uint8)
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    hits = []
    for st, c in _components(red, int(0.0025 * w * h)):
        x, y, tw, th = st[:4]
        label = region[y + int(0.7 * th):y + th, x:x + tw]  # the name sits along the bottom of the tile
        grey = cv2.resize(label.min(2), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        # Gun art leaks stray letters at some thresholds ('Starveil AWP in'), so try a few and need an exact read
        reads = (pytesseract.image_to_string(255 - cv2.threshold(grey, t, 255, cv2.THRESH_BINARY)[1], config="--psm 7")
                 for t in (200, 220, 240))
        if any(_letters(text) == _letters(name) for text in reads):
            hits.append((x0 + int(c[0]), y0 + int(c[1])))
    return hits


def find_skin_tile(img: np.ndarray, name: str) -> Point | None:
    """Centre of the one tile in the (searched) skin grid whose label is `name`; None if not exactly one."""
    if classify(img) != "collection":
        return None
    h, w = img.shape[:2]
    hits = _tiles_named(img, name, (int(0.28 * w), int(0.18 * h), int(0.84 * w), int(0.82 * h)))
    return hits[0] if len(hits) == 1 else None


def options_is_for(img: np.ndarray, name: str) -> bool:
    """True if the Search Options box shows skin `name` (the picture and label above its title)."""
    if classify(img) != "options":
        return False
    x, y, w, h = modal_box(img)
    return len(_tiles_named(img, name, (x, y, x + w, y + h // 2))) == 1
