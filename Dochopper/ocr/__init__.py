"""OCR backend dispatcher for OCRMill.

Engines are lazily imported so a default install without Tesseract does not
pay the import cost and does not fail to start just because pytesseract or
PyMuPDF are missing.
"""
from __future__ import annotations

from typing import Any, Optional

from .base import OCRBackend, NullBackend


def get_ocr_engine(config: Any, engine_override: Optional[str] = None) -> OCRBackend:
    """Factory. Returns the active OCR backend based on configuration.

    Args:
        config: ConfigManager instance (dotted .get() access expected).
        engine_override: Per-template engine name; takes precedence over config.
    """
    if not config.get('ocr.enabled', False):
        return NullBackend(reason='ocr.enabled is False')

    engine = engine_override or config.get('ocr.engine', 'tesseract')
    engine = (engine or '').lower()

    if engine in ('', 'null', 'none'):
        return NullBackend(reason=f'engine={engine!r}')

    if engine == 'tesseract':
        try:
            from .tesseract import TesseractBackend
        except ImportError as e:
            return NullBackend(reason=f'tesseract import failed: {e}')
        return TesseractBackend(config)

    if engine == 'docuware':
        try:
            from .docuware import DocuWareBackend
        except ImportError as e:
            return NullBackend(reason=f'docuware import failed: {e}')
        return DocuWareBackend(config)

    return NullBackend(reason=f'unknown engine {engine!r}')


__all__ = ['OCRBackend', 'NullBackend', 'get_ocr_engine']
