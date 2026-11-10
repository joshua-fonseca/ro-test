import json
import types
import urllib.error
from datetime import datetime

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
        files = json.loads(body.split(b"\r\n\r\n", 1)[1].split(b"\r\n", 1)[0]).get("attachments", []) \
            if content_type.startswith("multipart") else []
        return {"id": "55", "attachments": [{"id": f"a{i}"} for i, _ in enumerate(files)]}
    monkeypatch.setattr(discord, "_request", request)
    monkeypatch.setattr(discord, "_pool", types.SimpleNamespace(submit=lambda fn, *a: fn(*a)))
    monkeypatch.setattr(discord, "_channels", {})
    monkeypatch.setattr(discord, "_run", {"on": False, "lines": [], "found": 0, "id": None, "files": []})
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "t")
    return calls


def sent(calls):
    return [(c[0], c[1], json.loads(c[2]) if c[3] == "application/json" else c[2]) for c in calls if c[0] != "GET"]


def test_the_time_reads_like_19_22_nov_11_2026():
    assert discord.stamp(datetime(2026, 11, 1, 9, 5)) == "09:05, Nov 1 2026"


def test_nothing_is_sent_while_the_server_or_channel_is_empty(api):
    for cfg in (Config(discord_server="My Server"), Config()):
        discord.start(cfg, "Run started")
        discord.notify(cfg, LINE, "Bought the item")
        discord.finish(cfg, "Run ended.")
    assert api == []


def test_no_token_means_no_message_and_one_notice(api, monkeypatch, capsys):
    monkeypatch.delenv("DISCORD_BOT_TOKEN")
    monkeypatch.setattr(discord, "_told_no_token", False)
    discord.start(CFG, "Run started")
    discord.notify(CFG, LINE, "x")
    assert api == [] and capsys.readouterr().out.count("DISCORD_BOT_TOKEN") == 1


def test_one_message_per_run_edited_with_each_outcome_and_the_end(api):
    discord.start(CFG, "Run started 19:22, Nov 11 2026 (--snipe)")
    discord.notify(CFG, LINE, "the seller left the server; walked back. Nothing bought. Going on.")
    discord.notify(CFG, LINE, "Bought the item, then put your stall up again.")
    discord.finish(CFG, "Finished: the stall is up again.")
    calls = sent(api)
    assert [(m, p) for m, p, _ in calls] == [("POST", "/channels/8/messages")] + [("PATCH", "/channels/8/messages/55")] * 3
    last = calls[-1][2]["content"].split("\n")
    assert last[0] == "Run started 19:22, Nov 11 2026 (--snipe)" and last[1:5] == [
        LINE, "the seller left the server; walked back. Nothing bought. Going on.",
        LINE, "Bought the item, then put your stall up again."]
    assert last[5] == "Finished: the stall is up again." and last[6].startswith("Run ended: ")


def test_a_run_with_no_match_says_so_and_a_new_run_is_a_new_message(api):
    discord.start(CFG, "Run started")
    discord.finish(CFG, "Finished 1 pass(es).")
    assert sent(api)[-1][2]["content"].split("\n")[1:] == ["Finished 1 pass(es). No match found.",
                                                          f"Run ended: {discord.stamp()}"]
    discord.start(CFG, "Run started")
    discord.finish(CFG, "Stopped with Ctrl+C.", early=True)
    assert sent(api)[-1][2]["content"].split("\n")[1:] == ["Stopped with Ctrl+C.", f"Run ended early: {discord.stamp()}"]
    discord.start(CFG, "Run started again")
    assert sent(api)[-1][0] == "POST"


def test_picture_mode_attaches_each_card_picture_and_keeps_the_earlier_ones(api, tmp_path, monkeypatch):
    for name in ("x.png", "y.png"):
        (tmp_path / name).write_bytes(b"PNG" + name.encode())
    monkeypatch.chdir(tmp_path)
    cfg = Config(discord_server="my server", discord_channel="#sniper-alerts", discord_send="Picture")
    discord.start(cfg, "Run started")
    discord.notify(cfg, "[SECRET] [A] [#1] [6,000] [x.png]", "The item was gone from the stall; nothing bought")
    discord.notify(cfg, "[SECRET] [B] [#2] [7,000] [y.png]", "Bought the item")
    first, second = [c for c in api if c[3].startswith("multipart")]
    assert b"PNGx.png" in first[2] and b"[SECRET] [A] [#1] [6,000]\\nThe item was gone" in first[2]
    assert b"x.png]" not in first[2]  # the file path is left out: the picture is there instead
    assert b'"id": "a0"' in second[2] and b"PNGy.png" in second[2]  # the first picture is kept on the edit


def test_a_failed_send_prints_a_line_and_never_raises(api, monkeypatch, capsys):
    def boom(*a, **k):
        raise urllib.error.URLError("no network")
    monkeypatch.setattr(discord, "_request", boom)
    discord.start(CFG, "Run started")
    assert "Discord message not sent" in capsys.readouterr().out


def test_an_unknown_server_or_channel_says_so(api, capsys):
    discord.start(Config(discord_server="Nope", discord_channel="x"), "Run started")
    discord.start(Config(discord_server="my server", discord_channel="nope"), "Run started")
    out = capsys.readouterr().out
    assert "not in a server called 'Nope'" in out and "no text channel called 'nope'" in out


def test_notify_never_raises_even_when_the_pool_is_gone(api, monkeypatch):
    discord.start(CFG, "Run started")
    def refuse(*a):
        raise RuntimeError("cannot schedule new futures after shutdown")
    monkeypatch.setattr(discord, "_pool", types.SimpleNamespace(submit=refuse))
    discord.notify(CFG, LINE, "x")  # must not raise


def test_a_long_run_keeps_the_start_and_the_latest_lines_under_2000_characters():
    lines = ["Run started"] + [f"line {i} " + "x" * 50 for i in range(100)]
    text = discord._content(lines)
    assert len(text) <= 2000 and text.startswith("Run started\n...") and text.endswith(lines[-1])


def test_a_message_deleted_in_discord_is_posted_again(api, monkeypatch):
    discord.start(CFG, "Run started")
    real = discord._request

    def gone(method, path, token, body=None, content_type="application/json"):
        if method == "PATCH":
            api.append((method, path, body, content_type))
            raise urllib.error.HTTPError(path, 404, "Unknown Message", {}, None)
        return real(method, path, token, body, content_type)
    monkeypatch.setattr(discord, "_request", gone)
    discord.notify(CFG, LINE, "Bought the item")
    method, _, body = sent(api)[-1]
    assert method == "POST" and body["content"] == "Run started\n" + LINE + "\nBought the item"
