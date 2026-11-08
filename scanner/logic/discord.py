"""Optional Discord message about a weapon the scanner found, with what became of it (bought, gone, seller left...).

Off unless config.json sets both discord_server and discord_channel. The bot token is never stored in a file: it is
read from the DISCORD_BOT_TOKEN environment variable. Messages go out on a background thread, so the scan never waits
for Discord, and a failure only prints a line and logs a warning. Standard library only (Discord's REST API).
"""
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


def _send(token: str, server: str, channel: str, picture: bool, line: str, status: str) -> None:
    try:
        path = f"/channels/{_channel_id(token, server, channel)}/messages"
        shot = re.search(r"\[([^\[\]]*)\]$", line)  # a match line ends with [screenshot path]
        file = Path(shot.group(1)) if picture and shot else None
        if file is not None and file.is_file():
            body, kind = _multipart({"content": status[:1900]}, file.name, file.read_bytes())  # the picture, then the status
        else:
            body, kind = json.dumps({"content": "\n".join(part for part in (line, status) if part)[:1900]}).encode(), "application/json"
        _request("POST", path, token, body, kind)
    except urllib.error.HTTPError as e:
        why = f"Discord said {e.code}: {e.read().decode(errors='replace')[:200]}"
        log.warning("Discord message not sent: %s", why)
        print(f"Discord message not sent: {why}")
    except Exception as e:  # never let a message take the scan down
        log.warning("Discord message not sent: %r", e)
        print(f"Discord message not sent: {e}")


def notify(cfg, line: str, status: str = "") -> None:
    """Send `line` (the match line, e.g. '[SECRET] [Skin] [#345] [6,000] [output/...png]') or its picture, then `status`.
    Does nothing unless the server and channel are set in the config."""
    global _told_no_token
    try:  # called mid-snipe, after Teleport: whatever goes wrong here must not look like a crashed snipe
        if not (cfg.discord_server and cfg.discord_channel):
            return
        token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            if not _told_no_token:
                _told_no_token = True
                print("Discord: the DISCORD_BOT_TOKEN environment variable is not set; no messages will be sent.")
            return
        _pool.submit(_send, token, cfg.discord_server, cfg.discord_channel,
                     cfg.discord_send.strip().casefold() == "picture", line, status)
    except Exception as e:
        log.warning("Discord message not queued: %r", e)
