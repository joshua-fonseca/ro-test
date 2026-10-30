"""Read the Search Results modal from a screenshot (BGR numpy array). No Windows calls.

Every field is located relative to a detected card, so the window size is not fixed.
A wrong serial is worse than none: serials need both brackets and all OCR variants to agree.
"""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract

from scanner.logic.models import Listing
from scanner.logic.parsing import parse_price, parse_serial, price_is_approximate

# The Windows installer does not put tesseract on PATH; WSL/Linux finds it on PATH.
_WIN_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.name == "nt" and os.path.exists(_WIN_TESSERACT):
    pytesseract.pytesseract.tesseract_cmd = _WIN_TESSERACT

Box = tuple[int, int, int, int]  # left, top, right, bottom

CARD_ASPECT = 4.62  # card width / height, measured on three window sizes
# Below this card width (about a 1500-wide window) OCR agreed on wrong serials, so serials are left unreadable.
MIN_SERIAL_CARD_WIDTH = 600  # shortcut: set from one fixture near the limit (1538 wide), retune once live captures at 1536-1700 exist
# Field boxes as fractions of the card: x0, y0, x1, y1. Serial includes both brackets.
PRICE_BOX = (0.72, 0.08, 0.895, 0.40)
SERIAL_BOX = (0.04, 0.60, 0.22, 0.80)  # search area; the text itself is found by colour

_BG = np.array([48, 42, 39])  # modal background, BGR
# shortcut: cards are found only on this exact colour (+-2), so a colour-shifted capture finds none and looks like
# "no results"; main.py must treat [] as an unknown screen, and widen this if real captures miss.
_SERIAL_STRICT = re.compile(r"\[#(ST\.)?\d+\]")


@dataclass(frozen=True)
class Card:
    box: Box  # for cropper.save_crop
    complete: bool  # readable: whole, or cut off only a little by the list edge (see is_readable)
    listing: Listing | None = None
    repeat: bool = False  # already read in an earlier frame of this scroll (listing is that earlier read)
    wait: bool = False  # cut off and its serial did not read: a later frame shows it whole (not an unreadable card)


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
    runs: list[list[int]] = []
    max_h = 1.05 * (x1 - x0) / CARD_ASPECT * 1.012  # joined pieces never make something taller than one card
    join = 0.12 * (x1 - x0) / CARD_ASPECT  # cards are ~0.14 card heights apart; art overhang gaps measured up to 0.10
    for a, b in _runs(ok):  # gun art sticking out past a card's edge breaks a few rows: join runs close together
        if runs and a - runs[-1][1] <= join and b - runs[-1][0] <= max_h:
            runs[-1][1] = b
        else:
            runs.append([a, b])
    return [(x0, a, x1, b) for a, b in runs if b - a >= min_h]


# How much of a card the top / bottom edge of the list may cut off and its price / serial still read the same:
# tested by cutting 16 cards of a saved scroll (price fine to 15% off the top, serial to 25% off the bottom).
# shortcut: tested on one skin's cards at 1920x1166; retest on other skins and window sizes before widening.
CLIP_TOP, CLIP_BOTTOM = 0.05, 0.20


def full_card(box: Box, list_mid: float) -> Box:
    """The whole card's box when the edge of the list cuts the card off: the cut side is the one nearer the list's
    edge (a card in the top half of the list is cut at the top), and the card is as tall as a complete one."""
    l, t, r, b = box
    h = round((r - l) / CARD_ASPECT * 1.012)  # complete cards measure 169 px where width / aspect gives 167
    if b - t >= 0.97 * (r - l) / CARD_ASPECT:
        return box
    return (l, b - h, r, b) if (t + b) / 2 < list_mid else (l, t, r, t + h)


def is_readable(box: Box, full: Box) -> bool:
    """True if what the list edge cuts off leaves the price and serial in view."""
    h = full[3] - full[1]
    return box[1] - full[1] <= CLIP_TOP * h and full[3] - box[3] <= CLIP_BOTTOM * h


def is_complete(box: Box) -> bool:
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


_pool = ThreadPoolExecutor(max_workers=min(9, os.cpu_count() or 1))  # each OCR call runs tesseract as its own process


def _ocr_all(images: list[np.ndarray], whitelist: str | None) -> list[str]:
    """OCR every image at once (the calls are separate tesseract processes), results in the order given."""
    cfg = "--psm 7" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
    texts = _pool.map(lambda v: pytesseract.image_to_string(v, config=cfg), images)
    return [re.sub(r"\s+", "", t) if whitelist else t.strip() for t in texts]


def _ocr(crop: np.ndarray, whitelist: str | None, **kw) -> list[str]:
    return _ocr_all(_variants(crop, **kw), whitelist)


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


def _fix_one(text: str) -> str:
    """A last '1' next to the closing bracket is read as 'T' ('[#ST.10T]') or merges into it ('[#ST.10]]'). Both are
    impossible serials (a serial has no letter after a digit and one bracket), so only a lost '1' explains them."""
    return re.sub(r"(?<=\d)(?:T\]|\]\])", "1]", text)


