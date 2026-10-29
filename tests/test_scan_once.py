import csv
import glob
from pathlib import Path
from datetime import datetime, timezone

import pytest

cv2 = pytest.importorskip("cv2")
from scanner.logic.models import Target  # noqa: E402
from scan_once import scan_list, scan_visible  # noqa: E402
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
    monkeypatch.chdir(tmp_path)
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
        find_roblox=lambda: 1, is_focused=lambda h: True, capture=lambda h: frame,
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
