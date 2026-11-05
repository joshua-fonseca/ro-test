import dataclasses
import types

import pytest

cv2 = pytest.importorskip("cv2")
from scanner.logic.config import Config  # noqa: E402
from scanner.reading import screens  # noqa: E402
from scanner.windows import snipe  # noqa: E402

import numpy as np  # noqa: E402

BLACK = np.zeros((743, 1322, 3), np.uint8)  # the "Teleporting..." screen
FAST = Config(teleport_wait_seconds=1, teleport_max_seconds=3, stall_load_seconds=0, snipe_step_timeout=0, snipe_click_pause=0, robux_box_wait_seconds=0)


def shot(n):
    return cv2.imread(f"sniper_arena_scanner_handoff/snipe_{n}.png")


def _flow(monkeypatch, screens_in_order, skin, price):
    frames = iter([BLACK] + [n if not isinstance(n, (int, str)) else shot(n) for n in screens_in_order])  # loading first
    done = []
    monkeypatch.setattr(snipe.screen, "capture", lambda hwnd: next(frames), raising=False)
    monkeypatch.setattr(snipe.screen, "find_roblox", lambda prefer=None: 1, raising=False)
    monkeypatch.setattr(snipe.screen, "foreground_title", lambda: "x", raising=False)
    monkeypatch.setattr(snipe.navigate, "_click", lambda hwnd, p, img, hover=0: done.append(("click", p)) or True)
    monkeypatch.setattr(snipe.controller, "hold_key", lambda hwnd, key, s: done.append(("hold", chr(key))) or True)
    monkeypatch.setattr(snipe.screen, "client_rect", lambda hwnd: (0, 0, 1322, 743), raising=False)
    monkeypatch.setattr(snipe.controller, "scroll", lambda hwnd, x, y, n: done.append(("scroll", n)) or True)
    _clock(monkeypatch)
    return done, lambda: snipe.after_teleport(1, FAST, skin, price, price)


def _clock(monkeypatch):
    """A fake clock: sleep() moves it on, so waits and timeouts run instantly. Returns the list of sleeps."""
    now, sleeps = [0.0], []
    monkeypatch.setattr(snipe, "time", types.SimpleNamespace(
        time=lambda: now[0], sleep=lambda s: (sleeps.append(s), now.__setitem__(0, now[0] + s))))
    return sleeps


def test_the_matched_item_is_bought_and_the_stall_put_up_again(monkeypatch):
    done, run = _flow(monkeypatch, [6, 8, 8, 9, 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6], "Northern Forest Kukri", 15)
    assert run().startswith("Bought")
    assert [d[1] for d in done if d[0] == "hold"] == ["W", "S", "E", "E"]
    clicks = [d[1] for d in done if d[0] == "click"]
    assert len(clicks) == 9 and clicks[0] == screens.find_stall_buy(shot(8), "Northern Forest Kukri", 15, 15)


def test_an_item_that_is_gone_is_not_bought_and_the_rest_goes_on(monkeypatch):
    done, run = _flow(monkeypatch, [6, 8, 8, 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6], "Nya Reaper", 15)  # the extra 8: the scroll that moves nothing
    assert run().startswith("The item was gone")
    assert len([d for d in done if d[0] == "click"]) == 7  # exit, inventory, All, Inspect, Sell, claim, same items


def test_a_button_that_never_shows_stops_everything(monkeypatch):
    done, run = _flow(monkeypatch, [6, 8, 8, 9, 8, 8, 6, 6], "Northern Forest Kukri", 15)  # still in the world: no Inventory screen
    monkeypatch.setattr(screens, "snipe_button", lambda img, name: None if name == "inventory" else (1, 1))
    monkeypatch.setattr(snipe, "GONE_AFTER", set())  # this fake shows every other button always
    with pytest.raises(snipe.Stopped, match="inventory"):
        run()
    assert len([d for d in done if d[0] == "click"]) == 3  # buy, its check, the stall's X; nothing after


