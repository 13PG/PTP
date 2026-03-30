from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

import fitz

logger = logging.getLogger(__name__)

try:
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover - optional dependency
    np = None
    RapidOCR = None

_ocr_engine = None
_ocr_lock = Lock()


def is_ocr_available() -> bool:
    return RapidOCR is not None and np is not None


def extract_page_text_with_ocr(page: fitz.Page, zoom: float = 2.0) -> str:
    engine = _get_engine()
    if engine is None or np is None:
        return ""

    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        result, _ = engine(image)
    except Exception:
        logger.exception("OCR 页面失败: page=%s", page.number + 1)
        return ""

    if not result:
        return ""

    lines: list[tuple[float, float, str]] = []
    for item in result:
        if not item or len(item) < 3:
            continue
        box, text, score = item
        if not text or score < 0.45:
            continue
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        lines.append((min(ys), min(xs), text.strip()))

    if not lines:
        return ""

    lines.sort(key=lambda entry: (entry[0], entry[1]))
    grouped: list[list[str]] = []
    current_group: list[str] = []
    current_y = None

    for y, _, text in lines:
        if current_y is None or abs(y - current_y) <= 18:
            current_group.append(text)
        else:
            grouped.append(current_group)
            current_group = [text]
        current_y = y

    if current_group:
        grouped.append(current_group)

    return "\n".join(" ".join(group) for group in grouped if group)


def _get_engine():
    global _ocr_engine
    if not is_ocr_available():
        return None
    if _ocr_engine is not None:
        return _ocr_engine

    with _ocr_lock:
        if _ocr_engine is None:
            _ocr_engine = RapidOCR()
    return _ocr_engine
