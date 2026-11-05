import pytest

cv2 = pytest.importorskip("cv2")
from scanner.reading import screens  # noqa: E402

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
    # 1900x1069 window: the cursor is dimmer (~200) there; the placeholder letters must not count as a cursor
    assert screens.search_caret(load(base + "live_search_caret_dim.png"))
    assert not screens.search_caret(load(base + "live_search_empty_no_caret.png"))


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


def test_category_buttons_are_found_by_their_labels():
    base = "sniper_arena_scanner_handoff/"
    img = load(base + "live_collection.png")
    found = {c: screens.find_category_button(img, c) for c in ("Sniper", "Knife", "Glove", "Charm")}
    assert all(found.values()) and len(set(found.values())) == 4
    assert screens.find_category_button(img, "Souvenir") is None
    assert screens.find_category_button(load(base + "live_options.png"), "Knife") is None  # other screen: no point
    assert screens.find_category_button(load(base + "live_search_empty_no_caret.png"), "Knife")  # 1900x1069 window


def test_dim_unowned_tile_is_found_and_split_tiles_count_once():
    base = "sniper_arena_scanner_handoff/"

    def tiles(file, name):
        img = load(base + file)
        h, w = img.shape[:2]
        return screens._tiles_named(img, name, (int(0.28 * w), int(0.18 * h), int(0.84 * w), int(0.82 * h)))

    assert len(tiles("live_knife_tiles.png", "Nya Reaper")) == 1  # dimmed, rainbow border
    assert tiles("live_knife_tiles.png", "Nya") == []  # a part of a name is not a hit
    assert len(tiles("live_search_typed.png", "Starveil AWP")) == 1  # art splits the tile


def test_search_options_for_a_dim_rainbow_skin_names_it():
    img = load("sniper_arena_scanner_handoff/live_options_knife.png")
    assert screens.options_is_for(img, "Nya Reaper") and not screens.options_is_for(img, "Starveil AWP")


def test_a_tile_cut_off_at_the_edge_is_skipped_not_a_crash():
    img = load("sniper_arena_scanner_handoff/live_knife_tiles.png").copy()
    img[:, :, :] = img  # same frame; move the search area so the tile's label falls outside it
    h, w = img.shape[:2]
    assert screens._tiles_named(img, "Nya Reaper", (int(0.28 * w), int(0.18 * h), int(0.84 * w), int(0.28 * h))) == []


def test_first_tile_is_found_by_shape_even_when_its_name_cannot_be_read():
    base = "sniper_arena_scanner_handoff/"
    x, y = screens.find_first_tile(load(base + "live_crossbow_tile.png"))  # long name in small letters under gun art
    assert 531 <= x <= 694 and 190 <= y <= 355
    x, y = screens.find_first_tile(load(base + "live_knife_tiles.png"))  # two tiles: the left one
    assert 531 <= x <= 694
    assert screens.find_first_tile(load(base + "live_options_knife.png")) is None  # not the collection screen


def test_a_long_name_under_gun_art_is_read_in_search_options():
    img = load("sniper_arena_scanner_handoff/live_options_crossbow.png")
    assert screens.options_is_for(img, "Wild Fiend Crossbow") and not screens.options_is_for(img, "Wild Fiend")


def test_a_short_name_over_gun_art_is_read_in_search_options():
    img = load("sniper_arena_scanner_handoff/live_options_mallow.png")
    assert screens.options_is_for(img, "9D Mallow") and not screens.options_is_for(img, "Wild Fiend Crossbow")


def test_a_hovered_category_button_that_merges_with_its_neighbour_still_gives_the_fixed_point():
    from scanner.reading import layout
    img = load("sniper_arena_scanner_handoff/live_sniper_hover.png")  # Sniper grown by the mouse: Sniper and Knife unreadable
    assert screens.find_category_button(img, "Knife") is None
    x, y = layout.from_sibling(img, "category:Knife", lambda n: screens.find_category_button(img, n.split(":")[1]))
    assert abs(x - 0.0942 * img.shape[1]) < 2 and abs(y - 0.2703 * img.shape[0]) < 2


def test_a_short_name_over_pink_art_with_a_rainbow_border_is_read_in_search_options():
    img = load("sniper_arena_scanner_handoff/live_options_nya_pink.png")
    assert screens.options_is_for(img, "Nya Reaper") and not screens.options_is_for(img, "Noire Nya Reaper")


