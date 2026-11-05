import types
import csv
import glob
from pathlib import Path
from datetime import datetime, timezone

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402
from scanner.logic.models import Target  # noqa: E402
import scan_once  # noqa: E402
from scan_once import scan_list, scan_visible  # noqa: E402
from scanner.reading import screens, vision  # noqa: E402
from scanner.logic.storage import Store  # noqa: E402

NOW = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)


def test_visible_cards_are_matched_cropped_and_logged(tmp_path, monkeypatch):
    files = glob.glob("sniper_arena_scanner_handoff/scroll_starveil_f02.png")
    if not files:
        pytest.skip("fixture screenshots missing")
    img = cv2.imread(files[0])  # complete cards: #ST.744 at 4,000 and #2248 at 8,000
    monkeypatch.chdir(tmp_path)  # crops and CSVs land in the temp folder
    target = Target("Starveil AWP", "Sniper", "Limited", 5000, None, True)
    store = Store(tmp_path / "output")
    store.begin_cycle("c1")
    r = scan_visible(img, target, store, tmp_path / "output", NOW)

    assert (r["read"], r["matches"], r["clipped"]) == (2, 1, 1)
    assert len(r["lines"]) == 1 and r["lines"][0].startswith("[LIMITED] [Starveil AWP] [#ST.744] [4,000] [output/")
    crops = list((tmp_path / "output" / "screenshots" / "matches").glob("*.png"))
    assert len(crops) == 1
    with open(tmp_path / "output" / "listings.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [(x["serial"], x["price"], x["matched"]) for x in rows] == [("744", "4000", "true"), ("Unknown", "8000", "false")]  # over max_price: serial not read


def _frames(files):
    """next_frame over saved frames: each notch moves one frame (the frames are ~150 px apart)."""
    pos = 0

    def next_frame(notches):
        nonlocal pos
        pos = min(max(pos + notches, 0), len(files) - 1)
        return cv2.imread(files[pos])
    return next_frame


def _scan(tmp_path, monkeypatch, files, max_price, max_serial=0):  # serial 0 never shows: no match, keep scrolling
    import scan_once
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scan_once, "STEP", 2)  # these frames are 150 px apart in a 1166-high window: 2 frames = 300 px
    target = Target("Starveil AWP", "Sniper", "Limited", max_price, max_serial, True)
    store = Store(tmp_path / "output")
    store.begin_cycle("c1")
    r = scan_list(cv2.imread(files[0]), _frames(files), target, store, tmp_path / "output", NOW)
    with open(tmp_path / "output" / "listings.csv", encoding="utf-8") as f:
        return r, [int(x["price"]) for x in csv.DictReader(f)]


FRAMES = sorted(str(p.resolve()) for p in Path("sniper_arena_scanner_handoff/scroll_starveil").glob("f*.png"))
needs_frames = pytest.mark.skipif(len(FRAMES) != 29, reason="scroll frames missing")


@needs_frames
def test_full_scroll_reads_every_card_once(tmp_path, monkeypatch):
    r, prices = _scan(tmp_path, monkeypatch, FRAMES, 100_000)
    assert (r["status"], r["sorted"], r["records"]) == ("complete", True, 20)
    # 8,111 is left out on purpose: its price reads disagree
    assert prices == [3000, 4000, 4000] + [8000] * 5 + [8888, 9500, 9500, 9999, 10000] + [12000] * 3 + [17000, 20000, 22000]


@needs_frames
def test_stops_after_two_cards_over_max_price(tmp_path, monkeypatch):
    r, prices = _scan(tmp_path, monkeypatch, FRAMES, 5000)
    assert r["status"] == "stopped_at_price"
    assert prices[:3] == [3000, 4000, 4000] and len(prices) < 8


@needs_frames
def test_stops_at_the_cheapest_match(tmp_path, monkeypatch):
    r, prices = _scan(tmp_path, monkeypatch, FRAMES, 5000, max_serial=None)
    assert (r["status"], r["matches"], prices) == ("stopped_at_first_match", 1, [3000])


