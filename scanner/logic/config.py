"""Tunable settings. Defaults live here; an optional config.json overrides them."""
import json
from dataclasses import dataclass, fields, replace
from pathlib import Path


@dataclass(frozen=True)
class Config:
    window_width: int | None = None  # None = largest 16:9 size that fits its monitor (bigger reads serials better)
    window_height: int | None = None
    min_window_width: int = 1200  # real pixels; refuse to scan below this
    targets_path: str = "targets.csv"
    output_dir: str = "output"
    # main.py --snipe (seconds)
    teleport_wait_seconds: float = 2  # after the black loading screen is gone, before walking to the stall
    teleport_max_seconds: float = 60  # stop if the new server has not shown after this long
    teleport_retries: int = 3  # "Teleport Failed" (server full): click Teleport on the same listing this many more times
    walk_seconds: float = 0.5  # hold W, then S, to stand where the stall's "E Open" prompt shows
    hold_e_seconds: float = 1  # hold E to open a stall
    back_to_search_seconds: float = 1.0  # hold W from the map centre (the seller had left) to reach the Search terminal
    stall_max_scrolls: int = 20  # how many times to scroll down a stall looking for the item (about 3 rows each)
    stall_scroll_notches: int = 3  # per scroll: 375 px, less than the 2+ rows in view, so no row is skipped
    stall_load_seconds: float = 5  # how long to keep looking for the item in a stall before calling it gone
    snipe_step_timeout: float = 8  # how long each button may take to show before the flow stops
    dry_run: bool = False  # set by `main.py --snipe --dry-run`: every step but the buy check; the box is cancelled
    robux_box_wait_seconds: float = 2  # after the green check: how long to wait for a late Buy Robux box
    snipe_click_pause: float = 0.5  # after each click, for the next screen to show


def load_config(path: str = "config.json") -> Config:
    """Defaults, overridden by keys in config.json. Unknown keys are ignored."""
    p = Path(path)
    if not p.exists():
        return Config()
    known = {f.name for f in fields(Config)}
    overrides = {k: v for k, v in json.loads(p.read_text()).items() if k in known}
    return replace(Config(), **overrides)