def test_the_rarity_button_that_is_lit_is_told_from_the_ones_that_are_not():
    img = load("sniper_arena_scanner_handoff/live_limited_on.png")  # Limited lit (magenta), Secret and All dark
    assert screens.rarity_is_on(img, "Limited") and not screens.rarity_is_on(img, "Secret")
    plain = load("sniper_arena_scanner_handoff/live_crossbow_tile.png")  # All lit: both rarity buttons are off
    assert not screens.rarity_is_on(plain, "Limited") and not screens.rarity_is_on(plain, "Secret")


def test_a_lit_rarity_button_that_grew_under_the_mouse_still_reads_as_lit():
    img = load("sniper_arena_scanner_handoff/live_limited_hover.png")
    assert screens.rarity_is_on(img, "Limited") and not screens.rarity_is_on(img, "Secret")


def test_small_label_over_red_gun_art_reads_in_search_options():
    img = load("sniper_arena_scanner_handoff/live_options_starember.png")
    assert screens.options_is_for(img, "Starember GM6 Lynx") and not screens.options_is_for(img, "Starfade GM6 Lynx")


def test_a_smaller_window_on_another_monitor_is_still_the_collection_screen():
    img = load("sniper_arena_scanner_handoff/live_small_window_1582.png")  # 1582x911: the search bar's grey band is thin
    assert screens.classify(img) == "collection" and screens.find_search_box(img) is not None
    assert screens.find_category_button(img, "Knife") is not None and screens.find_first_tile(img) is not None


def test_search_options_on_a_small_window_reads_the_label_from_the_tile_frame():
    img = load("sniper_arena_scanner_handoff/live_options_nya_1333.png")  # 1333x750: pink art, little red to size from
    assert screens.options_is_for(img, "Nya Reaper") and not screens.options_is_for(img, "Noire Nya Reaper")


def test_a_card_whose_art_sticks_out_for_17_rows_is_still_one_card():
    from scanner.reading import vision
    img = cv2.imread("sniper_arena_scanner_handoff/live_daisho_rainbow_results.png")
    boxes = vision.find_cards(img)
    assert boxes[0][1:4:2] == (301, 470) and vision.is_complete(boxes[0])  # the Nocturne Daisho [Rainbow] card
    assert boxes[1][1] > 480  # the next card stays a separate one


def test_an_unlit_rarity_button_is_not_read_as_lit_even_with_a_bright_bottom_lip():
    for f in ("live_rarity_off_search_1900.png", "live_rarity_off_options_1900.png"):  # seen live: Secret off
        img = cv2.imread(f"sniper_arena_scanner_handoff/{f}")
        assert not screens.rarity_is_on(img, "Secret") and not screens.rarity_is_on(img, "Limited")


def test_the_search_bar_is_not_confused_with_a_grey_strip_at_the_window_bottom():
    img = cv2.imread("sniper_arena_scanner_handoff/live_search_text_150pct_1900.png")  # name pasted, grid down to 1 tile
    x, y, w, h = screens._search_bar(img)
    assert 900 < y < 960 and w > 600  # the real bar, not the strip at y 1011
    assert screens.search_has_text(img)


def test_the_no_listings_box_is_its_own_screen_with_a_close_button():
    img = cv2.imread("sniper_arena_scanner_handoff/live_no_listings.png")  # 1890x1068, seen live for a skin nobody sells
    assert screens.classify(img) == "empty"
    x, y = screens.find_close_button(img)
    assert 878 < x < 1011 and 808 < y < 875  # inside the red X button at the bottom centre of the box
    assert screens.classify(load("sniper_arena_scanner_handoff/live_empty_price_read.png")) == "results"  # a real list is not it
    assert screens.classify(load("sniper_arena_scanner_handoff/live_search_empty_no_caret.png")) == "collection"


def test_no_listings_is_read_from_the_title_in_the_lists_own_dark_grey_too():
    dark = cv2.imread("sniper_arena_scanner_handoff/live_no_listings_dark_1900.png")  # seen live: classify says "results"
    assert screens.classify(dark) == "results" and screens.no_listings(dark)
    assert screens.no_listings(cv2.imread("sniper_arena_scanner_handoff/live_no_listings.png"))  # the lighter grey
    assert not screens.no_listings(load("sniper_arena_scanner_handoff/live_empty_price_read.png"))  # a list with cards
    assert not screens.no_listings(load("sniper_arena_scanner_handoff/live_search_empty_no_caret.png"))  # not a box at all