@needs_frames
def test_unsorted_list_turns_the_early_stop_off(tmp_path, monkeypatch):
    img = cv2.imread(FRAMES[0])  # 3,000 above 4,000; swap them so the frame shows a lower price below a higher one
    img[347:517], img[542:712] = img[542:712].copy(), img[347:517].copy()
    cv2.imwrite(str(tmp_path / "swapped.png"), img)
    r, prices = _scan(tmp_path, monkeypatch, [str(tmp_path / "swapped.png")], 1000)  # both over: would stop if sorted
    assert (r["status"], r["sorted"], prices) == ("complete", False, [4000, 3000])


@needs_frames
def test_banner_means_look_again_before_scrolling(tmp_path, monkeypatch):
    import scan_once
    banners, calls = iter([True, True]), []
    monkeypatch.setattr(scan_once.vision, "has_banner", lambda img: next(banners, False))
    monkeypatch.setattr(scan_once.time, "sleep", lambda s: None)
    frames = _frames(FRAMES[24:])  # static list end: one card, quick
    monkeypatch.chdir(tmp_path)
    store = Store(tmp_path / "output")
    store.begin_cycle("c1")
    target = Target("Starveil AWP", "Sniper", "Limited", 100_000, 0, True)
    r = scan_list(cv2.imread(FRAMES[24]), lambda n: calls.append(n) or frames(n), target, store, tmp_path, NOW)
    assert r["status"] == "complete"
    assert [n for n in calls if n >= 0][:3] == [0, 0, scan_once.STEP]  # two looks while the banner is up, then the scroll


@needs_frames
def test_live_frames_keeps_scrolling_when_no_card_is_complete(monkeypatch):
    import sys
    import types
    import numpy as np
    import scan_once
    shown = [cv2.imread(FRAMES[0])]  # what the screen shows right now
    scrolls = []
    _fake(monkeypatch, "screen", types.SimpleNamespace(
        client_rect=lambda hwnd: (100, 50, 1920, 1166), capture=lambda hwnd: shown[0]))
    _fake(monkeypatch, "controller", types.SimpleNamespace(
        scroll=lambda hwnd, x, y, n: scrolls.append((x, y, n)) or True))
    monkeypatch.setattr(scan_once.time, "sleep", lambda s: None)
    next_frame = scan_once._live_frames(1)
    next_frame(0)
    shown[0] = np.zeros((1166, 1920, 3), np.uint8)
    next_frame(3)  # the frame it gets back has no complete card (covered)
    shown[0] = cv2.imread(FRAMES[1])
    assert next_frame(3) is not None  # still scrolls, at the same point, instead of reporting focus lost
    assert len(scrolls) == 2 and scrolls[0] == scrolls[1]
    assert scrolls[0][0] < 100 + 1352 - 0.2 * (1352 - 570)  # left of the Teleport area


@needs_frames
def test_scrolls_past_cheap_high_serials_to_the_first_low_serial(tmp_path, monkeypatch):
    r, prices = _scan(tmp_path, monkeypatch, FRAMES, 100_000, max_serial=600)
    # 3,000-8,111 all have serials over 600; the first under it is ST.324 at 8,888 (ST.504 at 9,500 if 324 misreads)
    assert (r["status"], r["matches"]) == ("stopped_at_first_match", 1)
    assert prices[0] == 3000 and prices[-1] in (8888, 9500) and len(prices) >= 8


@needs_frames
def test_two_identical_looking_cards_in_one_frame_are_both_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    img = cv2.imread(FRAMES[0])
    img[542:712] = img[347:517]  # same seller, price and serial picture twice in one frame
    target = Target("Starveil AWP", "Sniper", "Limited", 100_000, 0, True)
    store = Store(tmp_path / "output")
    store.begin_cycle("c1")
    r = scan_visible(img, target, store, tmp_path / "output", NOW, seen=[])
    assert r["read"] == 2  # the second one used to be dropped as a "repeat" of the first


@needs_frames
def test_list_vanishing_while_going_to_the_top_stops_the_wheel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    img, calls = cv2.imread(FRAMES[10]), []
    blank = img * 0  # modal closed: no cards on screen
    target = Target("Starveil AWP", "Sniper", "Limited", 5000, 10, True)
    store = Store(tmp_path / "output")
    store.begin_cycle("c1")
    r = scan_list(img, lambda n: calls.append(n) or blank, target, store, tmp_path / "output", NOW)
    assert (r["status"], calls) == ("list_lost", [-10])  # one look, not 300 wheel steps