def test_the_stall_finder_reads_price_then_name():
    img = shot(8)
    assert screens.find_stall_buy(img, "Viola Canis Knife", 70, 70) != screens.find_stall_buy(img, "Spirit Fiesta [Red] Stiletto", 70, 70)
    assert screens.find_stall_buy(img, "Starlight Fan", 1999, 1999) is not None
    assert screens.find_stall_buy(img, "Starlight Fan", 2000, 2000) is None  # another price: not this listing


def test_each_snipe_button_shows_only_on_its_own_screen():
    on = {n: [k for k in screens.SNIPE if screens.snipe_button(shot(n), k)] for n in range(6, 15)}
    assert on[8] == ["stall_exit"] and on[9] == ["buy_check"] and on[12] == ["sell_on_market"]
    assert on[13] == ["claim_check"] and on[14] == ["same_items_check"] and "inventory_all" not in on[6]


def test_a_stop_keeps_the_screen_it_gave_up_on(monkeypatch):
    _, run = _flow(monkeypatch, [6, 6], "Nya Reaper", 15)  # still in the world: no stall
    with pytest.raises(snipe.Stopped) as e:
        run()
    assert e.value.img is not None and "stall did not open" in str(e.value)


def test_the_flow_waits_for_the_loading_screen_to_come_and_go(monkeypatch):
    import numpy as np
    black = np.zeros((743, 1322, 3), np.uint8)
    results = cv2.imread("sniper_arena_scanner_handoff/live_nya_reaper.png")  # the old list, before the teleport starts
    frames = iter([results, results, black, None, shot(6), shot(6)])  # None: Roblox not in front for a moment
    held = []
    monkeypatch.setattr(snipe.screen, "capture", lambda hwnd: next(frames), raising=False)
    monkeypatch.setattr(snipe.screen, "find_roblox", lambda prefer=None: 1, raising=False)
    monkeypatch.setattr(snipe.screen, "foreground_title", lambda: "x", raising=False)
    monkeypatch.setattr(snipe.navigate, "_click", lambda hwnd, p, img, hover=0: True)
    monkeypatch.setattr(snipe.controller, "hold_key", lambda hwnd, key, s: held.append(key) or True)
    _clock(monkeypatch)
    with pytest.raises(snipe.Stopped, match="stall did not open"):  # arrived in the world (shot 6), but no stall
        snipe.after_teleport(1, FAST, "Nya Reaper", 15, 15)
    assert held  # the keys were only held after the black screen, never over the old list
    frames = iter([results] + [black] * 200)
    held.clear()
    with pytest.raises(snipe.Stopped, match="still loading"):
        snipe.after_teleport(1, FAST, "Nya Reaper", 15, 15)
    assert held == []


def test_a_full_server_is_answered_with_ok_and_reported(monkeypatch):
    done, run = _flow(monkeypatch, ["teleport_failed"], "Nya Reaper", 15)
    with pytest.raises(snipe.TeleportFailed):
        run()
    assert done == [("click", screens.find_teleport_failed_ok(shot("teleport_failed")))]  # Ok only: no keys held


def test_a_stall_still_loading_is_looked_at_again_before_the_item_counts_as_gone(monkeypatch):
    import numpy as np
    loading = shot(8).copy()
    loading[int(0.3 * loading.shape[0]):int(0.7 * loading.shape[0]), int(0.15 * loading.shape[1]):int(0.86 * loading.shape[1])] = 40
    done, _ = _flow(monkeypatch, [6, 8, loading, loading, 8, 9, 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6], "Northern Forest Kukri", 15)
    assert snipe.after_teleport(1, Config(**{**FAST.__dict__, "stall_load_seconds": 5}), "Northern Forest Kukri", 15, 15).startswith("Bought")


def test_the_stall_finder_on_a_live_stall_at_1890_wide():
    img = shot("stall_1890")  # Nya Reaper and Blackhole Glove both at 13,000; Noire Nya Reaper at 12,000
    assert screens.find_stall_buy(img, "Nya Reaper", 13000, 13000) == (574, 397)
    assert screens.find_stall_buy(img, "Noire Nya Reaper", 13000, 13000) is None


def test_a_longer_name_that_ends_the_same_is_not_the_item():
    img = shot("stall_1890")
    assert screens.find_stall_buy(img, "Nya Reaper", 12000, 12000) == (1483, 397)  # #737, not Noire Nya Reaper #694


