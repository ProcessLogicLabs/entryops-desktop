"""Tesseract OCR backend using PyMuPDF to render PDF pages to images.

PyMuPDF is used instead of pdf2image/Poppler so we don't need to ship a
separate native binary bundle; pytesseract drives the already-installed
Tesseract binary.

Binary discovery order for tesseract.exe:
    1. config.ocr.tesseract.binary_path (explicit override)
    2. pytesseract's default PATH lookup
    3. Well-known Windows install path: C:/Program Files/Tesseract-OCR/tesseract.exe
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
from pathlib import Path
from typing import Any, Optional

from .base import OCRBackend
from .preprocess import apply_preprocess


# Common install paths to check when PATH lookup fails.
_WINDOWS_DEFAULT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def _resolve_tesseract_binary(config: Any) -> Optional[str]:
    explicit = config.get('ocr.tesseract.binary_path', '') or ''
    if explicit:
        p = Path(explicit)
        if p.exists():
            return str(p)

    if sys.platform.startswith('win') and _WINDOWS_DEFAULT.exists():
        return str(_WINDOWS_DEFAULT)

    return None  # pytesseract will use PATH


def _resolve_tessdata(config: Any) -> Optional[str]:
    tessdata = config.get('ocr.tesseract.tessdata_dir', '') or ''
    return tessdata or None


class TesseractBackend(OCRBackend):
    """Render each PDF page with PyMuPDF, then OCR with pytesseract."""

    name = 'tesseract'

    def __init__(self, config: Any):
        import pytesseract  # deferred import — keep cold start cheap

        self._pytesseract = pytesseract
        self.config = config

        binary = _resolve_tesseract_binary(config)
        if binary:
            pytesseract.pytesseract.tesseract_cmd = binary

        self._tessdata = _resolve_tessdata(config)
        self._language = config.get('ocr.tesseract.language', 'eng') or 'eng'
        self._cache_enabled = bool(config.get('ocr.tesseract.cache_ocr_text', True))

    def ocr_pdf(self, pdf_path: Path, *, dpi: int = 300,
                preprocess: Optional[list] = None) -> str:
        cached = self._read_cache(pdf_path, dpi, preprocess)
        if cached is not None:
            return cached

        import pymupdf  # deferred
        from PIL import Image  # Pillow is already a base dep

        pieces: list[str] = []
        with pymupdf.open(pdf_path) as doc:
            zoom = dpi / 72.0  # pymupdf's base DPI is 72
            matrix = pymupdf.Matrix(zoom, zoom)
            for page in doc:
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
                img = apply_preprocess(img, preprocess)
                pieces.append(self._image_to_text(img))

        full_text = '\n'.join(pieces)
        self._write_cache(pdf_path, dpi, preprocess, full_text)
        return full_text

    # ----- internals -----

    def _image_to_text(self, img) -> str:
        kwargs = {'lang': self._language}
        if self._tessdata:
            kwargs['config'] = f'--tessdata-dir "{self._tessdata}"'
        try:
            return self._pytesseract.image_to_string(img, **kwargs)
        except Exception as exc:
            return f'[tesseract error: {exc}]'

    def _cache_path(self, pdf_path: Path, dpi: int,
                    preprocess: Optional[list]) -> Path:
        tag = hashlib.sha1(
            f'{pdf_path.stat().st_size}:{pdf_path.stat().st_mtime}:'
            f'{dpi}:{",".join(preprocess or [])}:{self._language}'.encode()
        ).hexdigest()[:10]
        return pdf_path.with_suffix(pdf_path.suffix + f'.ocr.{tag}.txt')

    def _read_cache(self, pdf_path: Path, dpi: int,
                    preprocess: Optional[list]) -> Optional[str]:
        if not self._cache_enabled:
            return None
        try:
            cache = self._cache_path(pdf_path, dpi, preprocess)
            if cache.exists():
                return cache.read_text(encoding='utf-8', errors='replace')
        except OSError:
            pass
        return None

    def _write_cache(self, pdf_path: Path, dpi: int,
                     preprocess: Optional[list], text: str) -> None:
        if not self._cache_enabled or not text:
            return
        try:
            cache = self._cache_path(pdf_path, dpi, preprocess)
            cache.write_text(text, encoding='utf-8')
        except OSError:
            pass
