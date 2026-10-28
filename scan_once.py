"""First milestone: read the results window that is open now, match one target, save crops and CSVs.

Sends no input: you open the skin's results in Roblox yourself. Run with Windows Python:
    python scan_once.py "Starveil AWP"
Only the cards visible on screen are read (no scrolling yet).
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

import vision
from config import load_config
from cropper import save_crop
from matcher import matches
from models import Target, load_targets
from storage import Store, setup_run_log


def scan_visible(img: np.ndarray, target: Target, store: Store, out: Path, now: datetime) -> dict:
    """Read every card in one capture, record it, and save a crop for each new match. No Windows calls."""
    pil = Image.fromarray(img[:, :, ::-1])  # BGR -> RGB, real captured pixels
    cards = vision.read_cards(img)
    result = {"cards": len(cards), "read": 0, "matches": 0, "loading": 0, "unreadable": 0, "clipped": 0,
              "lines": [], "records": vision.read_record_count(img) if cards else None}
    for card in cards:
        if not card.complete:
            result["clipped"] += 1
        elif card.loading:
            result["loading"] += 1
        elif card.complete and card.listing is None:
            result["unreadable"] += 1
        if card.listing is None:
            continue
        listing = card.listing
        result["read"] += 1
        ok = matches(target, listing)
        result["matches"] += ok
        line = store.record(now, target, listing, ok, make_crop=lambda box=card.box, l=listing: save_crop(
            pil, box, out / "screenshots" / "matches", Path.cwd(), now, target.skin_name, l.price, l.seller))
        if line:
            result["lines"].append(line)
    return result


def main(argv: list[str] | None = None) -> int:
    import screen  # Windows only

    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("skin", help="skin_name exactly as in targets.csv")
    args.add_argument("--wait", type=int, default=30, help="seconds to wait for you to click Roblox")
    a = args.parse_args(argv)

    cfg = load_config()
    target = next((t for t in load_targets(cfg.targets_path) if t.skin_name.casefold() == a.skin.casefold()), None)
    if target is None:
        print(f"{a.skin!r} is not a valid row in {cfg.targets_path}")
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
    img = screen.capture(hwnd)
    for _ in range(3):  # an in-game "X bought Y" banner covers cards for a few seconds: wait it out
        if img is None or not vision.has_banner(img):
            break
        print("Announcement banner on screen, waiting...")
        time.sleep(2)
        img = screen.capture(hwnd)
    if img is None:
        print("Roblox is not in front (or minimized); nothing captured")
        return 2
    banner = vision.has_banner(img)
    if img.shape[1] < cfg.min_window_width:
        print(f"Roblox is {img.shape[1]} px wide; at least {cfg.min_window_width} is needed")
        return 2

    out = Path(cfg.output_dir)
    setup_run_log(out)
    Image.fromarray(img[:, :, ::-1]).save(out / "last_capture.png")  # diagnostics: what the scan saw
    store = Store(out)
    now = datetime.now().astimezone()
    store.begin_cycle(now.strftime("%Y%m%dT%H%M%S"))
    r = scan_visible(img, target, store, out, now)
    if not r["cards"]:
        print("No results list on screen; nothing recorded")
        store.log_scan(now, target, "no_results_visible")
        return 1
    store.log_scan(now, target, "visible_only", r["read"], r["matches"],
                   f"records_found={r['records']} cards={r['cards']} unreadable={r['unreadable']} loading={r['loading']}"
                   f" clipped={r['clipped']} banner={banner}")
    for line in r["lines"]:
        print(line)
    print(f"{r['read']} listing(s) read, {r['matches']} match(es); records found: {r['records']}"
          + (f"; {r['loading']} still loading, run again" if r["loading"] else "")
          + (f"; {r['unreadable']} unreadable" if r["unreadable"] else "")
          + (f"; {r['clipped']} cut off (not read)" if r["clipped"] else "")
          + ("; a banner was still covering the screen, run again" if banner else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
