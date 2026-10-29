"""Scan every enabled skin in targets.csv, one after another, over and over until Ctrl+C. Windows Python.

Start with the collection screen open in Roblox. Each pass reads targets.csv again (so edits and enabled=false take
effect) and scans each enabled row that has a max_price. A skin scanned twice in a row is reopened without
searching again; a different skin is searched for. The next pass starts at once: there is no pause.
It clicks and types the same way as `scan_once.py --navigate` and never clicks Teleport, buy, trade or payment
buttons. Matches are printed and saved under output/. Stops by itself after 3 failed scans in a row.
    python main.py
    python main.py --clear-matches    first delete matches.csv and the saved match pictures
"""
import argparse
import logging
import sys
import time
from pathlib import Path

import scan_once
from scanner.logic.config import load_config
from scanner.logic.models import load_targets
from scanner.logic.storage import clear_matches, setup_run_log

MAX_FAILURES = 3  # in a row: the screen is probably not what we think; stop clicking


def _wait_for_focus(hwnd: int, screen, seconds: float | None = None) -> bool:
    """Wait until Roblox is in front (forever if `seconds` is None); False if it still is not after `seconds`."""
    deadline = None if seconds is None else time.time() + seconds
    told = False
    while not screen.is_focused(hwnd):
        if deadline is not None and time.time() >= deadline:
            return False
        if not told:
            print("Roblox is not in front: click its title bar to go on (Ctrl+C stops).")
            told = True
        time.sleep(0.5)
    return True


def main(argv: list[str] | None = None) -> int:
    from scanner.windows import navigate, screen  # Windows only

    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--wait", type=int, default=30, help="seconds to wait for you to click Roblox")
    args.add_argument("--cycles", type=int, default=0, help="stop after this many passes over targets.csv (0 = until Ctrl+C)")
    args.add_argument("--clear-matches", action="store_true",
                      help="first delete matches.csv and the saved match pictures (old matches); then scan as usual")
    a = args.parse_args(argv)
    cfg = load_config()
    if a.clear_matches:
        print(f"Cleared matches.csv and {clear_matches(cfg.output_dir)} match picture(s).")
    hwnd = screen.find_roblox()
    if hwnd is None:
        print("Roblox window not found")
        return 2
    if not screen.is_focused(hwnd):
        print(f"Click the Roblox title bar within {a.wait} s (not inside the game)...")
        if not _wait_for_focus(hwnd, screen, a.wait):
            print("Roblox is not in front; nothing was sent.")
            return 2
    out = Path(cfg.output_dir)
    setup_run_log(out)
    searched, failures = None, 0  # searched: the skin whose search text is still in the box
    passes = 0
    try:
        while not a.cycles or passes < a.cycles:
            passes += 1
            targets = [t for t in load_targets(cfg.targets_path) if t.enabled and t.max_price is not None]
            if not targets:
                print(f"No enabled skin with a max_price in {cfg.targets_path}")
                return 2
            for target in targets:
                _wait_for_focus(hwnd, screen)  # pause here while you are in another window
                try:
                    code, ok = scan_once._run_once(hwnd, cfg, out, target, True, searched == target.skin_name)
                except Exception:  # one bad read or screen must not end an unattended run: count it as a failed scan
                    logging.getLogger(__name__).exception("%s: the scan crashed", target.skin_name)
                    code, ok = 1, False
                searched = target.skin_name if ok and not code else None  # after a failure, search again
                if code and not screen.is_focused(hwnd):  # focus was lost mid-scan: not a failed screen
                    continue
                failures = failures + 1 if code else 0
                if code:
                    navigate.back_to_collection(hwnd)  # leave no dialog open before the next try
                if failures >= MAX_FAILURES:
                    print(f"{failures} scans failed in a row; stopping. Check the screen and start again.")
                    return 1
        return 0
    except KeyboardInterrupt:
        print("Stopped (Ctrl+C).")
        return 130


if __name__ == "__main__":
    sys.exit(main())
