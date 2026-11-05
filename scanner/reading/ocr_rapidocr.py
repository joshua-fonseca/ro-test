"""RapidOCR (PaddleOCR models on onnxruntime, CPU) standing in for Tesseract. Benchmark branch only."""
import re

import cv2

from scanner.reading import ocr_backend

_engine = None


def image_to_string(image, config: str) -> str:
    """Same call shape as pytesseract.image_to_string(image, config=...): the text found, lines joined by newlines.
    A tessedit_char_whitelist in config is applied afterwards (RapidOCR has no such switch)."""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    img = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image
    if "--psm 7" in config:  # one line, already cropped: recognition only (no text detection), as Tesseract's psm 7
        result, _ = _engine(img, use_det=False, use_cls=False)
        text = "\n".join(r[0] for r in result) if result else ""
    else:
        result, _ = _engine(img)
        text = "\n".join(r[1] for r in result) if result else ""
    wl = re.search(r"tessedit_char_whitelist=(\S+)", config)
    if wl:
        text = "".join(ch for ch in text if ch in wl.group(1) or ch.isspace())
    return text


ocr_backend.install(image_to_string, "rapidocr")