def test_not_enough_cash_closes_the_robux_box_and_goes_on(monkeypatch):
    done, run = _flow(monkeypatch, [6, 8, 8, "buy_robux", "buy_robux", "buy_robux", 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6],
                      "Northern Forest Kukri", 15)  # the first click on the X is ignored (the box was still sliding in)
    assert run().startswith("Not enough cash")
    clicks = [d[1] for d in done if d[0] == "click"]
    assert clicks[1] == screens.find_robux_prompt_close(shot("buy_robux"))  # its X, far above its Buy button
    assert clicks[1][1] < 0.45 * shot("buy_robux").shape[0] and clicks[2] == clicks[1] and len(clicks) == 10


def test_a_world_screen_before_the_loading_screen_does_not_count_as_arrived(monkeypatch):
    frames = iter([shot(6), shot(6), BLACK] + [shot(n) for n in (6, 8, 8, 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6)])
    # still the old server, then loading, then the new one
    looks = []
    monkeypatch.setattr(snipe.screen, "capture", lambda hwnd: looks.append(1) or next(frames), raising=False)
    monkeypatch.setattr(snipe.screen, "find_roblox", lambda prefer=None: 1, raising=False)
    monkeypatch.setattr(snipe.navigate, "_click", lambda hwnd, p, img, hover=0: True)
    held = []
    monkeypatch.setattr(snipe.controller, "hold_key", lambda hwnd, key, s: held.append(len(looks)) or True)
    monkeypatch.setattr(snipe.screen, "client_rect", lambda hwnd: (0, 0, 1322, 743), raising=False)
    monkeypatch.setattr(snipe.controller, "scroll", lambda hwnd, x, y, n: True)
    _clock(monkeypatch)
    snipe.after_teleport(1, FAST, "Nya Reaper", 15, 15)
    assert held[0] == 4  # the first key went down only after the 4th look: old world, old world, black, new world


def test_a_robux_box_that_will_not_close_stops_everything(monkeypatch):
    done, run = _flow(monkeypatch, [6, 8, 8] + ["buy_robux"] * 6, "Northern Forest Kukri", 15)
    with pytest.raises(snipe.Stopped, match="robux_box_x button was clicked 3 times"):
        run()
    clicks = [d[1] for d in done if d[0] == "click"]
    assert clicks[1:] == [screens.find_robux_prompt_close(shot("buy_robux"))] * 3  # only ever its X


def test_every_click_keeps_the_screen_before_it_in_order(monkeypatch):
    _, _ = _flow(monkeypatch, [6, 8, 8, 9, 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6], "Northern Forest Kukri", 15)
    saved = []
    snipe.after_teleport(1, FAST, "Northern Forest Kukri", 15, 15, lambda name, img: saved.append(name))
    assert saved[:4] == ["snipe_01_arrived", "snipe_stall", "snipe_02_cash_button", "snipe_03_buy_check"]
    assert saved[-1] == "snipe_10_same_items_check"


def test_an_ignored_click_on_the_stall_x_is_sent_again(monkeypatch):
    done, run = _flow(monkeypatch, [6, 8, 8, 8, 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6], "Nya Reaper", 15)
    assert run().startswith("The item was gone")  # the stall was still open after the first click on its X
    exit_point = screens.snipe_button(shot(8), "stall_exit")
    assert [d[1] for d in done if d[0] == "click"][:2] == [exit_point, exit_point]


def test_no_loading_screen_means_the_teleport_did_not_happen(monkeypatch):
    frames = iter([shot(6)] * 100)  # the old screen stays up: no black screen ever
    monkeypatch.setattr(snipe.screen, "capture", lambda hwnd: next(frames), raising=False)
    monkeypatch.setattr(snipe.screen, "find_roblox", lambda prefer=None: 1, raising=False)
    sent = []
    monkeypatch.setattr(snipe.navigate, "_click", lambda *a: sent.append(a) or True)
    monkeypatch.setattr(snipe.controller, "hold_key", lambda *a: sent.append(a) or True)
    _clock(monkeypatch)
    with pytest.raises(snipe.NotTeleported):
        snipe.after_teleport(1, dataclasses.replace(FAST, teleport_max_seconds=60), "Nya Reaper", 15, 15)
    assert sent == []  # nothing pressed or clicked


