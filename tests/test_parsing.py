import pytest

from scanner.logic.parsing import format_serial, parse_price, parse_serial, price_high, price_is_approximate


@pytest.mark.parametrize("text,expected", [
    ("8,700", 8700), ("8700", 8700), ("  9,000 ", 9000), ("1,234,567", 1234567), ("0", 0),
    ("12.2k", 12200), ("12k", 12000), ("12.2K", 12200), ("1.5m", 1500000), ("0.5k", 500), ("10.1k", 10100),
    ("", None), ("8.700", None), ("12,34", None), ("1,2345", None), ("-5", None), ("8,7OO", None),
    ("12.k", None), ("k", None), ("12.2kk", None), ("1,200k", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("#610", (610, False)), ("[#610]", (610, False)),
    ("#ST.291", (291, True)), ("[#ST.291]", (291, True)),
    ("", None), ("610", None), ("#", None), ("#ST.", None), ("#12a", None), ("ST.291", None),
])
def test_parse_serial(text, expected):
    assert parse_serial(text) == expected


def test_format_serial_round_trips():
    assert format_serial(610, False) == "#610"
    assert format_serial(291, True) == "#ST.291"
    assert parse_serial(format_serial(291, True)) == (291, True)


def test_price_is_approximate_only_for_abbreviated_prices():
    assert price_is_approximate("12.2k") and price_is_approximate("1.5M")
    assert not price_is_approximate("9,949") and not price_is_approximate("8700")


def test_price_high_is_the_most_a_cut_off_price_can_mean():
    assert price_high(11700, True) == 11799  # '11.7k': first three digits kept, the rest cut off
    assert price_high(10000, True) == 10099  # confirmed in game: 10,099 shows as '10k'
    assert price_high(117000, True) == 117999
    assert price_high(1500000, True) == 1509999
    assert price_high(11749, False) == 11749  # exact prices are exact
