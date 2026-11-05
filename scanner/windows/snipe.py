"""`main.py --snipe`: what happens after Teleport was clicked on a match. Windows only.

Wait for the new server, walk up to the seller's stall (W, then S), hold E to open it, buy the matched item if it is
still there (green cash button, then the green check; with too little cash, only the X of Roblox's "Buy Robux"
box), leave the stall (red X), then list on the market: Inventory,
All, Inspect, Sell on Market, the green check in "Claim this stall?", hold E, and the green check in "Want to use the
same items as last time?". Every click waits for its button's colour at its fixed point (screens.SNIPE); anything
that does not show in time stops the whole flow with nothing more sent.
"""
import time

from scanner.reading import screens
from scanner.windows import controller, navigate, screen

W, S, E = 0x57, 0x53, 0x45  # virtual keys
HOVER = 0.1  # Roblox can ignore a press that lands the instant the cursor reaches a button (seen live on the stall X)


class Stopped(Exception):
    """The flow could not go on; the message says where. `img` is the last screen seen, kept for diagnostics."""

    def __init__(self, why: str, img=None):
        super().__init__(why)
        self.img = img


class NotTeleported(Stopped):
    """No loading screen after the Teleport click: the click did nothing, and the results list is still up."""


class TeleportFailed(Stopped):
    """Roblox said "Teleport Failed" (server full); its Ok was clicked, so the results list shows again."""


def _wait(hwnd: int, seconds: float, find):
    """Look again and again until find(img) gives a point; (point, img). Stops on lost focus or after `seconds`."""
    end = time.time() + seconds
    while True:
        img = screen.capture(hwnd)
        if img is None:
            raise Stopped(f"Roblox lost focus ({screen.foreground_title()!r} was in front)")
        point = find(img)
        if point is not None:
            return point, img
        if time.time() >= end:
            return None, img
        time.sleep(0.1)


_steps = {"n": 0, "save": lambda name, img: None, "short": False}  # short: the Buy Robux box showed (too little cash)


def _shot(name: str, img) -> None:
    """Diagnostics: keep the screen right before each click, numbered in order (snipe_01_stall_exit.png ...)."""
    if img is not None:
        _steps["n"] += 1
        _steps["save"](f"snipe_{_steps['n']:02d}_{name}", img)


def _click(hwnd: int, point, img, name: str) -> bool:
    _shot(name, img)
    return navigate._click(hwnd, point, img, HOVER)


# Buttons that go away when the click works (the stall closes, a box closes): looked at again and clicked again if
# still there. The rest (Inventory, All, Inspect) stay on screen after their click.
# Roblox's "Buy Robux and item" box slides in, and a click on its X while it still moves is ignored (seen live).
GONE_AFTER = {"stall_exit", "buy_check", "sell_on_market", "claim_check", "same_items_check", "robux_box_x"}


def _press(hwnd: int, cfg, name: str, find=None) -> None:
    """Wait for the button (screens.SNIPE `name`, or `find(img)`), click it; one that should go away is looked at
    again and clicked again if still there, 3 tries in all. Roblox's Buy Robux box can come up late, over everything
    (seen live: a second after the green check, with too little cash): whenever it shows, only its X is clicked first."""
    find = find or (lambda im: screens.snipe_button(im, name))

    def look(im):
        if name != "robux_box_x" and screens.find_robux_prompt_close(im) is not None:
            return "robux"
        return find(im)
    point, img = _wait(hwnd, cfg.snipe_step_timeout, look)
    for _ in range(3):
        if point is None:
            raise Stopped(f"the {name} button did not show", img)
        if point == "robux":
            _steps["short"] = True
            _press(hwnd, cfg, "robux_box_x", screens.find_robux_prompt_close)
            point, img = _wait(hwnd, cfg.snipe_step_timeout, look)
            continue
        if not _click(hwnd, point, img, name):
            raise Stopped(f"click on {name} not sent (Roblox lost focus, or the window changed size)", img)
        time.sleep(cfg.snipe_click_pause)  # the next screen takes a moment to replace this one
        if name not in GONE_AFTER:
            return
        img = screen.capture(hwnd)
        if img is None:
            raise Stopped("Roblox lost focus")
        point = look(img)
        if point is None:
            return
    raise Stopped(f"the {name} button was clicked 3 times and is still there", img)