def test_a_buy_robux_box_that_slides_in_after_the_green_check_is_closed_before_the_stall_x(monkeypatch):
    # seen live: the confirm box, then "You don't have enough Cash" and Roblox's box a moment after the check
    done, run = _flow(monkeypatch, [6, 8, 8, 9, "buy_robux", "buy_robux", 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6],
                      "Northern Forest Kukri", 15)
    assert run().startswith("Not enough cash")
    clicks = [d[1] for d in done if d[0] == "click"]
    x = screens.find_robux_prompt_close(shot("buy_robux"))
    exit_point = screens.snipe_button(shot(8), "stall_exit")
    assert clicks[2:4] == [x, exit_point]  # the box's X (nothing else in it) before the stall's red X


def test_the_cancel_x_of_the_confirm_box_is_found_at_both_sizes():
    big = cv2.imread("sniper_arena_scanner_handoff/snipe_confirm_1900.png")
    x, y = screens.find_buy_cancel(big)
    assert abs(x - 861) < 15 and abs(y - 692) < 15
    assert screens.find_buy_cancel(shot(8)) is None  # the stall itself has no such box
    assert screens.find_buy_cancel(shot(9)) is not None


def test_dry_run_clicks_everything_but_the_green_check(monkeypatch):
    done, _ = _flow(monkeypatch, [6, 8, 8, 9, 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6], "Northern Forest Kukri", 15)
    dry = dataclasses.replace(FAST, dry_run=True)
    result = snipe.after_teleport(1, dry, "Northern Forest Kukri", 15, 15)
    clicks = [d[1] for d in done if d[0] == "click"]
    green = screens.snipe_button(shot(9), "buy_check")
    assert result.startswith("Dry run") and green not in clicks
    assert clicks[1] == screens.find_buy_cancel(shot(9)) and len(clicks) == 10  # the same steps as a real buy


def _stall(n):
    return cv2.imread(f"sniper_arena_scanner_handoff/stall_scroll_{n}.png")


def _scrolling(monkeypatch, screens_in_order, skin, price):
    done, run = _flow(monkeypatch, screens_in_order, skin, price)
    monkeypatch.setattr(snipe.screen, "client_rect", lambda hwnd: (0, 0, 1880, 1065), raising=False)
    return done, run


def test_the_item_further_down_the_stall_is_found_by_scrolling(monkeypatch):
    s1, s2, s3 = _stall(1), _stall(2), _stall(3)  # the three screens of one stall, top to bottom
    done, run = _scrolling(monkeypatch, [6, 8, s1, s2, s2, s2, s3, s3, s3, 9, 8, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6],
                           "Plastic Toy WA 2000", 10)
    assert run().startswith("Bought")
    assert [d for d in done if d[0] == "scroll"] == [("scroll", 3)] * 2
    assert [d[1] for d in done if d[0] == "click"][0] == screens.find_stall_buy(s3, "Plastic Toy WA 2000", 10, 10)


def test_the_scrolling_stops_at_the_end_of_the_stall(monkeypatch):
    s1 = _stall(1)
    done, run = _scrolling(monkeypatch, [6, 8, s1, s1, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6], "Plastic Toy WA 2000", 10)
    assert run().startswith("The item was gone")  # the list did not move after the scroll: nothing further down
    assert [d for d in done if d[0] == "scroll"] == [("scroll", 3)]


def test_the_scrolling_stops_once_everything_in_view_is_cheaper_than_the_item(monkeypatch):
    s2 = _stall(2)  # prices 400 down to 15 only
    done, run = _scrolling(monkeypatch, [6, 8, s2, 8, 10, 10, 11, 11, 12, 13, 13, 14, 14, 6], "Plastic Toy WA 2000", 2000)
    assert run().startswith("The item was gone")
    assert [d for d in done if d[0] == "scroll"] == []  # a stall lists dearest first: it would be above, already passed
