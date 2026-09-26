"""Lens: fast on-device OCR (RapidOCR / PP-OCR, ONNX on CPU).

Understanding an image ("what is this?", "translate this sign") goes through
the chat pipeline with the photo attached, so the vision model can look at it
and the answer is saved like any other message. This module provides the
instant text layer shown over photos.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from pathlib import Path

import numpy as np

from . import log

L = log.get("lens")


class LensService:
    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()

    def _ocr(self):
        if self._engine is None:
            from rapidocr import RapidOCR

            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            self._engine = RapidOCR()
        return self._engine

    def ocr_bytes(self, data: bytes) -> dict:
        from PIL import Image, ImageOps

        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        img.thumbnail((2400, 2400))
        return self._run(np.asarray(img), img.width, img.height)

    def ocr_path(self, path: Path) -> dict:
        return self.ocr_bytes(Path(path).read_bytes())

    def _run(self, arr: np.ndarray, w: int, h: int) -> dict:
        t0 = time.time()
        with self._lock:
            r = self._ocr()(arr)
        lines = []
        txts = list(r.txts or []) if r is not None else []
        boxes = r.boxes if r is not None and r.boxes is not None else []
        scores = list(r.scores or []) if r is not None else []
        for i, text in enumerate(txts):
            box = boxes[i].tolist() if i < len(boxes) else None
            lines.append({"text": text, "box": box, "score": round(float(scores[i]), 3) if i < len(scores) else None})
        # reading order: top-to-bottom, then left-to-right
        lines.sort(key=lambda l: ((l["box"][0][1] // 18) if l["box"] else 0, l["box"][0][0] if l["box"] else 0))
        return {"text": "\n".join(l["text"] for l in lines), "lines": lines, "width": w, "height": h, "ms": int((time.time() - t0) * 1000)}
