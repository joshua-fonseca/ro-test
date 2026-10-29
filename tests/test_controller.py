import numpy as np

from scanner.windows import controller


class FakeUser32:
    def __init__(self):
        self.events = []

    def SetCursorPos(self, x, y):
        assert type(x) is int and type(y) is int  # the real ctypes call rejects numpy ints
        self.events.append(("pos", x, y))

    def mouse_event(self, flags, dx, dy, data, extra):
        self.events.append((flags, dx, dy, data))

    def VkKeyScanW(self, code):  # real layout: a-z plain, A-Z with shift (0x100), '[' has no key in this fake
        ch = chr(code)
        if ch == "@":  # a key that needs AltGr (Ctrl+Alt) on some layouts
            return 0x32 | 0x600
        return -1 if ch == "[" else ord(ch.upper()) | (0x100 if ch.isupper() else 0)

    def MapVirtualKeyW(self, key, kind):
        return key + 1000

    def keybd_event(self, key, scan, flags, extra):
        self.events.append(("key", key, flags))


def _run(monkeypatch, focused_for, action=lambda: controller.scroll(1, 100, 200, 3)):
    fake, checks = FakeUser32(), iter(range(100))
    monkeypatch.setattr(controller, "user32", fake, raising=False)
    monkeypatch.setattr(controller.screen, "is_focused", lambda hwnd: next(checks) < focused_for, raising=False)
    monkeypatch.setattr(controller.screen, "client_rect", lambda hwnd: (0, 0, 2000, 1200), raising=False)
    monkeypatch.setattr(controller.time, "sleep", lambda s: None)
    return action(), fake.events


def test_hover_then_wheel_down(monkeypatch):
    ok, events = _run(monkeypatch, 100)
    assert ok and events == [("pos", 100, 200), (1, 1, 0, 0), (1, -1, 0, 0)] + [(0x800, 0, 0, -120)] * 3


def test_focus_lost_stops_input_at_once(monkeypatch):
    ok, events = _run(monkeypatch, 4)  # focus checked before every event: lost before the 2nd wheel notch
    assert not ok and len(events) == 4


def test_click_hovers_presses_and_releases(monkeypatch):
    ok, events = _run(monkeypatch, 100, lambda: controller.click(1, 100, 200))
    assert ok and events == [("pos", 100, 200), (1, 1, 0, 0), (1, -1, 0, 0), (2, 0, 0, 0), (4, 0, 0, 0)]


def test_click_with_focus_lost_sends_no_button_at_all(monkeypatch):
    ok, events = _run(monkeypatch, 3, lambda: controller.click(1, 100, 200))  # lost just before the press
    assert not ok and [e for e in events if e[0] in (2, 4)] == []


def test_typing_presses_shift_for_capitals_and_releases_everything(monkeypatch):
    ok, events = _run(monkeypatch, 100, lambda: controller.type_text(1, "Ab"))
    assert ok and events == [("key", 0x10, 0), ("key", 65, 0), ("key", 65, 2), ("key", 0x10, 2),
                             ("key", 66, 0), ("key", 66, 2)]


def test_typing_stops_when_focus_is_lost_but_still_releases_shift(monkeypatch):
    ok, events = _run(monkeypatch, 1, lambda: controller.type_text(1, "Ab"))  # shift went down, then focus was lost
    assert not ok and events == [("key", 0x10, 0), ("key", 65, 2), ("key", 0x10, 2)]


def test_typing_a_character_with_no_key_sends_nothing(monkeypatch):
    ok, events = _run(monkeypatch, 100, lambda: controller.type_text(1, "["))
    assert not ok and events == []


