import glob

import pytest

cv2 = pytest.importorskip("cv2")
import vision  # noqa: E402

FIX = "sniper_arena_scanner_handoff/*{}.png"


def load(stamp):
    files = glob.glob(FIX.format(stamp))
    if not files:
        pytest.skip("fixture screenshots missing")
    return cv2.imread(files[0])


# stamp: (records, [(price, serial, stattrak) for each complete card]); serial None = may be unreadable
CASES = {
    "163556": (6, [(15000, (11, True)), (20000, (18, False))]),
    "155835": (7, [(9949, (240, True)), (12200, (107, False))]),
    "125355": (6, [(8700, (610, False)), (8998, (291, True))]),
    "nya_reaper": (17, [(9500, (668, False)), (9500, (575, False))]),  # pink blade touches the ']'
}


# Serials that read correctly today; losing one is a regression.
READABLE = {(11, True), (18, False), (240, True), (107, False), (610, False), (291, True), (668, False), (575, False)}


@pytest.mark.parametrize("stamp", CASES)
def test_cards(stamp):
    img = load(stamp)
    records, expected = CASES[stamp]
    assert vision.read_record_count(img) == records
    cards = vision.read_cards(img)
    full = [c for c in cards if c.complete]
    assert len(full) == len(expected)
    assert all(c.listing is None for c in cards if not c.complete)
    for c, (price, serial) in zip(full, expected):
        assert c.listing.price == price
        # A wrong serial is worse than none: unreadable is allowed, wrong is not.
        if c.listing.serial is not None:
            assert (c.listing.serial, c.listing.stattrak) == serial
        elif serial in READABLE:
            pytest.fail(f"serial {serial} used to read and is now unreadable")


def test_clipped_card_has_no_serial():
    img = load("163556")
    last = vision.read_cards(img)[-1]
    assert not last.complete and last.listing is None


def test_no_cards_on_blank_image():
    import numpy as np
    assert vision.find_cards(np.zeros((300, 500, 3), np.uint8)) == []


def test_loading_seller_is_not_recorded():
    files = glob.glob("sniper_arena_scanner_handoff/loading_*.png")
    if not files:
        pytest.skip("fixture screenshots missing")
    cards = [c for c in vision.read_cards(cv2.imread(files[0])) if c.complete]
    assert any(c.loading for c in cards)
    assert all(c.listing is None for c in cards if c.loading)


def test_small_window_leaves_serials_unreadable():
    # At 1200 wide all three OCR reads once agreed on '#262' for '#282'.
    img = load("125355")
    small = cv2.resize(img, (1200, round(img.shape[0] * 1200 / img.shape[1])), interpolation=cv2.INTER_AREA)
    listings = [c.listing for c in vision.read_cards(small) if c.listing]
    assert listings and all(x.serial is None and x.stattrak is None for x in listings)
