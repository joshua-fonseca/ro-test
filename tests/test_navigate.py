import json
import types

import cv2
import numpy as np
import pytest

from scanner.reading import layout, screens
from scanner.windows import navigate


class World:
    """A fake game: clicks move it from screen to screen; the finders and the clock are scripted around it."""

    def __init__(self, monkeypatch, state="collection", tile=True, label_ok=True, caret=True, banner_for=0,
                 box_text=False, stuck_text=False, paste_fails=False, size=(1920, 1166)):
        self.state, self.tile, self.label_ok, self.caret = state, tile, label_ok, caret
        self.box_text, self.stuck_text, self.backspaces = box_text, stuck_text, 0  # old text in the search box
        self.banner_for = banner_for  # the first N screenshots are covered by an in-game banner ("unknown")
        self.size = size
        layout._agreed.clear()
        self.clicks, self.typed, self.pasted, self.now = [], [], [], 0.0
        self.paste_fails = paste_fails
        m = monkeypatch
        m.setattr(navigate, "time", types.SimpleNamespace(time=lambda: self.now, sleep=self._sleep))
        blank = np.zeros((size[1], size[0], 3), np.uint8)
        m.setattr(navigate.screen, "capture", lambda hwnd: blank, raising=False)
        m.setattr(navigate.screen, "client_rect", lambda hwnd: (10, 20, *self.size), raising=False)
        m.setattr(navigate.screens, "classify", self._classify)
        m.setattr(navigate.screens, "find_search_box", lambda img: (50, 60))
        m.setattr(navigate.screens, "find_category_button", lambda img, c: (70, 80) if c == "Knife" else None)
        m.setattr(navigate.screens, "search_caret", lambda img: self.caret)
        m.setattr(navigate.screens, "search_has_text", lambda img: self.box_text)
        m.setattr(navigate.controller, "clear_box", self._backspace)
        m.setattr(navigate.screens, "find_first_tile", lambda img: (100, 200) if self.tile else None)
        m.setattr(navigate.screens, "options_is_for", lambda img, name: self.label_ok)
        m.setattr(navigate.screens, "collected_total", lambda img: None)
        m.setattr(navigate.vision, "has_banner", lambda img: False)
        m.setattr(navigate.screens, "find_check_button", lambda img: (300, 400) if self.state == "options" else None)
        m.setattr(navigate.screens, "find_options_cancel", lambda img: (400, 500) if self.state == "options" else None)
        m.setattr(navigate.screens, "find_close_button", lambda img: (500, 600) if self.state == "results" else None)
        m.setattr(navigate.controller, "click", self._click)
        m.setattr(navigate.controller, "type_text", lambda hwnd, text: self.typed.append(text) or True)
        m.setattr(navigate.controller, "paste_text", self._paste)

    def _classify(self, img):
        if self.banner_for > 0:
            self.banner_for -= 1
            return "unknown"
        return self.state

    def _paste(self, hwnd, text):
        self.pasted.append(text)
        self.box_text = not self.paste_fails  # the pasted name shows in the box
        return True

    def _backspace(self, hwnd, times):
        self.backspaces += times
        self.box_text = self.stuck_text
        return True

    def _sleep(self, s):
        self.now += s

    def _click(self, hwnd, x, y):
        self.clicks.append((x, y))
        self.state = {(110, 220): "options", (286, 220): "options", (310, 420): "results", (510, 620): "collection",
                                           (410, 520): "collection"}.get((x, y), self.state)
        return True


def test_a_paste_needs_no_cursor_but_typing_does(monkeypatch):
    w = World(monkeypatch, caret=False)
    assert navigate.search_for(1, "Starveil AWP") == (True, "") and w.pasted == ["Starveil AWP"] and w.typed == []
    w = World(monkeypatch, caret=False, paste_fails=True)  # the paste did not show: nothing is typed over it
    assert navigate.search_for(1, "Starveil AWP") == (False, "the pasted name did not show in the search box") and w.typed == []


def test_open_results_clicks_tile_then_check(monkeypatch):
    w = World(monkeypatch)
    img, why = navigate.open_results(1, "Starveil AWP")
    assert img is not None and why == "" and w.clicks == [(110, 220), (310, 420)]  # screen offset (10, 20) added


