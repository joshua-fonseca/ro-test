"""Scan one skin's results list: scroll it top to bottom, match one target, save crops and CSVs.

Run with Windows Python. Without --navigate you open the skin's results in Roblox yourself, and the scan only moves
the mouse and turns the wheel over the list (no clicks):
    python scan_once.py "Starveil AWP"
With --navigate it starts from the collection screen (old search text is cleared) and also clicks the search box, the skin's
tile, the green check in Search Options and the red X that closes the results, and types the skin name. It never
clicks Teleport, buy, trade or payment buttons.
    python scan_once.py "Starveil AWP" --navigate
Lists are sorted cheapest first, so the scan stops at the first (cheapest) match, or once prices are past
max_price (see scan_list).
"""
import argparse
import itertools
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from scanner.reading import screens, vision
from scanner.logic.config import load_config
from scanner.logic.cropper import save_crop
from scanner.logic.matcher import matches
from scanner.logic.models import Target, load_targets
from scanner.logic.parsing import price_high
from scanner.logic.storage import Store, setup_run_log

log = logging.getLogger(__name__)

# Cards are 193 px apart in a 537 px list, and a card is read while at most 5% of its top or 20% of its bottom is cut
# off (about 127 px of it must show), so a step can be up to 537 - 127 = 410 px without skipping a card. A notch moves
# 125 px on some sessions (3 notches = 375 px: fine) and 150 px on others (3 = 450 px: skips a card, 2 = 300 px is fine),
# so STEP is only the most it will try: scan_list measures one notch at the start of a run and picks the step from it.
STEP = 3  # most notches per step
UP = 10  # notches per step while going back to the top (nothing is read on the way)
CLEARLY_OVER = 1.1  # a first card this far over max_price ends the scan alone: not a borderline price


_card_pool = ThreadPoolExecutor(max_workers=3)  # a frame shows 3-4 cards; vision has its own pool for the OCR calls


def _over(target: Target, listing) -> bool:
    # '11.7k' is at least 11,700 (the game cuts digits off, never rounds up), so the shown price is the lowest
    return target.max_price is not None and listing.price > target.max_price


def scan_visible(img: np.ndarray, target: Target, store: Store, out: Path, now: datetime,
                 seen: list | None = None, first_only: bool = False) -> dict:
    """Read every card in one capture, record it, and save a crop for each new match. No Windows calls.

    seen: vision.read_card's cache across frames; repeat cards are not recorded again.
    first_only: stop at the first match (cards below it are read but not recorded).
    """
    pil = Image.fromarray(img[:, :, ::-1])  # BGR -> RGB, real captured pixels
    boxes = vision.find_cards(img)
    result = {"cards": len(boxes), "read": 0, "matches": 0, "unreadable": 0, "clipped": 0, "lines": [],
              "over_pair": False, "unsorted": False}
    over, lowest = 0, 0  # lowest: the least the cards above can cost
    earlier = len(seen) if seen is not None else 0
    # the cards of one frame are read together (each read is several tesseract processes); the loop below stays in order
    cards = list(_card_pool.map(lambda b: vision.read_card(img, b, seen, earlier, target.max_price), boxes))
    for card in cards:
        if not card.complete or card.wait:
            result["clipped"] += 1
        elif card.listing is None:
            result["unreadable"] += 1
        if card.listing is None:
            over = 0  # an unreadable card never counts toward the early stop
            continue
        listing = card.listing
        # Early stop needs two readable cards in a row over max_price in one frame, so surely two different cards;
        # one card clearly over (not a borderline read) is enough: the list is cheapest first
        over = (2 if listing.price > CLEARLY_OVER * target.max_price else over + 1) if _over(target, listing) else 0
        result["over_pair"] |= over >= 2
        # Cheapest first? Checked within this frame, top to bottom: no need to recognise cards across frames
        result["unsorted"] |= price_high(listing.price, listing.price_approx) < lowest
        lowest = max(lowest, listing.price)
        if card.repeat:
            continue
        result["read"] += 1
        ok = matches(target, listing)
        result["matches"] += ok
        line = store.record(now, target, listing, ok, make_crop=lambda box=card.box, l=listing: save_crop(
            pil, box, out / "screenshots" / "matches", Path.cwd(), now, target.skin_name, l.price, l.seller))
        if line:
            result["lines"].append(line)
        if ok and first_only:
            result["match_box"] = vision.full_card(card.box, 0.48 * img.shape[0])  # where --snipe clicks Teleport
            result["match_listing"] = listing
            break
    return result


