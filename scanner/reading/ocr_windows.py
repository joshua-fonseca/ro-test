"""The OCR built into Windows (Windows.Media.Ocr, through the winrt Python packages) standing in for Tesseract.
Windows only. Benchmark branch only."""
import asyncio
import re
import threading

import cv2

from scanner.reading import ocr_backend

_engine = None
_lock = threading.Lock()  # the engine failed with E_FAIL when called from the scanner's reader threads at once


async def _recognize(png: bytes) -> str:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(bytearray(png))
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await _engine.recognize_async(bitmap)
    return "\n".join(line.text for line in result.lines)


def image_to_string(image, config: str) -> str:
    """Same call shape as pytesseract.image_to_string(image, config=...). A tessedit_char_whitelist in config is
    applied afterwards (Windows OCR has no such switch)."""
    global _engine
    if _engine is None:
        from winrt.windows.media.ocr import OcrEngine
        _engine = OcrEngine.try_create_from_user_profile_languages()
    ok, buf = cv2.imencode(".png", image)
    with _lock:
        text = asyncio.run(_recognize(buf.tobytes()))
    wl = re.search(r"tessedit_char_whitelist=(\S+)", config)
    if wl:
        text = "".join(ch for ch in text if ch in wl.group(1) or ch.isspace())
    return text


ocr_backend.install(image_to_string, "windows")
