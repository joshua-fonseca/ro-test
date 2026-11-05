# OCR benchmark: Tesseract vs RapidOCR vs Windows OCR

Branches: `bench/ocr-tesseract` (baseline), `bench/ocr-rapidocr`, `bench/ocr-windows`. Each branch swaps the one OCR call
the scanner makes (`pytesseract.image_to_string`, hooked in `scanner/reading/ocr_backend.py`) for another engine, with
everything else unchanged. Measured 2026-11-05 on this machine (WSL for Tesseract and RapidOCR, Windows Python for
Windows OCR and a Windows Tesseract run).

How to repeat: `pytest -q` (accuracy proxy: how many of the 266 tests, which read saved game screenshots, still pass;
the run writes `benchmarks/<backend>_stats.txt`), then `python tools/ocr_replay.py` (122 recorded OCR calls, one at a
time: mean and 95th-percentile time, and how often the letters/digits equal Tesseract's).

| | Tesseract (WSL) | RapidOCR (WSL) | Windows OCR | Tesseract (Windows) |
|---|---|---|---|---|
| Tests passing | 266 / 266 | 262 / 266 | 238 / 266 | 266 / 266 |
| Suite wall time | 2 m 26 s | 2 m 53 s | 1 m 29 s | 2 m 56 s |
| OCR calls in the suite | 1,957 | 1,927 | 2,012 | 1,959 |
| One call at a time, mean | 128 ms | 78 ms (p95 666 ms) | 9 ms (p95 13 ms) | 152 ms |
| Same text as Tesseract (122 samples) | 100 % | 89 % | 44 % | 94 % |
| CPU time for the suite (user) | 7 m 23 s | 27 m 4 s | not measured | not measured |

## What it shows
- **RapidOCR** (PaddleOCR models, onnxruntime, CPU): single-line reads are faster (recognition only, no text
  detection), but calls that need detection (psm 6) are slow (p95 0.7 s), and it uses about 3.7 times the CPU of
  Tesseract (onnxruntime runs many threads per call). 4 tests fail: the serial `101` next to the bracket, the small-window
  Search Options label, and two stall price reads.
- **Windows OCR** (Windows.Media.Ocr): about 14 times faster per call than Tesseract, but 28 tests fail: serials (`#ST.123`
  with brackets), prices and card text from small stylised crops. It has no character whitelist or single-line mode, so it
  is not a drop-in. It had to be called one at a time (E_FAIL from several threads). Windows only, so the WSL tests could
  not use it.
- **Caveat:** the image preparation (thresholds, crops, upscaling) in `vision.py` and `screens.py` was tuned for
  Tesseract, which favours it. "Same text as Tesseract" measures agreement, not truth; the passing-tests count is the
  better accuracy proxy.
- **Not measured:** how much of a live scan is OCR (a frame read takes about 1 s in `run.log`, including scrolling), so
  the real-world gain from a faster engine is unknown. EasyOCR/PaddleOCR proper (PyTorch/Paddle, large installs) and
  `tesserocr` were not tried.

## Suggestion
Keep Tesseract. If speed is the goal, first split a live scan's time into OCR, scrolling and screen capture. A faster
engine could then be tried for the plain-text reads only (titles, skin names), with Tesseract kept for serials and prices.
