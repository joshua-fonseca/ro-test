"""Target and Listing types, plus read-only loading of targets.csv."""
import csv
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

CATEGORIES = {"Sniper", "Knife"}
RARITIES = {"Secret", "Limited"}
STATTRAK_VALUES = {"with", "without"}


@dataclass(frozen=True)
class Target:
    skin_name: str
    category: str
    rarity: str
    max_price: int | None  # None = not configured, never "unlimited"
    max_serial: int | None  # None = any serial
    stattrak: str | None  # None = any variant, else "with" / "without"
    enabled: bool


@dataclass(frozen=True)
class Listing:
    price: int | None  # None = unreadable
    serial: int | None
    stattrak: bool | None  # None = unknown
    seller: str = ""
    price_approx: bool = False  # True when read from an abbreviated '12.2k' price


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
    stattrak = (row.get("stattrak") or "").strip().lower() or None
    enabled = (row.get("enabled") or "").strip().lower()
    if not skin:
        raise ValueError("empty skin_name")
    if category not in CATEGORIES:
        raise ValueError(f"bad category {category!r}")
    if rarity not in RARITIES:
        raise ValueError(f"bad rarity {rarity!r}")
    if stattrak is not None and stattrak not in STATTRAK_VALUES:
        raise ValueError(f"bad stattrak {stattrak!r}")
    if enabled not in {"true", "false"}:
        raise ValueError(f"bad enabled {enabled!r}")
    return Target(
        skin, category, rarity,
        _opt_int(row.get("max_price") or ""),
        _opt_int(row.get("max_serial") or ""),
        stattrak, enabled == "true",
    )


def load_targets(path: str) -> list[Target]:
    """Read targets.csv without modifying it. Invalid rows and repeated skins are skipped with a warning."""
    targets: list[Target] = []
    seen: set[str] = set()
    with open(path, newline="", encoding="utf-8") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
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
