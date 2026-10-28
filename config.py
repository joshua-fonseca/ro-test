"""Tunable settings. Defaults live here; an optional config.json overrides them."""
import json
from dataclasses import dataclass, fields, replace
from pathlib import Path


@dataclass(frozen=True)
class Config:
    window_width: int | None = None  # None = smallest size Roblox allows on its monitor
    window_height: int | None = None
    min_window_width: int = 1200  # real pixels; refuse to scan below this
    initial_backward_seconds: float = 2.0  # hold S once at start to reach the E Open prompt
    interact_hold_seconds: float = 0.1  # E press length
    cycle_delay_seconds: float = 15.0  # wait after a completed cycle
    targets_path: str = "targets.csv"
    output_dir: str = "output"


def load_config(path: str = "config.json") -> Config:
    """Defaults, overridden by keys in config.json. Unknown keys are ignored."""
    p = Path(path)
    if not p.exists():
        return Config()
    known = {f.name for f in fields(Config)}
    overrides = {k: v for k, v in json.loads(p.read_text()).items() if k in known}
    return replace(Config(), **overrides)
