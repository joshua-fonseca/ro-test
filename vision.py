"""Read the Search Results modal from a screenshot (BGR numpy array). No Windows calls.

Every field is located relative to a detected card, so the window size is not fixed.
A wrong serial is worse than none: serials need both brackets and all OCR variants to agree.
"""
import re
from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract

from models import Listing
from parsing import parse_price, parse_serial, price_is_approximate

Box = tuple[int, int, int, int]  # left, top, right, bottom

CARD_ASPECT = 4.62  # card width / height, measured on three window sizes
# Below this card width (about a 1500-wide window) OCR agreed on wrong serials, so serials are left unreadable.
MIN_SERIAL_CARD_WIDTH = 600  # shortcut: set from one fixture near the limit (1538 wide), retune once live captures at 1536-1700 exist
LOADING = "[Loading...]"
# Field boxes as fractions of the card: x0, y0, x1, y1. Serial includes both brackets.
SELLER_BOX = (0.20, 0.08, 0.71, 0.38)
PRICE_BOX = (0.72, 0.08, 0.895, 0.40)
SERIAL_BOX = (0.04, 0.60, 0.22, 0.80)  # search area; the text itself is found by colour

_BG = np.array([48, 42, 39])  # modal background, BGR
# shortcut: cards are found only on this exact colour (+-2), so a colour-shifted capture finds none and looks like
# "no results"; main.py must treat [] as an unknown screen, and widen this if real captures miss.
_SERIAL_STRICT = re.compile(r"\[#(ST\.)?\d+\]")


@dataclass(frozen=True)
class Card:
    box: Box  # for cropper.save_crop
    complete: bool  # fully inside the list area; clipped cards are never read
    loading: bool = False  # seller still shows [Loading...]: wait and retry
    listing: Listing | None = None


