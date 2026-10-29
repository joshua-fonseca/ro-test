import controller


class FakeUser32:
    def __init__(self):
        self.events = []

    def SetCursorPos(self, x, y):
        self.events.append(("pos", x, y))

    def mouse_event(self, flags, dx, dy, data, extra):
        self.events.append((flags, dx, dy, data))


def _run(monkeypatch, focused_for):
    fake, checks = FakeUser32(), iter(range(100))
    monkeypatch.setattr(controller, "user32", fake, raising=False)
    monkeypatch.setattr(controller.screen, "is_focused", lambda hwnd: next(checks) < focused_for, raising=False)
    monkeypatch.setattr(controller.time, "sleep", lambda s: None)
    return controller.scroll(1, 100, 200, 3), fake.events


def test_hover_then_wheel_down(monkeypatch):
    ok, events = _run(monkeypatch, 100)
    assert ok and events == [("pos", 100, 200), (1, 1, 0, 0), (1, -1, 0, 0)] + [(0x800, 0, 0, -120)] * 3


def test_focus_lost_stops_input_at_once(monkeypatch):
    ok, events = _run(monkeypatch, 4)  # focus checked before every event: lost before the 2nd wheel notch
    assert not ok and len(events) == 4
