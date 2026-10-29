"""Which Roblox screen is showing, and where its buttons are. Pure vision on a BGR screenshot: no Windows calls.

Every finder returns a click point only on the screen it belongs to, and None anywhere else. That is the safety
rule for navigation: the green check in Search Options looks like the green Teleport buttons in the results
list, so a point is never returned unless classify() has first confirmed the right screen.
"""
import itertools

import cv2
import numpy as np
import pytesseract

from scanner.reading import layout, vision  # vision sets the Tesseract path on Windows

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
    # The cursor is a thin line a little taller than the bar (35 px on a 26 px bar) and only ~200 bright at some
    # sizes; the grey "Search ..." letters are shorter (20 px), so a column taller than the bar is the cursor.
    return bool(((region.min(2) > 150).sum(0) >= 1.1 * h).any())


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
    """'options' (Search Options box), 'results' (listing list), 'collection' (skin grid) or 'unknown'.

    Colour and size only, no OCR (the old text check took 0.3 s a call): the collection screen is the only one with
    the search bar showing; the Search Options box is a small modal (about 40% of the height) and the results
    list a big one (65-70%). The finders below still insist on their own screen's buttons before giving a point.
    """
    h, w = img.shape[:2]
    bar = _search_bar(img)
    if bar is not None and bar[1] > 0.8 * h:  # the real bar sits low; a grey strip inside the results list does not
        return "collection"
    box = modal_box(img)
    if box is None or box[2] < 0.3 * w:  # no modal, or only a speck of the background colour (the game world)
        return "unknown"
    return "options" if box[3] < 0.5 * img.shape[0] else "results"


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


def find_options_cancel(img: np.ndarray) -> Point | None:
    """Red X at the bottom of Search Options: closes it without opening the results. None on any other screen."""
    if classify(img) != "options":
        return None
    x, y, w, h = modal_box(img)
    box = img[y:y + h, x:x + w].astype(int)
    red = (box[..., 2] > 150) & (box[..., 1] < 60) & (box[..., 0] < 60)
    found = [(s, c) for s, c in _components(red, int(0.0005 * w * h)) if s[2] > s[3] and s[1] > 0.7 * h]
    if len(found) != 1:
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


def _trim(text: str) -> str:
    """Drop stray one-symbol words at the ends of a read ('1 Nya Reaper' -> 'Nya Reaper'): border bits read as symbols."""
    words = text.split()
    while words and len(words[0]) == 1 and not words[0].isalpha():
        words.pop(0)
    while words and len(words[-1]) == 1 and not words[-1].isalpha():
        words.pop()
    return " ".join(words)


