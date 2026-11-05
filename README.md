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

4. Update later with `git pull` (if the repo changes).
   - If it refuses because of a local `targets.csv` change, commit it or run `git checkout targets.csv` first.

## Choose what to scan: `targets.csv`

One row per skin: `skin_name,category,rarity,max_price,max_serial,enabled`.

```
Wild Fiend Crossbow,Sniper,Limited,15,,true
Nocturne M200 [Rainbow],Sniper,Secret,7500,,false
```

- `category` is `Sniper` or `Knife`.
- `rarity` is `Secret` or `Limited` (the scanner clicks that filter first).
- `max_serial` can be empty.
- Only rows with `enabled=true` and a `max_price` are scanned. A row with the wrong number of columns is skipped (a warning goes to `output/run.log`).

## Run

1. Open the game, log in, join S.Arena, go to the trading market and go to the Search Menu. Don't type anything or change any filters.
2. In PowerShell, from the `ro-test` folder:

```powershell
# scan only (read-only: nothing is bought)
& $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe main.py --width 1900

# rehearsal: teleport and do every step but the buy (the confirm box is cancelled)
& $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe main.py --snipe --dry-run --width 1900

# for real: buy on the first match, then put your own stall up again, then stop
& $env:USERPROFILE\.venvs\ro-test\Scripts\python.exe main.py --snipe --width 1900
```

3. Press `y` + Enter when asked, then click on the game window and take your hands off the
   mouse and keyboard. The game must stay in front: if it loses focus the scanner pauses and sends nothing.
4. Stop with **Ctrl+C**.

Commonly used flags:

| Flag | Meaning |
|---|---|
| `--snipe` | on the first match: Teleport, buy from the seller's stall, relist your own stall, stop |
| `--dry-run` | with `--snipe`: everything except the buy (the confirm box is cancelled) |
| `--width N` / `--height N` | first resize every game window so the game area is N px wide / high (16:9). Run it once per session. 1900 works on a 1920x1200 screen |

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
