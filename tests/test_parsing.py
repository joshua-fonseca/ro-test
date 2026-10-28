import pytest

from parsing import format_serial, parse_price, parse_rarity, parse_serial


@pytest.mark.parametrize("text,expected", [
    ("8,700", 8700), ("8700", 8700), ("  9,000 ", 9000), ("1,234,567", 1234567), ("0", 0),
    ("", None), ("8.700", None), ("12,34", None), ("1,2345", None), ("-5", None), ("8,7OO", None),
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


@pytest.mark.parametrize("tag,expected", [
    ("[SCRT]", "Secret"), ("[HSCRT]", "Secret"), ("HSCRT", "Secret"),
    ("[LTD]", "Limited"), ("[HLTD]", "Limited"), ("[ltd]", "Limited"),
    ("[ST]", None), ("", None),
])
def test_parse_rarity(tag, expected):
    assert parse_rarity(tag) == expected