def read_serial(area: np.ndarray) -> tuple[tuple[int, bool] | None, int | None]:
    """((serial, stattrak), digits). The serial only if at least 8 of the 9 reads, at three sizes, give the same strict
    `[#N]` / `[#ST.N]`; else the digit count (display only) if every read has that form and the same length."""
    crop = _serial_text(area)
    if crop is None:
        return None, None
    # Reads at one size agree even when wrong ('1]' merging into ']'); other sizes split glyphs differently.
    variants = [v for h in (60, 90, 120) for v in _variants(crop, channel=_text_colour, height=h)]
    texts = [_fix_one(t) for t in _ocr_all(variants, "#ST.0123456789[]")]
    # shortcut: tested on 107 saved cards (none changed by the 8-of-9 rule or _fix_one), but the 9 reads are 3 sizes x 3
    # variants of one crop, so they are not independent; a wrong strict text could reach 8. Re-check on more skins.
    top = max(set(texts), key=texts.count)  # all but one read on one strict text: the odd read out may be anything
    if texts.count(top) >= len(texts) - 1 and _SERIAL_STRICT.fullmatch(top):
        serial = parse_serial(top)
        return serial, len(str(serial[0]))
    if not all(_SERIAL_STRICT.fullmatch(t) for t in texts):
        return None, None
    lengths = {len(str(parse_serial(t)[0])) for t in texts}
    return None, lengths.pop() if len(lengths) == 1 else None


def read_price(card_img: np.ndarray) -> tuple[int, bool] | None:
    """(price, approximate) only if at least three reads agree and none disagree; a cut digit still parses."""
    texts = _ocr(card_img, "0123456789,.kKmM")
    if "" in texts or len(set(texts)) > 1:  # a live 7,000 card read '7,000', '7,000', ''; two variants can agree on a wrong price, so read
        texts += _ocr(card_img, "0123456789,.kKmM", height=60)  # again at another size, as read_serial does
    texts = [t for t in texts if t]
    best = max(texts, key=lambda t: (texts.count(t) >= 3, len(t)), default=None)  # the longest text read 3+ times
    # Reads drop a digit ('1k' for '11k') far more often than they invent one, so shorter reads that are the best
    # text minus some characters do not disagree with it; any other read does
    if best is None or texts.count(best) < 3 or not all(_is_subsequence(t, best) for t in texts) or parse_price(best) is None:
        return None
    return parse_price(best), price_is_approximate(best)


def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(c in it for c in short)


def read_card(img: np.ndarray, box: Box, seen: list | None = None, upto: int | None = None,
              max_price: int | None = None) -> Card:
    """Read one card. Cards cut off too far and unreadable prices give listing=None (complete=False for the first).
    A card cut off a little by the top or bottom of the list is still read. The seller is not read: it shows
    [Loading...] for a moment and is not needed.

    seen: cards read in earlier frames of one scroll (filled here). A card already there skips the serial OCR
    and comes back with repeat=True. upto: only the first `upto` entries count, so cards read from this same
    frame are never taken for repeats (two cards in one frame are always two cards).
    max_price: a card whose price is above it can never match, so its serial is not read (listing.serial=None).
    """
    full = full_card(box, 0.48 * img.shape[0])  # 0.48: the middle of the list on a 16:9 window
    if not is_readable(box, full):
        return Card(box, False)
    price = read_price(_sub(img, full, PRICE_BOX))
    if price is None:
        return Card(box, True)
    area = _sub(img, full, SERIAL_BOX)
    look = cv2.resize(cv2.cvtColor(area, cv2.COLOR_BGR2GRAY), (64, 20), interpolation=cv2.INTER_AREA).astype(int)
    for p, lk, old in (seen or [])[:upto]:
        # Serial area difference on the 29 scroll frames: same card <= 0.8, other cards >= 1.2 (with the seller too).
        # shortcut: animated thumbnail borders (Noir Nya Reaper) give the same card up to 2.7, so most repeats are
        # read again (slower; a differing serial read adds a row); match cards by scroll offset if scans get slow.
        if p == price[0] and np.abs(lk - look).mean() < 1.0:
            return Card(box, True, listing=old, repeat=True)
    if max_price is not None and price[0] > max_price:
        listing = Listing(price=price[0], serial=None, stattrak=None, price_approx=price[1])
    else:
        stattrak = read_stattrak(area)
        big_enough = full[2] - full[0] >= MIN_SERIAL_CARD_WIDTH
        serial, digits = read_serial(area) if big_enough else (None, None)
        if serial and serial[1] != stattrak:  # text says ST but colour says plain, or the reverse: trust neither
            serial = stattrak = digits = None
        if serial is None and full != box:  # cut off and no serial: a later frame shows it whole, so don't keep a ghost
            return Card(box, True, wait=True)
        listing = Listing(price=price[0], serial=serial[0] if serial else None, stattrak=stattrak,
                          price_approx=price[1], serial_digits=None if serial else digits)
    if seen is not None:
        seen.append((price[0], look, listing))
    return Card(box, True, listing=listing)


def has_banner(img: np.ndarray) -> bool:
    """True while an in-game announcement ("X bought Y") band is drawn across the window.

    It is part of the game, so focus checks can't see it; it covers cards and the title.
    """
    c = img.astype(int)
    r, g, b = c[..., 2], c[..., 1], c[..., 0]
    olive = (r >= 70) & (np.abs(r - g) <= 25) & (r - b >= 35)  # yellow tint: red ~ green, little blue
    banner_rows = olive.mean(1) > 0.6
    return banner_rows.sum() >= 0.02 * img.shape[0]


def read_cards(img: np.ndarray, seen: list | None = None) -> list[Card]:
    return [read_card(img, b, seen) for b in find_cards(img)]


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
