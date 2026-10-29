import glob

import pytest

cv2 = pytest.importorskip("cv2")
from scanner.reading import vision  # noqa: E402

FIX = "sniper_arena_scanner_handoff/*{}.png"


def load_path(path):
    img = cv2.imread(path)
    if img is None:
        pytest.skip("fixture screenshots missing")
    return img


def load(stamp):
    files = glob.glob(FIX.format(stamp))
    if not files:
        pytest.skip("fixture screenshots missing")
    return cv2.imread(files[0])


# stamp: (records, [(price, (serial, stattrak)) for each complete card]); None = card must give no listing
CASES = {
    "163556": (6, [(15000, (11, True)), (20000, (18, False))]),
    "155835": (7, [(9949, (240, True)), (12200, (107, False))]),
    "125355": (6, [(8700, (610, False)), (8998, (291, True))]),
    "nya_reaper": (17, [(9500, (668, False)), (9500, (575, False))]),  # pink blade touches the ']'
    "starveil_f02": (20, [(4000, (744, True)), (8000, (2248, False))]),
    # Ryu's price (8,111) read 8,171 twice and 8,111 once: disagreeing reads must give no listing.
    "starveil_f10": (20, [None, (8888, (324, True))]),
    "starveil_f20": (20, [(12000, (2503, False)), (17000, (1644, False))]),
    # Live 1898x1068: Rope's 7,000 reads '7,000', '7,000', '' and must still give a price.
    "live_empty_price_read": (19, [(5500, (2195, False)), (7000, (740, True))]),
    # Noir Nya Reaper: rainbow thumbnail border, Japanese seller name, 'k' prices
    "live_noir_012": (15, [(13500, (73, True)), (13900, (141, True))]),
    "live_noir_019": (15, [(30000, (25, True)), (85000, (5, False))]),
}


# Serials that read correctly today; losing one is a regression.
READABLE = {(240, True), (610, False), (291, True), (668, False), (575, False), (744, True), (2248, False),
            (2503, False), (1644, False), (73, True), (5, False)}


@pytest.mark.parametrize("stamp", CASES)
def test_cards(stamp):
    img = load(stamp)
    records, expected = CASES[stamp]
    assert vision.read_record_count(img) == records
    cards = vision.read_cards(img)
    full = [c for c in cards if c.complete]
    assert len(full) == len(expected)
    assert all(c.listing is None for c in cards if not c.complete)
    for c, want in zip(full, expected):
        if want is None:
            assert c.listing is None
            continue
        price, serial = want
        assert c.listing.price == price
        # A wrong serial is worse than none: unreadable is allowed, wrong is not.
        assert c.listing.stattrak == serial[1]  # from the text colour, even when the digits don't read
        if c.listing.serial is not None:
            assert (c.listing.serial, c.listing.stattrak) == serial
        elif c.listing.serial_digits is not None:  # display-only length label must not be wrong either
            assert c.listing.serial_digits == len(str(serial[0]))
        elif serial in READABLE:
            pytest.fail(f"serial {serial} used to read and is now unreadable")


def test_clipped_card_has_no_serial():
    img = load("163556")
    last = vision.read_cards(img)[-1]
    assert not last.complete and last.listing is None


def test_no_cards_on_blank_image():
    import numpy as np
    assert vision.find_cards(np.zeros((300, 500, 3), np.uint8)) == []


def test_a_loading_seller_does_not_matter():
    files = glob.glob("sniper_arena_scanner_handoff/loading_*.png")
    if not files:
        pytest.skip("fixture screenshots missing")
    cards = [c for c in vision.read_cards(cv2.imread(files[0])) if c.complete]
    assert any(c.listing for c in cards)  # the seller is not read, so [Loading...] no longer blocks a card


def test_a_card_over_max_price_skips_its_serial():
    img = load("125355")
    box = next(b for b in vision.find_cards(img) if vision.is_complete(b))
    full = vision.read_card(img, box).listing
    over = vision.read_card(img, box, max_price=full.price - 1).listing
    assert over.price == full.price and over.serial is None  # never read: it cannot match


