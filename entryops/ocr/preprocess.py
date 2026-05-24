"""Image preprocessing helpers for the OCR pipeline.

Intentionally dependency-light: only Pillow. Advanced operations (deskew via
OpenCV, denoise, binarize) can be added later as class attrs on templates
drive which steps run.
"""
from __future__ import annotations

from typing import Iterable

from PIL import Image, ImageOps


def apply_preprocess(img: Image.Image, steps: Iterable[str] | None) -> Image.Image:
    """Apply a sequence of preprocessing steps. Unknown steps are ignored."""
    if not steps:
        return img

    for step in steps:
        s = step.lower().strip()
        if s == 'grayscale':
            img = ImageOps.grayscale(img)
        elif s == 'autocontrast':
            img = ImageOps.autocontrast(img)
        elif s == 'invert':
            img = ImageOps.invert(img.convert('RGB'))
        # 'deskew' intentionally omitted: needs cv2/numpy. Add when we see
        # tilted scans in the wild.
    return img
