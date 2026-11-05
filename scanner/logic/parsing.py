"""Turn text read from the screen into typed values. None means unreadable, never a guess."""
import re
from decimal import Decimal

_PRICE = re.compile(r"\d{1,3}(,\d{3})+|\d+")
_ABBREV = re.compile(r"(\d+(?:\.\d+)?)([kKmM])")
_SCALE = {"k": 1_000, "m": 1_000_000}
_SERIAL = re.compile(r"\[?\s*#\s*(ST\.)?\s*(\d+)\s*\]?")


def parse_price(text: str) -> int | None:
    """'8,700' -> 8700; '12.2k' -> 12200 (see price_is_approximate). Anything else is None."""
    t = text.strip()
    if _PRICE.fullmatch(t):
        return int(t.replace(",", ""))
    m = _ABBREV.fullmatch(t)
    if m:
        return int(Decimal(m.group(1)) * _SCALE[m.group(2).lower()])
    return None


def price_is_approximate(text: str) -> bool:
    """The game shows large prices as '12.2k', which only has three significant digits."""
    return _ABBREV.fullmatch(text.strip()) is not None


def price_high(price: int, approximate: bool) -> int:
    """Highest price a reading can mean. The game cuts '11,799' down to '11.7k' (first three digits, not rounded)."""
    return price + 10 ** max(0, len(str(price)) - 3) - 1 if approximate else price


def parse_serial(text: str) -> tuple[int, bool] | None:
    """'#610' -> (610, False); '#ST.291' -> (291, True); malformed -> None."""
    m = _SERIAL.fullmatch(text.strip())
    if not m:
        return None
    return int(m.group(2)), m.group(1) is not None


def format_serial(serial: int, stattrak: bool) -> str:
    return f"#ST.{serial}" if stattrak else f"#{serial}"
