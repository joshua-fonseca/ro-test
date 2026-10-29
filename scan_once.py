"""Scan one skin's results list: scroll it top to bottom, match one target, save crops and CSVs.

Run with Windows Python. Without --navigate you open the skin's results in Roblox yourself, and the scan only moves
the mouse and turns the wheel over the list (no clicks):
    python scan_once.py "Starveil AWP"
With --navigate it starts from the collection screen (empty search box) and also clicks the search box, the skin's
tile, the green check in Search Options and the red X that closes the results, and types the skin name. It never
clicks Teleport, buy, trade or payment buttons.
    python scan_once.py "Starveil AWP" --navigate
Lists are sorted cheapest first, so the scan stops at the first (cheapest) match, or once prices are past
max_price (see scan_list).
"""
import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import vision
from config import load_config
from cropper import save_crop
from matcher import matches
from models import Target, load_targets
from parsing import price_high
from storage import Store, setup_run_log

log = logging.getLogger(__name__)

# One notch moves the list ~150 px (measured live at 1898x1068 and on the saved frames); the list shows ~540 px and a
# card is ~170 px, so a step must stay under ~370 px or a card is never fully visible (3 notches skipped two cards).
STEP = 1  # notches per step
UP = 10  # notches per step while going back to the top (nothing is read on the way)


def _over(target: Target, listing) -> bool:
    # '11.7k' is at least 11,700 (the game cuts digits off, never rounds up), so the shown price is the lowest
    return target.max_price is not None and listing.price > target.max_price


def scan_visible(img: np.ndarray, target: Target, store: Store, out: Path, now: datetime,
                 seen: list | None = None, first_only: bool = False) -> dict:
    """Read every card in one capture, record it, and save a crop for each new match. No Windows calls.

    seen: vision.read_card's cache across frames; repeat cards are not recorded again.
    first_only: stop reading at the first match (cards below it are not read).
    """
    pil = Image.fromarray(img[:, :, ::-1])  # BGR -> RGB, real captured pixels
    boxes = vision.find_cards(img)
    result = {"cards": len(boxes), "read": 0, "matches": 0, "loading": 0, "unreadable": 0, "clipped": 0,
              "lines": [], "records": vision.read_record_count(img) if boxes else None, "over_pair": False,
              "unsorted": False}
    over, lowest = 0, 0  # lowest: the least the cards above can cost
    earlier = len(seen) if seen is not None else 0
    for box in boxes:
        card = vision.read_card(img, box, seen, earlier)
        if not card.complete:
            result["clipped"] += 1
        elif card.loading:
            result["loading"] += 1
        elif card.complete and card.listing is None:
            result["unreadable"] += 1
        if card.listing is None:
            over = 0  # an unreadable card never counts toward the early stop
            continue
        listing = card.listing
        # Early stop needs two readable cards in a row over max_price in one frame, so surely two different cards
        over = over + 1 if _over(target, listing) else 0
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


def scan_list(img: np.ndarray, next_frame, target: Target, store: Store, out: Path, now: datetime,
              max_steps: int = 300) -> dict:
    """Go to the top of the list, then read it down to the end or until prices pass max_price. No Windows calls.

    next_frame(notches) scrolls (down if > 0, 0 = just look again) and returns the next capture, or None when
    Roblox lost focus. status: complete (end reached), stopped_at_price, stopped_at_first_match, focus_lost,
    list_lost or max_steps. Only the cheapest match is wanted, so the scan stops at the first one; an unreadable
    card above it is skipped, not waited for.
    """
    total = {"read": 0, "matches": 0, "unreadable": 0, "loading": 0, "lines": [], "frames": 0,
             "records": vision.read_record_count(img), "sorted": True, "status": "max_steps"}
    view, still = _view(img), 0
    for _ in range(max_steps):  # start from the top so the first card is the cheapest
        img = next_frame(-UP)
        if img is None:
            return {**total, "status": "focus_lost"}
        v = _view(img)
        if v is None:  # the list is gone (closed?): stop sending the wheel anywhere
            return {**total, "status": "list_lost"}
        still, view = (still + 1 if _same(v, view) else 0), v
        if still >= 2:
            break
    seen, retries, still = [], 0, 0
    for _ in range(max_steps):
        if view is None:
            total["status"] = "list_lost"
            break
        r = scan_visible(img, target, store, out, now, seen, first_only=total["sorted"])
        total["frames"] += 1
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
            break
        # a card still says [Loading...] or a banner covers cards: look again before scrolling past them
        if (r["loading"] or vision.has_banner(img)) and retries < 3:
            retries += 1
            time.sleep(1)
            notches = 0
        else:
            total["loading"] += r["loading"]
            retries, notches = 0, STEP
        img = next_frame(notches)
        if img is None:
            total["status"] = "focus_lost"
            break
        v = _view(img)
        if notches:
            still = still + 1 if _same(v, view) else 0
        view = v
        if still >= 2:  # the last notches may still bounce, so two unchanged steps
            total["status"] = "complete"
            break
    return total