def _fake_game(monkeypatch, tmp_path, row="Starveil AWP,Sniper,Limited,5000,,true", nav=None, clicks=None):
    """Run scan_once.main() against fake screen/navigate modules, from a temp folder holding targets.csv."""
    import sys
    import types
    monkeypatch.chdir(tmp_path)
    (tmp_path / "targets.csv").write_text("skin_name,category,rarity,max_price,max_serial,enabled\n" + row + "\n")
    frame = cv2.imread(FRAMES[0])
    _fake(monkeypatch, "screen", types.SimpleNamespace(
        find_roblox=lambda prefer=None: 1, is_focused=lambda h: True, capture=lambda h: frame,
        client_rect=lambda h: (0, 0, 1920, 1166)))
    _fake(monkeypatch, "controller", types.SimpleNamespace(scroll=lambda *a: True))
    clicks = [] if clicks is None else clicks
    _fake(monkeypatch, "navigate", types.SimpleNamespace(
        search_for=lambda *a, **k: nav or (True, ""), open_results=lambda *a, **k: (frame, ""),
        close_results=lambda h: clicks.append("close") or True, back_to_collection=lambda h: True))
    return clicks


def _fake(monkeypatch, name, module):
    """Stand in for scanner.windows.<name> (Windows only) where scan_once imports it."""
    monkeypatch.setattr(f"scanner.windows.{name}", module, raising=False)


def _log_statuses(tmp_path):
    with open(tmp_path / "output" / "scan_log.csv", encoding="utf-8") as f:
        return [r["status"] for r in csv.DictReader(f)]


@needs_frames
def test_main_refuses_rows_without_a_price_or_switched_off(monkeypatch, tmp_path, capsys):
    import scan_once
    _fake_game(monkeypatch, tmp_path, row="Starveil AWP,Sniper,Limited,,,true")
    assert scan_once.main(["Starveil AWP"]) == 2 and "no max_price" in capsys.readouterr().out
    _fake_game(monkeypatch, tmp_path, row="Starveil AWP,Sniper,Limited,5000,,false")
    assert scan_once.main(["Starveil AWP"]) == 2 and "enabled=false" in capsys.readouterr().out
    assert not (tmp_path / "output").exists()  # refused before anything was touched


@needs_frames
def test_failed_navigation_is_logged_and_closes_nothing(monkeypatch, tmp_path):
    import scan_once
    clicks = _fake_game(monkeypatch, tmp_path, nav=(False, "no text cursor in the search box"))
    assert scan_once.main(["Starveil AWP", "--navigate"]) == 1
    assert _log_statuses(tmp_path) == ["navigation_failed"] and clicks == []


@needs_frames
def test_ctrl_c_is_logged_and_sends_no_more_clicks(monkeypatch, tmp_path):
    import scan_once

    def boom(*a, **k):
        raise KeyboardInterrupt
    clicks = _fake_game(monkeypatch, tmp_path)
    monkeypatch.setattr(scan_once, "scan_list", boom)
    assert scan_once.main(["Starveil AWP", "--navigate"]) == 130  # Ctrl+C stops cleanly
    assert _log_statuses(tmp_path) == ["interrupted"] and clicks == []  # it was asked to stop: no closing click


@needs_frames
def test_a_crash_is_logged_and_the_results_are_still_closed(monkeypatch, tmp_path):
    import scan_once

    def boom(*a, **k):
        raise RuntimeError("boom")
    clicks = _fake_game(monkeypatch, tmp_path)
    monkeypatch.setattr(scan_once, "scan_list", boom)
    with pytest.raises(RuntimeError):
        scan_once.main(["Starveil AWP", "--navigate"])
    assert _log_statuses(tmp_path) == ["error"] and clicks == ["close"]


@needs_frames
def test_repeats_stop_at_the_first_failure_and_zero_repeats_is_refused(monkeypatch, tmp_path, capsys):
    import scan_once
    clicks = _fake_game(monkeypatch, tmp_path, nav=(False, "no search box"))
    assert scan_once.main(["Starveil AWP", "--navigate", "--repeat", "3"]) == 1
    assert _log_statuses(tmp_path) == ["navigation_failed"]  # one try, not three
    assert scan_once.main(["Starveil AWP", "--repeat", "0"]) == 2 and "at least 1" in capsys.readouterr().out