def _tiles_named(img: np.ndarray, name: str, box: tuple[int, int, int, int]) -> list[Point]:
    """Centres (whole-image coordinates) of the red skin tiles inside box = (x0, y0, x1, y1) whose label reads
    exactly `name`. A doubtful read is not a hit: a wrong skin must never be opened."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    region = img[y0:y1, x0:x1]
    red = ((region[..., 2].astype(int) > 40) & (region[..., 1] < 45) & (region[..., 0] < 45)).astype(np.uint8)  # unowned tiles are dark red (~60)
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    hits = []
    for st, c in _components(red, int(0.0025 * w * h)):
        x, y, tw, th = st[:4]
        tall = max(th, tw)  # tiles are square; the red part can stop short of the label (dark art)
        label = region[y + int(0.7 * tall):y + tall, x:x + tw]  # the name sits along the bottom of the tile
        if y + tall > region.shape[0]:  # tile cut off by the edge of the search area (grid still moving): not readable yet
            continue
        owned = np.median(region[y:y + tall, x:x + tw, 2]) > 90  # owned tiles are bright red, unowned ones dark (~60)
        if owned:
            # Gun art leaks stray letters at some thresholds ('Starveil AWP in'), so try a few and need an exact read
            grey = cv2.resize(label.min(2), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            reads = (pytesseract.image_to_string(255 - cv2.threshold(grey, t, 255, cv2.THRESH_BINARY)[1], config="--psm 7")
                     for t in (200, 220, 240))
            # A long name under gun art ('Wild Fiend Crossbow') only reads from the tight band at a lower threshold
            def tight_reads(x=x, y=y, tw=tw, tall=tall):  # lazy: only built if the first reads did not match
                tight = cv2.resize(region[y + int(0.8 * tall):y + int(0.96 * tall), x:x + tw].min(2), None, fx=3, fy=3,
                                   interpolation=cv2.INTER_CUBIC)
                for t in (160, 190, 220):
                    yield pytesseract.image_to_string(255 - cv2.threshold(tight, t, 255, cv2.THRESH_BINARY)[1],
                                                      config="--psm 7")
                # The rainbow border adds stray letters beside a short name ('Nya Reaper' over pink art): trim the sides
                i = int(0.03 * tw)
                low = cv2.resize(region[y + int(0.84 * tall):y + tall, x + i:x + tw - i].min(2), None, fx=3, fy=3,
                                 interpolation=cv2.INTER_CUBIC)
                for t in (190, 220, 240):
                    yield pytesseract.image_to_string(255 - cv2.threshold(low, t, 255, cv2.THRESH_BINARY)[1],
                                                      config="--psm 7")
                # Red gun art behind a small label ('Starember GM6 Lynx'): the red part is shorter than the tile, so the label sits higher
                mid = cv2.resize(region[y + int(0.73 * tall):y + int(0.845 * tall), x + 4:x + tw - 4].min(2), None, fx=3, fy=3,
                                 interpolation=cv2.INTER_CUBIC)
                for t in (200, 230):
                    yield pytesseract.image_to_string(255 - cv2.threshold(mid, t, 255, cv2.THRESH_BINARY)[1],
                                                      config="--psm 7")
            reads = itertools.chain(reads, tight_reads())
        else:
            # Unowned tiles are dimmed (grey text ~90 on dark red) with a coloured border: keep only grey pixels
            reads = (pytesseract.image_to_string(255 - cv2.resize(
                ((d.max(2) - d.min(2) < 25) & (d.min(2) > 40)).astype(np.uint8) * 255, None, fx=3, fy=3,
                interpolation=cv2.INTER_CUBIC), config="--psm 7")
                for d in (region[y + int(0.78 * tall):y + tall, x + inset:x + tw - inset].astype(int) for inset in (12, 16)))
        pt = (x0 + int(c[0]), y0 + int(c[1]))
        if any(_letters(_trim(text)) == _letters(name) for text in reads) and not any(  # art can split one tile in two
                abs(pt[0] - hx) < tw and abs(pt[1] - hy) < tw for hx, hy in hits):
            hits.append(pt)
    return hits


def find_first_tile(img: np.ndarray) -> Point | None:
    """Centre of the first (top-left) skin tile in the grid, found by its red shape, with no name reading: a long
    name in small letters under gun art does not read. The caller checks which skin opened (Search Options)."""
    if classify(img) != "collection":
        return None
    h, w = img.shape[:2]
    x0, y0, x1, y1 = int(0.28 * w), int(0.18 * h), int(0.84 * w), int(0.82 * h)
    region = img[y0:y1, x0:x1]
    red = ((region[..., 2].astype(int) > 40) & (region[..., 1] < 45) & (region[..., 0] < 45)).astype(np.uint8)
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    tiles = _components(red, int(0.0025 * w * h))
    if not tiles:
        return None
    st, c = min(tiles, key=lambda t: (t[0][1] // 40, t[0][0]))  # top row first, then leftmost
    return x0 + int(c[0]), y0 + int(c[1])


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


def find_category_button(img: np.ndarray, category: str) -> Point | None:
    """Centre of the blue category button (Sniper, Knife, Glove, Charm) down the left side of the collection
    screen whose label reads exactly `category`; None on any other screen or if not exactly one."""
    if classify(img) != "collection":
        return None
    h, w = img.shape[:2]
    x0, y0 = 0, int(0.1 * h)
    strip = img[y0:int(0.55 * h), :int(0.16 * w)].astype(int)
    blue = (strip[..., 2] < 12) & (strip[..., 0] > 60) & (strip[..., 0] > 1.3 * strip[..., 1])  # flat blue or its darker top
    blue = cv2.morphologyEx(blue.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    hits = []
    for st, c in _components(blue, int(0.002 * w * h)):
        x, y, bw, bh = st[:4]
        label = strip[y:y + bh, x + bw // 3:x + bw].astype(np.uint8)  # the icon sits on the left third
        grey = cv2.resize(label.min(2), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        text = pytesseract.image_to_string(255 - cv2.threshold(grey, 220, 255, cv2.THRESH_BINARY)[1], config="--psm 7")
        if _letters(text) == _letters(category):
            hits.append((x0 + int(c[0]), y0 + int(c[1])))
    return hits[0] if len(hits) == 1 else None


def rarity_is_on(img: np.ndarray, rarity: str) -> bool:
    """True if the Secret / Limited filter button is lit (bright magenta; off it is dark purple). It looks at the button
    face beside and below the label, so it still works when the mouse is over the button and it grows."""
    p = layout.fixed(img, f"rarity:{rarity}")
    if p is None:
        return False
    h, w = img.shape[:2]
    for dx, dy in ((-0.034 * w, 0), (0.034 * w, 0), (0, 0.020 * h)):
        x, y = min(max(p[0] + int(dx), 2), w - 3), min(max(p[1] + int(dy), 2), h - 3)
        b, g, r = img[y - 2:y + 3, x - 2:x + 3].reshape(-1, 3).mean(0)
        if r > 200 and b > 200 and g < 90:
            return True
    return False