def test_no_tile_means_no_click(monkeypatch):
    w = World(monkeypatch, tile=False)
    assert navigate.open_results(1, "Starveil AWP")[0] is None and w.clicks == []


def test_results_of_another_skin_are_closed_and_not_scanned(monkeypatch):
    w = World(monkeypatch, label_ok=False)
    img, why = navigate.open_results(1, "Nya Reaper")
    assert img is None and "not for" in why
    assert w.clicks == [(110, 220), (310, 420), (510, 620)] and w.state == "collection"  # tile, check, then close


def test_stops_when_search_options_never_opens(monkeypatch):
    w = World(monkeypatch)
    monkeypatch.setattr(navigate.controller, "click", lambda hwnd, x, y: w.clicks.append((x, y)) or True)  # screen never changes
    img, why = navigate.open_results(1, "Starveil AWP")
    assert img is None and "did not open" in why and len(w.clicks) == 1


def test_close_results_clicks_the_x_and_waits_for_the_collection(monkeypatch):
    w = World(monkeypatch, state="results")
    assert navigate.close_results(1) and w.clicks == [(510, 620)]
    w = World(monkeypatch, state="collection")  # nothing to close: no click
    assert not navigate.close_results(1) and w.clicks == []


def test_a_banner_over_the_screen_is_waited_out_before_closing(monkeypatch):
    w = World(monkeypatch, state="results", banner_for=6)  # ~6 captures covered, 0.4 s apart: a few seconds
    assert navigate.close_results(1) and w.clicks == [(510, 620)]


def test_no_click_if_the_window_changed_size_since_the_screenshot(monkeypatch):
    w = World(monkeypatch)
    real_find = navigate.screens.find_first_tile

    def resized_during_ocr(img):  # the user drags the window while the tile is being read
        w.size = (1600, 900)
        return real_find(img)
    monkeypatch.setattr(navigate.screens, "find_first_tile", resized_during_ocr)
    img, why = navigate.open_results(1, "Starveil AWP")
    assert img is None and "window changed size" in why and w.clicks == []


def test_old_search_text_is_cleared_before_typing(monkeypatch):
    w = World(monkeypatch, box_text=True)
    assert navigate.search_for(1, "Nya Reaper") == (True, "")
    assert w.backspaces == 40 and w.pasted == ["Nya Reaper"]  # cleared first, then pasted
    w = World(monkeypatch)  # an empty box is left alone
    navigate.search_for(1, "Nya Reaper")
    assert w.backspaces == 0


def test_nothing_is_typed_if_the_old_text_will_not_clear(monkeypatch):
    w = World(monkeypatch, box_text=True, stuck_text=True)
    assert navigate.search_for(1, "Nya Reaper") == (False, "could not clear the search box") and w.typed == []


def test_category_is_clicked_before_the_search_box(monkeypatch):
    w = World(monkeypatch)
    assert navigate.search_for(1, "Nya Reaper", category="Knife") == (True, "")
    assert w.clicks == [(80, 100), (60, 80)] and w.pasted == ["Nya Reaper"]


def test_unknown_category_stops_before_any_click(monkeypatch):
    w = World(monkeypatch)
    ok, why = navigate.search_for(1, "Nya Reaper", category="Charm")
    assert not ok and "button" in why and w.clicks == [] and w.typed == []




def test_a_16_9_window_asks_the_finder_for_the_check_when_no_green_button_is_at_the_fixed_spot(monkeypatch):
    w = World(monkeypatch, size=(1900, 1069))
    asked = []
    monkeypatch.setattr(navigate.screens, "find_first_tile", lambda img: asked.append(1) or (614, 274))
    monkeypatch.setattr(navigate.screens, "find_check_button", lambda img: asked.append(2) or (1036, 725))
    steps = iter(["options", "results"] * 2)

    def click(hwnd, x, y):  # whatever the point, the game moves on one screen
        w.clicks.append((x, y))
        w.state = next(steps)
        return True
    monkeypatch.setattr(navigate.controller, "click", click)
    assert navigate.open_results(1, "Nya Reaper")[0] is not None
    first = w.clicks[:]
    w.state = "collection"
    assert navigate.open_results(1, "Nya Reaper")[0] is not None
    assert asked == [2, 2]  # this fake screen has no green at the fixed spot, so the finder is asked each time; the first tile never needs one
    assert w.clicks[2:] == first and first[0] == (10 + 614, 20 + 274) and first[1] == (10 + 1036, 20 + 725)