def test_ctrl_c_during_a_click_still_releases_the_button(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(controller, "user32", fake, raising=False)
    monkeypatch.setattr(controller.screen, "is_focused", lambda hwnd: True, raising=False)
    monkeypatch.setattr(controller.screen, "client_rect", lambda hwnd: (0, 0, 2000, 1200), raising=False)
    sleeps = iter([None, None, None, KeyboardInterrupt])  # hover steps sleep fine, then Ctrl+C while the button is down

    def sleep(s):
        r = next(sleeps)
        if r:
            raise r
    monkeypatch.setattr(controller.time, "sleep", sleep)
    try:
        controller.click(1, 5, 6)
    except KeyboardInterrupt:
        pass
    assert fake.events[-2:] == [(2, 0, 0, 0), (4, 0, 0, 0)]  # pressed, then released


def test_ctrl_c_while_typing_a_capital_releases_shift_and_the_key(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(controller, "user32", fake, raising=False)
    monkeypatch.setattr(controller.screen, "is_focused", lambda hwnd: True, raising=False)
    monkeypatch.setattr(controller.screen, "client_rect", lambda hwnd: (0, 0, 2000, 1200), raising=False)
    real = fake.keybd_event

    def interrupted(key, scan, flags, extra):  # Ctrl+C lands right after the letter goes down
        real(key, scan, flags, extra)
        if key == 65 and flags == 0:
            raise KeyboardInterrupt
    fake.keybd_event = interrupted
    try:
        controller.type_text(1, "A")
    except KeyboardInterrupt:
        pass
    assert fake.events == [("key", 0x10, 0), ("key", 65, 0), ("key", 65, 2), ("key", 0x10, 2)]


def test_numpy_coordinates_reach_windows_as_plain_ints(monkeypatch):
    ok, events = _run(monkeypatch, 100, lambda: controller.click(1, np.int64(100), np.int64(200)))
    assert ok and events[0] == ("pos", 100, 200)  # FakeUser32 asserts the type, as ctypes does
    ok, events = _run(monkeypatch, 100, lambda: controller.scroll(1, np.int64(100), np.int64(200), 1))
    assert ok and events[0] == ("pos", 100, 200)


def test_points_outside_the_game_area_are_never_clicked_or_scrolled(monkeypatch):
    for point in [(-1, 50), (2000, 50), (50, 1200), (50, -1)]:  # window is 2000x1200 at (0, 0)
        ok, events = _run(monkeypatch, 100, lambda: controller.click(1, *point))
        assert not ok and events == []
        ok, events = _run(monkeypatch, 100, lambda: controller.scroll(1, *point, 3))
        assert not ok and events == []


def test_a_character_needing_ctrl_or_alt_is_refused_not_typed_wrong(monkeypatch):
    ok, events = _run(monkeypatch, 100, lambda: controller.type_text(1, "@"))
    assert not ok and events == []


def test_backspace_presses_and_releases_each_time(monkeypatch):
    ok, events = _run(monkeypatch, 100, lambda: controller.backspace(1, 2))
    assert ok and events == [("key", 8, 0), ("key", 8, 2)] * 2


def test_backspace_stops_when_focus_is_lost(monkeypatch):
    ok, events = _run(monkeypatch, 1, lambda: controller.backspace(1, 5))  # first press goes down, then focus is lost
    assert not ok and events == [("key", 8, 0), ("key", 8, 2), ("key", 8, 2)]  # no 2nd press; the extra release is harmless


def test_paste_sets_the_clipboard_then_presses_ctrl_v_and_releases(monkeypatch):
    copied = []
    monkeypatch.setattr(controller, "_set_clipboard", lambda text: copied.append(text) or True)
    ok, events = _run(monkeypatch, 100, lambda: controller.paste_text(1, "Nya Reaper"))
    assert ok and copied == ["Nya Reaper"]
    assert events == [("key", 0x11, 0), ("key", 0x56, 0), ("key", 0x56, 2), ("key", 0x11, 2)]  # Ctrl down, V, V up, Ctrl up


def test_paste_sends_nothing_when_the_clipboard_is_busy_and_releases_ctrl_if_focus_is_lost(monkeypatch):
    monkeypatch.setattr(controller, "_set_clipboard", lambda text: False)
    ok, events = _run(monkeypatch, 100, lambda: controller.paste_text(1, "x"))
    assert not ok and events == []
    monkeypatch.setattr(controller, "_set_clipboard", lambda text: True)
    ok, events = _run(monkeypatch, 1, lambda: controller.paste_text(1, "x"))  # focus gone after Ctrl went down
    assert not ok and events[0] == ("key", 0x11, 0) and events[-1] == ("key", 0x11, 2)
