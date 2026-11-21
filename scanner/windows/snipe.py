"""`main.py --snipe`: what happens after Teleport was clicked on a match. Windows only.

Wait for the new server, walk up to the seller's stall (W, then S), hold E to open it, buy the matched item if it is
still there (green cash button, then the green check; with too little cash, only the X of Roblox's "Buy Robux"
box), leave the stall (red X), then list on the market: Inventory,
All, Inspect, Sell on Market, the green check in "Claim this stall?", hold E, and the green check in "Want to use the
same items as last time?". Every click waits for its button's colour at its fixed point (screens.SNIPE; Inspect, which
moves, is found by colour alone); anything that does not show in time stops the whole flow with nothing more sent.
"""
import logging
import time

import numpy as np
from concurrent.futures import ThreadPoolExecutor

from scanner.reading import screens
from scanner.windows import controller, navigate, screen

W, S, E, ESC, L, ENTER = 0x57, 0x53, 0x45, 0x1B, 0x4C, 0x0D  # virtual keys
MAX_RECONNECTS = 3  # Reconnect clicks in one snipe; the network is still down after that: Leave
LEAVE_AFTER = 30  # s after the first Reconnect click: still disconnected, so Leave (it closes Roblox) and stop
NEWS_WAIT = 4  # s for the news box after a reconnect; it may not show at all
_timer_reader = ThreadPoolExecutor(max_workers=1)  # reads "Available in N" timers while the stall is scrolled on
PENDING_MAX = 90  # s: the longest "Available in N Secs" timer the game shows
STAY_PAUSE = 0.2  # after Inventory, All and Inspect (they stay on screen), and once a closing button is gone
HOVER = 0.1  # Roblox can ignore a press that lands the instant the cursor reaches a button (seen live on the stall X)


log = logging.getLogger(__name__)


class Stopped(Exception):
    """The flow could not go on; the message says where. `img` is the last screen seen, kept for diagnostics."""

    def __init__(self, why: str, img=None):
        super().__init__(why)
        self.img = img


class Left(Stopped):
    """Reconnect did not work, so Leave was clicked: Roblox closes."""


class NotTeleported(Stopped):
    """No loading screen after the Teleport click: the click did nothing, and the results list is still up."""


class SellerLeft(Exception):
    """The seller had left the server, so the Teleport landed at the map centre: no stall to buy from. The flow walked
    back to the Search terminal and opened the search menu again; the scan can go on."""


class TeleportFailed(Stopped):
    """Roblox said "Teleport Failed" (server full); its Ok was clicked, so the results list shows again."""


def _look(hwnd: int, last=None):
    """The screen now; stops, keeping the `last` screen for the diagnostics, if Roblox lost focus."""
    img = screen.capture(hwnd)
    if img is None:
        raise Stopped(f"Roblox lost focus ({screen.foreground_title()!r} was in front)", last)
    return img


def _wait(hwnd: int, seconds: float, find):
    """Look again and again until find(img) gives a point; (point, img). Stops on lost focus or after `seconds`."""
    end = time.time() + seconds
    while True:
        img = _look(hwnd)
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
GONE_AFTER = {"news_x", "stall_exit", "buy_check", "sell_on_market", "claim_check", "same_items_check", "robux_box_x"}


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
        if name not in GONE_AFTER:
            time.sleep(STAY_PAUSE)  # the next button may already show on the old screen: give the new one a moment
            return
        end = time.time() + cfg.snipe_click_pause
        while True:  # on as soon as the button is gone; clicked again only if it is still there after the full pause
            time.sleep(0.1)
            img = screen.capture(hwnd)
            if img is None:
                raise Stopped("Roblox lost focus")
            point = look(img)
            if point is None:
                time.sleep(STAY_PAUSE)  # gone, but a closing box may still be fading: let the next screen settle
                return
            if time.time() >= end:
                break
    raise Stopped(f"the {name} button was clicked 3 times and is still there", img)


def _back_to_search(hwnd: int, cfg, stopped: str, left: str) -> None:
    """From the map centre: W for back_to_search_seconds (new lobby) reaches the Search terminal and holding E opens
    the search menu, then raises SellerLeft(left) so the scan goes on. Its "E Search" prompt is not looked for: depending
    on the camera it can sit under the leaderboard (seen live). E only opens a menu; anything but the search menu is a
    stop (Stopped(stopped))."""
    _hold(hwnd, W, cfg.back_to_search_seconds)
    _hold(hwnd, E, cfg.hold_e_seconds)
    menu, img = _wait(hwnd, cfg.snipe_step_timeout, lambda im: (0, 0) if screens.classify(im) == "collection" else None)
    if menu is None:
        raise Stopped(stopped, img)
    raise SellerLeft(left)