def _runs(v: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.r_[0, v.astype(int), 0])
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def find_cards(img: np.ndarray) -> list[Box]:
    """Card boxes (including clipped ones) top to bottom, or [] if no results list is visible.

    Cards are the only wide non-background runs that have modal background on both sides.
    """
    h, w = img.shape[:2]
    bg = np.abs(img.astype(int) - _BG).max(2) <= 2
    nonbg = cv2.morphologyEx((~bg).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((1, max(3, w // 300)), np.uint8)) > 0  # dark thumbnail pixels look like bg
    rows: list[tuple[int, int] | None] = []
    for y in range(h):
        found = None
        for a, b in _runs(nonbg[y]):
            if a > 0 and b < w and 0.2 * w <= b - a <= 0.7 * w and (found is None or b - a > found[1] - found[0]):
                found = (a, b)
        rows.append(found)
    xs = [r for r in rows if r]
    if not xs:
        return []
    x0, x1 = (int(np.median([r[i] for r in xs])) for i in (0, 1))
    ok = np.array([r is not None and abs(r[0] - x0) <= 3 and abs(r[1] - x1) <= 3 for r in rows])
    min_h = 0.15 * (x1 - x0) / CARD_ASPECT  # drops the thin separator line under the title
    return [(x0, a, x1, b) for a, b in _runs(ok) if b - a >= min_h]


def _is_complete(box: Box) -> bool:
    l, t, r, b = box
    return (b - t) >= 0.97 * (r - l) / CARD_ASPECT


def _sub(img: np.ndarray, box: Box, frac: tuple[float, float, float, float]) -> np.ndarray:
    l, t, r, b = box
    w, h = r - l, b - t
    return img[t + int(frac[1] * h):t + int(frac[3] * h), l + int(frac[0] * w):l + int(frac[2] * w)]


def _text_colour(img: np.ndarray) -> np.ndarray:
    """Bright for orange/magenta serial text; dark for white, pink and red art around it."""
    c = img.astype(int)
    r, g, b = c[..., 2], c[..., 1], c[..., 0]
    return np.clip(np.minimum(r, np.maximum(g, b)) - np.minimum(g, b), 0, 255).astype(np.uint8)


def _variants(crop: np.ndarray, channel=lambda img: img.max(2), height: int = 90) -> list[np.ndarray]:
    """Upscaled to `height` px tall: Otsu, inverted Otsu, and the plain channel."""
    scale = height / max(1, crop.shape[0])
    big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    g = channel(big)
    g = cv2.copyMakeBorder(g, 10, 10, 10, 10, cv2.BORDER_REPLICATE)
    _, otsu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return [otsu, 255 - otsu, g]


def _ocr(crop: np.ndarray, whitelist: str | None, **kw) -> list[str]:
    cfg = "--psm 7" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
    return [re.sub(r"\s+", "", pytesseract.image_to_string(v, config=cfg)) if whitelist
            else pytesseract.image_to_string(v, config=cfg).strip() for v in _variants(crop, **kw)]


def _serial_text(area: np.ndarray) -> np.ndarray | None:
    """Crop to the orange/magenta serial text: a fixed box either cuts a bracket or catches gun art."""
    mask = _text_colour(area) >= 120  # orange text ~170, magenta ~255; pink gun art ~80, red/white ~0
    rows = mask.sum(1)
    if rows.max() == 0:
        return None
    # Only the block of touching rows around the busiest one, so stray coloured rows can't stretch the crop.
    y0, y1 = next(r for r in _runs(rows >= 0.3 * rows.max()) if r[0] <= rows.argmax() < r[1])
    pad = max(2, (y1 - y0) // 4)
    # The thumbnail frame is a coloured vertical bar: columns lit far above or below the text are not text.
    outside = np.r_[mask[:max(0, y0 - pad)], mask[y1 + pad:]]
    bar = outside.mean(0) >= 0.3 if len(outside) else np.zeros(mask.shape[1], bool)
    gap = max(2, (y1 - y0) // 2)
    text = (mask[y0:y1].any(0) & ~bar).astype(np.uint8)[None]
    cols = cv2.morphologyEx(text, cv2.MORPH_CLOSE, np.ones((1, gap), np.uint8))[0]
    x0, x1 = max(_runs(cols > 0), key=lambda r: r[1] - r[0])
    left = max([x0 - pad, 0] + [i + 1 for i in np.where(bar[:x0])[0]])
    right = min([x1 + pad] + [i for i in np.where(bar[x1:])[0] + x1])  # stop before the frame
    return area[max(0, y0 - pad):y1 + pad, left:right]


def read_stattrak(area: np.ndarray) -> bool | None:
    """StatTrak serials are orange, plain ones magenta; a colour check, so it works when the digits don't read."""
    crop = _serial_text(area)
    if crop is None:
        return None
    text = _text_colour(crop) >= 120
    c = crop.astype(int)
    orange = (c[..., 1][text] > c[..., 0][text]).mean()  # orange has more green than blue, magenta the reverse
    return True if orange >= 0.8 else False if orange <= 0.2 else None


def read_serial(area: np.ndarray) -> tuple[tuple[int, bool] | None, int | None]:
    """((serial, stattrak), digits). The serial only if every read, at three sizes, gives the same strict
    `[#N]` / `[#ST.N]`; else the digit count (display only) if every read has that form and the same length."""
    crop = _serial_text(area)
    if crop is None:
        return None, None
    # Reads at one size agree even when wrong ('1]' merging into ']'); other sizes split glyphs differently.
    texts = [t for h in (60, 90, 120) for t in _ocr(crop, "#ST.0123456789[]", channel=_text_colour, height=h)]
    # shortcut: tested on 37 serials from 3 skin families (28 read, 0 wrong); add live captures of other skins
    # before trusting serial-limited targets.
    if not all(_SERIAL_STRICT.fullmatch(t) for t in texts):
        return None, None
    lengths = {len(str(parse_serial(t)[0])) for t in texts}
    if len(set(texts)) == 1:
        return parse_serial(texts[0]), lengths.pop()
    return None, lengths.pop() if len(lengths) == 1 else None


def read_price(card_img: np.ndarray) -> tuple[int, bool] | None:
    """(price, approximate) only if every variant reads the same text; a cut digit still parses."""
    texts = _ocr(card_img, "0123456789,.kKmM")
    # shortcut: one empty read rejects an otherwise agreed price (seen on a 7,000 card); ignore empty reads if
    # prices go missing in real scans, but keep rejecting disagreeing non-empty reads.
    if len(set(texts)) != 1 or parse_price(texts[0]) is None:
        return None
    return parse_price(texts[0]), price_is_approximate(texts[0])


def read_seller(card_img: np.ndarray) -> str | None:
    """Display name with the fixed "'s stall" suffix removed; None if no two variants agree."""
    texts = [t for t in _ocr(card_img, None) if t]
    if not texts:
        return None
    text, n = Counter(texts).most_common(1)[0]
    if n < 2:
        return None
    if "loading" in text.casefold():
        return LOADING
    return re.sub(r"\s*['’]s\s*stall\W*$", "", text).strip() or None


def read_card(img: np.ndarray, box: Box) -> Card:
    """Read one card. Clipped cards and unreadable prices/sellers give listing=None."""
    if not _is_complete(box):
        return Card(box, False)
    seller = read_seller(_sub(img, box, SELLER_BOX))
    if seller == LOADING:
        return Card(box, True, loading=True)
    price = read_price(_sub(img, box, PRICE_BOX))
    if seller is None or price is None:
        return Card(box, True)
    area = _sub(img, box, SERIAL_BOX)
    stattrak = read_stattrak(area)
    big_enough = box[2] - box[0] >= MIN_SERIAL_CARD_WIDTH
    serial, digits = read_serial(area) if big_enough else (None, None)
    if serial and serial[1] != stattrak:  # text says ST but colour says plain, or the reverse: trust neither
        serial = stattrak = digits = None
    return Card(box, True, listing=Listing(
        price=price[0], serial=serial[0] if serial else None, stattrak=stattrak, seller=seller,
        price_approx=price[1], serial_digits=None if serial else digits))


def read_cards(img: np.ndarray) -> list[Card]:
    return [read_card(img, b) for b in find_cards(img)]


def read_record_count(img: np.ndarray) -> int | None:
    """'N records found' from the modal title, which sits above the first card."""
    cards = find_cards(img)
    if not cards:
        return None
    l, t, r, b = cards[0]
    h = (r - l) / CARD_ASPECT
    band = img[max(0, int(t - 0.7 * h)):max(1, int(t - 0.03 * h)), l:r]
    if band.size == 0:
        return None
    for v in _variants(band)[:2]:
        m = re.search(r"(\d+)\s*records?\s*found", pytesseract.image_to_string(v, config="--psm 6"), re.I)
        if m:
            return int(m.group(1))
    return None