def test_the_first_tile_is_its_fixed_slot_even_when_the_finder_points_at_the_second_tile(monkeypatch):
    w = World(monkeypatch, size=(1900, 1069))
    monkeypatch.setattr(navigate.screens, "find_first_tile", lambda img: (787, 275))  # seen live: the pale rainbow tile 1 is missed
    navigate.open_results(1, "Nya Reaper")
    assert w.clicks[0] == (10 + 614, 20 + 274)


def test_a_late_paste_is_not_typed_over(monkeypatch):
    w = World(monkeypatch, paste_fails=True)  # paste was sent but the name never shows
    ok, why = navigate.search_for(1, "Nya Reaper")
    assert not ok and "did not show" in why and w.typed == []  # typing now could double the name


def test_typing_is_used_only_when_nothing_was_pasted(monkeypatch):
    w = World(monkeypatch)
    monkeypatch.setattr(navigate.controller, "paste_text", lambda hwnd, text: False)  # clipboard busy
    assert navigate.search_for(1, "Nya Reaper") == (True, "") and w.typed == ["Nya Reaper"]


def test_back_to_collection_cancels_or_closes_whichever_is_open(monkeypatch):
    w = World(monkeypatch, state="options")
    assert navigate.back_to_collection(1) and w.clicks == [(410, 520)] and w.state == "collection"
    assert navigate.back_to_collection(1) and len(w.clicks) == 1  # already there: nothing clicked
    w = World(monkeypatch, state="results")
    assert navigate.back_to_collection(1) and w.clicks == [(510, 620)]


def test_a_failed_cleanup_after_the_wrong_skin_is_reported(monkeypatch):
    w = World(monkeypatch, label_ok=False)
    monkeypatch.setattr(navigate.screens, "find_close_button", lambda img: None)  # the close button is not found
    img, why = navigate.open_results(1, "Nya Reaper")
    assert img is None and "not for" in why and "could not get back" in why
    assert w.state == "results"  # nothing more was clicked on a screen it could not handle


def test_the_rarity_filter_is_clicked_when_off_and_left_alone_when_on(monkeypatch):
    w = World(monkeypatch, size=(1920, 1080))
    on = [False]
    monkeypatch.setattr(navigate.screens, "rarity_is_on", lambda img, r: on[0])
    real_click = w._click
    monkeypatch.setattr(navigate.controller, "click", lambda h, x, y: on.__setitem__(0, True) or real_click(h, x, y))
    assert navigate.search_for(1, "Starry Flip Knife", rarity="Limited") == (True, "")
    assert w.clicks[0] == (10 + int(0.2034 * 1920), 20 + int(0.3807 * 1080))  # the Limited button, then the search box
    n = len(w.clicks)
    assert navigate.search_for(1, "Starry Flip Knife", rarity="Limited") == (True, "") and len(w.clicks) == n + 1  # box only


def test_a_rarity_filter_that_never_lights_up_stops_the_search(monkeypatch):
    w = World(monkeypatch, size=(1920, 1080))
    monkeypatch.setattr(navigate.screens, "rarity_is_on", lambda img, r: False)
    saved = []
    ok, why = navigate.search_for(1, "Starry Flip Knife", lambda name, img: saved.append(name), rarity="Secret")
    assert not ok and "Secret filter did not light up" in why and saved == ["rarity_not_on"] and w.pasted == []


def test_the_rarity_is_looked_at_only_after_the_category_changed_the_grid(monkeypatch):
    w = World(monkeypatch, size=(1920, 1080))
    looks = []
    monkeypatch.setattr(navigate, "_grid_change", lambda a, b: looks.append(1) or (0 if len(looks) < 4 else 9))
    monkeypatch.setattr(navigate.screens, "rarity_is_on", lambda img, r: True)
    assert navigate.search_for(1, "Nya Reaper", category="Knife", rarity="Limited") == (True, "")
    assert len(looks) >= 4 and len(w.clicks) == 2  # waited for the change; the filter was already on: no click