def test_small_window_leaves_serials_unreadable():
    # At 1200 wide all three OCR reads once agreed on '#262' for '#282'.
    img = load("125355")
    small = cv2.resize(img, (1200, round(img.shape[0] * 1200 / img.shape[1])), interpolation=cv2.INTER_AREA)
    listings = [c.listing for c in vision.read_cards(small) if c.listing]
    assert [x.serial for x in listings] == [None, None]
    assert [x.stattrak for x in listings] == [False, True]  # colour still tells #610 from #ST.291


def test_text_and_colour_disagreeing_keeps_neither(monkeypatch):
    img = load("125355")
    box = [b for b in vision.find_cards(img) if vision.is_complete(b)][0]  # #610, plain, reads exactly
    assert vision.read_card(img, box).listing.serial == 610
    monkeypatch.setattr(vision, "read_stattrak", lambda area: True)  # colour now claims StatTrak
    listing = vision.read_card(img, box).listing
    assert (listing.serial, listing.stattrak, listing.serial_digits) == (None, None, None)


def test_announcement_banner_is_detected():
    assert vision.has_banner(load("live_banner"))  # "X bought Y" band across the top of the list
    assert not vision.has_banner(load("nya_reaper"))  # same list, no banner


def test_a_card_cut_off_a_little_is_read_but_one_cut_off_a_lot_is_not():
    base = "sniper_arena_scanner_handoff/scroll_noire_1069/"
    third = vision.find_cards(load_path(base + "001.png"))[-1]  # the third card, cut off at the bottom by 8%
    img1, img2 = load_path(base + "001.png"), load_path(base + "002.png")
    cut = vision.read_card(img1, third, list_mid=516, max_price=10**9)
    whole = vision.read_card(img2, vision.find_cards(img2)[1], list_mid=516, max_price=10**9)
    assert cut.complete and cut.listing and (cut.listing.price, cut.listing.serial) == (9999, 628)
    assert (whole.listing.price, whole.listing.serial) == (9999, 628)  # the same card, whole, one step later
    top = vision.find_cards(img2)[0]  # cut off at the top by 36%: the price is gone
    assert not vision.read_card(img2, top, list_mid=516).complete


def test_full_card_puts_back_the_cut_off_part():
    box = (100, 248, 872, 356)  # a card 108 px tall at the top of the list: cut at the top
    assert vision.full_card(box, 516) == (100, 356 - 169, 872, 356)
    box = (100, 687, 872, 785)  # in the bottom half: cut at the bottom
    assert vision.full_card(box, 516) == (100, 687, 872, 687 + 169)
    whole = (100, 301, 872, 470)
    assert vision.full_card(whole, 516) == whole
    assert vision.is_readable((100, 630, 872, 785), (100, 630, 872, 799)) and not vision.is_readable(box, (100, 687, 872, 856))


def test_a_cut_off_card_with_no_readable_serial_is_left_for_the_next_frame(monkeypatch):
    base = "sniper_arena_scanner_handoff/scroll_noire_1069/"
    img = load_path(base + "001.png")
    third = vision.find_cards(img)[-1]  # cut off at the bottom
    monkeypatch.setattr(vision, "read_serial", lambda area: (None, None))
    card = vision.read_card(img, third, list_mid=516, max_price=10**9)
    assert card.complete and card.wait and card.listing is None
    whole = vision.find_cards(img)[0]  # a whole card with the same failure is still kept (serial Unknown)
    assert vision.read_card(img, whole, list_mid=516, max_price=10**9).listing is not None


def test_a_price_read_with_a_dropped_digit_still_reads_when_the_full_text_is_read_three_times():
    img = load_path("sniper_arena_scanner_handoff/live_nya_11k.png")  # 11k read as 11k, 1k, 1k, 11k, 11k, 1k
    box = vision.find_cards(img)[1]
    assert vision.read_price(vision._sub(img, box, vision.PRICE_BOX)) == (11000, True)


def test_reads_that_disagree_for_real_are_still_refused(monkeypatch):
    for texts in (["7,000", "7,000", "7,000", "9,000"], ["7,000", "7,000", "1,000"], ["11k", "11k"]):
        monkeypatch.setattr(vision, "_ocr", lambda *a, texts=texts, **k: list(texts))
        assert vision.read_price(None) is None
