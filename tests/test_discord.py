import json
import types
import urllib.error

import pytest

from scanner.logic import discord
from scanner.logic.config import Config

LINE = "[SECRET] [Prismatica Aurora ShadowDaggers] [#345] [6,000] [output/screenshots/matches/x.png]"
CFG = Config(discord_server="My Server", discord_channel="Sniper Alerts")


@pytest.fixture
def api(monkeypatch):
    """A fake Discord: records every request; the pool runs a send at once."""
    calls = []

    def request(method, path, token, body=None, content_type="application/json"):
        calls.append((method, path, body, content_type))
        if path == "/users/@me/guilds":
            return [{"id": "1", "name": "Other"}, {"id": "2", "name": "my server"}]
        if path == "/guilds/2/channels":
            return [{"id": "7", "name": "general", "type": 0}, {"id": "8", "name": "sniper-alerts", "type": 0},
                    {"id": "9", "name": "sniper-alerts", "type": 2}]
        return {}
    monkeypatch.setattr(discord, "_request", request)
    monkeypatch.setattr(discord, "_pool", types.SimpleNamespace(submit=lambda fn, *a: fn(*a)))
    monkeypatch.setattr(discord, "_channels", {})
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "t")
    return calls


def posts(calls):
    return [c for c in calls if c[0] == "POST"]


def test_nothing_is_sent_while_the_server_or_channel_is_empty(api):
    discord.notify(Config(discord_server="My Server"), LINE, "Bought the item")
    discord.notify(Config(), LINE, "Bought the item")
    assert api == []


def test_no_token_means_no_message_and_one_notice(api, monkeypatch, capsys):
    monkeypatch.delenv("DISCORD_BOT_TOKEN")
    monkeypatch.setattr(discord, "_told_no_token", False)
    discord.notify(CFG, LINE, "x")
    discord.notify(CFG, LINE, "x")
    assert api == [] and capsys.readouterr().out.count("DISCORD_BOT_TOKEN") == 1


def test_the_match_line_and_the_status_go_out_as_one_text_message(api):
    discord.notify(CFG, LINE, "Bought the item, then put your stall up again.")
    (_, path, body, kind), = posts(api)
    assert path == "/channels/8/messages" and kind == "application/json"  # the text channel, found by name in any case
    assert json.loads(body)["content"] == LINE + "\nBought the item, then put your stall up again."


def test_picture_mode_sends_the_card_picture_with_the_status(api, tmp_path, monkeypatch):
    (tmp_path / "x.png").write_bytes(b"PNGDATA")
    monkeypatch.chdir(tmp_path)
    line = LINE.replace("output/screenshots/matches/x.png", "x.png")
    discord.notify(Config(discord_server="my server", discord_channel="#sniper-alerts", discord_send="Picture"), line,
                   "The item was gone from the stall; nothing bought")
    (_, _, body, kind), = posts(api)
    assert kind.startswith("multipart/form-data") and b"PNGDATA" in body and b'filename="x.png"' in body
    assert b"The item was gone from the stall; nothing bought" in body and b"[SECRET]" not in body


def test_picture_mode_falls_back_to_text_when_the_picture_is_missing(api):
    discord.notify(Config(**{**CFG.__dict__, "discord_send": "picture"}), LINE, "Dry run: nothing bought")
    (_, _, body, kind), = posts(api)
    assert kind == "application/json" and LINE in json.loads(body)["content"]


def test_a_failed_send_prints_a_line_and_never_raises(api, monkeypatch, capsys):
    def boom(*a, **k):
        raise urllib.error.URLError("no network")
    monkeypatch.setattr(discord, "_request", boom)
    discord.notify(CFG, LINE, "x")
    assert "Discord message not sent" in capsys.readouterr().out


def test_an_unknown_server_or_channel_says_so(api, capsys):
    discord.notify(Config(discord_server="Nope", discord_channel="x"), LINE, "x")
    discord.notify(Config(discord_server="my server", discord_channel="nope"), LINE, "x")
    out = capsys.readouterr().out
    assert "not in a server called 'Nope'" in out and "no text channel called 'nope'" in out


def test_notify_never_raises_even_when_the_pool_is_gone(api, monkeypatch):
    def refuse(*a):
        raise RuntimeError("cannot schedule new futures after shutdown")
    monkeypatch.setattr(discord, "_pool", types.SimpleNamespace(submit=refuse))
    discord.notify(CFG, LINE, "x")  # must not raise