@needs_frames
def test_a_repeat_reopens_the_skin_without_searching_again(monkeypatch, tmp_path):
    import sys
    import types
    import scan_once
    _fake_game(monkeypatch, tmp_path)
    calls = []
    frame = cv2.imread(FRAMES[0])
    nav = types.SimpleNamespace(
        search_for=lambda *a, **k: calls.append("search") or (True, ""),
        open_results=lambda *a, **k: calls.append("open") or (frame, ""),
        close_results=lambda h: calls.append("close") or True, back_to_collection=lambda h: True)
    _fake(monkeypatch, "navigate", nav)
    done = {"status": "stopped_at_price", "read": 1, "matches": 0, "records": 5, "frames": 1, "unreadable": 0,
            "sorted": True, "lines": []}
    monkeypatch.setattr(scan_once, "scan_list", lambda *a, **k: done)
    assert scan_once.main(["Starveil AWP", "--navigate", "--repeat", "3"]) == 0
    assert calls == ["search", "open", "close", "open", "close", "open", "close"]  # searched once, then only reopened
    calls.clear()  # a stale tile (the reopen fails) falls back to searching again
    opens = iter([(frame, ""), (None, "no tile")])  # the second run's quick reopen finds no tile
    nav.open_results = lambda *a, **k: calls.append("open") or next(opens, (frame, ""))
    assert scan_once.main(["Starveil AWP", "--navigate", "--repeat", "2"]) == 0
    assert calls == ["search", "open", "close", "open", "search", "open", "close"]  # the failed reopen searches again


@needs_frames
def test_a_freshly_opened_list_is_not_scrolled_up_first(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    img, calls = cv2.imread(FRAMES[0]), []
    target = Target("Starveil AWP", "Sniper", "Limited", 1, None, True)
    store = Store(tmp_path / "output")
    store.begin_cycle("c1")
    scan_list(img, lambda n: calls.append(n) or img, target, store, tmp_path / "output", NOW, at_top=True)
    assert all(n >= 0 for n in calls)  # no wheel-up steps
    calls.clear()
    scan_list(img, lambda n: calls.append(n) or img, target, store, tmp_path / "output", NOW)
    assert calls[0] < 0  # an unknown position goes to the top first


def test_one_notch_shift_is_measured_from_two_frames():
    base = "sniper_arena_scanner_handoff/scroll_starveil/f0{}.png"
    imgs = [cv2.imread(base.format(i)) for i in (0, 1)]
    if any(i is None for i in imgs):
        pytest.skip("fixture screenshots missing")
    import scan_once
    px, err = scan_once._shift(*imgs)
    assert px == 150 and err < 12  # one notch on this 1920x1166 window
    assert scan_once._shift(imgs[0], imgs[0])[1] >= 12  # the list did not move: a bad match, so no calibration


def _notches_asked(monkeypatch, tmp_path, bad_first_scroll=False):
    """Run a calibrating scan_list over the saved frames; return the scroll sizes it asked for (and stop at price)."""
    import scan_once
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scan_once, "_steps", {})
    frames, asked, first = _frames(FRAMES), [], [True]  # first: the next measurement is the bad one

    def next_frame(notches):
        asked.append(notches)
        return frames(notches)
    real = scan_once._shift
    monkeypatch.setattr(scan_once, "_shift", lambda a, b: (300, 50.0) if bad_first_scroll and first.pop() else real(a, b))
    target = Target("Starveil AWP", "Sniper", "Limited", 9000, 0, True)
    store = Store(tmp_path / "output")
    store.begin_cycle("c1")
    scan_list(cv2.imread(FRAMES[0]), next_frame, target, store, tmp_path / "output", NOW, at_top=True, calibrate=True)
    return [n for n in asked if n > 0], scan_once._steps


@needs_frames
def test_the_step_is_chosen_from_the_measured_notch(tmp_path, monkeypatch):
    asked, steps = _notches_asked(monkeypatch, tmp_path)
    assert asked[0] == 1 and set(asked[1:]) == {2}  # 150 px a notch in 1166 px: 2 notches stay under the safe 446 px
    assert list(steps.values()) == [2]


