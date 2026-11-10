r"""Scan every enabled skin in targets.csv, one after another, over and over until Ctrl+C. Windows Python.

Start with the collection screen open in Roblox. Each pass reads targets.csv again (so edits and enabled=false take
effect) and scans each enabled row that has a max_price. A skin scanned twice in a row is reopened without
searching again; a different skin is searched for. The next pass starts at once: there is no pause.
It clicks and types the same way as `scan_once.py --navigate` and never clicks trade or payment buttons; Teleport, buy
and Sell on Market are clicked only with --snipe. Matches are printed and saved under output/. Stops by itself after 3 failed scans in a row.

Flags:
    --wait N          seconds to wait for you to click the Roblox title bar (default 30). First it asks you to
                      press y + Enter (so you are ready); with several Roblox windows, --width/--height resize
                      them all, and the one you click is the one used
    --cycles N        stop after N passes over targets.csv (default 0 = until Ctrl+C)
    --clear-matches   first delete matches.csv and the saved match pictures, then scan as usual
    --snipe           on the first match: Teleport, buy it from the seller's stall, put your own stall up again, then
                      stop the loop (scanner/windows/snipe.py; waits and hold times are in config.json)
    --dry-run         with --snipe: do every step but the buy: the confirm box is cancelled (its red X), the rest
                      (stall X, Inventory ... same-items check) still runs, so it is a full rehearsal. Reads
                      dry_targets.csv instead of targets.csv
    --width N         first resize the Roblox window so its game area is N px wide (height follows at 16:9);
    --height N        or N px high (width follows). Both = that exact size. Runs tools/resize_roblox.ps1.

Run it on Windows (it captures the screen and sends input), with Roblox open on the collection screen.
From the Windows copy of the project, C:\Users\joshu\ro-test (no WSL needed; `git pull` there first to get updates):
    cd $env:USERPROFILE\ro-test
    & $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe main.py --snipe --dry-run --width 1900
From the WSL copy:
    Windows PowerShell:  & $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe \\wsl.localhost\Ubuntu\home\kkura\repos\ro-test\main.py --cycles 1
    From WSL:            powershell.exe -c '& $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe \\wsl.localhost\Ubuntu\home\kkura\repos\ro-test\main.py'
Stop with Ctrl+C in the window it runs in. (From WSL, Ctrl+C may leave the Windows process running: use the first form.)
"""
import argparse
import dataclasses
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import scan_once
from scanner.logic import discord
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


RESIZE_SCRIPT = Path(__file__).parent / "tools" / "resize_roblox.ps1"


def resize_roblox(width: int, height: int) -> bool:
    """Run tools/resize_roblox.ps1 (give a width, a height, or both; the other follows from 16:9). True if it ran."""
    size = [x for flag, n in (("-Width", width), ("-Height", height)) if n for x in (flag, str(n))]
    done = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(RESIZE_SCRIPT), *size])
    return done.returncode == 0