def _view(img: np.ndarray):
    """Card boxes and a small grey image of the card list, to tell whether the list moved; None if no list."""
    boxes = vision.find_cards(img)
    if not boxes:
        return None
    l, t, r, b = boxes[0][0], boxes[0][1], boxes[-1][2], boxes[-1][3]
    return boxes, cv2.resize(cv2.cvtColor(img[t:b, l:r], cv2.COLOR_BGR2GRAY), (160, 80),
                             interpolation=cv2.INTER_AREA).astype(int)


def _same(a, b) -> bool:
    # Only the card list is compared: the blurred game behind the modal keeps moving
    return a is not None and b is not None and a[0] == b[0] and np.abs(a[1] - b[1]).mean() < 2


SAFE_STEP = 0.383  # of the window height: 410 px at 1069, the most a step can cover without skipping a card
_steps: dict[tuple[int, int], int] = {}  # (width, height) -> notches per step, measured once per run


def _shift(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """(px, mismatch): how far the card list moved up from frame a to frame b after ONE notch, the best match among
    0.05-0.23 of the height (a range narrower than a card, so repeating cards cannot be taken for each other), and how
    badly the frames still differ there (large if the list did not move or the frames are unrelated)."""
    h, w = a.shape[:2]
    y0, y1, x0, x1 = int(0.232 * h), int(0.734 * h), int(0.33 * w), int(0.69 * w)
    ga, gb = (cv2.cvtColor(i[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(int) for i in (a, b))
    cands = range(int(0.05 * h), int(0.23 * h))
    errs = {s: np.abs(ga[s:] - gb[:len(gb) - s]).mean() for s in cands}
    best = min(errs, key=errs.get)
    return best, errs[best]


def _top_card_hidden(img: np.ndarray) -> bool:
    """True if the first card of the list is cut off too far to read (at the top of a fresh list it is whole)."""
    boxes = vision.find_cards(img)
    return bool(boxes) and not vision.is_readable(boxes[0], vision.full_card(boxes[0], 0.48 * img.shape[0]))


def scan_list(img: np.ndarray, next_frame, target: Target, store: Store, out: Path, now: datetime,
              max_steps: int = 300, at_top: bool = False, calibrate: bool = False, snipe: bool = False) -> dict:
    """Go to the top of the list, then read it down to the end or until prices pass max_price. No Windows calls.

    at_top: the list was just opened, so it is already at the top: no scrolling up first.
    next_frame(notches) scrolls (down if > 0, 0 = just look again) and returns the next capture, or None when
    Roblox lost focus. status: complete (end reached), stopped_at_price, stopped_at_first_match, focus_lost,
    list_lost or max_steps. Only the cheapest match is wanted, so the scan stops at the first one; an unreadable
    card above it is skipped, not waited for.
    snipe: on a match the list is scrolled back to it (it moved on while the frame was read) and the result has
    total["match"] = (a fresh frame, the matched card's box in it, its listing), or no "match" if it was not found.
    """
    total = {"read": 0, "matches": 0, "unreadable": 0, "lines": [], "frames": 0,
             "records": vision.read_record_count(img), "sorted": True, "status": "max_steps"}
    view, still = _view(img), 0
    for _ in range(0 if at_top else max_steps):  # start from the top so the first card is the cheapest
        img = next_frame(-UP)
        if img is None:
            return {**total, "status": "focus_lost"}
        v = _view(img)
        if v is None:  # the list is gone (closed?): stop sending the wheel anywhere
            return {**total, "status": "list_lost"}
        still, view = (still + 1 if _same(v, view) else 0), v
        if still >= 2:
            break
    seen, retries, still, hidden = [], 0, 0, 0
    key = (img.shape[1], img.shape[0])
    step = _steps.get(key, STEP)
    measuring = calibrate and key not in _steps  # a notch is 125-150 px depending on the window: measure it first
    with ThreadPoolExecutor(max_workers=1) as reader:  # reads one frame while the list scrolls to the next
        for _ in range(max_steps):
            if view is None:
                total["status"] = "list_lost"
                break
            if not total["frames"] and hidden < 6 and _top_card_hidden(img):
                # something (an announcement banner) covers the top of the first card: it is the cheapest, and no later
                # frame shows it again, so look again for up to 3 s instead of matching a dearer card below it
                hidden += 1
                time.sleep(0.5)
                img = next_frame(0)
                if img is None:
                    return {**total, "status": "focus_lost"}
                view = _view(img)  # the list may have closed meanwhile: the check at the top of the loop stops the wheel
                continue
            t_frame = time.perf_counter()
            job = reader.submit(scan_visible, img, target, store, out, now, seen, first_only=total["sorted"])
            # a banner covers cards: look again before scrolling past them
            if vision.has_banner(img) and retries < 3:
                retries += 1
                time.sleep(1)
                notches = 0
            else:
                retries, notches = 0, (1 if measuring else step)
            before = img
            img = next_frame(notches)  # one scroll past a stop is harmless: the next frame is simply not read
            t_scrolled = time.perf_counter()
            r = job.result()
            total["frames"] += 1
            log.info("timing: frame %d: scroll and settle %.2f s, then %.2f s more for the read (read took %.2f s in all)",
                     total["frames"], t_scrolled - t_frame, time.perf_counter() - t_scrolled, time.perf_counter() - t_frame)
            for k in ("read", "matches", "unreadable", "lines"):
                total[k] += r[k]
            if r["unsorted"] and total["sorted"]:  # one lower price below a higher one and the early stops are off
                log.warning("%s: list not sorted by price; scrolling to the end", target.skin_name)
                total["sorted"] = False
            if total["sorted"] and r["over_pair"]:
                total["status"] = "stopped_at_price"
                break
            if total["sorted"] and r["matches"]:
                total["status"] = "stopped_at_first_match"
                if snipe and "match_box" in r:
                    total["match"] = _back_to_match(next_frame, before, img, notches, r["match_box"], r["match_listing"],
                                                 Path(out) / "probe")
                break
            if img is None:
                total["status"] = "focus_lost"
                break
            if measuring and notches:
                px, err = _shift(before, img)
                if err < 12 and 0.08 <= px / img.shape[0] <= 0.17:  # a believable match
                    measuring = False
                    step = _steps[key] = max(1, min(STEP, int(SAFE_STEP * img.shape[0] / px)))
                    log.info("one notch moves %d px: %d notches per step", px, step)
                else:  # not cached: the next scan measures again; this one goes on at no more than 2 notches
                    measuring = False
                    step = min(step, 2)
                    log.warning("could not measure the notch (moved %d px, mismatch %.0f): %d notches per step", px, err, step)
            v = _view(img)
            if notches:
                still = still + 1 if _same(v, view) else 0
            view = v
            if still >= 2:  # the last notches may still bounce, so two unchanged steps
                total["status"] = "complete"
                break
    return total


def _relocate(src: np.ndarray, box, dst: np.ndarray):
    """The box in `dst` of the card at `box` in `src`, found by matching its picture; None unless clearly found."""
    h = src.shape[0]
    l, t, r, b = (int(v) for v in box)
    t, b = max(0, t), min(h, b)  # a card cut off at the list edge: match the part that shows
    if b - t < 20 or src.shape != dst.shape:
        return None
    gray = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)  # noqa: E731
    # The right 32% of the card: the price and the Teleport button (a long seller name reaches further left). Not the picture (rainbow frames and
    # sparkles animate, so it never matches itself, seen live at score 0.93) and not the seller's name ("[Loading...]").
    x0 = l + int(0.68 * (r - l))
    scores = cv2.matchTemplate(gray(dst)[:, x0:r], gray(src)[t:b, x0:r], cv2.TM_CCOEFF_NORMED)[:, 0]
    near = np.abs(np.arange(len(scores)) - t) <= 0.5 * (b - t)  # the list was scrolled back to the same place: a
    scores = np.where(near, np.nan_to_num(scores, nan=-1), -1)   # neighbour card (same layout) is a full card away
    best = int(scores.argmax())
    log.info("matched card found again at score %.3f (needs 0.99)", scores[best])
    # same card 1.000 live, a card with another price 0.95; `not >=` so a NaN is refused too. shortcut: tune if a live match is missed
    if not scores[best] >= 0.99:
        return None
    dy = best - t
    return l, box[1] + dy, r, box[3] + dy


def _back_to_match(next_frame, before: np.ndarray, now: np.ndarray | None, notches: int, box, listing, probe=None):
    """--snipe: the list scrolled on while `before` was read; scroll back the same notches and find the matched card
    again by its picture. (frame, box, listing) for the Teleport click, or None: then nothing is clicked."""
    t = time.perf_counter()
    img = now if not notches else (None if now is None else next_frame(-notches))
    if img is None:
        return None
    t_back = time.perf_counter() - t
    found = _relocate(before, box, img)
    log.info("timing: scroll back %.2f s, find the card again %.2f s", t_back, time.perf_counter() - t - t_back)
    if found is None:
        log.warning("the matched card was not found again after scrolling back: no Teleport")
        if probe is not None:  # diagnostics: the frame it was read on and the one after scrolling back
            probe.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(probe / "relocate_before.png"), before)
            cv2.imwrite(str(probe / "relocate_after.png"), img)
        return None
    return img, found, listing


def _live_frames(hwnd: int, frames_dir: Path | None = None):
    """next_frame for scan_list on the real window: scroll over a seller name, wait for it to settle, capture."""
    from scanner.windows import controller
    from scanner.windows import screen
    last, point, frame_no = None, None, itertools.count()

    def next_frame(notches: int) -> np.ndarray | None:
        nonlocal last, point
        if notches:
            cards = [b for b in vision.find_cards(last) if vision.is_complete(b)] if last is not None else []
            if cards:  # none (banner): keep the last point; a list that is really gone ends as list_lost
                l, t, r, b = cards[0]
                x0, y0 = screen.client_rect(hwnd)[:2]
                # 35% across is the seller name; Teleport is in the right 20% of every card
                point = x0 + l + int(0.35 * (r - l)), y0 + t + int(0.23 * (b - t))
            if point is None or not controller.scroll(hwnd, *point, notches):
                return None
        img = screen.capture(hwnd)
        if img is None:
            return None
        if notches:  # the list glides after a scroll: wait until two looks are alike, not a fixed time
            view = _view(img)
            for _ in range(12):
                time.sleep(0.05)
                cur = screen.capture(hwnd)
                if cur is None:
                    return None
                v = _view(cur)
                img, done, view = cur, _same(v, view), v
                if done:
                    break
        for _ in range(3):  # an in-game "X bought Y" banner covers cards for a few seconds: wait it out
            if img is None or not vision.has_banner(img):
                break
            print("Announcement banner on screen, waiting...")
            time.sleep(2)
            img = screen.capture(hwnd)
        last = img
        if frames_dir and img is not None:  # diagnostics: every frame, to check how far a step moves the list
            cv2.imwrite(str(frames_dir / f"{next(frame_no):03d}.png"), img, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        return img
    return next_frame


TELEPORTED = 10  # _run_once's exit code once --snipe clicked Teleport (and ran the steps after it): the caller stops


def _teleport(hwnd: int, shown: np.ndarray, card) -> tuple[bool, str]:
    """--snipe: click Teleport on the matched card, but only if the list still looks exactly as it did when the card
    was read (nothing scrolled or covered it) and the spot is a green Teleport button. (clicked, why not)."""
    from scanner.windows import navigate, screen
    now = screen.capture(hwnd)
    if now is None:
        return False, "Roblox lost focus"
    a, b = _view(now), _view(shown)
    if a is None or b is None or not _same(a, b):
        return False, "the list moved since the match was read"
    point = screens.find_teleport(now, card)
    if point is None:
        return False, "no green Teleport button where the matched card is"
    from scanner.windows.snipe import HOVER
    if not navigate._click(hwnd, point, now, HOVER):
        return False, "click not sent (Roblox lost focus, or the window changed size)"
    return True, ""


def _snipe(hwnd: int, cfg, out: Path, target, shown: np.ndarray, card, listing) -> bool:
    """--snipe on a match: Teleport, then snipe.after_teleport. A full server ("Teleport Failed", Ok clicked) is tried
    again on the same listing, up to cfg.teleport_retries more times, while the list still shows it. True once it
    teleported (the loop stops); False to close the results and go on with the next skin."""
    from scanner.windows import snipe as flow
    probe = out / "probe"
    probe.mkdir(parents=True, exist_ok=True)
    for old in probe.glob("snipe_*.png"):  # only this snipe's step screens are kept
        old.unlink()
    for attempt in range(1 + cfg.teleport_retries):
        if attempt:
            time.sleep(1)  # after Ok: let the list settle before checking it still shows the listing
        t = time.perf_counter()
        teleported, why = _teleport(hwnd, shown, card)
        log.info("timing: checking and clicking Teleport took %.2f s", time.perf_counter() - t)
        print("Teleport clicked." if teleported else f"Teleport not clicked: {why}. Going on with the next skin.")
        if not teleported:
            return False
        try:
            print(flow.after_teleport(hwnd, cfg, target.skin_name, listing.price,
                                      price_high(listing.price, listing.price_approx),
                                      lambda name, im: cv2.imwrite(str(probe / f"{name}.png"), im)))
        except flow.NotTeleported as e:  # still on this server with the list up: same as Teleport not clicked
            print(f"{e}. Going on with the next skin.")
            return False
        except flow.TeleportFailed as e:  # Ok was clicked: the results list shows again
            print(f"Teleport failed: {e}. Clicked Ok; "
                  + ("going on with the next skin." if attempt == cfg.teleport_retries else "trying the same listing again."))
            continue
        except flow.Stopped as e:
            print(f"Snipe stopped: {e}. Nothing more was sent; take over from here.")
            if e.img is not None:  # diagnostics: the screen the flow gave up on
                cv2.imwrite(str(probe / "snipe_stopped.png"), e.img)
                print(f"The screen it stopped on: {probe / 'snipe_stopped.png'}")
        except Exception:  # Teleport went through: whatever broke, never go back to scanning on the new server
            log.exception("the snipe flow crashed after Teleport")
            print("Snipe stopped: the flow crashed after Teleport (see run.log). Nothing more was sent; take over from here.")
        return True
    return False


def _run_once(hwnd: int, cfg, out: Path, target, navigate_mode: bool, searched: bool,
              filters_on: bool = False, snipe: bool = False) -> tuple[int, bool]:
    """One scan of `target`. With navigate_mode it opens the results first (straight from the grid if `searched`:
    the skin is still searched from the last run) and closes them after. filters_on: the category and rarity buttons
    already show this target's choice, so they are not clicked again. snipe: click Teleport on the first match, run
    snipe.after_teleport (buy it, put the stall up again) and return TELEPORTED. (exit code, skin is still searched)."""
    store = Store(out)
    now = datetime.now().astimezone()
    t_start = time.perf_counter()
    store.begin_cycle(now.strftime("%Y%m%dT%H%M%S"))
    navigated = stopped = teleported = False
    if navigate_mode:
        from scanner.windows import navigate, screen
        if screen.client_rect(hwnd)[2] < cfg.min_window_width:  # before any click: the layout is only known for big windows
            print(f"Roblox is {screen.client_rect(hwnd)[2]} px wide; at least {cfg.min_window_width} is needed")
            return 2, False
        probe = out / "probe"  # diagnostics: the screens it saw, to see why a step failed
        probe.mkdir(parents=True, exist_ok=True)
        save = lambda name, im: cv2.imwrite(str(probe / f"nav_{name}.png"), im)  # noqa: E731
        opened, why = (navigate.open_results(hwnd, target.skin_name, save) if searched else (None, ""))
        if opened is None and searched:  # the quick reopen failed: back to the grid, then search again
            navigate.back_to_collection(hwnd)
        if opened is None:  # first time, or the tile is no longer where it was: search for the skin again
            ok, why = navigate.search_for(hwnd, target.skin_name, save, category=target.category, rarity=target.rarity,
                                         filters_on=filters_on)
            opened, why = navigate.open_results(hwnd, target.skin_name, save) if ok else (None, why)
        if opened is None:
            navigate.back_to_collection(hwnd)  # leave no dialog open
            print(f"Navigation stopped: {why}")
            store.log_scan(now, target, "navigation_failed", detail=why)
            return 1, False
        navigated = True
        log.info("timing: search and open the results took %.2f s", time.perf_counter() - t_start)
    t_open = time.perf_counter()
    try:
        frames_dir = Path(cfg.output_dir) / "scan_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for old in frames_dir.glob("*.png"):  # only the latest run's frames are kept
            old.unlink()
        next_frame = _live_frames(hwnd, frames_dir)
        img = next_frame(0)
        # A long list takes a moment to draw its first cards after it opens; "No listings found" can show a moment after
        # the box itself (seen live). 3 s, not a count of looks: each look saves a frame and took up to 0.4 s.
        end = time.time() + 3
        while True:
            if img is None or any(vision.is_complete(b) for b in vision.find_cards(img)):
                break
            if screens.no_listings(img):  # no seller has it: nothing to read (not a failure)
                print("No listings found; nothing to scan")
                store.log_scan(now, target, "no_listings")
                return 0, navigated
            if time.time() > end:
                break
            time.sleep(0.1)
            img = next_frame(0)
        if img is None:
            print("Roblox is not in front (or minimized); nothing captured")
            return 2, navigated
        if img.shape[1] < cfg.min_window_width:
            print(f"Roblox is {img.shape[1]} px wide; at least {cfg.min_window_width} is needed")
            return 2, navigated

        log.info("timing: first card on screen %.2f s after the results opened", time.perf_counter() - t_open)
        Image.fromarray(img[:, :, ::-1]).save(out / "last_capture.png")  # diagnostics: what the scan saw
        if not any(vision.is_complete(b) for b in vision.find_cards(img)):  # the StatTrak dialog has a card-like bar
            print("No results list on screen; nothing recorded")
            store.log_scan(now, target, "no_results_visible")
            return 1, navigated
        print("Scrolling the list: hands off the mouse; click another window to stop.")
        t_scan = time.perf_counter()
        r = scan_list(img, next_frame, target, store, out, now, at_top=navigated, calibrate=True,
                      snipe=snipe and navigated)
        if r["status"] == "complete":
            store.end_cycle()  # only a full scroll saw every listing; an early stop must not mark the rest unseen
        store.log_scan(now, target, r["status"], r["read"], r["matches"],
                       f"records_found={r['records']} frames={r['frames']} unreadable_reads={r['unreadable']}"
                       f" sorted={r['sorted']}")
        for line in r["lines"]:
            print(line)
        print(f"{r['status']}: {r['read']} listing(s) read, {r['matches']} match(es); records found: {r['records']}"
              + (f"; {r['unreadable']} unreadable card read(s)" if r["unreadable"] else "")
              + ("" if r["sorted"] else "; list was not sorted by price, scrolled to the end"))
        log.info("timing: reading the list took %.2f s (%d frames); results opened %.2f s ago",
                 time.perf_counter() - t_scan, r["frames"], time.perf_counter() - t_open)
        if r.get("match"):  # only set when scan_list ran with snipe
            teleported = _snipe(hwnd, cfg, out, target, *r["match"])
            if teleported:
                return TELEPORTED, navigated
        return (0 if r["status"] in ("complete", "stopped_at_price", "stopped_at_first_match") else 1), navigated
    except BaseException as e:  # a cut-short run still leaves a row in scan_log.csv
        store.log_scan(now, target, "interrupted" if isinstance(e, KeyboardInterrupt) else "error", detail=repr(e))
        stopped = isinstance(e, KeyboardInterrupt)  # asked to stop: no more clicks
        raise
    finally:
        if navigated and not stopped and not teleported:
            try:
                if not navigate.close_results(hwnd):
                    print("Could not close the results list; close it yourself (red X) before the next run")
            except Exception as e:  # must not hide the error that ended the scan
                print(f"Could not close the results list ({e!r}); close it yourself (red X)")


def main(argv: list[str] | None = None) -> int:
    from scanner.windows import screen  # Windows only

    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("skin", help="skin_name exactly as in targets.csv")
    args.add_argument("--wait", type=int, default=30, help="seconds to wait for you to click Roblox")
    args.add_argument("--navigate", action="store_true",
                      help="search for the skin, open its results, scan, then close them (start on the collection "
                           "screen); clicks and types")
    args.add_argument("--repeat", type=int, default=1,
                      help="scan this many times; with --navigate a repeat reopens the same skin without searching again")
    args.add_argument("--pause", type=int, default=0, help="seconds between repeats")
    a = args.parse_args(argv)

    if a.repeat < 1:
        print("--repeat must be at least 1")
        return 2
    cfg = load_config()
    target = next((t for t in load_targets(cfg.targets_path) if t.skin_name.casefold() == a.skin.casefold()), None)
    if target is None:
        print(f"{a.skin!r} is not a valid row in {cfg.targets_path}")
        return 2
    if not target.enabled:
        print(f"{target.skin_name!r} has enabled=false in {cfg.targets_path}; set it to true to scan it")
        return 2
    if target.max_price is None:  # not configured: nothing could match, and no early stop would ever fire
        print(f"{target.skin_name!r} has no max_price in {cfg.targets_path}; set one to scan it")
        return 2
    hwnd = screen.find_roblox()
    if hwnd is None:
        print("Roblox window not found")
        return 2
    if not screen.is_focused(hwnd):
        print(f"Click the Roblox title bar within {a.wait} s (not inside the game)...")
        deadline = time.time() + a.wait
        while not screen.is_focused(hwnd) and time.time() < deadline:
            time.sleep(0.5)
        if not screen.is_focused(hwnd):
            print("Roblox is not in front; nothing was sent.")
            return 2
    out = Path(cfg.output_dir)
    setup_run_log(out)
    searched = False
    for i in range(a.repeat):
        if i:
            time.sleep(a.pause)
        try:
            code, searched = _run_once(hwnd, cfg, out, target, a.navigate, searched)
        except KeyboardInterrupt:
            print("Stopped (Ctrl+C).")
            return 130
        if code:  # a failed scan leaves the screen in an unknown state: no further clicks
            return code
    return code


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)  # targets.csv and output/ are found next to this file, wherever it is started from
    sys.exit(main())
