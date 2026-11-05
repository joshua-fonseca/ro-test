"""OCR hook for the benchmark branches (bench/ocr-*): every image_to_string call in the scanner goes through here, so
a backend can be swapped in one place and each run reports how many OCR calls it made and how long they took.
Baseline: Tesseract. Stats are written to benchmarks/<backend>_stats.txt when the process ends."""
import atexit
import gzip
import os
import pickle
import threading
import time
from pathlib import Path

import pytesseract

_real = pytesseract.image_to_string
_lock = threading.Lock()
_stats = {"backend": "tesseract", "calls": 0, "seconds": 0.0}
_samples: list = []  # with OCR_RECORD=1: every 16th call as (image, config, output), saved by _report for tools/ocr_replay.py


def install(fn, name: str) -> None:
    """Make every pytesseract.image_to_string(image, config=...) call use fn(image, config), timed."""
    _stats["backend"] = name

    def timed(image, config="", **kw):
        start = time.perf_counter()
        out = fn(image, config)
        took = time.perf_counter() - start
        with _lock:
            _stats["calls"] += 1
            _stats["seconds"] += took
            if os.environ.get("OCR_RECORD") and _stats["calls"] % 16 == 0:
                _samples.append((image.copy(), config, out))
        return out
    pytesseract.image_to_string = timed


@atexit.register
def _report() -> None:
    if not _stats["calls"]:
        return
    line = (f"backend={_stats['backend']} ocr_calls={_stats['calls']} ocr_seconds={_stats['seconds']:.1f} "
            f"mean_ms={1000 * _stats['seconds'] / _stats['calls']:.0f}")
    out = Path(__file__).resolve().parents[2] / "benchmarks"
    out.mkdir(exist_ok=True)
    with open(out / f"{_stats['backend']}_stats.txt", "w", encoding="utf-8") as f:
        f.write(line + "\n")
    if _samples:
        with gzip.open(out / "ocr_samples.pkl.gz", "wb") as f:
            pickle.dump(_samples, f)


install(lambda image, config: _real(image, config=config), "tesseract")
