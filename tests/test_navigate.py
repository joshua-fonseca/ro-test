import types

import pytest

import navigate


class World:
    """A fake game: clicks move it from screen to screen; the finders and the clock are scripted around it."""

    def __init__(self, monkeypatch, state="collection", tile=True, label_ok=True, caret=True, banner_for=0,
                 box_text=False, stuck_text=False):
        self.state, self.tile, self.label_ok, self.caret = state, tile, label_ok, caret
        self.box_text, self.stuck_text, self.backspaces = box_text, stuck_text, 0  # old text in the search box
        self.banner_for = banner_for  # the first N screenshots are covered by an in-game banner ("unknown")
        self.size = (1920, 1166)
        self.clicks, self.typed, self.now = [], [], 0.0
        m = monkeypatch
        m.setattr(navigate, "time", types.SimpleNamespace(time=lambda: self.now, sleep=self._sleep))
        m.setattr(navigate.screen, "capture", lambda hwnd: types.SimpleNamespace(shape=(1166, 1920, 3)), raising=False)
        m.setattr(navigate.screen, "client_rect", lambda hwnd: (10, 20, *self.size), raising=False)
        m.setattr(navigate.screens, "classify", self._classify)
        m.setattr(navigate.screens, "find_search_box", lambda img: (50, 60))
        m.setattr(navigate.screens, "search_caret", lambda img: self.caret)
        m.setattr(navigate.screens, "search_has_text", lambda img: self.box_text)
        m.setattr(navigate.controller, "backspace", self._backspace)
        m.setattr(navigate.screens, "find_skin_tile", lambda img, name: (100, 200) if self.tile else None)
        m.setattr(navigate.screens, "options_is_for", lambda img, name: self.label_ok)
        m.setattr(navigate.screens, "find_check_button", lambda img: (300, 400) if self.state == "options" else None)
        m.setattr(navigate.screens, "find_close_button", lambda img: (500, 600) if self.state == "results" else None)
        m.setattr(navigate.controller, "click", self._click)
        m.setattr(navigate.controller, "type_text", lambda hwnd, text: self.typed.append(text) or True)

    def _classify(self, img):
        if self.banner_for > 0:
            self.banner_for -= 1
            return "unknown"
        return self.state

    def _backspace(self, hwnd, times):
        self.backspaces += times
        self.box_text = self.stuck_text
        return True

    def _sleep(self, s):
        self.now += s

    def _click(self, hwnd, x, y):
        self.clicks.append((x, y))
        self.state = {(110, 220): "options", (310, 420): "results", (510, 620): "collection"}.get((x, y), self.state)
        return True


def test_search_types_only_after_the_cursor_is_seen(monkeypatch):
    w = World(monkeypatch, caret=False)
    assert navigate.search_for(1, "Starveil AWP") == (False, "no text cursor in the search box; typed nothing")
    assert w.typed == [] and w.clicks == [(60, 80)]  # clicked the box, typed nothing
    w = World(monkeypatch)
    assert navigate.search_for(1, "Starveil AWP") == (True, "") and w.typed == ["Starveil AWP"]


def test_open_results_clicks_tile_then_check(monkeypatch):
    w = World(monkeypatch)
    img, why = navigate.open_results(1, "Starveil AWP")
    assert img is not None and why == "" and w.clicks == [(110, 220), (310, 420)]  # screen offset (10, 20) added


def test_no_tile_means_no_click(monkeypatch):
    w = World(monkeypatch, tile=False)
    assert navigate.open_results(1, "Starveil AWP")[0] is None and w.clicks == []


def test_search_options_for_another_skin_never_gets_the_check(monkeypatch):
    w = World(monkeypatch, label_ok=False)
    img, why = navigate.open_results(1, "Nya Reaper")
    assert img is None and "not for" in why and w.clicks == [(110, 220)]  # the tile only, never the green check


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
    real_find = navigate.screens.find_skin_tile

    def resized_during_ocr(img, name):  # the user drags the window while the tile is being read
        w.size = (1600, 900)
        return real_find(img, name)
    monkeypatch.setattr(navigate.screens, "find_skin_tile", resized_during_ocr)
    img, why = navigate.open_results(1, "Starveil AWP")
    assert img is None and "window changed size" in why and w.clicks == []


def test_old_search_text_is_cleared_before_typing(monkeypatch):
    w = World(monkeypatch, box_text=True)
    assert navigate.search_for(1, "Nya Reaper") == (True, "")
    assert w.backspaces == 40 and w.typed == ["Nya Reaper"]  # cleared first, then typed
    w = World(monkeypatch)  # an empty box is left alone
    navigate.search_for(1, "Nya Reaper")
    assert w.backspaces == 0


def test_nothing_is_typed_if_the_old_text_will_not_clear(monkeypatch):
    w = World(monkeypatch, box_text=True, stuck_text=True)
    assert navigate.search_for(1, "Nya Reaper") == (False, "could not clear the search box") and w.typed == []