def _until(hwnd: int, seconds: float, find, why: str):
    """Like _wait, while Roblox switches between a game and its home page: it may be out of front a moment or change
    window. (point, img, hwnd); Stopped(why) after `seconds`."""
    end, img = time.time() + seconds, None
    while time.time() < end:
        hwnd = screen.find_roblox(hwnd) or hwnd
        im = screen.capture(hwnd)
        if im is not None:
            img, point = im, find(im)
            if point is not None:
                return point, im, hwnd
        time.sleep(0.25)
    raise Stopped(why, img)


def rejoin(hwnd: int, cfg) -> None:
    """--loop, after a buy: leave the seller's server (Esc, L, Enter), click cfg.loop_friend on Roblox's home page,
    then Join (only if the box says they are playing Sniper Arena), close the news box shown on joining, walk to the
    Search terminal and open the search menu. Raises Stopped when a step does not show."""
    for key in (ESC, L, ENTER):
        if not controller._tap(hwnd, key):
            raise Stopped("Roblox lost focus while leaving the server")
        time.sleep(cfg.snipe_click_pause)
    point, img, hwnd = _until(hwnd, cfg.loop_home_seconds, lambda im: screens.find_friend(im, cfg.loop_friend),
                              f"left the server, but {cfg.loop_friend!r} did not show on Roblox's home page")
    if not _click(hwnd, point, img, "friend"):
        raise Stopped("click on the friend's name not sent", img)
    point, img, hwnd = _until(hwnd, cfg.snipe_step_timeout, screens.find_join,
                              f"no Join button saying {cfg.loop_friend} is playing Sniper Arena")
    if not _click(hwnd, point, img, "join"):
        raise Stopped("click on Join not sent", img)
    # in the game: the news box shown on joining (it hides the Inventory button), or the Inventory button (seen live:
    # no news box that time). Not while the home page (whose pictures can be red there) still shows
    def joined(im):
        seen = ("news" if screens.snipe_button(im, "news_x") else "world" if screens.snipe_button(im, "inventory")
                else None)  # cheap colour checks first: the name is read only when one hits
        return None if seen is None or screens.find_friend(im, cfg.loop_friend) else seen
    found, img, hwnd = _until(hwnd, cfg.teleport_max_seconds, joined, "joined, but the game did not show")
    if found == "world":  # the news box may still come a moment later
        found = "news" if _wait(hwnd, NEWS_WAIT, lambda im: screens.snipe_button(im, "news_x"))[0] else None
    if found == "news":
        _press(hwnd, cfg, "news_x")
    try:
        _back_to_search(hwnd, cfg, "rejoined, but the search menu did not open after walking", "rejoined")
    except SellerLeft:  # the search menu is open: the scan goes on
        pass


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


def _find_in_stall(hwnd: int, cfg, skin: str, low: int, high: int, first_wait: float, timers: list | None = None):
    """Look for the item, scrolling down the stall: (cash button or None, last screen, scrolls made). `timers`, if
    given, gets (when read, a future of stall_timers) for every screen passed while the item is not found: read in the
    background, so the search does not wait for it."""
    buy, img, seen = _look_in_stall(hwnd, skin, low, high, first_wait)
    scrolls = 0
    while True:
        if timers is not None and buy is None:
            timers.append((time.time(), _timer_reader.submit(screens.stall_timers, img)))
        # found, or everything in view is cheaper than the item (shortcut: assumes the stall is sorted high to low, as seen on 3 stalls)
        if buy is not None or (seen and max(seen) < low) or scrolls >= cfg.stall_max_scrolls:
            return buy, img, scrolls
        if _scroll_stall(hwnd, cfg, img) is None:
            return buy, img, scrolls  # the list did not move: that was the end (img stays the last real screen)
        scrolls += 1
        buy, img, seen = _look_in_stall(hwnd, skin, low, high, 2)


def _stall_to_top(hwnd: int, cfg, img, scrolls: int) -> None:
    """Scroll the stall back up `scrolls` steps, then on until it no longer moves: a big wheel burst can fall short."""
    if not scrolls:
        return
    notches = -scrolls * cfg.stall_scroll_notches
    for _ in range(cfg.stall_max_scrolls):
        img = _scroll_stall(hwnd, cfg, img, notches)
        if img is None:
            return
        notches = -cfg.stall_scroll_notches


