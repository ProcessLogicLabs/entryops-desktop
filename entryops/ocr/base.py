"""OCR backend protocol + null implementation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class OCRBackend(ABC):
    """Abstract OCR backend. Produces text from a PDF file path."""

    name: str = 'base'

    @abstractmethod
    def ocr_pdf(self, pdf_path: Path, *, dpi: int = 300,
                preprocess: Optional[list] = None) -> str:
        """Run OCR over all pages of the PDF and return concatenated text."""
        raise NotImplementedError


class NullBackend(OCRBackend):
    """No-op backend used when OCR is disabled or misconfigured.

    Returns '' so the empty-text failure path in ProcessorEngine is preserved.
    """

    name = 'null'

    def __init__(self, reason: str = ''):
        self.reason = reason

    def ocr_pdf(self, pdf_path: Path, *, dpi: int = 300,
                preprocess: Optional[list] = None) -> str:
        return ''
