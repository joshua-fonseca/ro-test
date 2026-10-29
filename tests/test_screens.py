import pytest

cv2 = pytest.importorskip("cv2")
import screens  # noqa: E402

S = "sniper_arena_scanner_handoff/Screenshot 2026-10-28 "
# name: (file, screen, search box, check button, close button); None = must not be found
CASES = {
    "collection": (S + "125747.png", "collection", True, False, False),
    "options": (S + "125319.png", "options", False, True, False),
    "results": (S + "125355.png", "results", False, False, True),
    "results_small": (S + "155835.png", "results", False, False, True),
    "results_loading": ("sniper_arena_scanner_handoff/loading_8_records.png", "results", False, False, True),
    "live_collection": ("sniper_arena_scanner_handoff/live_collection.png", "collection", True, False, False),
    "live_options": ("sniper_arena_scanner_handoff/live_options.png", "options", False, True, False),
    "live_results": ("sniper_arena_scanner_handoff/live_results_after_check.png", "results", False, False, True),
    "market_world": (S + "124140.png", "unknown", False, False, False),
}


def load(path):
    img = cv2.imread(path)
    if img is None:
        pytest.skip("fixture screenshots missing")
    return img


@pytest.mark.parametrize("name", CASES)
def test_screen_and_buttons(name):
    path, screen, search, check, close = CASES[name]
    img = load(path)
    assert screens.classify(img) == screen
    # A button is found on its own screen only. The green Teleport buttons in the results list must never be
    # mistaken for the green check, so check/close/search are None everywhere else.
    assert (screens.find_search_box(img) is not None) == search
    assert (screens.find_check_button(img) is not None) == check
    assert (screens.find_close_button(img) is not None) == close


def test_button_points_sit_on_the_buttons():
    x, y = screens.find_check_button(load(S + "125319.png"))
    assert (1470, 849) <= (x, y) <= (1584, 900)  # the green check box in the 2856x1331 fixture
    x, y = screens.find_close_button(load(S + "125355.png"))
    assert (1334, 1104) <= (x, y) <= (1522, 1157)  # the red X under the results list


def test_caret_shows_only_in_the_focused_search_box():
    base = "sniper_arena_scanner_handoff/"
    assert not screens.search_caret(load(base + "live_collection.png"))
    assert screens.search_caret(load(base + "live_search_focused.png"))


def test_skin_tile_is_found_only_when_its_label_matches():
    img = load("sniper_arena_scanner_handoff/live_search_typed.png")
    x, y = screens.find_skin_tile(img, "Starveil AWP")
    assert (540, 238) < (x, y) < (703, 402)  # inside the one tile (live 1920x1166 frame)
    assert screens.find_skin_tile(img, "Nocturne AWP") is None  # a different name must not click this tile
    # Unfiltered grid: the Starveil AWP tile is on screen too, and is the one that is found (not its neighbours)
    assert screens.find_skin_tile(load("sniper_arena_scanner_handoff/live_search_focused.png"), "Starveil AWP") is not None
    assert screens.find_skin_tile(load("sniper_arena_scanner_handoff/Screenshot 2026-10-28 125355.png"), "Starveil AWP") is None  # results screen


def test_options_box_must_show_the_requested_skin():
    img = load("sniper_arena_scanner_handoff/live_options.png")
    assert screens.options_is_for(img, "Starveil AWP")
    assert not screens.options_is_for(img, "Nya Reaper")
    assert not screens.options_is_for(load("sniper_arena_scanner_handoff/live_collection.png"), "Starveil AWP")  # not that screen


def test_search_box_text_is_told_from_an_empty_box_with_a_cursor():
    base = "sniper_arena_scanner_handoff/"
    assert screens.search_has_text(load(base + "live_search_typed.png"))
    assert not screens.search_has_text(load(base + "live_collection.png"))
    assert not screens.search_has_text(load(base + "live_search_focused.png"))  # empty, only the cursor