def _stall_moved(a, b) -> float:
    """How far the stall's list moved between two captures: the share (%) of pixels that turned from colourful to grey
    or back, or that are grey in both (dark gaps, white names and prices) but changed. Not the plain pixel difference:
    rainbow tiles animate their colours all the time (seen live: a stall at its end looked like it still moved, so the
    search scrolled on for a minute), but a scroll moves the tiles and the text on them."""
    if a.shape != b.shape:
        return 99.0
    h, w = a.shape[:2]
    area = (slice(int(0.15 * h), int(0.85 * h)), slice(int(0.15 * w), int(0.86 * w)))
    a, b = a[area].astype(int), b[area].astype(int)
    ca, cb = (a.max(2) - a.min(2)) > 40, (b.max(2) - b.min(2)) > 40
    text_moved = ~ca & ~cb & (np.abs(a - b).max(2) > 40)
    return 100 * float(((ca != cb) | text_moved).mean())


def _scroll_stall(hwnd: int, cfg, img, notches: int | None = None):
    """Scroll the stall's list down (up if notches < 0) and return the screen once it stopped gliding; None if nothing
    moved (the end)."""
    x0, y0, w, h = screen.client_rect(hwnd)
    if not controller.scroll(hwnd, x0 + w // 2, y0 + h // 2, cfg.stall_scroll_notches if notches is None else notches):
        raise Stopped("Roblox lost focus while scrolling the stall", img)
    for _ in range(6):  # up to 0.9 s: a slow start must not read as "the end"
        time.sleep(0.15)
        new = _look(hwnd, img)
        if _stall_moved(new, img) >= 1.0:
            break
    else:
        return None
    still = 0
    for _ in range(12):  # it is gliding: wait until it stands still twice in a row (the end of a glide is slow)
        time.sleep(0.15)
        cur = _look(hwnd, new)
        still = still + 1 if _stall_moved(cur, new) < 1.0 else 0
        new = cur
        if still >= 2:
            return cur
    return new


def after_teleport(hwnd: int, cfg, skin: str, low: int, high: int, save=lambda name, img: None) -> str:
    """Run the whole flow; returns what happened. Raises Stopped (nothing more sent) when a step fails.
    save(name, img) keeps the screen before every click and key hold (snipe_01_... in order)."""
    _steps.update(n=0, save=save, short=False, bought=False)
    # Arrived once the black "Teleporting..." screen has come and gone. Looked for from the click on, twice a second,
    # so a short one is not missed: the old list can stay up a while first, and a closed list alone proves nothing.
    seen_black, reconnects, img, start = False, 0, None, time.time()
    first_reconnect = None
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
        again = None if img is None else screens.find_reconnect(img)  # "Disconnected": Reconnect
        if again is not None:
            if reconnects >= MAX_RECONNECTS or (first_reconnect and time.time() - first_reconnect > LEAVE_AFTER):
                # Reconnect is not working: Leave closes Roblox (user decision 2026-11-21), and the run stops
                leave = screens.find_leave(img)
                if leave is None:
                    raise Stopped(f"still disconnected after {reconnects} Reconnect click(s), and no Leave button found", img)
                if not _click(hwnd, leave, img, "leave"):
                    raise Stopped(f"still disconnected after {reconnects} Reconnect click(s); the click on Leave was not "
                                  "sent (Roblox lost focus, or the window changed size)", img)
                raise Left(f"still disconnected after {reconnects} Reconnect click(s) in "
                           f"{time.time() - first_reconnect:.0f} s: clicked Leave, so Roblox closed", img)
            first_reconnect = first_reconnect or time.time()
            if not _click(hwnd, again, img, "reconnect"):
                raise Stopped("click on Reconnect not sent", img)
            seen_black, reconnects, start = False, reconnects + 1, time.time()  # a fresh join from here: wait for it again
            end = start + cfg.teleport_max_seconds
            time.sleep(cfg.snipe_click_pause)
            continue
        if img is not None:
            if _mostly_black(img):
                seen_black = True
            elif seen_black and img.std() >= 5:  # one flat colour (the grey of a reconnect) is not the world yet
                break
        # shortcut: 15 s is a guess at the longest wait for a teleport to start; raise it if real ones are missed
        if not seen_black and img is not None and time.time() > start + 15:
            if reconnects:  # not the old list: going back to scanning would click on a loading screen
                raise Stopped("no loading screen within 15 s of the Reconnect click", img)
            raise NotTeleported("no loading screen within 15 s: the Teleport click did nothing", img)
        if time.time() > end:
            why = "loading" if img is not None else f"Roblox not in front ({screen.foreground_title()!r} was)"
            raise Stopped(f"after {cfg.teleport_max_seconds} s the new server was still {why}", img)
        time.sleep(0.5)
    log.info("timing: the new server showed %.1f s after the Teleport click", time.time() - start)
    t_world = time.time()
    time.sleep(cfg.teleport_wait_seconds)  # the new world finishes drawing before the walk
    _shot("arrived", img)
    if reconnects:  # another server, at the map centre: close the news box shown on joining, then back to searching
        news, img = _wait(hwnd, min(NEWS_WAIT, cfg.snipe_step_timeout), lambda im: screens.snipe_button(im, "news_x"))
        if news is not None:
            _press(hwnd, cfg, "news_x")
        _back_to_search(hwnd, cfg, "reconnected after a disconnect, but the search menu did not open after walking",
                        "reconnected after a disconnect (on another server, away from the seller)")
    _hold(hwnd, W, cfg.walk_seconds)
    _hold(hwnd, S, cfg.back_seconds)  # only after stepping back does the "E Open" prompt show
    _hold(hwnd, E, cfg.hold_e_seconds)
    # The search menu has its red X where the stall's is (seen live: the seller had left, we were at the map centre,
    # and E opened the search menu, which was scrolled as if it were the stall): tell them apart first
    def opened(im):
        return "search" if screens.classify(im) == "collection" else screens.snipe_button(im, "stall_exit")
    exit_point, img = _wait(hwnd, cfg.snipe_step_timeout, opened)
    if exit_point == "search":
        _shot("search_menu_not_stall", img)
        raise SellerLeft("the seller left the server (the search menu opened, not a stall)")
    if exit_point is None:
        _shot("seller_not_at_stall", img)  # most likely the seller left the server: the Teleport put us at the map centre
        _back_to_search(hwnd, cfg, "the seller's stall did not open, and the search menu did not open after walking back",
                        "the seller left the server")
    t_stall = time.time()
    log.info("timing: stall open %.1f s after the world showed (wait, walk and hold E included)", t_stall - t_world)
    # the stall's X shows before its items and prices have loaded: keep looking a while before calling the item gone
    timers = []
    buy, img, scrolls = _find_in_stall(hwnd, cfg, skin, low, high, cfg.stall_load_seconds, timers)
    log.info("timing: item %s %.1f s after the stall opened", "found" if buy is not None else "not found",
             time.time() - t_stall)
    # Not found, but items listed a moment ago show "Available in N Secs" over their name: one of them may be it.
    # Wait for the next timer to run out (they can differ), look again from the top, and so on; every look reads the
    # timers again (a misread, or an item listed meanwhile)
    t_wait, due = time.time(), set()
    for _ in range(10):  # shortcut: at most 10 looks, against timers misread over and over
        due |= {t + n + 1 for t, read in timers for n in read.result() if n <= PENDING_MAX}
        due = {d for d in due if d > time.time() - 1}
        if buy is not None or not due:
            break
        when = min(due)
        time.sleep(max(0.0, when - time.time()))
        due = {d for d in due if d > when + 0.5}
        _stall_to_top(hwnd, cfg, img, scrolls)
        timers = []
        buy, img, scrolls = _find_in_stall(hwnd, cfg, skin, low, high, 2, timers)
        log.info("waited %.0f s for items listed just now: the item %s", time.time() - t_wait,
                 "is there" if buy is not None else "is not")
    waited = round(time.time() - t_wait) if time.time() - t_wait > 1 else 0
    gone = ("The item was gone from the stall" + (f" (waited {waited} s for items listed just now)" if waited else "")
            + "; nothing bought")
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
    _steps["bought"] = dry or (buy is not None and not _steps["short"])
    if not cfg.relist and not _steps["short"]:  # --loop, not the last snipe: rejoin() comes next, the stall is set up at the end
        return ("Dry run: stopped at the confirm box (cancelled), nothing bought" if dry else
                "Bought the item" if buy is not None else gone) + "."
    _press(hwnd, cfg, "inventory")
    _press(hwnd, cfg, "inventory_all")
    _press(hwnd, cfg, "inspect", screens.find_inspect)  # it moves with the item shown
    _press(hwnd, cfg, "sell_on_market")
    _press(hwnd, cfg, "claim_check")
    _hold(hwnd, E, cfg.hold_e_seconds)
    _press(hwnd, cfg, "same_items_check")
    done = ("Not enough cash (closed Roblox's Buy Robux box); nothing bought" if _steps["short"] else
            "Dry run: stopped at the confirm box (cancelled), nothing bought" if dry else
            "Bought the item" if buy is not None else gone)
    return done + ", then put your stall up again."
