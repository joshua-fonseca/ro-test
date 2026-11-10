# ro-test: S.Arena scanner

Scans the S.Arena market in the game for skins in `targets.csv` that are at or below your price, and can
teleport to the seller and buy the item (`--snipe`). It reads the screen with OCR and sends normal mouse and
keyboard input. No injection, executors or game APIs. You log in yourself; no passwords or tokens are stored.

It runs on **Windows** (it captures the screen and sends input). The logic and tests also run in WSL/Linux.

## Set up on Windows

1. Install the three programs (Python 3.10 or newer; tested on 3.12, which the commands below install). Easiest: open PowerShell and run these (Windows 10/11 has `winget`), then close
   and reopen PowerShell so the new programs are found:

```powershell
winget install --id Python.Python.3.12 -e
winget install --id Git.Git -e
winget install --id UB-Mannheim.TesseractOCR -e
```

<details>
<summary>Or install by hand</summary>

- Python: python.org (tick "Add python.exe to PATH").
- Git: git-scm.com.
- Tesseract OCR: the UB Mannheim Windows build (5.x), from github.com/UB-Mannheim/tesseract/wiki.
  - Keep it in its default folder: the scanner looks for `C:\Program Files\Tesseract-OCR\tesseract.exe` (it is not on PATH).
  - The default English language data is enough.

</details>

2. Check them (each should print a version, and the last should print `True`):

```powershell
python --version
git --version
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version
Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

3. Get the code, make a virtual environment, and install the Python packages (PowerShell):

```powershell
cd $env:USERPROFILE
git clone https://github.com/joshua-fonseca/ro-test.git
cd ro-test
python -m venv $env:USERPROFILE\.venvs\ro-test
& $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe -m pip install -r requirements.txt
```

   `requirements.txt` installs:
   - `pillow`: screenshots of the game.
   - `opencv-python-headless` and `numpy`: image matching.
   - `pytesseract`: the link to Tesseract.

4. Make your own skin lists: copy `targets.example.csv` to `targets.csv` and `dry_targets.example.csv` to `dry_targets.csv`, then edit them (next section).
   Both are ignored by git, so they stay on your machine and `git pull` never touches them.

```powershell
copy targets.example.csv targets.csv
copy dry_targets.example.csv dry_targets.csv
```

5. Update later with `git pull` (if the repo changes).

## Choose what to scan: `targets.csv`

One row per skin: `skin_name,category,rarity,max_price,max_serial,enabled`.
Use the full name as the game shows it: `Nya Machete` and `Nya Machete [Rainbow]` are two different skins.

```
Wild Fiend Crossbow,Sniper,Limited,15,,true
Nocturne M200 [Rainbow],Sniper,Secret,7500,,false
```

- `category` is `Sniper`, `Knife` or `Glove`.
- `rarity` is `Secret` (or `scrt`) or `Limited` (or `ltd`); the scanner clicks that filter first.
- Capital letters don't matter anywhere (`SCRT`, `Ltd`, `sniper` all work, and so do the column names in the first line).
- `max_serial` can be empty.
- `enabled` is `true` or `t` to scan the row, `false` or `f` to skip it. Only enabled rows with a `max_price` are scanned. A row with the wrong number of columns is skipped (a warning goes to `output/run.log`).
- `dry_targets.csv` (copied from `dry_targets.example.csv`) has the same columns and is read instead of `targets.csv` with `--dry-run`, so a rehearsal can use its own skins.
  - Test the items you want to snipe first: put them in `dry_targets.csv` with a high `max_price`, so a listing matches and a `--dry-run` goes through every step.

## Run

1. Open the game, go to the trading market, join the smallest server, then go to the Search Menu. Don't type anything or change any filters.
2. In PowerShell, from the `ro-test` folder. Always add `--width 1900`: it is the only window size the scanner is reliable at so far (other sizes, such as 1700, are not supported yet). It needs a screen 1920 px wide.

```powershell
# scan only (read-only: nothing is bought). Reads targets.csv
& $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe main.py --width 1900

# rehearsal: teleport and do every step but the buy (the confirm box is cancelled).
# Reads dry_targets.csv, NOT targets.csv: its max_price is the one that counts
& $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe main.py --snipe --dry-run --width 1900