def main(argv: list[str] | None = None) -> int:
    from scanner.windows import navigate, screen  # Windows only

    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--wait", type=int, default=30, help="seconds to wait for you to click Roblox")
    args.add_argument("--cycles", type=int, default=0, help="stop after this many passes over targets.csv (0 = until Ctrl+C)")
    args.add_argument("--clear-matches", action="store_true",
                      help="first delete matches.csv and the saved match pictures (old matches); then scan as usual")
    args.add_argument("--width", type=int, default=0, help="first resize the Roblox window to this client width (height follows at 16:9)")
    args.add_argument("--height", type=int, default=0, help="first resize the Roblox window to this client height (width follows at 16:9)")
    args.add_argument("--snipe", action="store_true",
                      help="on the first match: Teleport, buy it from the stall, put your stall up again, then stop")
    args.add_argument("--dry-run", action="store_true",
                      help="with --snipe: every step except the green check that buys (the confirm box is cancelled)")
    a = args.parse_args(argv)
    if a.dry_run and not a.snipe:
        args.error("--dry-run only works together with --snipe")
    cfg = dataclasses.replace(load_config(), dry_run=a.dry_run)
    if a.dry_run:
        cfg = dataclasses.replace(cfg, targets_path="dry_targets.csv")
    if not os.path.exists(cfg.targets_path):
        print(f"{cfg.targets_path} not found")
        return 2
    if (a.width or a.height) and not resize_roblox(a.width, a.height):
        print("Could not resize the Roblox window (is it open and not fullscreen?)")
        return 2
    if a.clear_matches:
        print(f"Cleared matches.csv and {clear_matches(cfg.output_dir)} match picture(s).")
    if screen.find_roblox() is None:
        print("Roblox window not found")
        return 2
    if sys.stdin.isatty():  # clicking Roblox takes the keyboard from this window, so the "ready?" comes first
        try:
            while input("Press y then Enter when you are ready to click the Roblox window to use: ").strip().lower() != "y":
                pass
        except (EOFError, KeyboardInterrupt):
            print("Stopped before sending anything.")
            return 130
    print(f"Click the title bar of the Roblox window to use within {a.wait} s (not inside the game)...")
    deadline = time.time() + a.wait
    while True:  # with several Roblox windows, the one you click is the one used
        hwnd = screen.find_roblox()
        if hwnd is not None and screen.is_focused(hwnd):
            break
        if time.time() >= deadline:
            print("Roblox is not in front; nothing was sent.")
            return 2
        time.sleep(0.5)
    out = Path(cfg.output_dir)
    setup_run_log(out)
    discord.start(cfg, f"Run started {discord.stamp()} ("
                  + ("--snipe --dry-run" if a.dry_run else "--snipe" if a.snipe else "scan only") + ")")
    ended = "Run ended early: the program crashed (see output/run.log)."
    searched, failures = None, 0  # searched: the skin whose search text is still in the box
    picked = None  # (category, rarity) the buttons were last set to by a good scan
    passes = 0
    try:
        while not a.cycles or passes < a.cycles:
            passes += 1
            targets = [t for t in load_targets(cfg.targets_path) if t.enabled and t.max_price is not None]
            if not targets:
                print(f"No enabled skin with a max_price in {cfg.targets_path}")
                ended = f"Run ended early: no enabled skin with a max_price in {cfg.targets_path}."
                return 2
            for target in targets:
                _wait_for_focus(hwnd, screen)  # pause here while you are in another window
                try:
                    code, ok = scan_once._run_once(hwnd, cfg, out, target, True, searched == target.skin_name,
                                                    picked == (target.category, target.rarity), a.snipe)
                except Exception:  # one bad read or screen must not end an unattended run: count it as a failed scan
                    logging.getLogger(__name__).exception("%s: the scan crashed", target.skin_name)
                    code, ok = 1, False
                if code == scan_once.TELEPORTED:
                    print(f"Teleported for {target.skin_name}. Stopping the loop: it is your turn.")
                    ended = "Run ended: finished, the stall is up again."
                    return 0
                if code == scan_once.SNIPE_STOPPED:
                    print(f"Teleported for {target.skin_name}, but the steps after it stopped. Stopping the loop: take over.")
                    ended = "Run ended early: the snipe stopped part way; take over in the game."
                    return 1
                searched = target.skin_name if ok and not code else None  # after a failure, search again
                picked = (target.category, target.rarity) if ok and not code else None  # and click the buttons again
                if code and not screen.is_focused(hwnd):  # focus was lost mid-scan: not a failed screen
                    continue
                failures = failures + 1 if code else 0
                if code:
                    navigate.back_to_collection(hwnd)  # leave no dialog open before the next try
                if failures >= MAX_FAILURES:
                    print(f"{failures} scans failed in a row; stopping. Check the screen and start again.")
                    ended = f"Run ended early: {failures} scans failed in a row."
                    return 1
            print(f"Loop {passes} done" + (", trying again" if not a.cycles or passes < a.cycles else ""))
        ended = f"Run ended after {passes} pass(es)."
        return 0
    except KeyboardInterrupt:
        print("Stopped (Ctrl+C).")
        ended = "Run ended early: stopped with Ctrl+C."
        return 130
    finally:
        discord.finish(cfg, ended)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):  # a window title like '✳ ...' must not crash a print to a pipe or file
        stream.reconfigure(errors="replace")
    os.chdir(Path(__file__).parent)  # targets.csv and output/ are found next to this file, wherever it is started from
    sys.exit(main())
