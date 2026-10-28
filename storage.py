"""Persistence. Everything is written as it happens so an interrupted run loses nothing.

matches.csv / listings.csv / scan_log.csv  append-only history, never cleared
listing_state.json                         latest status per listing, survives restarts
run.log                                    diagnostics, truncated each start
discovered_skins.csv                       discovery results only, never targets.csv
"""
import csv
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from models import Listing, Target
from parsing import format_serial

log = logging.getLogger(__name__)

TARGET_FIELDS = ["skin_name", "category", "rarity", "max_price", "max_serial", "stattrak", "enabled"]
ROW_FIELDS = ["scan_id", "observed_at", "skin_name", "category", "rarity", "stattrak", "serial", "price",
              "price_approx", "seller_display_name", "listing_id", "screenshot_path", "crop_status"]
LISTING_FIELDS = ROW_FIELDS + ["matched"]
SCAN_FIELDS = ["observed_at", "scan_id", "skin_name", "status", "listings_seen", "matches", "detail"]


_waiting: dict[Path, list[dict]] = {}  # rows that could not be written because the file was locked


def append_csv(path: Path, fields: list[str], row: dict) -> None:
    """Append a row. If the file is locked (Excel has it open on Windows), keep the row and retry next time."""
    queue = _waiting.setdefault(path, [])
    queue.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fields)
            if new:
                writer.writeheader()
            writer.writerows(queue)
    except PermissionError:
        log.warning("%s is locked (open in another program?); %d row(s) waiting", path.name, len(queue))
        return
    queue.clear()


def listing_id(target: Target, listing: Listing) -> str:
    """Best-effort fingerprint. Serial is part of it, price is not, so a price change is the same listing.

    Identical listings from one seller with no visible serial collide; that is accepted.
    """
    parts = [target.skin_name.casefold(), target.category.casefold(), listing.seller.strip().casefold(),
             "" if listing.serial is None else str(listing.serial), str(listing.stattrak)]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def serial_label(listing: Listing) -> str:
    """Exact serial, else '3-digit' when only the length is known, else 'Unknown'. Display only."""
    # User decision 2026-10-28: 'Unknown' and the n-digit labels replace the spec's NO_SERIAL; keep them.
    if listing.serial is not None:
        return format_serial(listing.serial, bool(listing.stattrak))
    if listing.serial_digits is not None:
        return f"{'ST.' if listing.stattrak else ''}{listing.serial_digits}-digit"
    return "Unknown"


def format_match_line(target: Target, listing: Listing, screenshot_path: str) -> str:
    serial = serial_label(listing)
    price = "PRICE_UNREADABLE" if listing.price is None else f"{listing.price:,}"
    return f"[{target.rarity.upper()}] [{target.skin_name}] [{serial}] [{price}] [{screenshot_path}]"


class Store:
    def __init__(self, output_dir: str | Path):
        self.dir = Path(output_dir)
        self.state_path = self.dir / "listing_state.json"
        self.state: dict[str, dict] = (
            json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {})
        self.scan_id = ""
        self._seen: set[str] = set()

    def begin_cycle(self, scan_id: str) -> None:
        self.scan_id, self._seen = scan_id, set()

    def end_cycle(self) -> None:
        """Call only for a completed cycle. Absent listings are marked not observed, not sold."""
        for lid, entry in self.state.items():
            entry["observed_in_latest_cycle"] = lid in self._seen
        self._save_state()

    def record(self, observed_at: datetime, target: Target, listing: Listing, matched: bool,
               make_crop: Callable[[], tuple[str, str]] | None = None) -> str | None:
        """Log one observation. Returns the compact notification line the first time a listing qualifies.

        Repeat sightings within a cycle (scroll overlap) are ignored. A listing that stops
        qualifying and later qualifies again notifies again; a price change alone does not.
        make_crop is called only for a new match and returns (screenshot_path, crop_status).
        """
        assert observed_at.tzinfo is not None, "observed_at must carry a timezone offset"
        lid = listing_id(target, listing)
        if lid in self._seen:
            return None
        self._seen.add(lid)

        was_matching = self.state.get(lid, {}).get("matching", False)
        new_match = matched and not was_matching
        shot, crop_status = make_crop() if new_match and make_crop else ("", "")
        row = {
            "scan_id": self.scan_id, "observed_at": observed_at.isoformat(timespec="seconds"),
            "skin_name": target.skin_name, "category": target.category, "rarity": target.rarity,
            "stattrak": "" if listing.stattrak is None else str(listing.stattrak).lower(),
            "serial": listing.serial if listing.serial is not None else serial_label(listing),
            "price": "" if listing.price is None else listing.price,
            "price_approx": str(listing.price_approx).lower(), "seller_display_name": listing.seller,
            "listing_id": lid, "screenshot_path": shot, "crop_status": crop_status,
        }
        append_csv(self.dir / "listings.csv", LISTING_FIELDS, {**row, "matched": str(matched).lower()})
        if new_match:
            append_csv(self.dir / "matches.csv", ROW_FIELDS, row)
        self.state[lid] = {"skin_name": target.skin_name, "price": listing.price, "matching": was_matching if listing.price is None else matched,
                           "last_seen_scan": self.scan_id, "observed_in_latest_cycle": True}
        self._save_state()
        return format_match_line(target, listing, shot) if new_match else None

    def log_scan(self, observed_at: datetime, target: Target, status: str,
                 listings_seen: int = 0, matches: int = 0, detail: str = "") -> None:
        append_csv(self.dir / "scan_log.csv", SCAN_FIELDS, {
            "observed_at": observed_at.isoformat(timespec="seconds"), "scan_id": self.scan_id,
            "skin_name": target.skin_name, "status": status, "listings_seen": listings_seen,
            "matches": matches, "detail": detail})

    def _save_state(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.state, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_path)  # atomic: an interrupt never leaves half a file


def add_discovered_skins(path: Path, names: list[str], dry_run: bool = False) -> list[str]:
    """Append skin names not already present. Only skin_name is filled; other columns stay blank."""
    known: set[str] = set()
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            known = {(r.get("skin_name") or "").strip().casefold() for r in csv.DictReader(f)}
    new: list[str] = []
    for name in (n.strip() for n in names):
        if name and name.casefold() not in known:
            known.add(name.casefold())
            new.append(name)
    if not dry_run:
        for name in new:
            append_csv(path, TARGET_FIELDS, {"skin_name": name})
    return new


def setup_run_log(output_dir: str | Path) -> logging.Handler:
    """Diagnostic log, truncated on every start. CSV history and state are untouched."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(out / "run.log", mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    return handler