def test_a_window_that_is_not_16_9_searches_unfiltered(monkeypatch):
    w = World(monkeypatch, size=(1000, 1000))
    assert navigate.search_for(1, "Nya Reaper", rarity="Limited") == (True, "") and w.clicks == [(60, 80)]


def test_nothing_is_typed_without_a_cursor_when_the_paste_was_not_possible(monkeypatch):
    w = World(monkeypatch, caret=False)
    monkeypatch.setattr(navigate.controller, "paste_text", lambda hwnd, text: False)
    assert navigate.search_for(1, "Nya Reaper") == (False, "no text cursor in the search box; typed nothing") and w.typed == []


def test_filters_that_are_already_on_are_not_clicked_again(monkeypatch):
    w = World(monkeypatch, size=(1920, 1080))
    monkeypatch.setattr(navigate.screens, "rarity_is_on", lambda img, r: True)
    assert navigate.search_for(1, "Nya Reaper", category="Knife", rarity="Limited", filters_on=True) == (True, "")
    assert w.clicks == [(10 + 623, 20 + 959)]  # only the search box, at its fixed slot


def test_filters_on_still_checks_the_rarity_and_clicks_it_if_the_game_reset_it(monkeypatch):
    w = World(monkeypatch, size=(1920, 1080))
    lit = [False]
    monkeypatch.setattr(navigate.screens, "rarity_is_on", lambda img, r: lit[0])
    real_click = w._click
    monkeypatch.setattr(navigate.controller, "click", lambda h, x, y: lit.__setitem__(0, True) or real_click(h, x, y))
    assert navigate.search_for(1, "Nya Reaper", category="Knife", rarity="Limited", filters_on=True) == (True, "")
    assert len(w.clicks) == 2  # the Limited button (it was off), then the search box; no category click


def test_a_paste_that_did_not_land_is_clicked_and_pasted_once_more(monkeypatch):
    w = World(monkeypatch)
    calls = []

    def paste(hwnd, text):  # the first paste hits an unfocused box and does nothing
        calls.append(text)
        w.box_text = len(calls) > 1
        return True
    monkeypatch.setattr(navigate.controller, "paste_text", paste)
    assert navigate.search_for(1, "Nya Reaper") == (True, "")
    assert calls == ["Nya Reaper"] * 2 and w.typed == []
    assert w.clicks.count(w.clicks[-1]) == 2  # the search box (the last click) was clicked a second time


def test_the_search_box_is_not_clicked_on_a_screen_that_is_not_the_collection(monkeypatch):
    w = World(monkeypatch)
    looks = iter(["collection", "options"])  # a modal opened after the screen was first seen
    monkeypatch.setattr(navigate.screens, "classify", lambda img: next(looks))
    ok, why = navigate.search_for(1, "Nya Reaper")
    assert not ok and why.startswith("not on the collection screen") and w.pasted == [] and w.clicks == []


def test_the_no_listings_box_is_closed_at_its_own_x_not_the_lists_fixed_point():
    import cv2
    img = cv2.imread("sniper_arena_scanner_handoff/live_no_listings.png")
    x, y = navigate._close_point(img)
    assert (x, y) == navigate.screens.find_close_button(img) and y < 870  # the fixed point (875) is that button's very edge
    assert navigate.layout.fixed(img, "close_results")[1] >= 870


def test_a_skin_that_is_the_second_variant_is_opened_from_there_and_remembered(monkeypatch):
    monkeypatch.setattr(navigate, "_slot", {})
    w = World(monkeypatch, label_ok=False)
    monkeypatch.setattr(navigate, "_has_tile", lambda img, point: True)
    monkeypatch.setattr(navigate.screens, "options_is_for", lambda img, name: w.clicks[-2] == (286, 220))  # tile 2 only
    img, why = navigate.open_results(1, "Nya Machete")  # seen live: "Nya Machete [Rainbow]" is tile 1, "Nya Machete" tile 2
    assert img is not None and why == "" and navigate._slot == {"Nya Machete": 1}
    assert w.clicks == [(110, 220), (310, 420), (510, 620), (286, 220), (310, 420)]  # wrong tile, close, right tile
    w.clicks.clear()
    w.state = "collection"
    assert navigate.open_results(1, "Nya Machete")[0] is not None and w.clicks == [(286, 220), (310, 420)]  # straight there