@needs_frames
def test_a_bad_measurement_goes_on_at_two_notches_and_is_not_remembered(tmp_path, monkeypatch):
    asked, steps = _notches_asked(monkeypatch, tmp_path, bad_first_scroll=True)
    assert asked[0] == 1 and set(asked[1:]) == {2} and steps == {}


@needs_frames
def test_a_frame_is_read_while_the_list_scrolls_to_the_next(tmp_path, monkeypatch):
    import scan_once
    import threading
    import time
    monkeypatch.chdir(tmp_path)
    reading, overlaps = threading.Event(), []

    def slow_scan_visible(img, *a, **k):
        reading.set()
        time.sleep(0.3)
        reading.clear()
        return {"read": 0, "matches": 0, "unreadable": 0, "lines": [], "unsorted": False, "over_pair": False}
    monkeypatch.setattr(scan_once, "scan_visible", slow_scan_visible)
    frames = _frames(FRAMES)

    def next_frame(notches):
        if notches > 0:
            time.sleep(0.05)  # the scroll starts a moment after the read was handed over
            overlaps.append(reading.is_set())
        return frames(notches)
    target = Target("Starveil AWP", "Sniper", "Limited", 100_000, 0, True)
    store = Store(tmp_path / "output")
    store.begin_cycle("c1")
    r = scan_list(cv2.imread(FRAMES[0]), next_frame, target, store, tmp_path / "output", NOW, at_top=True, max_steps=3)
    assert r["frames"] == 3 and overlaps and all(overlaps)


@needs_frames
def test_live_frames_returns_none_not_a_crash_when_focus_is_lost_right_after_a_scroll(monkeypatch):
    import types
    import scan_once
    shown = [cv2.imread(FRAMES[0])]
    _fake(monkeypatch, "screen", types.SimpleNamespace(
        client_rect=lambda hwnd: (100, 50, 1920, 1166), capture=lambda hwnd: shown[0]))
    _fake(monkeypatch, "controller", types.SimpleNamespace(scroll=lambda hwnd, x, y, n: True))
    monkeypatch.setattr(scan_once.time, "sleep", lambda s: None)
    next_frame = scan_once._live_frames(1)
    next_frame(0)
    shown[0] = None  # the user clicked another window: the capture comes back empty
    assert next_frame(2) is None


def test_find_teleport_points_at_a_green_button_of_the_given_card():
    img = cv2.imread("sniper_arena_scanner_handoff/live_nya_reaper.png")
    boxes = vision.find_cards(img)
    full = vision.full_card(boxes[1], 0.48 * img.shape[0])
    x, y = screens.find_teleport(img, full)
    assert 1170 < x < 1330 and 520 < y < 585  # inside the second card's Teleport button
    assert screens.find_teleport(img, (100, 100, 800, 270)) is None  # not a card of the list: nothing green there


def test_snipe_scrolls_back_to_the_match_and_finds_the_card_again(tmp_path):
    frames = sorted(glob.glob("sniper_arena_scanner_handoff/scroll_noire_1069/*.png"))
    first, second = cv2.imread(frames[0]), cv2.imread(frames[1])
    asked = []

    def next_frame(n):  # down goes to the next saved frame, back up to the first
        asked.append(n)
        return second if n > 0 else first
    target = Target("Noire Nya Reaper", "Sniper", "Secret", 10_000_000, None, True)  # the first card matches
    r = scan_list(first, next_frame, target, Store(tmp_path / "output"), tmp_path, NOW, at_top=True, snipe=True)
    shown, box, listing = r["match"]
    assert r["status"] == "stopped_at_first_match" and asked[0] > 0 and asked[-1] == -asked[0] and shown is first
    assert screens.find_teleport(first, box) is not None
    r = scan_list(first, next_frame, target, Store(tmp_path / "o2"), tmp_path, NOW, at_top=True)
    assert "match" not in r  # without snipe nothing is kept for a click


def test_the_matched_card_is_found_by_its_picture_or_not_at_all():
    img = cv2.imread("sniper_arena_scanner_handoff/live_nya_reaper.png")
    box = vision.full_card(vision.find_cards(img)[1], 0.48 * img.shape[0])
    shifted = np.roll(img, -40, axis=0)  # the list 40 px further down
    assert scan_once._relocate(img, box, shifted) == (box[0], box[1] - 40, box[2], box[3] - 40)
    assert scan_once._relocate(img, box, cv2.imread("sniper_arena_scanner_handoff/live_crossbow_results.png")) is None


