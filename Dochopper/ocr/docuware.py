"""DocuWare OCR backend stub.

Reserves the interface slot so the dispatcher can pick 'docuware' from config
without plumbing changes. Real implementation deferred until endpoint / auth
details are supplied; see the approved plan file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .base import OCRBackend


class DocuWareBackend(OCRBackend):
    name = 'docuware'

    def __init__(self, config: Any):
        self.config = config

    def ocr_pdf(self, pdf_path: Path, *, dpi: int = 300,
                preprocess: Optional[list] = None) -> str:
        raise NotImplementedError(
            'DocuWare adapter deferred. Configure ocr.engine="tesseract" for now.'
        )
