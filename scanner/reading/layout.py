"""Click points as fractions of a 16:9 Roblox window, measured on 1900x1069 frames: no screenshot search needed.

A fixed point is only trusted after the screenshot finder has agreed with it once (per window size and button):
if the game's layout does not scale the way the fractions assume, the finder's point is used instead. Pure maths,
no Windows calls.
"""
from typing import Callable

import numpy as np

Point = tuple[int, int]
# name: (x / width, y / height)
FIXED = {
    "category:Sniper": (0.0926, 0.1880), "category:Knife": (0.0942, 0.2703),
    "category:Glove": (0.0932, 0.3536), "category:Charm": (0.0942, 0.4369),
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