def test_teleport_is_clicked_only_while_the_list_looks_as_it_did(monkeypatch):
    from scanner.windows import navigate, screen
    img = cv2.imread("sniper_arena_scanner_handoff/live_nya_reaper.png")
    box = vision.full_card(vision.find_cards(img)[1], 0.48 * img.shape[0])
    clicks = []
    monkeypatch.setattr(screen, "capture", lambda hwnd: img, raising=False)
    monkeypatch.setattr(navigate, "_click", lambda hwnd, p, im, hover=0: clicks.append(p) or True)
    assert scan_once._teleport(1, img, box) == (True, "") and len(clicks) == 1
    moved = img[:, ::-1].copy()  # a different picture: the list is not what was read
    monkeypatch.setattr(screen, "capture", lambda hwnd: moved, raising=False)
    ok, why = scan_once._teleport(1, img, box)
    assert not ok and len(clicks) == 1


def test_a_full_server_is_tried_again_on_the_same_listing_then_the_next_skin(monkeypatch, tmp_path):
    from scanner.logic.config import Config
    from scanner.windows import snipe as flow
    tries, still_listed = [], iter([True, True, False])
    monkeypatch.setattr(scan_once, "_teleport", lambda hwnd, shown, card: (next(still_listed), "the list moved"))

    def full(*a):
        tries.append(1)
        raise flow.TeleportFailed("the server is full")
    monkeypatch.setattr(flow, "after_teleport", full)
    listing = types.SimpleNamespace(price=100, price_approx=False)
    target = Target("Nya Reaper", "Knife", "Secret", 999, 2, True)
    assert not scan_once._snipe(1, Config(teleport_retries=3), tmp_path, target, None, None, listing)
    assert len(tries) == 2  # tried twice; on the third look the listing was gone: next skin
    still_listed = iter([True] * 9)
    monkeypatch.setattr(scan_once, "_teleport", lambda hwnd, shown, card: (next(still_listed), ""))
    tries.clear()
    assert not scan_once._snipe(1, Config(teleport_retries=3), tmp_path, target, None, None, listing)
    assert len(tries) == 4  # the first try and 3 retries, then next skin


def test_the_card_is_found_again_though_its_rainbow_picture_and_seller_name_changed():
    # seen live: the picture animates and "[Loading...]" became a name, so a whole-card match scored only 0.93
    before = cv2.imread("sniper_arena_scanner_handoff/relocate_before.png")
    after = cv2.imread("sniper_arena_scanner_handoff/relocate_after.png")
    for card in vision.find_cards(before)[:3]:
        assert scan_once._relocate(before, card, after) == tuple(int(v) for v in card)


def test_a_neighbouring_card_is_never_taken_for_the_matched_one():
    before = cv2.imread("sniper_arena_scanner_handoff/relocate_before.png")
    first, second = vision.find_cards(before)[:2]
    shifted = np.roll(before, int(first[1] - second[1]), axis=0)  # card 2 now sits where card 1 was
    assert scan_once._relocate(before, first, shifted) is None  # same layout, other price: a card away is refused


def test_a_flat_colour_frame_is_never_taken_for_the_matched_card():
    before = cv2.imread("sniper_arena_scanner_handoff/relocate_before.png")
    card = vision.find_cards(before)[0]
    flat = np.full_like(before, 40)  # no texture at all: the match score is not a number
    assert scan_once._relocate(before, card, flat) is None


@needs_frames
def test_a_skin_nobody_sells_is_skipped_at_once_and_is_not_a_failure(monkeypatch, tmp_path, capsys):
    import scan_once
    empty = cv2.imread("sniper_arena_scanner_handoff/live_no_listings.png")  # before _fake_game changes the folder
    clicks = _fake_game(monkeypatch, tmp_path)
    import scanner.windows as w
    monkeypatch.setattr(w.navigate, "open_results", lambda *a, **k: (empty, ""))
    assert scan_once.main(["Starveil AWP", "--navigate"]) == 0
    assert "No listings found" in capsys.readouterr().out
    assert _log_statuses(tmp_path) == ["no_listings"] and clicks == ["close"]  # the box is closed, nothing scrolled
