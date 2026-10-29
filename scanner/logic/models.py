"""Target and Listing types, plus read-only loading of targets.csv."""
import csv
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

CATEGORIES = {"Sniper", "Knife"}
RARITIES = {"Secret", "Limited"}


@dataclass(frozen=True)
class Target:
    skin_name: str
    category: str
    rarity: str
    max_price: int | None  # None = not configured, never "unlimited"
    max_serial: int | None  # None = any serial; no StatTrak filter (user decision 2026-10-28: serial is what matters)
    enabled: bool


@dataclass(frozen=True)
class Listing:
    price: int | None  # None = unreadable
    serial: int | None
    stattrak: bool | None  # None = unknown
    seller: str = ""
    price_approx: bool = False  # True when read from an abbreviated '12.2k' price
    serial_digits: int | None = None  # display only: digit count when the exact serial is unreadable


def _opt_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    n = int(value)  # ValueError on junk -> row skipped
    if n < 0:
        raise ValueError("negative")
    return n


def _parse_row(row: dict) -> Target:
    skin = (row.get("skin_name") or "").strip()
    category = (row.get("category") or "").strip()
    rarity = (row.get("rarity") or "").strip()
    enabled = (row.get("enabled") or "").strip().lower()
    if not skin:
        raise ValueError("empty skin_name")
    if category not in CATEGORIES:
        raise ValueError(f"bad category {category!r}")
    if rarity not in RARITIES:
        raise ValueError(f"bad rarity {rarity!r}")
    if enabled not in {"true", "false"}:
        raise ValueError(f"bad enabled {enabled!r}")
    return Target(
        skin, category, rarity,
        _opt_int(row.get("max_price") or ""),
        _opt_int(row.get("max_serial") or ""),
        enabled == "true",
    )


def load_targets(path: str) -> list[Target]:
    """Read targets.csv without modifying it. Invalid rows and repeated skins are skipped with a warning; lines starting
    with # are comments."""
    targets: list[Target] = []
    seen: set[str] = set()
    with open(path, newline="", encoding="utf-8") as f:
        # A line starting with # is a comment: blanked, so it is skipped like an empty line. Blank and comment lines
        # above the header are left out, or the reader would take one as the header; `start` keeps line numbers right.
        lines = ["\n" if text.lstrip().startswith("#") else text for text in f]
        start = next((i for i, text in enumerate(lines) if text.strip()), len(lines))
        rows = csv.DictReader(lines[start:])
        for row in rows:
            line = start + rows.line_num
            try:
                t = _parse_row(row)
            except ValueError as e:
                log.warning("targets.csv line %d skipped: %s", line, e)
                continue
            key = t.skin_name.casefold()
            if key in seen:
                log.warning("targets.csv line %d skipped: duplicate skin %r", line, t.skin_name)
                continue
            seen.add(key)
            targets.append(t)
    return targets