def test_no_tile_in_the_next_slot_ends_the_search_without_more_clicks(monkeypatch):
    monkeypatch.setattr(navigate, "_slot", {})
    w = World(monkeypatch, label_ok=False)
    monkeypatch.setattr(navigate, "_has_tile", lambda img, point: False)  # one tile only, and it is the wrong one
    monkeypatch.setattr(navigate.screens, "search_reads", lambda img, name: False)  # the box holds something else
    img, why = navigate.open_results(1, "Nya Reaper")
    assert img is None and "was not for" in why and len(w.clicks) == 3  # tile, check, close; no second tile tried


def test_one_tile_under_a_search_box_that_reads_the_skin_needs_no_label(monkeypatch):
    monkeypatch.setattr(navigate, "_slot", {})
    w = World(monkeypatch, label_ok=False)  # the label never reads (white on bright rainbow)
    monkeypatch.setattr(navigate, "_has_tile", lambda img, point: False)  # no second tile
    monkeypatch.setattr(navigate.screens, "search_reads", lambda img, name: name == "Prismatica Frostbite ShadowDaggers")
    monkeypatch.setattr(navigate.screens, "collected_total", lambda img: 1)
    monkeypatch.setattr(navigate, "_settled", lambda hwnd, img: img)
    img, why = navigate.open_results(1, "Prismatica Frostbite ShadowDaggers")
    assert img is not None and why == "" and len(w.clicks) == 2  # tile and check, nothing closed



@pytest.mark.parametrize("count, settled_tiles, opened", [(1, 1, True), (6, 1, False), (1, 2, False)])
def test_one_tile_is_believed_only_on_a_settled_grid_that_the_game_counts_as_one(monkeypatch, count, settled_tiles, opened):
    monkeypatch.setattr(navigate, "_slot", {})
    w = World(monkeypatch, label_ok=False)  # the label never reads
    tiles = {"n": 1}
    monkeypatch.setattr(navigate, "_has_tile", lambda img, point: point[0] < 150 or tiles["n"] > 1)
    def settled(hwnd, img):  # the grid finishes drawing
        tiles["n"] = settled_tiles
        return img
    monkeypatch.setattr(navigate, "_settled", settled)
    monkeypatch.setattr(navigate.screens, "search_reads", lambda img, name: True)
    monkeypatch.setattr(navigate.screens, "collected_total", lambda img: count)
    img, why = navigate.open_results(1, "Prismatica ShadowDaggers")
    assert (img is not None) is opened

def test_a_remembered_tile_that_is_gone_is_forgotten_and_the_first_tile_is_tried(monkeypatch):
    monkeypatch.setattr(navigate, "_slot", {"Nya Machete": 1})  # the second variant was here last time
    w = World(monkeypatch)
    monkeypatch.setattr(navigate, "_has_tile", lambda img, point: point[0] < 150)  # now only the first tile is listed
    img, why = navigate.open_results(1, "Nya Machete")
    assert img is not None and w.clicks[0] == (110, 220) and navigate._slot == {}  # the first tile is the default: nothing kept


def test_buttons_in_a_taller_search_options_are_found_not_taken_from_the_fixed_spot():
    for name, fixed_ok in (("live_options_crossbow", True), ("live_options_nya_pink", False)):  # the second has the StatTrak row
        img = cv2.imread(f"sniper_arena_scanner_handoff/{name}.png")
        assert img is not None
        check = navigate._button_point(img, "check", lambda: screens.find_check_button(img))
        cancel = navigate._button_point(img, "options_cancel", lambda: screens.find_options_cancel(img), red=True)
        assert (check == layout.fixed(img, "check")) is fixed_ok
        assert (cancel == layout.fixed(img, "options_cancel")) is fixed_ok
        assert check == screens.find_check_button(img) or fixed_ok
        assert cancel == screens.find_options_cancel(img) or fixed_ok



@pytest.mark.parametrize("name, tiles", [("live_desert_eagle_six_grid_1900", 6), ("live_prismatica_six_grid", 6),
                                         ("live_frostbite_grid_1900", 1), ("live_nya_machete_grid_1900", 3)])
