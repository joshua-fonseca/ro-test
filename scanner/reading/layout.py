"""Click points as fractions of a 16:9 Roblox window, measured on 1900x1069 frames: no screenshot search needed.

A fixed point is only trusted after the screenshot finder has agreed with it once (per window size and button):
if the game's layout does not scale the way the fractions assume, the finder's point is used instead. Exceptions,
read through fixed() with no finder: the rarity buttons and the first tile (its finder, by red shape, misses pale
rainbow tiles; the Search Options name check catches a wrong tile). Pure maths,
no Windows calls.
"""
from typing import Callable

import numpy as np

Point = tuple[int, int]
# name: (x / width, y / height)
FIXED = {
    "category:Sniper": (0.0926, 0.1880), "category:Knife": (0.0942, 0.2703),
    "category:Glove": (0.0932, 0.3536), "category:Charm": (0.0942, 0.4369),
    "rarity:Secret": (0.2034, 0.3209), "rarity:Limited": (0.2034, 0.3807),  # the buttons above the skin list (All is lit by default)
    "search_box": (0.3247, 0.8887),
    "first_tile": (0.3232, 0.2572),  # the searched skin: first slot of the filtered grid
    "check": (0.5453, 0.6791),  # green check in Search Options
    "options_cancel": (0.4537, 0.6829),  # red X in Search Options
    "close_results": (0.5000, 0.8195),  # red X under the results list
}
TOLERANCE = 0.02  # a finder point further than this fraction of the width from the fixed one means the layout is off
_agreed: dict[tuple[int, int, str], bool] = {}


def is_16_9(img: np.ndarray) -> bool:
    h, w = img.shape[:2]
    return abs(w / h - 16 / 9) < 0.02


def point(img: np.ndarray, name: str, finder: Callable[[], Point | None]) -> Point | None:
    """Where to click `name` on this screenshot: the fixed point once the finder has agreed with it, else the finder's
    own point (None if the finder finds nothing: nothing is clicked)."""
    h, w = img.shape[:2]
    if not is_16_9(img) or name not in FIXED:
        return finder()
    fixed = (int(FIXED[name][0] * w), int(FIXED[name][1] * h))
    key = (w, h, name)
    if _agreed.get(key):
        return fixed
    found = finder()
    if found is None:
        return None
    _agreed[key] = abs(found[0] - fixed[0]) <= TOLERANCE * w and abs(found[1] - fixed[1]) <= TOLERANCE * w
    return fixed if _agreed[key] else found


def from_sibling(img: np.ndarray, name: str, find: Callable[[str], Point | None]) -> Point | None:
    """The finder for a category button: its own point, else (when the mouse hovers a neighbour, which grows and
    merges with it) the fixed point, if another category button is found where the fixed points say it should be."""
    own = find(name)
    if own is not None or not is_16_9(img):
        return own
    h, w = img.shape[:2]
    for other in (n for n in FIXED if n.startswith("category:") and n != name):
        found = find(other)
        if found and abs(found[0] - FIXED[other][0] * w) <= TOLERANCE * w and abs(found[1] - FIXED[other][1] * h) <= TOLERANCE * w:
            return int(FIXED[name][0] * w), int(FIXED[name][1] * h)
    return None


def fixed(img: np.ndarray, name: str) -> Point | None:
    """The fixed point for `name` on a 16:9 screenshot, with no finder to check it against (None on any other shape)."""
    if not is_16_9(img) or name not in FIXED:
        return None
    h, w = img.shape[:2]
    return int(FIXED[name][0] * w), int(FIXED[name][1] * h)
