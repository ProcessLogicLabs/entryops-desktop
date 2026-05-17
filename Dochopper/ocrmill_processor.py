"""
OCRMill Processing Engine for DocHopper
PDF invoice processing using OCR templates.
"""

import csv
import re
from pathlib import Path
from typing import List, Dict, Callable, Optional, Tuple
from datetime import datetime
import time

import pandas as pd

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from Dochopper.templates import get_all_templates, refresh_templates
    from Dochopper.templates.bill_of_lading import BillOfLadingTemplate
except ImportError:
    from templates import get_all_templates, refresh_templates
    from templates.bill_of_lading import BillOfLadingTemplate


# ============================================================================
# Spreadsheet (XLSX / XLS) loader — feeds the standard template pipeline
# the same (text, tables) shape that pdfplumber produces for PDFs.
# ============================================================================


def _coerce_cell(value) -> str:
    """Normalize an Excel cell value to a clean string for templates.

    Numbers that are integer-valued floats are stripped of the trailing
    `.0` (matters for HTS codes and line numbers stored in number-typed
    cells). datetime objects render as `MM/DD/YYYY` to match the format
    most invoice templates expect for dates.
    """
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    import datetime as _dt
    if isinstance(value, _dt.datetime):
        return value.strftime('%m/%d/%Y')
    if isinstance(value, _dt.date):
        return value.strftime('%m/%d/%Y')
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def _load_xlsx_openpyxl(path: Path):
    """Read an .xlsx workbook via openpyxl. ``data_only=True`` returns the
    cached values for formula cells (otherwise we'd see ``=SUM(...)``);
    ``read_only=True`` keeps memory low for large invoices."""
    try:
        import openpyxl
    except ImportError:
        return ('', [])
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    tables: list = []
    text_chunks: list = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [_coerce_cell(v) for v in row]
            if any(c for c in cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
            text_chunks.append('\n'.join('\t'.join(r) for r in rows))
    return ('\n\n'.join(text_chunks), tables)


def _load_xls_xlrd(path: Path):
    """Read a legacy binary .xls via xlrd. xlrd >= 2.0 deliberately dropped
    .xlsx support, so we route by suffix rather than try-then-fall-back."""
    try:
        import xlrd
    except ImportError:
        return ('', [])
    wb = xlrd.open_workbook(str(path), formatting_info=False)
    tables: list = []
    text_chunks: list = []
    datemode = wb.datemode
    XL_CELL_DATE = 3  # xlrd.XL_CELL_DATE
    for sheet in wb.sheets():
        rows = []
        for r in range(sheet.nrows):
            cells = []
            for c in range(sheet.ncols):
                v = sheet.cell_value(r, c)
                t = sheet.cell_type(r, c)
                if t == XL_CELL_DATE and isinstance(v, (int, float)):
                    try:
                        d = xlrd.xldate.xldate_as_datetime(v, datemode)
                        cells.append(d.strftime('%m/%d/%Y'))
                        continue
                    except Exception:
                        pass
                cells.append(_coerce_cell(v))
            if any(c for c in cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
            text_chunks.append('\n'.join('\t'.join(r) for r in rows))
    return ('\n\n'.join(text_chunks), tables)


def load_xlsx_as_text_and_tables(path: Path) -> Tuple[str, List[List[List[str]]]]:
    """Read an .xlsx or .xls file and return ``(flat_text, tables)``.

    ``tables`` matches ``pdfplumber.page.extract_tables()`` shape — a list
    of tables (one per non-empty sheet), each a list of rows of cell
    strings — so table-aware templates' ``extract_from_tables(tables)``
    consumes it unchanged.

    ``text`` is a tab-separated flat rendering of the same data, with a
    blank line between sheets, suitable for the text-only template path
    via ``can_process(text)`` and ``extract_line_items(text)``.

    Raises ``ValueError`` for unsupported extensions.
    """
    suffix = path.suffix.lower()
    if suffix == '.xlsx':
        return _load_xlsx_openpyxl(path)
    if suffix == '.xls':
        return _load_xls_xlrd(path)
    raise ValueError(f"Unsupported spreadsheet format: {suffix}")


class _OCRConfigAdapter:
    """Dotted-path config reader for the Dochopper/ocr package.

    The ocr/*.py files were ported verbatim from OCRMill, which expects
    ``config.get('ocr.enabled', False)``-style lookups. DocHopper's
    ``OCRMillConfig`` doesn't speak that dialect, and OCR preferences
    aren't a top-level concept in DocHopper's settings yet. This adapter
    resolves dotted keys against a hardcoded DEFAULTS tree first, then
    overlays any matching ``ocr.*`` rows from the shared DB's
    ``billing_settings`` table so an admin can override without code.
    """

    DEFAULTS = {
        "ocr": {
            "enabled": True,
            "engine": "tesseract",
            "fallback_on_empty_text": True,
            "fallback_on_image_heavy": True,
            "tesseract": {
                "binary_path": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                "tessdata_dir": "",
                "language": "eng",
                "dpi": 300,
                "preprocess": ["grayscale"],
                "cache_ocr_text": True,
            },
        },
    }

    def __init__(self, db_path=None):
        self._db_path = db_path
        self._overrides = self._load_overrides()

    def _load_overrides(self) -> dict:
        """Read ``ocr.*`` rows from billing_settings. Returns {dotted_key: value}."""
        if not self._db_path:
            return {}
        try:
            import sqlite3
            conn = sqlite3.connect(str(self._db_path))
            c = conn.cursor()
            c.execute("SELECT key, value FROM billing_settings WHERE key LIKE 'ocr.%'")
            rows = c.fetchall()
            conn.close()
            return {k: v for k, v in rows if v is not None}
        except Exception:
            return {}

    @staticmethod
    def _coerce(raw: str, default):
        """Coerce a billing_settings string value toward the default's type."""
        if raw is None:
            return default
        if isinstance(default, bool):
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            try:
                return int(raw)
            except (TypeError, ValueError):
                return default
        if isinstance(default, float):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return default
        if isinstance(default, list):
            parts = [p.strip() for p in str(raw).split(",") if p.strip()]
            return parts or default
        return raw

    def get(self, dotted_key: str, default=None):
        """Resolve a dotted key: DB override (typed-coerced) > DEFAULTS > default."""
        # Walk the DEFAULTS tree for the fallback value
        node = self.DEFAULTS
        for part in dotted_key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        base = node if node is not None else default

        if dotted_key in self._overrides:
            return self._coerce(self._overrides[dotted_key], base)
        return base


class OCRMillConfig:
    """Configuration holder for OCRMill processing."""

    def __init__(self):
        self.input_folder = Path("Input/OCRMill")
        self.output_folder = Path("Output/OCRMill")
        self.consolidate_multi_invoice = False
        self.poll_interval = 60
        self.auto_start = False
        self.template_settings = {}  # template_name -> enabled

    def get_template_enabled(self, template_name: str) -> bool:
        """Check if a template is enabled."""
        return self.template_settings.get(template_name, True)

    def set_template_enabled(self, template_name: str, enabled: bool):
        """Set template enabled state."""
        self.template_settings[template_name] = enabled


class ProcessorEngine:
    """Core processing engine using templates for PDF invoice extraction."""

    def __init__(self, db, config: OCRMillConfig = None, log_callback: Callable[[str], None] = None, auth_manager=None):
        """
        Initialize the processor engine.

        Args:
            db: OCRMillDatabase instance for parts tracking
            config: OCRMillConfig with processing settings
            log_callback: Function to call with log messages
            auth_manager: optional AuthManager to resolve the current user at
                          processing time (recovers from startup races where
                          the processor is created before login completes)
        """
        self.config = config or OCRMillConfig()
        self.log_callback = log_callback or print
        self.templates = {}
        self.parts_db = db
        self.current_user = None  # Track current user for statistics
        self._auth_manager = auth_manager
        self._last_template_name = None  # Cache last-used template for faster matching
        self._last_section_232 = {}      # Section 232 data from last extraction
        self._ocr_config = _OCRConfigAdapter(getattr(db, 'db_path', None))
        self._load_templates()

    def set_current_user(self, username: str):
        """Set the current user for statistics tracking."""
        self.current_user = username

    def set_auth_manager(self, auth_manager):
        """Wire (or rewire) the auth manager so process_pdf can resolve the
        current user even if it changes after construction (e.g. switch user)."""
        self._auth_manager = auth_manager

    def _resolve_username(self):
        """Pick the best username available right now.

        Priority: live auth_manager.current_user (covers the case where the
        processor was created before login completed) → previously set
        current_user → OS account name. Returning a real OS account is better
        than NULL — historical NULLs render as "Unknown" in the Admin Panel.
        """
        try:
            if self._auth_manager is not None:
                user = getattr(self._auth_manager, 'current_user', None)
                if user:
                    return user
        except Exception:
            pass
        if self.current_user:
            return self.current_user
        try:
            import getpass
            return getpass.getuser() or None
        except Exception:
            return None

    def _load_templates(self):
        """Load all available templates, including shared templates."""
        refresh_templates()
        self.templates = get_all_templates()

    def reload_templates(self):
        """Reload templates from disk. Call after adding/removing template files."""
        refresh_templates()  # Force re-discovery from disk
        self._load_templates()
        self.log(f"Reloaded {len(self.templates)} templates")

    def log(self, message: str):
        """Log a message."""
        self.log_callback(message)

    def get_best_template(self, text: str):
        """Find the best template for the given text.

        Uses cached last-used template as fast path (skip full scoring if
        the cached template scores > 0.8).

        Returns:
            Tuple of (template, confidence_score) or (None, 0.0) if no match
        """
        best_template = None
        best_score = 0.0

        # Fast path: try last-used template first
        if self._last_template_name and self._last_template_name in self.templates:
            cached = self.templates[self._last_template_name]
            if cached.enabled and self.config.get_template_enabled(self._last_template_name):
                cached_score = cached.get_confidence_score(text)
                if cached_score > 0.8:
                    self.log(f"  Template cache hit: {self._last_template_name} (score: {cached_score:.2f})")
                    return cached, cached_score

        self.log(f"  Evaluating {len(self.templates)} templates...")

        for name, template in self.templates.items():
            if not self.config.get_template_enabled(name):
                self.log(f"    - {name}: Disabled in config")
                continue
            if not template.enabled:
                self.log(f"    - {name}: Disabled in template")
                continue

            score = template.get_confidence_score(text)
            self.log(f"    - {name}: Confidence score {score:.2f}")

            if score > best_score:
                best_score = score
                best_template = template

        if best_template:
            self._last_template_name = best_template.name
            self.log(f"  Selected template: {best_template.name} (score: {best_score:.2f})")
        else:
            self.log(f"  No matching template found")

        return best_template, best_score

    # Reversed-text detection markers. pdfplumber on certain Linkfair-style
    # PDFs (CH_APP_CMDUSHZ7995383) returns each word with its characters in
    # reverse order — "INVOICE" comes out as "ECIOVNI", "PACKING LIST" as
    # "TSIL GNIKCAP". When any of these appear in a page's pdfplumber text
    # we re-extract that page with PyMuPDF, which renders the text correctly.
    _REVERSED_TEXT_MARKERS = (
        'ECIOVNI',         # INVOICE
        'TSIL GNIKCAP',    # PACKING LIST
        'RIAFKNIL',        # LINKFAIR
        ',LANOITANRETNI',  # ,INTERNATIONAL
        'EREBMUN',         # NUMBER (rev)
    )

    @classmethod
    def _looks_reversed(cls, text: str) -> bool:
        """True if the pdfplumber text contains right-to-left rendering markers."""
        if not text:
            return False
        upper = text.upper()
        return any(marker in upper for marker in cls._REVERSED_TEXT_MARKERS)

    def _extract_page_text(self, pdf_path: Path, page_index: int, pdfplumber_page) -> str:
        """Page-text extraction with PyMuPDF fallback for reversed pages.

        Try pdfplumber first (cheapest, already loaded). If the result looks
        reversed (see _looks_reversed), re-extract the same page index with
        PyMuPDF, which doesn't suffer from this rendering bug. Returns the
        original pdfplumber text if PyMuPDF isn't available or also fails.
        """
        text = pdfplumber_page.extract_text() or ""
        if not self._looks_reversed(text):
            return text

        # Reversed text detected — fall back to PyMuPDF for this page only.
        try:
            try:
                import pymupdf as fitz  # pymupdf >= 1.24 native module
            except ImportError:
                import fitz  # pymupdf legacy shim
        except ImportError:
            self.log(f"  Page {page_index + 1}: reversed-text detected but PyMuPDF not available; using pdfplumber output as-is")
            return text

        try:
            with fitz.open(str(pdf_path)) as doc:
                if page_index < doc.page_count:
                    fitz_text = doc[page_index].get_text() or ""
                    if fitz_text.strip() and not self._looks_reversed(fitz_text):
                        self.log(f"  Page {page_index + 1}: reversed pdfplumber text replaced with PyMuPDF extraction")
                        return fitz_text
        except Exception as exc:
            self.log(f"  Page {page_index + 1}: PyMuPDF fallback failed ({exc}); using pdfplumber output")

        return text

    def _ocr_fallback(self, pdf_path: Path, template=None) -> str:
        """Run the configured OCR backend against a scanned PDF.

        Returns extracted text, or empty string if OCR is disabled, the
        required packages aren't installed, or the backend errors out. Never
        raises — the caller checks for truthiness before using the result.
        """
        if not self._ocr_config.get('ocr.enabled', False):
            return ''
        engine_override = getattr(template, 'preferred_ocr_engine', None) if template else None
        try:
            try:
                from Dochopper.ocr import get_ocr_engine
            except ImportError:
                from ocr import get_ocr_engine
        except ImportError as exc:
            self.log(f"  OCR module unavailable: {exc}")
            return ''

        engine = get_ocr_engine(self._ocr_config, engine_override=engine_override)
        self.log(f"  OCR engine: {engine.name}")
        if getattr(engine, 'reason', None):
            self.log(f"  OCR disabled: {engine.reason}")

        dpi = int(self._ocr_config.get('ocr.tesseract.dpi', 300) or 300)
        preprocess = self._ocr_config.get('ocr.tesseract.preprocess', None)
        if template is not None:
            dpi = getattr(template, 'ocr_dpi', dpi) or dpi
            preprocess = getattr(template, 'ocr_preprocess', None) or preprocess

        try:
            text = engine.ocr_pdf(pdf_path, dpi=dpi, preprocess=preprocess)
        except NotImplementedError as exc:
            self.log(f"  OCR skipped: {exc}")
            return ''
        except Exception as exc:
            self.log(f"  OCR error: {exc}")
            return ''

        if text.strip():
            self.log(f"  OCR produced {len(text):,} chars of text")
        else:
            self.log(f"  OCR returned no text")
        return text

    def process_pdf(self, pdf_path: Path) -> List[Dict]:
        """
        Process a single invoice file (PDF or XLSX/XLS), handling multiple
        invoices per source. Despite the name, this is the unified entry
        point for the OCRMill pipeline — XLSX/XLS files are detected by
        suffix and routed to the spreadsheet path; everything else flows
        through the original pdfplumber + OCR-fallback path.

        Args:
            pdf_path: Path to the PDF or spreadsheet file

        Returns:
            List of extracted line items as dictionaries
        """
        # Refresh current_user from auth_manager in case the processor was
        # constructed before login completed. record_template_usage calls
        # below all read self.current_user, so picking up the live value here
        # is enough to fix the "Unknown" attribution bug.
        resolved = self._resolve_username()
        if resolved:
            self.current_user = resolved

        self.log(f"Processing: {pdf_path.name}")

        # XLSX / XLS dispatch — spreadsheets bypass pdfplumber entirely and
        # never go through the OCR branch. The same template auto-discovery,
        # MultiFileWorker, and DirectExportWorker downstream paths all
        # consume the items list this returns.
        if pdf_path.suffix.lower() in (".xlsx", ".xls"):
            return self._process_spreadsheet(pdf_path)

        if pdfplumber is None:
            self.log("Error: pdfplumber is not installed. Run: pip install pdfplumber")
            return []

        start_time = time.time()

        try:
            with pdfplumber.open(pdf_path) as pdf:
                # First pass: extract all text to detect template
                full_text = ""
                text_pages = 0
                total_pages = len(pdf.pages)
                for page_idx, page in enumerate(pdf.pages):
                    text = self._extract_page_text(pdf_path, page_idx, page)
                    if text and text.strip():
                        full_text += text + "\n"
                        text_pages += 1

                # Decide whether to invoke OCR fallback. Two trigger conditions:
                #   (1) pdfplumber returned nothing at all (classic scanned PDF)
                #   (2) most pages lack a text layer (image-heavy PDF with a
                #       cover page that happens to have embedded text)
                image_heavy = (
                    total_pages > 0
                    and text_pages < total_pages * 0.5
                    and self._ocr_config.get('ocr.fallback_on_image_heavy', True)
                )
                ocr_text = ""
                if not full_text.strip() and self._ocr_config.get('ocr.fallback_on_empty_text', True):
                    self.log(f"  No text extracted from {pdf_path.name} (text layer empty)")
                    ocr_text = self._ocr_fallback(pdf_path)
                elif image_heavy:
                    self.log(f"  Image-heavy PDF: {text_pages}/{total_pages} pages have text; attempting OCR")
                    ocr_text = self._ocr_fallback(pdf_path)

                if ocr_text.strip():
                    # OCR path: page boundaries don't line up with the source
                    # PDF anyway, so treat the whole document as one buffer and
                    # route directly to the best template.
                    template, confidence_score = self.get_best_template(ocr_text)
                    if not template:
                        self.log(f"  No matching template for OCR text of {pdf_path.name}")
                        return []
                    self.log(f"  Using template: {template.name} (OCR source)")
                    if template.is_packing_list(ocr_text):
                        self.log(f"  Skipping packing list: {pdf_path.name}")
                        return []
                    invoice_number, project_number, items = template.extract_all(ocr_text)
                    if hasattr(template, '_section_232_updates') and template._section_232_updates:
                        self._last_section_232 = dict(template._section_232_updates)
                    for item in items:
                        if not item.get('invoice_number'):
                            item['invoice_number'] = invoice_number or 'UNKNOWN'
                        if not item.get('project_number'):
                            item['project_number'] = project_number or 'UNKNOWN'
                        if not item.get('manufacturer_name'):
                            item['manufacturer_name'] = template.name
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    try:
                        self.parts_db.record_template_usage(
                            template_name=template.name,
                            pdf_file=pdf_path.name,
                            items_extracted=len(items),
                            confidence_score=confidence_score,
                            processing_time_ms=processing_time_ms,
                            success=True,
                            username=self.current_user,
                        )
                    except Exception as e:
                        self.log(f"  Warning: Failed to record stats: {e}")
                    self.log(f"  Found 1 invoice(s) via OCR, {len(items)} total items, "
                             f"Grand Total: ${sum(float(i.get('total_price', 0) or 0) for i in items):,.2f}")
                    return items

                if not full_text.strip():
                    # OCR was disabled or returned nothing — preserve the
                    # existing "we can't process this" behavior.
                    has_images = any(len(page.images) > 0 for page in pdf.pages)
                    if has_images:
                        self.log(f"  WARNING: {pdf_path.name} appears to be a scanned image.")
                        self.log(f"  Scanned/image-based PDFs cannot be processed at this time.")
                        self.log(f"  Please request a text-based PDF from the supplier.")
                    else:
                        self.log(f"  No text extracted from {pdf_path.name}")
                    return []

                # Scan for Bill of Lading and extract gross weight
                bol_weight = None
                bol_template = BillOfLadingTemplate()

                for page_idx, page in enumerate(pdf.pages):
                    page_text = self._extract_page_text(pdf_path, page_idx, page)
                    if page_text and bol_template.can_process(page_text):
                        self.log(f"  Found Bill of Lading on a page")
                        bol_weight = bol_template.extract_gross_weight(page_text)
                        if bol_weight:
                            self.log(f"  Extracted BOL gross weight: {bol_weight} kg")
                            break

                # Find the best template
                template, confidence_score = self.get_best_template(full_text)
                if not template:
                    self.log(f"  No matching template for {pdf_path.name}")
                    # Record failed template match
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    self.parts_db.record_template_usage(
                        template_name="NO_MATCH",
                        pdf_file=pdf_path.name,
                        items_extracted=0,
                        confidence_score=0.0,
                        processing_time_ms=processing_time_ms,
                        success=False,
                        error_message="No matching template found",
                        username=self.current_user
                    )
                    return []

                self.log(f"  Using template: {template.name}")

                # Check if packing list only
                if template.is_packing_list(full_text):
                    self.log(f"  Skipping packing list: {pdf_path.name}")
                    return []

                # Second pass: process page-by-page to handle multiple invoices
                all_items = []
                current_invoice = None
                current_project = None
                page_buffer = []
                page_tables = []  # Collect tables from all processed pages
                packing_list_weights = {}  # net_weight, gross_weight from packing list pages
                all_section_232 = {}  # Section 232 metal content data (sku -> pct fields)

                self.log(f"  PDF has {len(pdf.pages)} page(s)")

                for page_idx, page in enumerate(pdf.pages):
                    page_text = self._extract_page_text(pdf_path, page_idx, page)
                    if not page_text:
                        self.log(f"  Page {page_idx + 1}: No text extracted")
                        continue

                    # Skip packing list and BOL pages
                    # But be careful not to skip invoice pages that just REFERENCE a B/L number
                    page_lower = page_text.lower()
                    if 'packing list' in page_lower and 'invoice' not in page_lower:
                        # Extract weight from packing list before skipping
                        try:
                            pl_tables = page.extract_tables() or []
                        except Exception:
                            pl_tables = []
                        self._extract_weight_from_page(page_text, packing_list_weights, pl_tables)
                        self.log(f"  Page {page_idx + 1}: Skipped (packing list)")
                        continue

                    # Only skip as BOL if it's primarily a BOL page, not just mentioning B/L
                    # Check for BOL-specific headers/indicators that wouldn't appear on invoices
                    is_bol_page = False
                    if 'bill of lading' in page_lower:
                        # BOL pages typically have these indicators
                        bol_indicators = ['non-negotiable', 'waybill', 'container no', 'seal no',
                                         'freight collect', 'freight prepaid', 'port of discharge',
                                         'notify party', 'place of delivery', 'ocean vessel']
                        # Invoice pages typically have these
                        invoice_indicators = ['commercial invoice', 'invoice no', 'unit price', 'total price',
                                            'qty', 'quantity', 'rate', 'amount', 'po date', 'po number',
                                            'unit rate', 'value', 'packing list', 'net weight', 'gross wt']

                        bol_count = sum(1 for ind in bol_indicators if ind in page_lower)
                        invoice_count = sum(1 for ind in invoice_indicators if ind in page_lower)

                        # Only skip if it's clearly a BOL page (more BOL indicators than invoice indicators)
                        # and has at least 2 BOL indicators
                        if bol_count > invoice_count and bol_count >= 2:
                            is_bol_page = True
                            self.log(f"  Page {page_idx + 1}: Skipped (bill of lading - {bol_count} BOL indicators vs {invoice_count} invoice indicators)")
                        else:
                            self.log(f"  Page {page_idx + 1}: Contains 'bill of lading' but keeping (likely invoice referencing B/L)")

                    if is_bol_page:
                        continue

                    self.log(f"  Page {page_idx + 1}: Processing ({len(page_text)} chars)")

                    # Extract tables from page for table-based extraction
                    page_page_tables = []
                    try:
                        page_page_tables = page.extract_tables() or []
                        if page_page_tables:
                            self.log(f"    Found {len(page_page_tables)} table(s) on page")
                            page_tables.extend(page_page_tables)
                    except Exception as e:
                        self.log(f"    Table extraction failed: {e}")

                    # Scan any page with packing list / weight memo indicators for weight data
                    if not packing_list_weights.get('net_weight'):
                        weight_indicators = ['packing list', 'weight memo', '装箱单', '重量单',
                                            'net weight', 'net wt', 'n.w', '净重', 'gross weight', 'g.w', '毛重',
                                            'n.wt', 'g.wt']
                        if any(ind in page_lower for ind in weight_indicators):
                            self._extract_weight_from_page(page_text, packing_list_weights, page_page_tables)

                    # Debug: Show first 100 chars of page
                    preview = page_text[:100].replace('\n', ' ')
                    self.log(f"    Preview: {preview}...")

                    # Check for new invoice on this page
                    inv_match = re.search(r'(?:Proforma\s+)?[Ii]nvoice\s+(?:number|n)\.?\s*:?\s*(\d+(?:/\d+)?)', page_text)
                    proj_match = re.search(r'(?:\d+\.\s*)?[Pp]roject\s*(?:n\.?)?\s*:?\s*(US\d+[A-Z]\d+)', page_text, re.IGNORECASE)

                    # If we found a new invoice number, process the buffer first
                    new_invoice = inv_match.group(1) if inv_match else None
                    if new_invoice and current_invoice and new_invoice != current_invoice:
                        # Process accumulated pages for previous invoice
                        if page_buffer:
                            buffer_text = "\n".join(page_buffer)
                            # Pass tables for table-based extraction
                            _, _, items = template.extract_all(buffer_text, tables=page_tables if page_tables else None)
                            if hasattr(template, '_section_232_updates') and template._section_232_updates:
                                all_section_232.update(template._section_232_updates)
                            for item in items:
                                item['invoice_number'] = current_invoice
                                if not item.get('manufacturer_name'):
                                    item['manufacturer_name'] = template.name
                                # Use per-item po_number if available, else fall back to document-level
                                if item.get('po_number') and not item.get('project_number'):
                                    item['project_number'] = item['po_number']
                                if not item.get('project_number') or item.get('project_number') == 'UNKNOWN':
                                    item['project_number'] = current_project
                                if bol_weight:
                                    item['bol_gross_weight'] = bol_weight
                                # NOTE: do NOT assign bol_weight to item['net_weight'].
                                # bol_weight is the WHOLE-SHIPMENT gross weight,
                                # not per-line net. Treating it as per-line caused
                                # every Qty1 (for WEIGHT_UNITS HTS like KG) to be
                                # set to the total shipment weight. Per-line weight
                                # falls through to CalcWtNet (value-proportional)
                                # in calculate_quantities instead — that's correct.
                            all_items.extend(items)
                            page_buffer = []

                    # Update current invoice/project if found
                    if inv_match:
                        current_invoice = inv_match.group(1)
                    if proj_match:
                        current_project = proj_match.group(1).upper()

                    # Add page to buffer
                    page_buffer.append(page_text)

                # Process remaining pages in buffer
                self.log(f"  Processing buffer with {len(page_buffer)} page(s), total chars: {sum(len(p) for p in page_buffer)}")
                if page_buffer:
                    buffer_text = "\n".join(page_buffer)

                    # If no invoice found with generic pattern, try the template's extraction
                    if not current_invoice:
                        current_invoice = template.extract_invoice_number(buffer_text)
                        current_project = template.extract_project_number(buffer_text)

                    # Pass tables for table-based extraction
                    _, _, items = template.extract_all(buffer_text, tables=page_tables if page_tables else None)
                    if hasattr(template, '_section_232_updates') and template._section_232_updates:
                        all_section_232.update(template._section_232_updates)
                        self.log(f"  Section 232 data found: {len(template._section_232_updates)} SKU(s)")
                    if page_tables:
                        self.log(f"  Passed {len(page_tables)} table(s) to template")
                    self.log(f"  Template extracted {len(items)} line items from buffer")
                    for item in items:
                        # Only set invoice_number if template didn't already provide one
                        if not item.get('invoice_number') or item.get('invoice_number') == 'UNKNOWN':
                            item['invoice_number'] = current_invoice or 'UNKNOWN'
                        if not item.get('manufacturer_name'):
                            item['manufacturer_name'] = template.name
                        # Use per-item po_number if available, else fall back to document-level
                        if item.get('po_number') and not item.get('project_number'):
                            item['project_number'] = item['po_number']
                        if not item.get('project_number') or item.get('project_number') == 'UNKNOWN':
                            item['project_number'] = current_project or 'UNKNOWN'
                        # Apply weight from packing list (highest priority for net weight)
                        if packing_list_weights.get('net_weight'):
                            item['total_net_weight'] = packing_list_weights['net_weight']
                        if packing_list_weights.get('gross_weight'):
                            item['total_gross_weight'] = packing_list_weights['gross_weight']
                        if bol_weight:
                            item['bol_gross_weight'] = bol_weight
                        # NOTE: do NOT fall back to bol_weight for item['net_weight'].
                        # bol_weight is the whole-shipment gross weight; using it
                        # per-line causes Qty1 (for KG-unit HTS like 8481/8413) to
                        # be the same total-shipment value on every row. Per-line
                        # weight allocation happens in calculate_weights /
                        # calculate_quantities via CalcWtNet (value-proportional).
                    all_items.extend(items)

                # Count unique invoices and calculate grand total
                unique_invoices = set(item.get('invoice_number', 'UNKNOWN') for item in all_items)
                grand_total = sum(float(item.get('total_price', 0) or 0) for item in all_items)
                self.log(f"  Found {len(unique_invoices)} invoice(s), {len(all_items)} total items, Grand Total: ${grand_total:,.2f}")

                for inv in sorted(unique_invoices):
                    inv_items = [item for item in all_items if item.get('invoice_number') == inv]
                    proj = inv_items[0].get('project_number', 'UNKNOWN') if inv_items else 'UNKNOWN'
                    total_value = sum(float(item.get('total_price', 0) or 0) for item in inv_items)
                    self.log(f"    - Invoice {inv} (Project {proj}): {len(inv_items)} items, ${total_value:,.2f}")

                # Store Section 232 data for access by process_and_export
                self._last_section_232 = all_section_232

                # Record successful template usage (don't let stats failure kill pipeline)
                processing_time_ms = int((time.time() - start_time) * 1000)
                try:
                    self.parts_db.record_template_usage(
                        template_name=template.name,
                        pdf_file=pdf_path.name,
                        items_extracted=len(all_items),
                        confidence_score=confidence_score,
                        processing_time_ms=processing_time_ms,
                        success=True,
                        username=self.current_user
                    )
                except Exception as e:
                    self.log(f"  Warning: Failed to record stats: {e}")

                return all_items

        except Exception as e:
            self.log(f"  Error processing {pdf_path.name}: {e}")
            # Record error
            processing_time_ms = int((time.time() - start_time) * 1000)
            try:
                self.parts_db.record_template_usage(
                    template_name=template.name if template else "ERROR",
                    pdf_file=pdf_path.name,
                    items_extracted=0,
                    processing_time_ms=processing_time_ms,
                    success=False,
                    error_message=str(e),
                    username=self.current_user
                )
            except Exception:
                pass  # Don't fail on stat recording error
            return []

    def save_to_csv(self, items: List[Dict], output_folder: Path, pdf_name: str = None) -> List[Path]:
        """
        Save items to CSV files and add to parts database.

        Args:
            items: List of extracted line items
            output_folder: Output folder for CSV files
            pdf_name: Original PDF filename for reference

        Returns:
            List of paths to created CSV files
        """
        if not items:
            return []

        output_folder.mkdir(exist_ok=True, parents=True)
        created_files = []

        # Add items to parts database and enrich with descriptions, HTS codes, MID
        for item in items:
            # Map template 'country' field to 'country_origin' if not already set
            if 'country' in item and ('country_origin' not in item or not item['country_origin']):
                item['country_origin'] = item['country']

            # Look up MID and country_origin from manufacturer name
            if ('mid' not in item or not item['mid']) or ('country_origin' not in item or not item['country_origin']):
                manufacturer_name = item.get('manufacturer_name', '')
                if manufacturer_name:
                    manufacturer = self.parts_db.get_manufacturer_by_name(manufacturer_name)
                    if manufacturer:
                        if 'mid' not in item or not item['mid']:
                            if manufacturer.get('mid'):
                                item['mid'] = manufacturer.get('mid', '')
                        if 'country_origin' not in item or not item['country_origin']:
                            if manufacturer.get('country'):
                                item['country_origin'] = manufacturer.get('country', '')

            # If country_origin still not set but we have MID, extract from first 2 letters
            if ('country_origin' not in item or not item['country_origin']) and item.get('mid'):
                mid = item.get('mid', '')
                if len(mid) >= 2:
                    item['country_origin'] = mid[:2].upper()

            part_data = item.copy()
            part_data['source_file'] = pdf_name or 'unknown'
            self.parts_db.add_part_occurrence(part_data)

            # Add description and HTS code back to item for CSV export
            if 'description' not in item or not item['description']:
                item['description'] = part_data.get('description', '')
            if 'hts_code' not in item or not item['hts_code']:
                item['hts_code'] = part_data.get('hts_code', '')

            # Remove manufacturer_name from item (we only need MID in output)
            if 'manufacturer_name' in item:
                del item['manufacturer_name']

        # Group by invoice number
        by_invoice = {}
        for item in items:
            inv_num = item.get('invoice_number', 'UNKNOWN')
            if inv_num not in by_invoice:
                by_invoice[inv_num] = []
            by_invoice[inv_num].append(item)

        # Determine columns from items with specific ordering
        columns = ['invoice_number', 'project_number', 'part_number', 'description',
                   'mid', 'country_origin', 'hts_code', 'quantity', 'quantity_unit', 'total_price']

        for item in items:
            for key in item.keys():
                if key not in columns:
                    columns.append(key)

        # Check consolidation mode
        consolidate = self.config.consolidate_multi_invoice

        if consolidate and len(by_invoice) > 1:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if pdf_name:
                base_name = Path(pdf_name).stem
            else:
                base_name = f"consolidated_{list(by_invoice.keys())[0]}"
            filename = f"{base_name}_{timestamp}.csv"
            filepath = output_folder / filename

            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(items)

            invoice_list = ", ".join(sorted(by_invoice.keys()))
            self.log(f"  Saved: {filename} ({len(items)} items from {len(by_invoice)} invoices: {invoice_list})")
            created_files.append(filepath)

        else:
            for inv_num, inv_items in by_invoice.items():
                proj_num = inv_items[0].get('project_number', 'UNKNOWN')
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                # Sanitize invoice and project numbers for valid filenames
                safe_inv_num = re.sub(r'[<>:"/\\|?*]', '-', inv_num)
                safe_proj_num = re.sub(r'[<>:"/\\|?*]', '-', proj_num)
                filename = f"{safe_inv_num}_{safe_proj_num}_{timestamp}.csv"
                filepath = output_folder / filename

                with open(filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(inv_items)

                self.log(f"  Saved: {filename} ({len(inv_items)} items)")
                created_files.append(filepath)

        return created_files

    def _extract_weight_from_page(self, page_text: str, weights_dict: dict, tables=None):
        """
        Extract net and gross weight from a packing list or weight memo page.
        Updates weights_dict in place with 'net_weight' and/or 'gross_weight'.
        Scans both text and table data.
        """
        # === Strategy 1: Scan tables for TOTAL row with weight columns ===
        if tables and not weights_dict.get('net_weight'):
            for table in tables:
                if not table:
                    continue
                # Find header row with N.WT or G.WT columns
                nwt_col = -1
                gwt_col = -1
                header_row = -1
                for row_idx, row in enumerate(table):
                    if not row:
                        continue
                    for col_idx, cell in enumerate(row):
                        cell_str = str(cell or '').upper().strip()
                        if any(h in cell_str for h in ['N.WT', 'NWT', 'NET', 'N.W']):
                            nwt_col = col_idx
                            header_row = row_idx
                        if any(h in cell_str for h in ['G.WT', 'GWT', 'GROSS', 'G.W']):
                            gwt_col = col_idx
                            header_row = row_idx

                if header_row < 0:
                    continue

                self.log(f"    Found weight table: header row {header_row}, N.WT col={nwt_col}, G.WT col={gwt_col}")

                # Look for TOTAL row or last row with numeric data
                for row_idx in range(len(table) - 1, header_row, -1):
                    row = table[row_idx]
                    if not row:
                        continue
                    row_text = ' '.join(str(c or '') for c in row).upper()
                    is_total = 'TOTAL' in row_text

                    if is_total or row_idx == len(table) - 1:
                        # Extract net weight from this row
                        if nwt_col >= 0 and nwt_col < len(row):
                            # The "total" column might be the one after nwt_col (per/CT vs total)
                            # Try nwt_col and nwt_col+1
                            for try_col in [nwt_col, nwt_col + 1]:
                                if try_col < len(row):
                                    val = str(row[try_col] or '').strip().replace(',', '')
                                    try:
                                        w = float(val)
                                        if w > 100:  # Total weight should be substantial
                                            weights_dict['net_weight'] = str(w)
                                            self.log(f"    Found net weight from table TOTAL row: {w} kg")
                                            break
                                    except (ValueError, TypeError):
                                        pass
                        # Extract gross weight
                        if gwt_col >= 0 and gwt_col < len(row):
                            for try_col in [gwt_col, gwt_col + 1]:
                                if try_col < len(row):
                                    val = str(row[try_col] or '').strip().replace(',', '')
                                    try:
                                        w = float(val)
                                        if w > 100:
                                            weights_dict['gross_weight'] = str(w)
                                            self.log(f"    Found gross weight from table TOTAL row: {w} kg")
                                            break
                                    except (ValueError, TypeError):
                                        pass
                        if weights_dict.get('net_weight'):
                            break

        # === Strategy 2: Regex on page text (fallback) ===
        if not weights_dict.get('net_weight'):
            net_patterns = [
                r'Total\s+Nett\.?\s+Wt\.?\s*\(Kgs?\)\s*:\s*([\d,]+\.?\d*)',
                r'(?:total\s*)?net\s*(?:weight|wt|w\.?t\.?)[\s:：]*([\d,]+\.?\d*)\s*(?:kg|kgs)',
                r'N\.?\s*W\.?\s*T?\.?\s*(?:KGS?)?[\s:：]*([\d,]+\.?\d+)',
                r'净\s*重\s*[:：]?\s*([\d,]+\.?\d*)\s*(?:kg|kgs|千克)',
                r'net[^0-9]{0,20}([\d,]+\.?\d+)\s*(?:kg|kgs)',
            ]
            for pattern in net_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    try:
                        weight = float(match.group(1).replace(',', ''))
                        if weight > 100:  # Sanity check — total weight should be > 100kg
                            weights_dict['net_weight'] = str(weight)
                            self.log(f"    Found net weight from text: {weight} kg")
                            break
                    except (ValueError, TypeError):
                        pass

        if not weights_dict.get('gross_weight'):
            gross_patterns = [
                r'Total\s+Gross\s+Wt\.?\s*\(Kgs?\)\s*:\s*([\d,]+\.?\d*)',
                r'(?:total\s*)?gross\s*(?:weight|wt|w\.?t\.?)[\s:：]*([\d,]+\.?\d*)\s*(?:kg|kgs)',
                r'G\.?\s*W\.?\s*T?\.?\s*(?:KGS?)?[\s:：]*([\d,]+\.?\d+)',
                r'毛\s*重\s*[:：]?\s*([\d,]+\.?\d*)\s*(?:kg|kgs|千克)',
                r'gross[^0-9]{0,20}([\d,]+\.?\d+)\s*(?:kg|kgs)',
            ]
            for pattern in gross_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    try:
                        weight = float(match.group(1).replace(',', ''))
                        if weight > 100:
                            weights_dict['gross_weight'] = str(weight)
                            self.log(f"    Found gross weight from text: {weight} kg")
                            break
                    except (ValueError, TypeError):
                        pass

        # === Strategy 3: Packing list TOTAL row with positional gross/net weights ===
        # Handles format: TOTAL:... qty gross_wt net_wt
        # where page header has "WEIGHT IN KGS" with GROSS and NET sub-columns
        page_upper = page_text.upper()
        if 'WEIGHT' in page_upper and ('GROSS' in page_upper or 'NET' in page_upper):
            if not weights_dict.get('net_weight') or not weights_dict.get('gross_weight'):
                # Find TOTAL row and extract the last 2-3 large numbers
                total_match = re.search(
                    r'TOTAL[:\s].*?([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*$',
                    page_text, re.MULTILINE | re.IGNORECASE
                )
                if total_match:
                    nums = []
                    for g in [total_match.group(1), total_match.group(2), total_match.group(3)]:
                        try:
                            nums.append(float(g.replace(',', '')))
                        except (ValueError, TypeError):
                            nums.append(0)
                    # Last 3 numbers on TOTAL row: qty, gross, net
                    # Gross > net > qty typically
                    if len(nums) == 3 and nums[1] > 100 and nums[2] > 100:
                        if nums[1] >= nums[2]:
                            gross, net = nums[1], nums[2]
                        else:
                            gross, net = nums[2], nums[1]
                        if not weights_dict.get('gross_weight'):
                            weights_dict['gross_weight'] = str(gross)
                            self.log(f"    Found gross weight from TOTAL row: {gross} kg")
                        if not weights_dict.get('net_weight'):
                            weights_dict['net_weight'] = str(net)
                            self.log(f"    Found net weight from TOTAL row: {net} kg")

    def _process_spreadsheet(self, path: Path) -> List[Dict]:
        """Process an .xlsx or .xls invoice via the same template auto-discovery
        pipeline used for PDFs. Mirrors the OCR branch of ``process_pdf`` but:

        - Loads (text, tables) from the workbook via ``load_xlsx_as_text_and_tables``
          instead of pdfplumber.
        - Calls ``template.extract_all(text, tables)`` so table-aware templates
          (~30% of the catalog) can use the spreadsheet's row structure
          natively, while text-only templates ignore the ``tables`` kwarg.
        - Skips the BOL gross-weight scan (spreadsheets don't carry BOLs).
        - Tags ``record_template_usage`` log lines as "spreadsheet source"
          so the Admin Panel can distinguish.
        """
        start_time = time.time()
        try:
            text, tables = load_xlsx_as_text_and_tables(path)
        except Exception as exc:
            self.log(f"  Error reading spreadsheet: {exc}")
            return []

        if not text.strip() and not tables:
            self.log(f"  Empty workbook — no items extracted from {path.name}")
            return []

        template, confidence_score = self.get_best_template(text)
        if not template:
            self.log(f"  No matching template for {path.name}")
            try:
                processing_time_ms = int((time.time() - start_time) * 1000)
                self.parts_db.record_template_usage(
                    template_name="NO_MATCH",
                    pdf_file=path.name,
                    items_extracted=0,
                    confidence_score=0.0,
                    processing_time_ms=processing_time_ms,
                    success=False,
                    error_message="No matching template found (spreadsheet)",
                    username=self.current_user,
                )
            except Exception:
                pass
            return []

        self.log(f"  Using template: {template.name} (spreadsheet source)")
        if template.is_packing_list(text):
            self.log(f"  Skipping packing list: {path.name}")
            return []

        invoice_number, project_number, items = template.extract_all(text, tables)
        if hasattr(template, '_section_232_updates') and template._section_232_updates:
            self._last_section_232 = dict(template._section_232_updates)
        for item in items:
            if not item.get('invoice_number'):
                item['invoice_number'] = invoice_number or 'UNKNOWN'
            if not item.get('project_number'):
                item['project_number'] = project_number or 'UNKNOWN'
            if not item.get('manufacturer_name'):
                item['manufacturer_name'] = template.name
        processing_time_ms = int((time.time() - start_time) * 1000)
        try:
            self.parts_db.record_template_usage(
                template_name=template.name,
                pdf_file=path.name,
                items_extracted=len(items),
                confidence_score=confidence_score,
                processing_time_ms=processing_time_ms,
                success=True,
                username=self.current_user,
            )
        except Exception as e:
            self.log(f"  Warning: Failed to record stats: {e}")
        self.log(
            f"  Spreadsheet: {len(items)} items, "
            f"Grand Total: ${sum(float(i.get('total_price', 0) or 0) for i in items):,.2f}"
        )
        return items

    def resolve_net_weight(self, items: List[Dict]) -> Optional[float]:
        """
        Resolve net weight from extracted items using priority chain:
        1. Template-extracted total_net_weight (from commercial invoice/packing list)
        2. Template-extracted total_gross_weight (fallback)
        3. BOL gross weight (from BillOfLadingTemplate)
        4. None (requires user input)

        Returns:
            Net weight in kg as float, or None if not available
        """
        # Priority 1: Template-extracted net weight
        for item in items:
            net_wt = item.get('total_net_weight')
            if net_wt:
                try:
                    weight = float(str(net_wt).replace(',', '').strip())
                    if weight > 0:
                        self.log(f"  Using template-extracted net weight: {weight} kg")
                        return weight
                except (ValueError, TypeError):
                    pass

        # Priority 2: Template-extracted gross weight
        for item in items:
            gross_wt = item.get('total_gross_weight')
            if gross_wt:
                try:
                    weight = float(str(gross_wt).replace(',', '').strip())
                    if weight > 0:
                        self.log(f"  Using template-extracted gross weight as fallback: {weight} kg")
                        return weight
                except (ValueError, TypeError):
                    pass

        # Priority 3: BOL gross weight
        for item in items:
            bol_wt = item.get('bol_gross_weight') or item.get('net_weight')
            if bol_wt:
                try:
                    weight = float(str(bol_wt).replace(',', '').strip())
                    if weight > 0:
                        self.log(f"  Using BOL gross weight: {weight} kg")
                        return weight
                except (ValueError, TypeError):
                    pass

        self.log("  No net weight found in extracted data")
        return None

    def process_and_export(self, items: List[Dict], output_folder: Path,
                           pdf_name: str, net_weight: float,
                           profile_name: str, db_path: Path,
                           override_mid: str = '') -> Tuple[List[Path], 'pd.DataFrame']:
        """
        Full pipeline: enrich extracted items and export XLSX using output profile.

        Args:
            items: Raw extracted line items from template
            output_folder: Where to save XLSX files
            pdf_name: Original PDF filename
            net_weight: Total net weight in kg
            profile_name: Output profile name (or empty for default)
            db_path: Path to the DocHopper database
            override_mid: If set, force this MID on every row (overrides parts_master)

        Returns:
            Tuple of (xlsx_paths, preview_df, enriched_df, enrichment_stats)
        """
        if not items:
            return [], pd.DataFrame(), pd.DataFrame(), {}

        # Step 1: Pre-enrich with MID/country/description from OCRMill parts DB
        for item in items:
            # Map template 'country' field to 'country_origin' if not already set
            if 'country' in item and ('country_origin' not in item or not item['country_origin']):
                item['country_origin'] = item['country']

            if ('mid' not in item or not item['mid']) or ('country_origin' not in item or not item['country_origin']):
                manufacturer_name = item.get('manufacturer_name', '')
                if manufacturer_name:
                    manufacturer = self.parts_db.get_manufacturer_by_name(manufacturer_name)
                    if manufacturer:
                        if 'mid' not in item or not item['mid']:
                            if manufacturer.get('mid'):
                                item['mid'] = manufacturer.get('mid', '')
                        if 'country_origin' not in item or not item['country_origin']:
                            if manufacturer.get('country'):
                                item['country_origin'] = manufacturer.get('country', '')

            if ('country_origin' not in item or not item['country_origin']) and item.get('mid'):
                mid = item.get('mid', '')
                if len(mid) >= 2:
                    item['country_origin'] = mid[:2].upper()

            # Record in parts DB
            part_data = item.copy()
            part_data['source_file'] = pdf_name or 'unknown'
            self.parts_db.add_part_occurrence(part_data)

            if 'description' not in item or not item['description']:
                item['description'] = part_data.get('description', '')
            if 'hts_code' not in item or not item['hts_code']:
                item['hts_code'] = part_data.get('hts_code', '')

            # Remove manufacturer_name (only MID needed in output)
            if 'manufacturer_name' in item:
                del item['manufacturer_name']

        # Step 2: Run enrichment pipeline
        try:
            from Dochopper.ocrmill_enrichment import EnrichmentPipeline
        except ImportError:
            from ocrmill_enrichment import EnrichmentPipeline

        pipeline = EnrichmentPipeline(db_path, log_callback=self.log_callback)
        # Pass Section 232 form data to enrichment for dollar-based splitting
        s232_data = dict(self._last_section_232) if self._last_section_232 else None
        enriched_df = pipeline.enrich(items, net_weight, override_mid=override_mid,
                                      section_232_updates=s232_data)

        # Collect enrichment stats for validation summary
        enrichment_stats = pipeline.get_enrichment_stats()

        # Pass 232 data through for country update dialog (if any)
        if self._last_section_232:
            enrichment_stats['section_232_updates'] = dict(self._last_section_232)
            self._last_section_232 = {}  # clear after consuming

        if enriched_df.empty:
            self.log("  Enrichment produced no data")
            return [], pd.DataFrame(), enriched_df, enrichment_stats

        # Step 3: Export using profile
        try:
            from Dochopper.ocrmill_exporter import ProfileExporter
        except ImportError:
            from ocrmill_exporter import ProfileExporter

        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)

        exporter = ProfileExporter(db_path, output_folder, log_callback=self.log_callback)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = Path(pdf_name).stem if pdf_name else "export"
        filename = f"{base_name}_{timestamp}.xlsx"

        created_files = exporter.export(enriched_df, profile_name, filename)

        # Build the profiled DataFrame for preview (same column order/naming as XLSX)
        profile = exporter.load_profile(profile_name) if profile_name else None
        if profile is None:
            try:
                from Dochopper.ocrmill_exporter import DEFAULT_OUTPUT_COLUMN_ORDER
            except ImportError:
                from ocrmill_exporter import DEFAULT_OUTPUT_COLUMN_ORDER
            profile = {
                'column_mapping': {name: name for name in DEFAULT_OUTPUT_COLUMN_ORDER},
                'column_order': DEFAULT_OUTPUT_COLUMN_ORDER.copy(),
                'column_visibility': {},
                'split_by_invoice': False,
            }
        preview_df, preview_cols, _ = exporter.build_export_df(enriched_df, profile)
        # Keep only the visible profile columns
        preview_df = preview_df[[c for c in preview_cols if c in preview_df.columns]]

        self.log(f"  Direct export complete: {len(created_files)} file(s) created, {len(enriched_df)} rows")
        return created_files, preview_df, enriched_df, enrichment_stats

    def move_to_processed(self, pdf_path: Path, processed_folder: Path):
        """Move processed PDF to the Processed folder. Retries if file is locked."""
        import shutil
        import time as _time

        processed_folder.mkdir(exist_ok=True, parents=True)

        dest = processed_folder / pdf_path.name
        counter = 1
        while dest.exists():
            stem = pdf_path.stem
            dest = processed_folder / f"{stem}_{counter}{pdf_path.suffix}"
            counter += 1

        # Retry with delay for locked files (e.g. PDF viewer still has handle)
        for attempt in range(3):
            try:
                shutil.move(str(pdf_path), str(dest))
                self.log(f"  Moved to: Processed/{dest.name}")
                return
            except (PermissionError, OSError) as e:
                if attempt < 2:
                    _time.sleep(1)
                else:
                    self.log(f"  Warning: Could not move {pdf_path.name} (file in use) - will remain in place")

    def move_to_failed(self, pdf_path: Path, failed_folder: Path, reason: str = ""):
        """Move failed PDF to the Failed folder."""
        failed_folder.mkdir(exist_ok=True, parents=True)

        dest = failed_folder / pdf_path.name
        counter = 1
        while dest.exists():
            stem = pdf_path.stem
            dest = failed_folder / f"{stem}_{counter}{pdf_path.suffix}"
            counter += 1

        pdf_path.rename(dest)
        reason_msg = f" ({reason})" if reason else ""
        self.log(f"  Moved to: Failed/{dest.name}{reason_msg}")

    def process_folder(self, input_folder: Path = None, output_folder: Path = None) -> int:
        """
        Process all PDFs in the input folder.

        Args:
            input_folder: Input folder path (uses config default if None)
            output_folder: Output folder path (uses config default if None)

        Returns:
            Number of successfully processed PDFs
        """
        input_folder = input_folder or self.config.input_folder
        output_folder = output_folder or self.config.output_folder

        input_folder = Path(input_folder)
        output_folder = Path(output_folder)

        input_folder.mkdir(exist_ok=True, parents=True)
        output_folder.mkdir(exist_ok=True, parents=True)
        processed_folder = input_folder / "Processed"
        failed_folder = input_folder / "Failed"

        pdf_files = list(input_folder.glob("*.pdf"))
        if not pdf_files:
            return 0

        self.log(f"Found {len(pdf_files)} PDF(s) to process")
        processed_count = 0
        failed_count = 0

        for pdf_path in pdf_files:
            try:
                items = self.process_pdf(pdf_path)
                if items:
                    self.save_to_csv(items, output_folder, pdf_name=pdf_path.name)
                    self.move_to_processed(pdf_path, processed_folder)
                    processed_count += 1
                else:
                    self.move_to_failed(pdf_path, failed_folder, "No items extracted")
                    failed_count += 1
            except Exception as e:
                self.log(f"  Error processing {pdf_path.name}: {e}")
                self.move_to_failed(pdf_path, failed_folder, f"Error: {str(e)[:50]}")
                failed_count += 1

        if failed_count > 0:
            self.log(f"Summary: {processed_count} processed successfully, {failed_count} failed")

        return processed_count

    def process_single_file(self, pdf_path: Path, output_folder: Path = None, move_after: bool = True) -> List[Dict]:
        """
        Process a single PDF file manually.

        Args:
            pdf_path: Path to PDF file
            output_folder: Output folder (uses config default if None)
            move_after: Whether to move the file after processing

        Returns:
            List of extracted items
        """
        output_folder = output_folder or self.config.output_folder
        output_folder = Path(output_folder)

        items = self.process_pdf(pdf_path)

        if items:
            self.save_to_csv(items, output_folder, pdf_name=pdf_path.name)
            if move_after:
                processed_folder = pdf_path.parent / "Processed"
                self.move_to_processed(pdf_path, processed_folder)

        return items

    def get_available_templates(self) -> Dict[str, Dict]:
        """Get information about available templates."""
        template_info = {}
        for name, template in self.templates.items():
            template_info[name] = {
                'name': template.name,
                'enabled': template.enabled and self.config.get_template_enabled(name),
                'description': getattr(template, 'description', 'No description'),
            }
        return template_info