def _live_frames(hwnd: int, frames_dir: Path | None = None):
    """next_frame for scan_list on the real window: scroll over a seller name, wait for it to settle, capture."""
    import controller
    import screen
    last, point = None, None

    def next_frame(notches: int) -> np.ndarray | None:
        nonlocal last, point
        if notches:
            cards = [b for b in vision.find_cards(last) if vision._is_complete(b)] if last is not None else []
            if cards:  # none (banner, loading): keep the last point; a list that is really gone ends as list_lost
                l, t, r, b = cards[0]
                x0, y0 = screen.client_rect(hwnd)[:2]
                # 35% across is the seller name; Teleport is in the right 20% of every card
                point = x0 + l + int(0.35 * (r - l)), y0 + t + int(0.23 * (b - t))
            if point is None or not controller.scroll(hwnd, *point, notches):
                return None
            time.sleep(0.4)  # let the list settle
        img = screen.capture(hwnd)
        for _ in range(3):  # an in-game "X bought Y" banner covers cards for a few seconds: wait it out
            if img is None or not vision.has_banner(img):
                break
            print("Announcement banner on screen, waiting...")
            time.sleep(2)
            img = screen.capture(hwnd)
        last = img
        if frames_dir and img is not None:  # diagnostics: every frame, to check how far a step moves the list
            cv2.imwrite(str(frames_dir / f"{len(list(frames_dir.glob('*.png'))):03d}.png"), img)
        return img
    return next_frame


def main(argv: list[str] | None = None) -> int:
    import screen  # Windows only

    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("skin", help="skin_name exactly as in targets.csv")
    args.add_argument("--wait", type=int, default=30, help="seconds to wait for you to click Roblox")
    args.add_argument("--navigate", action="store_true",
                      help="search for the skin, open its results, scan, then close them (start on the collection "
                           "screen with an empty search box); clicks and types")
    a = args.parse_args(argv)

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
    out = Path(cfg.output_dir)
    setup_run_log(out)
    store = Store(out)
    now = datetime.now().astimezone()
    store.begin_cycle(now.strftime("%Y%m%dT%H%M%S"))
    navigated = False
    if a.navigate:
        import navigate
        ok, why = navigate.search_for(hwnd, target.skin_name)
        opened = navigate.open_results(hwnd, target.skin_name)[0] if ok else None
        if opened is None:
            why = why or "the results did not open"
            print(f"Navigation stopped: {why}")
            store.log_scan(now, target, "navigation_failed", detail=why)
            return 1
        navigated = True
    try:
        frames_dir = Path(cfg.output_dir) / "scan_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for old in frames_dir.glob("*.png"):  # only the latest run's frames are kept
            old.unlink()
        next_frame = _live_frames(hwnd, frames_dir)
        img = next_frame(0)
        if img is None:
            print("Roblox is not in front (or minimized); nothing captured")
            return 2
        if img.shape[1] < cfg.min_window_width:
            print(f"Roblox is {img.shape[1]} px wide; at least {cfg.min_window_width} is needed")
            return 2

        Image.fromarray(img[:, :, ::-1]).save(out / "last_capture.png")  # diagnostics: what the scan saw
        if not any(vision._is_complete(b) for b in vision.find_cards(img)):  # the StatTrak dialog has a card-like bar
            print("No results list on screen; nothing recorded")
            store.log_scan(now, target, "no_results_visible")
            return 1
        print("Scrolling the list: hands off the mouse; click another window to stop.")
        r = scan_list(img, next_frame, target, store, out, now)
        if r["status"] == "complete":
            store.end_cycle()  # only a full scroll saw every listing; an early stop must not mark the rest unseen
        store.log_scan(now, target, r["status"], r["read"], r["matches"],
                       f"records_found={r['records']} frames={r['frames']} unreadable_reads={r['unreadable']}"
                       f" loading={r['loading']} sorted={r['sorted']}")
        for line in r["lines"]:
            print(line)
        print(f"{r['status']}: {r['read']} listing(s) read, {r['matches']} match(es); records found: {r['records']}"
              + (f"; {r['loading']} still loading when passed" if r["loading"] else "")
              + (f"; {r['unreadable']} unreadable card read(s)" if r["unreadable"] else "")
              + ("" if r["sorted"] else "; list was not sorted by price, scrolled to the end"))
        return 0 if r["status"] in ("complete", "stopped_at_price", "stopped_at_first_match") else 1
    except BaseException as e:  # a cut-short run still leaves a row in scan_log.csv
        store.log_scan(now, target, "interrupted" if isinstance(e, KeyboardInterrupt) else "error", detail=repr(e))
        raise
    finally:
        if navigated and not navigate.close_results(hwnd):
            print("Could not close the results list; close it yourself (red X) before the next run")


if __name__ == "__main__":
    sys.exit(main())
