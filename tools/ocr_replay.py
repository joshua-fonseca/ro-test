"""Replay the recorded OCR calls (benchmarks/ocr_samples.pkl.gz, made by the Tesseract baseline) one after another with
whatever backend this branch installs: mean and 95th-percentile time per call, and how often the text agrees with
Tesseract's (letters and digits only, ignoring case). Run: python tools/ocr_replay.py"""
import gzip
import pickle
import sys
import time
from pathlib import Path

import pytesseract

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scanner.reading import ocr_backend, vision  # noqa: E402,F401  (the import installs this branch's backend)


def letters(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def main() -> None:
    with gzip.open(Path(__file__).resolve().parents[1] / "benchmarks" / "ocr_samples.pkl.gz", "rb") as f:
        samples = pickle.load(f)
    for image, config, _ in samples[:3]:  # warm-up: model load, first call
        pytesseract.image_to_string(image, config=config)
    times, agree = [], 0
    for image, config, ref in samples:
        start = time.perf_counter()
        out = pytesseract.image_to_string(image, config=config)
        times.append(time.perf_counter() - start)
        agree += letters(out) == letters(ref)
    times.sort()
    print(f"backend={ocr_backend._stats['backend']} samples={len(samples)} mean_ms={1000 * sum(times) / len(times):.0f} "
          f"p95_ms={1000 * times[int(0.95 * len(times))]:.0f} agree_with_tesseract={100 * agree / len(samples):.0f}%")


if __name__ == "__main__":
    main()
