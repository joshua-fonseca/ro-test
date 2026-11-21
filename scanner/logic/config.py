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
    walk_seconds: float = 0.7  # hold W toward the stall... (0.5 stopped short of the "E Open" prompt: seen live)
    back_seconds: float = 0.3  # ...then S, to stand where its "E Open" prompt shows (0.5 was too far back: seen live)
    hold_e_seconds: float = 1  # hold E to open a stall
    back_to_search_seconds: float = 0.7  # hold W from the map centre (the seller had left) to reach the Search terminal
    stall_max_scrolls: int = 20  # how many times to scroll down a stall looking for the item (about 3 rows each)
    stall_scroll_notches: int = 3  # per scroll: 375 px, less than the 2+ rows in view, so no row is skipped
    stall_load_seconds: float = 5  # how long to keep looking for the item in a stall before calling it gone
    snipe_step_timeout: float = 8  # how long each button may take to show before the flow stops
    dry_run: bool = False  # set by `main.py --snipe --dry-run`: every step but the buy check; the box is cancelled
    relist: bool = True  # set by `main.py --loop`: False until the last snipe, so the stall is set up once, at the end
    loop_friend: str = "IAMBADATFUN"  # --loop: the friend whose server is joined again after each buy (the start of
    # the name as Roblox's home page shows it; "..." cuts long names, so the start is enough)
    loop_home_seconds: float = 30  # --loop: how long Roblox's home page may take to show the friend after leaving
    robux_box_wait_seconds: float = 2  # after the green check: how long to wait for a late Buy Robux box
    snipe_click_pause: float = 0.5  # after each click, for the next screen to show
    # Discord message about a found weapon (off while server or channel is empty); the bot token is the DISCORD_BOT_TOKEN
    # environment variable, never a file
    discord_server: str = ""  # the server's name, as the bot sees it
    discord_channel: str = ""  # the text channel's name in that server
    discord_send: str = "text"  # "text" = the match line, "picture" = the card's picture; the status follows either


def load_config(path: str = "config.json") -> Config:
    """Defaults, overridden by keys in config.json. Unknown keys are ignored."""
    p = Path(path)
    if not p.exists():
        return Config()
    known = {f.name for f in fields(Config)}
    overrides = {k: v for k, v in json.loads(p.read_text()).items() if k in known}
    return replace(Config(), **overrides)