# for real: buy on the first match, then put your own stall up again, then stop. Reads targets.csv
& $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe main.py --snipe --width 1900
```

3. Press `y` + Enter when asked, then click on the game window and take your hands off the
   mouse and keyboard. The game must stay in front: if it loses focus the scanner pauses and sends nothing.
4. Stop with **Ctrl+C**.

Commonly used flags:

| Flag | Meaning |
|---|---|
| `--snipe` | on the first match: Teleport, buy from the seller's stall, relist your own stall, stop |
| `--dry-run` | with `--snipe`: everything except the buy (the confirm box is cancelled). Reads `dry_targets.csv` instead of `targets.csv` |
| `--width N` / `--height N` | first resize every game window so the game area is N px wide / high (16:9). Run it once per session. Use 1900: the only size that is reliable so far |

Less used options:

| Flag | Meaning |
|---|---|
| `--wait N` | seconds to click the game's title bar (default 30) |
| `--cycles N` | stop after N passes over `targets.csv` (default: until Ctrl+C) |
| `--clear-matches` | delete `matches.csv` and the saved match pictures first |

The window must be 16:9 (the layout is measured in fractions of it). With several game windows `--width` resizes them all.

## Safety rules

- Without `--snipe` the scanner is read-only.
- Only `--snipe` clicks Teleport, the buy button and its confirm check, and the Sell on Market / stall steps.
- It never clicks the game's "Buy ... and item" box's Buy button (that charges real money). Only that box's X is clicked.
- `--dry-run` first: check the saved pictures in `output/probe/` (`snipe_NN_<step>.png`) before a real buy.

## Output (in `output/`, not committed)

- `run.log`: what happened, one line per click.
- `matches.csv` and the match pictures.
- `probe/`: step pictures. When a step fails, look at the last `snipe_NN_*.png` or `nav_*.png`.

## Settings

Optional `config.json` next to `main.py` overrides the defaults in `scanner/logic/config.py` (waits, holds, scroll
counts). Unknown keys are ignored.

- Example `config.json`: the Teleport wait is 60 s by default; this gives a slow server 120 s before the run stops.

```json
{"teleport_max_seconds": 120}
```

## Discord messages (optional)

Each time you start `main.py`, the scanner posts **one new message** in a Discord channel and keeps editing it as the run goes on:

- when the run started, e.g. `Run started 19:22, Nov 11 2026 (--snipe)`,
- each weapon found and what became of it: bought, gone from the stall, the seller left, a stop that needs you, and so on,
- how the run ended: `Run ended: finished, the stall is up again.` after a snipe that went through, or `Run ended early: ...` with the reason (the snipe stopped part way, scans kept failing, Ctrl+C...), with the time, and `No match found.` if nothing was found.

Leave the Discord settings empty and nothing is sent. A `--dry-run` posts too (its first line says `--snipe --dry-run`).

You need a Discord server where you can add bots (your own server is fine). Do steps 1-4 once.

**1. Make the bot**
1. Go to https://discord.com/developers/applications and log in.
2. Click **New Application**, give it a name, and accept.
3. In the left menu click **Bot**. Click **Reset Token**, then **Copy**. This is the token: keep it private and don't paste it anywhere public (anyone with it controls your bot). You can click Reset Token again any time to get a new one.

**2. Add the bot to your server**
1. In the left menu click **OAuth2**, then find **URL Generator**.
2. Under Scopes tick **bot**.
3. Under Bot Permissions tick **View Channels**, **Send Messages** and **Attach Files**.
4. Copy the link at the bottom, open it in your browser, pick your server and click **Authorize**. The bot now shows in the server's member list (offline is fine).

**3. Pick the channel**
Make a text channel for the alerts (for example `sniper-alerts`). If the channel is private, add the bot to it (channel settings, Permissions, add the bot's name) with View Channel, Send Messages and Attach Files allowed.

**4. Tell the scanner where to post.** Make `config.json` next to `main.py` (copy this, then change the names):

```json
{"discord_server": "My Server", "discord_channel": "sniper-alerts", "discord_send": "picture"}
```

- `discord_server`: the server's name exactly as shown in Discord (capital letters don't matter).
- `discord_channel`: the channel's name without the `#` (capital letters don't matter, and a space counts as `-`).
- `discord_send`: `"text"` sends the match line, `"picture"` sends the picture of the card. The status follows either way. If left out it is `"text"`.

**5. Give PowerShell the token, each time you start (or keep it).** The token is never saved in a project file; the scanner reads it from the `DISCORD_BOT_TOKEN` environment variable.
- For the current PowerShell window only: `$env:DISCORD_BOT_TOKEN = "paste the token here"`, then run the scanner from the same window.
- To keep it for every new window: `setx DISCORD_BOT_TOKEN "paste the token here"`, then close PowerShell and open a new one.

**6. Check it works.** Run `main.py --snipe --dry-run --width 1900` with a skin that has a listing. A message should show up in the channel as soon as you click the game window, and be edited as the run goes on. If not, the console prints one line saying why:
- `the DISCORD_BOT_TOKEN environment variable is not set`: do step 5 in the same window you run the scanner from.
- `the bot is not in a server called ...`: check `discord_server` is spelled like the server's name, and that step 2 was done.
- `no text channel called ...`: check `discord_channel`, and that the bot can see the channel (step 3).
- `Discord said 401`: the token is wrong; reset it and copy it again. `Discord said 403`: the bot is missing a permission in that channel.

A message looks like this (with `"discord_send": "text"`; with `"picture"` each card's picture is attached and the line has no file path):

```
Run started 19:22, Nov 11 2026 (--snipe)
[SECRET] [Prismatica Aurora ShadowDaggers] [#345] [6,000] [output/screenshots/matches/...png]
Bought the item, then put your stall up again.
Run ended: finished, the stall is up again. (19:23, Nov 11 2026)
```

If the message can't be sent or edited, one line in the console says why and the scan carries on.

## Develop and test (WSL or Linux)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
sudo apt install python3-venv tesseract-ocr   # Debian/Ubuntu; Tesseract is found on PATH there
.venv/bin/python -m pytest -q
```

Code that captures the screen or sends input lives in `scanner/windows/` and only runs on Windows. Everything else
(parsing, matching, reading screenshots, storage) is OS-independent and tested against saved screenshots.
You can also run the Windows Python from WSL:
`powershell.exe -c '& $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe \\wsl.localhost\Ubuntu\home\kkura\repos\ro-test\main.py --cycles 1'`