def _hold(hwnd: int, key: int, seconds: float) -> None:
    if not controller.hold_key(hwnd, key, seconds):
        raise Stopped("Roblox lost focus while a key was held")


def _mostly_black(img) -> bool:
    return (img.max(2) < 30).mean() > 0.9  # the loading screen between servers


def _look_in_stall(hwnd: int, skin: str, low: int, high: int, seconds: float):
    """(cash button of the item or None, last screen, prices read). Waits up to `seconds` while no price shows yet
    (still loading) or a price in range shows but the name does not read yet."""
    seen = []

    def look(im):
        seen.clear()
        point = screens.find_stall_buy(im, skin, low, high, seen)
        if point is not None:
            return point
        return "loaded" if seen and not any(low <= p <= high for p in seen) else None
    found, img = _wait(hwnd, seconds, look)
    return (found if isinstance(found, tuple) else None), img, list(seen)


def _scroll_stall(hwnd: int, cfg, img):
    """Scroll the stall's list down and return the screen once it stopped gliding; None if nothing moved (the end)."""
    x0, y0, w, h = screen.client_rect(hwnd)
    if not controller.scroll(hwnd, x0 + w // 2, y0 + h // 2, cfg.stall_scroll_notches):
        raise Stopped("Roblox lost focus while scrolling the stall", img)
    for wait in (0.3, 0.6):  # a slow start must not read as "the end": look again before giving up
        time.sleep(wait)
        cur = screen.capture(hwnd)
        if cur is None:
            raise Stopped(f"Roblox lost focus ({screen.foreground_title()!r} was in front)")
        if navigate._grid_change(cur, img) >= 1.0:
            break
    else:
        return None
    new = cur
    for _ in range(12):  # it is gliding: wait until two looks are alike
        time.sleep(0.15)
        cur = screen.capture(hwnd)
        if cur is None:
            raise Stopped(f"Roblox lost focus ({screen.foreground_title()!r} was in front)")
        done = navigate._grid_change(cur, new) < 1.0
        new = cur
        if done:
            break
    return new


def after_teleport(hwnd: int, cfg, skin: str, low: int, high: int, save=lambda name, img: None) -> str:
    """Run the whole flow; returns what happened. Raises Stopped (nothing more sent) when a step fails.
    save(name, img) keeps the screen before every click and key hold (snipe_01_... in order)."""
    _steps.update(n=0, save=save, short=False)
    # Arrived once the black "Teleporting..." screen has come and gone. Looked for from the click on, twice a second,
    # so a short one is not missed: the old list can stay up a while first, and a closed list alone proves nothing.
    seen_black, img, start = False, None, time.time()
    end = start + cfg.teleport_max_seconds
    while True:
        hwnd = screen.find_roblox(hwnd) or hwnd  # the teleport may leave Roblox in a new window
        img = screen.capture(hwnd)  # None while Roblox is not in front: wait for it too, nothing is sent
        ok = None if img is None else screens.find_teleport_failed_ok(img)
        if ok is not None:
            if not _click(hwnd, ok, img, "teleport_failed_ok"):
                raise Stopped("click on Ok (Teleport Failed) not sent", img)
            time.sleep(cfg.snipe_click_pause)
            raise TeleportFailed("the server is full (Teleport Failed)", img)
        if img is not None:
            if _mostly_black(img):
                seen_black = True
            elif seen_black:
                break
        # shortcut: 15 s is a guess at the longest wait for a teleport to start; raise it if real ones are missed
        if not seen_black and img is not None and time.time() > start + 15:
            raise NotTeleported("no loading screen within 15 s: the Teleport click did nothing", img)
        if time.time() > end:
            why = "loading" if img is not None else f"Roblox not in front ({screen.foreground_title()!r} was)"
            raise Stopped(f"after {cfg.teleport_max_seconds} s the new server was still {why}", img)
        time.sleep(0.5)
    time.sleep(cfg.teleport_wait_seconds)  # the new world finishes drawing before the walk
    _shot("arrived", img)
    _hold(hwnd, W, cfg.walk_seconds)
    _hold(hwnd, S, cfg.walk_seconds)  # only after stepping back does the "E Open" prompt show
    _hold(hwnd, E, cfg.hold_e_seconds)
    exit_point, img = _wait(hwnd, cfg.snipe_step_timeout, lambda im: screens.snipe_button(im, "stall_exit"))
    if exit_point is None:
        raise Stopped("the seller's stall did not open", img)
    # the stall's X shows before its items and prices have loaded: keep looking a while before calling the item gone
    buy, img, seen = _look_in_stall(hwnd, skin, low, high, cfg.stall_load_seconds)
    for _ in range(cfg.stall_max_scrolls):  # the item may be further down: a stall lists dearest first
        if buy is not None or (seen and max(seen) < low):
            break  # found, or everything in view is cheaper than the item (shortcut: assumes the stall is sorted high to low, as seen on 3 stalls)
        moved = _scroll_stall(hwnd, cfg, img)
        if moved is None:
            break  # the list did not move: that was the end (img stays the last real screen, for the diagnostics)
        buy, img, seen = _look_in_stall(hwnd, skin, low, high, 2)
    save("snipe_stall", img)  # diagnostics: the stall as it was read
    dry = False
    if buy is not None:
        if not _click(hwnd, buy, img, "cash_button"):
            raise Stopped("click on the cash button not sent (Roblox lost focus, or the window changed size)")
        time.sleep(cfg.snipe_click_pause)
        # Enough cash: the confirm box (green check). Not enough: Roblox's "Buy Robux and item" box, which charges real
        # money; only its X is clicked, then the flow goes on as if the item was gone
        def either(im):
            check = screens.snipe_button(im, "buy_check")
            if check is not None:
                return "check", check
            close = screens.find_robux_prompt_close(im)
            return None if close is None else ("robux", close)
        found, img = _wait(hwnd, cfg.snipe_step_timeout, either)
        if found is None:
            raise Stopped("neither the confirm box nor the not-enough-cash box showed", img)
        if found[0] == "robux":
            _steps["short"] = True
            _press(hwnd, cfg, "robux_box_x", screens.find_robux_prompt_close)
        elif cfg.dry_run:  # everything but the purchase: cancel the confirm box with its red X
            cancel = screens.find_buy_cancel(img)
            if cancel is None or not _click(hwnd, cancel, img, "buy_cancel"):
                raise Stopped("dry run: could not click the cancel X of the confirm box", img)
            time.sleep(cfg.snipe_click_pause)
            dry = True
        else:
            if not _click(hwnd, found[1], img, "buy_check"):
                raise Stopped("click not sent (Roblox lost focus, or the window changed size)", img)
            time.sleep(cfg.snipe_click_pause)
            # With too little cash the Buy Robux box slides in about a second after the check (seen live), and a
            # darkening screen looks like "button gone": wait for it here, before the stall's X is clicked
            late, img = _wait(hwnd, cfg.robux_box_wait_seconds, screens.find_robux_prompt_close)
            if late is not None:
                _steps["short"] = True
                _press(hwnd, cfg, "robux_box_x", screens.find_robux_prompt_close)
    _press(hwnd, cfg, "stall_exit")
    for name in ("inventory", "inventory_all", "inspect", "sell_on_market", "claim_check"):
        _press(hwnd, cfg, name, screens.find_inspect if name == "inspect" else None)  # Inspect moves with the item shown
    _hold(hwnd, E, cfg.hold_e_seconds)
    _press(hwnd, cfg, "same_items_check")
    done = ("Not enough cash (closed Roblox's Buy Robux box); nothing bought" if _steps["short"] else
            "Dry run: stopped at the confirm box (cancelled), nothing bought" if dry else
            "Bought" if buy is not None else "The item was gone from the stall; nothing bought")
    return done + ", then put your stall up again."
