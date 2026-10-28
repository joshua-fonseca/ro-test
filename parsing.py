"""Turn text read from the screen into typed values. None means unreadable, never a guess."""
import re

_PRICE = re.compile(r"\d{1,3}(,\d{3})+|\d+")
_SERIAL = re.compile(r"\[?\s*#\s*(ST\.)?\s*(\d+)\s*\]?")
_RARITY = {"SCRT": "Secret", "HSCRT": "Secret", "LTD": "Limited", "HLTD": "Limited"}


def parse_price(text: str) -> int | None:
    """'8,700' -> 8700. Anything that isn't a plain or comma-grouped integer is None."""
    t = text.strip()
    if not _PRICE.fullmatch(t):
        return None
    return int(t.replace(",", ""))


def parse_serial(text: str) -> tuple[int, bool] | None:
    """'#610' -> (610, False); '#ST.291' -> (291, True); malformed -> None."""
    m = _SERIAL.fullmatch(text.strip())
    if not m:
        return None
    return int(m.group(2)), m.group(1) is not None


def format_serial(serial: int, stattrak: bool) -> str:
    return f"#ST.{serial}" if stattrak else f"#{serial}"


def parse_rarity(tag: str) -> str | None:
    """'[HSCRT]' -> 'Secret'. Holiday (H) variants count as their base rarity."""
    return _RARITY.get(tag.strip().strip("[]").strip().upper())
