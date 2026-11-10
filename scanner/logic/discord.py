"""Optional Discord message, one per run of main.py: when the run started, each weapon found with what became of it
(bought, gone, seller left...), and how the run ended. The message is edited as the run goes on.

Off unless config.json sets both discord_server and discord_channel. The bot token is never stored in a file: it is
read from the DISCORD_BOT_TOKEN environment variable. Messages go out on a background thread, so the scan never waits
for Discord, and a failure only prints a line and logs a warning. Standard library only (Discord's REST API).
"""
from datetime import datetime
import json
import logging
import os
import re
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/joshua-fonseca/ro-test, 1)"  # Discord turns away the default Python one
_pool = ThreadPoolExecutor(max_workers=1)  # messages stay in order; the interpreter waits for them at exit
_channels: dict[tuple[str, str], str] = {}  # (server, channel) as typed, lower case -> channel id
_told_no_token = False
_run = {"on": False, "lines": [], "found": 0, "id": None, "files": []}  # this run's message: its lines, id, attachment ids
MAX_FILES = 10  # Discord's limit of attachments on one message


def _request(method: str, path: str, token: str, body: bytes | None = None, content_type: str = "application/json"):
    req = urllib.request.Request(API + path, data=body, method=method, headers={
        "Authorization": f"Bot {token}", "User-Agent": USER_AGENT, "Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read() or b"null")


def _channel_id(token: str, server: str, channel: str) -> str:
    key = (server.strip().casefold(), re.sub(r"\s+", "-", channel.strip().casefold().lstrip("#")))  # Discord: "my-channel"
    if key not in _channels:
        servers = [g for g in _request("GET", "/users/@me/guilds", token) if g["name"].casefold() == key[0]]
        if not servers:
            raise LookupError(f"the bot is not in a server called {server!r}")
        found = [c for c in _request("GET", f"/guilds/{servers[0]['id']}/channels", token)
                 if c.get("type") == 0 and c["name"].casefold() == key[1]]  # type 0: a text channel
        if not found:
            raise LookupError(f"no text channel called {channel!r} in {server!r} (can the bot see it?)")
        _channels[key] = found[0]["id"]
    return _channels[key]


def _multipart(payload: dict, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
            f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n"
            f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n").encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def stamp(when: datetime | None = None) -> str:
    """'19:22, Nov 11 2026'"""
    t = when or datetime.now()
    return f"{t:%H:%M}, {t:%b} {t.day} {t.year}"


def _content(lines: list[str]) -> str:
    """The first line (when the run started) and as many of the latest lines as fit in Discord's 2000 characters."""
    keep = []
    for line in reversed(lines[1:]):
        if len(lines[0]) + sum(len(k) + 1 for k in keep) + len(line) + 1 > 1990:
            keep.append("...")
            break
        keep.append(line)
    return "\n".join([lines[0], *reversed(keep)])


def _sync(token: str, server: str, channel: str, lines: list[str], picture: Path | None) -> None:
    """Post the run's message the first time, then edit it to show `lines` (and add `picture`, if given)."""
    try:
        path = f"/channels/{_channel_id(token, server, channel)}/messages"
        payload = {"content": _content(lines)}
        if picture is not None and picture.is_file() and len(_run["files"]) < MAX_FILES:
            payload["attachments"] = [{"id": f} for f in _run["files"]] + [{"id": 0, "filename": picture.name}]
            body, kind = _multipart(payload, picture.name, picture.read_bytes())
        else:
            body, kind = json.dumps(payload).encode(), "application/json"
        message = None
        if _run["id"] is not None:
            try:
                message = _request("PATCH", f"{path}/{_run['id']}", token, body, kind)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                _run["files"] = []  # the message was deleted in Discord: post a new one with everything so far
                if picture is not None and picture.is_file():
                    payload["attachments"] = [{"id": 0, "filename": picture.name}]
                    body, kind = _multipart(payload, picture.name, picture.read_bytes())
        if message is None:
            message = _request("POST", path, token, body, kind)
        _run["id"], _run["files"] = message["id"], [a["id"] for a in message.get("attachments", [])]
    except urllib.error.HTTPError as e:
        why = f"Discord said {e.code}: {e.read().decode(errors='replace')[:200]}"
        log.warning("Discord message not sent: %s", why)
        print(f"Discord message not sent: {why}")
    except Exception as e:  # never let a message take the scan down
        log.warning("Discord message not sent: %r", e)
        print(f"Discord message not sent: {e}")


def _update(cfg, add: list[str], picture: Path | None = None, start: bool = False) -> None:
    """Add lines to this run's message (a new message when `start`). Does nothing unless the server and channel are
    set in the config. Never raises: it is called mid-snipe, where an error would look like a crashed snipe."""
    global _told_no_token
    try:
        if not (cfg.discord_server and cfg.discord_channel) or not (start or _run["on"]):
            return
        token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            if not _told_no_token:
                _told_no_token = True
                print("Discord: the DISCORD_BOT_TOKEN environment variable is not set; no messages will be sent.")
            return
        if start:
            _run.update(on=True, lines=[], found=0, id=None, files=[])
        _run["lines"] += add
        _pool.submit(_sync, token, cfg.discord_server, cfg.discord_channel, list(_run["lines"]), picture)
    except Exception as e:
        log.warning("Discord message not queued: %r", e)


def start(cfg, title: str) -> None:
    """A new message for this run: `title` and the time, e.g. 'Run started 19:22, Nov 11 2026 (--snipe)'."""
    _update(cfg, [title], start=True)


def notify(cfg, line: str, status: str = "") -> None:
    """Add a weapon found: `line` ('[SECRET] [Skin] [#345] [6,000] [output/...png]') and what became of it. With
    discord_send "picture" the card's picture is attached and the line is shown without its file path."""
    shot = re.search(r" ?\[([^\[\]]*)\]$", line)  # a match line ends with [screenshot path]
    picture = cfg.discord_send.strip().casefold() == "picture" and shot is not None
    _run["found"] += 1
    _update(cfg, [part for part in (line[:shot.start()] if picture else line, status) if part],
            Path(shot.group(1)) if picture else None)


def finish(cfg, how: str) -> None:
    """The last line: how the run ended, and the time."""
    _update(cfg, [f"{how}{'' if _run['found'] else ' No match found.'} ({stamp()})"])