def test_every_tile_is_seen_red_limited_or_rainbow_secret(name, tiles):
    img = cv2.imread(f"sniper_arena_scanner_handoff/{name}.png")
    if img is None:
        pytest.skip("fixture screenshots missing")
    img = cv2.resize(img, (1900, 1069))
    first = layout.fixed(img, "first_tile")
    assert [navigate._has_tile(img, navigate._slot_point(first, k, img)) for k in range(8)] == [k < tiles for k in range(8)]



def test_one_lone_tile_replacing_another_counts_as_the_grid_changing():
    a = cv2.imread("sniper_arena_scanner_handoff/live_frostbite_grid_1900.png")
    b = cv2.imread("sniper_arena_scanner_handoff/live_prismatica_six_grid.png")
    if a is None or b is None:
        pytest.skip("fixture screenshots missing")
    b = cv2.resize(b, (a.shape[1], a.shape[0]))
    assert navigate._first_tile_change(a, a.copy()) == 0
    assert navigate._first_tile_change(a, b) > 8



@pytest.mark.parametrize("name, behind", [("live_grid_behind_count_1900", True), ("live_frostbite_grid_1900", False),
                                          ("live_desert_eagle_six_grid_1900", False)])
def test_a_grid_still_showing_more_tiles_than_the_count_is_behind(name, behind):
    img = cv2.imread(f"sniper_arena_scanner_handoff/{name}.png")
    if img is None:
        pytest.skip("fixture screenshots missing")
    assert navigate._grid_behind(img) is behind  # the first counts 1 over a full grid; the last counts 6: no telling



def test_a_count_that_has_not_changed_since_before_the_search_means_the_grid_is_behind():
    img = cv2.imread("sniper_arena_scanner_handoff/live_grid_search_not_applied_1900.png")  # counts 229 under the typed name
    if img is None:
        pytest.skip("fixture screenshots missing")
    assert navigate._grid_behind(img, 229) and not navigate._grid_behind(img, 230)


def test_a_lone_skin_after_a_lone_skin_is_not_taken_as_behind(monkeypatch):
    img = cv2.imread("sniper_arena_scanner_handoff/live_frostbite_grid_1900.png")  # counts 1, one tile
    if img is None:
        pytest.skip("fixture screenshots missing")
    assert not navigate._grid_behind(img, 1)  # the last search counted 1 too



def test_a_banner_over_the_top_row_is_waited_out_not_taken_for_tiles(monkeypatch):
    banner = cv2.imread("sniper_arena_scanner_handoff/live_grid_banner_1900.png")  # one tile under an "X bought Y" band
    clean = cv2.imread("sniper_arena_scanner_handoff/live_frostbite_grid_1900.png")
    if banner is None or clean is None:
        pytest.skip("fixture screenshots missing")
    assert not navigate._grid_behind(banner)  # no telling under it
    frames = iter([banner, banner, clean])
    monkeypatch.setattr(navigate.screen, "capture", lambda hwnd: next(frames), raising=False)
    monkeypatch.setattr(navigate.time, "sleep", lambda s: None)
    assert navigate._without_banner(1, banner) is clean


def test_the_tile_memory_is_kept_between_runs(tmp_path, monkeypatch):
    from scanner.windows import navigate
    monkeypatch.setattr(navigate, "_slot", {})
    path = tmp_path / "tile_slots.json"
    path.write_text('{"Prismatica ShadowDaggers": 1, "Bad": 9, "Null": null, "Text": "x"}')
    navigate.remember_slots(path)
    assert navigate._slot == {"Prismatica ShadowDaggers": 1}  # the good entry kept, the bad ones dropped
    path.write_text("not json")
    navigate.remember_slots(path)
    assert navigate._slot == {"Prismatica ShadowDaggers": 1}  # a broken file changes nothing
    navigate.remember_slots(tmp_path / "missing.json")  # no file yet: no error
    navigate._set_slot("Nya Machete", 2)
    assert json.loads((tmp_path / "missing.json").read_text()) == {"Prismatica ShadowDaggers": 1, "Nya Machete": 2}
    navigate._set_slot("Prismatica ShadowDaggers", None)  # forgotten (back on the first tile): the file follows
    assert json.loads((tmp_path / "missing.json").read_text()) == {"Nya Machete": 2}
