"""
template_wizard.py — Rule-based invoice template builder for OCRMill / DocHopper.

Zero AI/API calls. Uses pdfplumber to analyze PDF structure, detects tables,
maps columns to fields, suggests keywords, and generates production-ready
Python template code.

Drop-in companion to ai_template_generator.py — same public API.
"""

import re
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QLineEdit, QTextEdit, QPlainTextEdit,
    QComboBox, QCheckBox, QFileDialog, QMessageBox, QProgressBar,
    QApplication, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QWidget, QSplitter, QTabWidget, QListWidget,
    QListWidgetItem, QAbstractItemView, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

# ── Base class auto-detection ─────────────────────────────────────────────────
_BASE_IMPORT_LINE = ""
_BASE_CLASS = None

def _detect_base():
    global _BASE_IMPORT_LINE, _BASE_CLASS
    candidates = [
        ("from .base_template import BaseTemplate",          "base_template", "BaseTemplate"),
        ("from .SmartExtractor.base_template import BaseTemplate", "SmartExtractor.base_template", "BaseTemplate"),
    ]
    for import_line, mod, cls in candidates:
        try:
            import importlib
            m = importlib.import_module(mod)
            _BASE_CLASS = getattr(m, cls)
            _BASE_IMPORT_LINE = import_line
            return
        except Exception:
            pass
    # Fallback — inline stub will be embedded in generated code
    _BASE_IMPORT_LINE = ""
    _BASE_CLASS = None

_detect_base()

# ── PDF helpers ───────────────────────────────────────────────────────────────

COLUMN_KEYWORDS = {
    "part_number":  ["part", "item", "part no", "part#", "item no", "item#", "sku", "model", "code", "ref"],
    "quantity":     ["qty", "quantity", "pcs", "pieces", "units", "count"],
    "total_price":  ["total", "amount", "ext", "extended", "line total", "subtotal"],
    "unit_price":   ["unit price", "unit cost", "price", "rate", "each", "per unit"],
    "description":  ["description", "desc", "goods", "product", "item name", "details"],
}

INVOICE_NUM_PATTERNS = [
    (r'invoice\s*(?:no|num|number|#)[\s:.]*([A-Z0-9][\w\-/]+)', "Invoice No:"),
    (r'inv[\s.#:]*([A-Z0-9][\w\-/]+)',                           "INV#"),
    (r'invoice\s*:\s*([A-Z0-9][\w\-/]+)',                        "Invoice:"),
    (r'(?:^|\s)(INV[-/]\d+)',                                     "INV-NNNN"),
]

PO_NUM_PATTERNS = [
    (r'p\.?o\.?\s*(?:no|num|number|#)[\s:.]*([A-Z0-9][\w\-/]+)', "PO No:"),
    (r'purchase\s*order[\s#:.]*([A-Z0-9][\w\-/]+)',               "Purchase Order:"),
    (r'order\s*(?:no|number|#)[\s:.]*([A-Z0-9][\w\-/]+)',         "Order No:"),
    (r'project[\s#:.]*([A-Z0-9][\w\-/]+)',                        "Project:"),
]

NOISE_PATTERNS = [
    r'^\s*\d+\s*$',           # page numbers
    r'^\s*[-=_]{3,}\s*$',     # dividers
    r'^\s*$',                  # blank
    r'page\s+\d+\s+of\s+\d+', # "Page 1 of 3"
]


def _try_install(pkg: str, parent=None) -> bool:
    import subprocess
    msg = QMessageBox(parent)
    msg.setWindowTitle("Package Required")
    msg.setText(f"'{pkg}' is not installed.")
    msg.setInformativeText("Install it now?")
    install_btn = msg.addButton("Install", QMessageBox.ButtonRole.AcceptRole)
    msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    msg.exec()
    if msg.clickedButton() != install_btn:
        return False
    r = subprocess.run([sys.executable, "-m", "pip", "install", pkg],
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def extract_pdf(path: str) -> Tuple[str, List[List[List[str]]]]:
    """Return (full_text, tables). Tables: list of tables, each is list of rows of cells."""
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber")

    text_parts, all_tables = [], []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:10]:
            t = page.extract_text()
            if t:
                text_parts.append(t)
            for tbl in page.extract_tables() or []:
                if tbl:
                    all_tables.append(tbl)
    return "\n\n".join(text_parts), all_tables


def _is_noise(line: str) -> bool:
    for p in NOISE_PATTERNS:
        if re.search(p, line, re.IGNORECASE):
            return True
    return False


def guess_supplier_name(text: str) -> str:
    """Heuristic: first non-noise line that looks like a company name."""
    skip = re.compile(r'^\d|@|www\.|http|invoice|bill|receipt|tax|gst|vat|date|page', re.I)
    for line in text.splitlines()[:20]:
        line = line.strip()
        if len(line) < 4 or len(line) > 80:
            continue
        if _is_noise(line):
            continue
        if skip.search(line):
            continue
        if re.search(r'[a-zA-Z]{3}', line):
            return line
    return ""


def detect_column_mapping(tables: List[List[List[str]]]) -> Dict[str, int]:
    """
    Find the first table with recognizable headers and return
    {field_name: column_index} mapping.
    """
    for table in tables:
        for row_idx, row in enumerate(table[:5]):  # header usually in first 5 rows
            if not row:
                continue
            row_text = [str(c or "").lower().strip() for c in row]
            mapping = {}
            for field, keywords in COLUMN_KEYWORDS.items():
                for col_idx, cell in enumerate(row_text):
                    if any(kw in cell for kw in keywords):
                        if field not in mapping:
                            mapping[field] = col_idx
                            break
            if len(mapping) >= 2:  # at least 2 fields recognized
                return mapping
    return {}


def get_table_headers(tables: List[List[List[str]]]) -> List[str]:
    """Return headers from the best table."""
    for table in tables:
        for row in table[:5]:
            if not row:
                continue
            headers = [str(c or "").strip() for c in row if c and str(c).strip()]
            if len(headers) >= 2:
                return headers
    return []


def find_pattern_matches(text: str, patterns: List[Tuple]) -> List[Tuple[str, str, str]]:
    """Return list of (label, pattern, example_match) for patterns that match."""
    results = []
    for pat, label in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            example = m.group(1) if m.lastindex else m.group(0)
            results.append((label, pat, example.strip()))
    return results


def suggest_keywords(text: str, supplier: str) -> List[str]:
    """Extract candidate identifier keywords from the PDF text."""
    keywords = []
    if supplier:
        keywords.append(supplier.lower())

    # Look for registration/tax numbers
    for pat in [r'gstin\s*[:#]\s*(\S+)', r'gst\s*no[.:#]\s*(\S+)',
                r'tax\s*id\s*[:#]\s*(\S+)', r'ein\s*[:#]\s*(\S+)',
                r'reg\.?\s*no[.:#]\s*(\S+)', r'vat\s*[:#]\s*(\S+)']:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            keywords.append(m.group(1).strip().lower())

    # First few meaningful lines
    for line in text.splitlines()[:15]:
        line = line.strip().lower()
        if 3 < len(line) < 60 and not _is_noise(line) and line not in keywords:
            if re.search(r'[a-z]{3}', line):
                keywords.append(line)
                if len(keywords) >= 8:
                    break

    return list(dict.fromkeys(keywords))[:10]  # unique, max 10


# ── Code generator ────────────────────────────────────────────────────────────

def _to_class_name(name: str) -> str:
    words = re.sub(r'[^a-zA-Z0-9]+', ' ', name).split()
    return ''.join(w.title() for w in words) + "Template"


def _to_module_name(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')[:40]


INLINE_BASE_STUB = '''
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple

class BaseTemplate(ABC):
    name: str = ""
    description: str = ""
    client: str = ""
    version: str = "1.0.0"
    enabled: bool = True
    extra_columns: List[str] = []
    STANDARD_COLUMNS = ['invoice_number','project_number','part_number','quantity','total_price']

    @abstractmethod
    def can_process(self, text: str) -> bool: pass
    @abstractmethod
    def extract_invoice_number(self, text: str) -> str: pass
    @abstractmethod
    def extract_project_number(self, text: str) -> str: pass
    @abstractmethod
    def extract_line_items(self, text: str) -> List[Dict]: pass
    def extract_manufacturer_name(self, text: str) -> str: return ""
    def is_packing_list(self, text: str) -> bool:
        return 'packing list' in text.lower() and 'invoice' not in text.lower()
    def get_confidence_score(self, text: str) -> float: return 0.5 if self.can_process(text) else 0.0
    def pre_process_text(self, text: str) -> str: return text
    def post_process_items(self, items: List[Dict]) -> List[Dict]: return items
    def extract_all(self, text, tables=None):
        text = self.pre_process_text(text)
        inv = self.extract_invoice_number(text)
        po  = self.extract_project_number(text)
        items = self.extract_line_items(text)
        items = self.post_process_items(items)
        return inv, po, items
'''


def generate_template_code(
    class_name: str,
    module_name: str,
    supplier: str,
    client: str,
    country: str,
    keywords: List[str],
    inv_pattern: str,
    po_pattern: str,
    col_mapping: Dict[str, int],
    table_headers: List[str],
    extra_cols: List[str],
    use_table_extraction: bool,
) -> str:
    """Generate a complete, working template Python class."""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    extra_cols_repr = repr(extra_cols)
    keywords_repr = repr([k.lower() for k in keywords if k])

    # Import line
    if _BASE_IMPORT_LINE:
        import_section = f"from typing import List, Dict\n{_BASE_IMPORT_LINE}"
    else:
        import_section = INLINE_BASE_STUB.strip() + "\nfrom typing import List, Dict"

    # can_process
    can_process_body = f"""        text_lower = text.lower()
        keywords = {keywords_repr}
        return any(kw in text_lower for kw in keywords)"""

    # extract_invoice_number
    if inv_pattern:
        inv_body = f"""        pattern = r{repr(inv_pattern)}
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return (m.group(1) if m.lastindex else m.group(0)).strip()
        return "UNKNOWN" """
    else:
        inv_body = '        return "UNKNOWN"'

    # extract_project_number
    if po_pattern:
        po_body = f"""        pattern = r{repr(po_pattern)}
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return (m.group(1) if m.lastindex else m.group(0)).strip()
        return "UNKNOWN" """
    else:
        po_body = '        return "UNKNOWN"'

    # extract_line_items — table or regex
    if use_table_extraction and col_mapping:
        part_col  = col_mapping.get("part_number", -1)
        qty_col   = col_mapping.get("quantity", -1)
        price_col = col_mapping.get("total_price", -1)
        unit_col  = col_mapping.get("unit_price", -1)
        desc_col  = col_mapping.get("description", -1)

        items_body = f"""        # Fallback text extraction (table extraction preferred via extract_from_tables)
        return []

    def extract_from_tables(self, tables: List[List[List[str]]], text: str) -> List[Dict]:
        \"\"\"Extract line items from pdfplumber table data.\"\"\"
        items = []
        seen = set()
        expected = {repr(table_headers[:6])}

        for table in tables:
            header_row = self.detect_table_header_row(table, expected)
            if header_row < 0:
                continue
            for row in table[header_row + 1:]:
                if not row or all(not c for c in row):
                    continue
                try:
                    part    = str(row[{part_col}]  or "").strip() if {part_col} < len(row) else ""
                    qty     = str(row[{qty_col}]   or "").strip() if {qty_col}  < len(row) else ""
                    price   = str(row[{price_col}] or "").strip() if {price_col} < len(row) else ""
                    unit    = str(row[{unit_col}]  or "").strip() if {unit_col}  >= 0 and {unit_col} < len(row) else ""
                    desc    = str(row[{desc_col}]  or "").strip() if {desc_col}  >= 0 and {desc_col} < len(row) else ""
                except IndexError:
                    continue
                qty_clean   = re.sub(r'[^\\d.]', '', qty)
                price_clean = re.sub(r'[^\\d.]', '', price)
                key = f"{{part}}_{{qty_clean}}_{{price_clean}}"
                if part and key not in seen:
                    seen.add(key)
                    item = {{
                        'part_number':  part,
                        'quantity':     qty_clean,
                        'total_price':  price_clean,
                        'country_origin': '{country}',
                    }}
                    if unit:  item['unit_price']   = re.sub(r'[^\\d.]', '', unit)
                    if desc:  item['description']  = desc
                    items.append(item)
        return items"""
    else:
        # Generic regex fallback
        items_body = """        items, seen = [], set()
        # Generic pattern: PART_NUMBER  QTY  PRICE
        pattern = re.compile(
            r'([A-Z0-9][\\w\\-]{2,})\\s+(\\d+(?:\\.\\d+)?)\\s+\\$?([\\d,]+(?:\\.\\d{2})?)',
            re.MULTILINE | re.IGNORECASE
        )
        for m in pattern.finditer(text):
            part, qty, price = m.group(1), m.group(2), m.group(3)
            price = price.replace(',', '')
            key = f"{part}_{qty}_{price}"
            if key not in seen and part:
                seen.add(key)
                try:
                    q = float(qty); p = float(price)
                    unit = f"{p/q:.2f}" if q else price
                except ValueError:
                    unit = price
                items.append({
                    'part_number':   part,
                    'quantity':      qty,
                    'total_price':   price,
                    'unit_price':    unit,
                    'country_origin': '""" + country + """',
                })
        return items"""

    # confidence boost per keyword
    conf_checks = "\n".join(
        f"        if {repr(kw.lower())} in text_lower: score += 0.1"
        for kw in keywords[:4]
    )

    code = f'''"""
{supplier} Invoice Template

Auto-generated by TemplateWizard (rule-based, no AI).
Generated: {now}
"""

import re
{import_section}


class {class_name}(BaseTemplate):
    """Template for {supplier} invoices."""

    name        = "{supplier}"
    description = "Commercial Invoice"
    client      = "{client}"
    version     = "1.0.0"
    enabled     = True

    extra_columns = {extra_cols_repr}

    def can_process(self, text: str) -> bool:
        """Identify {supplier} invoices."""
{can_process_body}

    def get_confidence_score(self, text: str) -> float:
        if not self.can_process(text):
            return 0.0
        score = 0.5
        text_lower = text.lower()
{conf_checks}
        return min(score, 1.0)

    def extract_invoice_number(self, text: str) -> str:
        """Extract invoice number."""
{inv_body}

    def extract_project_number(self, text: str) -> str:
        """Extract PO / project number."""
{po_body}

    def extract_manufacturer_name(self, text: str) -> str:
        return "{supplier}"

    def is_packing_list(self, text: str) -> bool:
        text_lower = text.lower()
        return 'packing list' in text_lower and 'invoice' not in text_lower

    def extract_line_items(self, text: str) -> List[Dict]:
        """Extract line items."""
        {items_body}

    def post_process_items(self, items: List[Dict]) -> List[Dict]:
        """Deduplicate and validate."""
        seen, out = set(), []
        for item in items:
            key = f"{{item.get('part_number')}}__{{item.get('quantity')}}__{{item.get('total_price')}}"
            if key not in seen:
                seen.add(key)
                item.setdefault('country_origin', '{country}')
                out.append(item)
        return out
'''
    return code


# ── Main dialog ───────────────────────────────────────────────────────────────

class TemplateWizardDialog(QDialog):
    """
    Rule-based invoice template builder.
    Analyzes PDF structure with pdfplumber — no AI or API calls required.
    """

    template_created = pyqtSignal(str, str)  # name, file_path

    # ── countries ─────────────────────────────────────────────────────────────
    COUNTRIES = ["CHINA", "INDIA", "MEXICO", "TAIWAN", "VIETNAM",
                 "BANGLADESH", "PAKISTAN", "INDONESIA", "USA", "OTHER"]

    def __init__(self, parent=None, db=None):
        super().__init__(parent)
        self.db = db
        self._pdf_text = ""
        self._tables: List[List[List[str]]] = []
        self._col_mapping: Dict[str, int] = {}
        self._table_headers: List[str] = []
        self._generated_code = ""

        self.setWindowTitle("Template Wizard  —  No AI Required")
        self.setMinimumSize(1000, 720)
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # Header
        hdr = QLabel("📄  Template Wizard")
        hdr.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        hdr.setStyleSheet("color:#2c3e50; margin-bottom:4px")
        root.addWidget(hdr)

        sub = QLabel("Automatically analyze a PDF invoice and generate a Python template — zero tokens, zero API calls.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#7f8c8d; margin-bottom:8px")
        root.addWidget(sub)

        tabs = QTabWidget()
        root.addWidget(tabs, stretch=1)

        tabs.addTab(self._tab_load(),     "1 · Load PDF")
        tabs.addTab(self._tab_columns(),  "2 · Columns")
        tabs.addTab(self._tab_keywords(), "3 · Keywords")
        tabs.addTab(self._tab_patterns(), "4 · Patterns")
        tabs.addTab(self._tab_settings(), "5 · Settings")
        tabs.addTab(self._tab_preview(),  "6 · Preview & Save")
        self._tabs = tabs

        # Bottom buttons
        btns = QHBoxLayout()
        self._analyze_btn = QPushButton("⚡  Analyze PDF")
        self._analyze_btn.setEnabled(False)
        self._analyze_btn.setStyleSheet("background:#2980b9;color:white;font-weight:bold;padding:8px 20px;border-radius:4px")
        self._analyze_btn.clicked.connect(self._analyze)
        btns.addWidget(self._analyze_btn)

        gen_btn = QPushButton("🔧  Generate Template")
        gen_btn.setStyleSheet("background:#8e44ad;color:white;font-weight:bold;padding:8px 20px;border-radius:4px")
        gen_btn.clicked.connect(self._generate)
        btns.addWidget(gen_btn)

        self._save_btn = QPushButton("💾  Save Template")
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet("background:#27ae60;color:white;font-weight:bold;padding:8px 20px;border-radius:4px")
        self._save_btn.clicked.connect(self._save)
        btns.addWidget(self._save_btn)

        self._test_btn = QPushButton("▶  Test")
        self._test_btn.setEnabled(False)
        self._test_btn.setStyleSheet("background:#e67e22;color:white;font-weight:bold;padding:8px 20px;border-radius:4px")
        self._test_btn.clicked.connect(self._test)
        btns.addWidget(self._test_btn)

        btns.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        root.addLayout(btns)

    # ── Tab 1: Load PDF ───────────────────────────────────────────────────────
    def _tab_load(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        row = QHBoxLayout()
        self._pdf_path = QLineEdit()
        self._pdf_path.setPlaceholderText("Select a PDF invoice…")
        self._pdf_path.setReadOnly(True)
        row.addWidget(self._pdf_path, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_pdf)
        row.addWidget(browse)
        lay.addLayout(row)

        self._raw_text = QPlainTextEdit()
        self._raw_text.setReadOnly(True)
        self._raw_text.setFont(QFont("Courier New", 9))
        self._raw_text.setPlaceholderText("Extracted PDF text appears here…")
        lay.addWidget(self._raw_text, stretch=1)

        info = QLabel("")
        info.setStyleSheet("color:#27ae60; font-size:11px")
        self._load_info = info
        lay.addWidget(info)
        return w

    # ── Tab 2: Column mapping ─────────────────────────────────────────────────
    def _tab_columns(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self._col_info = QLabel("Load and analyze a PDF first.")
        self._col_info.setWordWrap(True)
        self._col_info.setStyleSheet("color:#7f8c8d")
        lay.addWidget(self._col_info)

        form = QFormLayout()
        self._col_combos: Dict[str, QComboBox] = {}
        for field in ["part_number", "quantity", "total_price", "unit_price", "description"]:
            cb = QComboBox()
            cb.addItem("— not mapped —")
            self._col_combos[field] = cb
            form.addRow(field.replace("_", " ").title() + ":", cb)
        lay.addLayout(form)

        self._use_tables = QCheckBox("Use table extraction (recommended when tables detected)")
        self._use_tables.setChecked(True)
        lay.addWidget(self._use_tables)
        lay.addStretch()
        return w

    # ── Tab 3: Keywords ───────────────────────────────────────────────────────
    def _tab_keywords(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Keywords used in can_process() to identify this supplier's invoices:"))

        self._kw_list = QListWidget()
        self._kw_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        lay.addWidget(self._kw_list, stretch=1)

        row = QHBoxLayout()
        self._kw_edit = QLineEdit()
        self._kw_edit.setPlaceholderText("Add custom keyword…")
        row.addWidget(self._kw_edit, stretch=1)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_keyword)
        row.addWidget(add_btn)
        rem_btn = QPushButton("Remove selected")
        rem_btn.clicked.connect(self._remove_keywords)
        row.addWidget(rem_btn)
        lay.addLayout(row)
        return w

    # ── Tab 4: Patterns ───────────────────────────────────────────────────────
    def _tab_patterns(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        # Invoice number
        inv_grp = QGroupBox("Invoice Number Pattern")
        inv_lay = QVBoxLayout(inv_grp)
        self._inv_combo = QComboBox()
        self._inv_combo.setEditable(True)
        inv_lay.addWidget(self._inv_combo)
        self._inv_preview = QLabel("Example: —")
        self._inv_preview.setStyleSheet("color:#27ae60; font-family:monospace")
        inv_lay.addWidget(self._inv_preview)
        self._inv_combo.currentTextChanged.connect(self._update_inv_preview)
        lay.addWidget(inv_grp)

        # PO number
        po_grp = QGroupBox("PO / Project Number Pattern")
        po_lay = QVBoxLayout(po_grp)
        self._po_combo = QComboBox()
        self._po_combo.setEditable(True)
        po_lay.addWidget(self._po_combo)
        self._po_preview = QLabel("Example: —")
        self._po_preview.setStyleSheet("color:#27ae60; font-family:monospace")
        po_lay.addWidget(self._po_preview)
        self._po_combo.currentTextChanged.connect(self._update_po_preview)
        lay.addWidget(po_grp)

        lay.addStretch()
        return w

    # ── Tab 5: Settings ───────────────────────────────────────────────────────
    def _tab_settings(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)

        self._supplier_edit = QLineEdit()
        self._supplier_edit.textChanged.connect(self._auto_module_name)
        lay.addRow("Supplier Name:", self._supplier_edit)

        self._module_edit = QLineEdit()
        self._module_edit.setPlaceholderText("auto-generated")
        lay.addRow("Template File Name:", self._module_edit)

        self._client_edit = QLineEdit()
        self._client_edit.setPlaceholderText("Your company name")
        lay.addRow("Client:", self._client_edit)

        self._country_cb = QComboBox()
        self._country_cb.addItems(self.COUNTRIES)
        lay.addRow("Country of Origin:", self._country_cb)

        extra_grp = QGroupBox("Extra Columns")
        extra_lay = QHBoxLayout(extra_grp)
        self._extra_checks: Dict[str, QCheckBox] = {}
        for col in ["country_origin", "unit_price", "description", "po_number"]:
            cb = QCheckBox(col)
            cb.setChecked(col in ("country_origin", "unit_price"))
            self._extra_checks[col] = cb
            extra_lay.addWidget(cb)
        lay.addRow(extra_grp)
        return w

    # ── Tab 6: Preview ────────────────────────────────────────────────────────
    def _tab_preview(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self._code_preview = QPlainTextEdit()
        self._code_preview.setFont(QFont("Courier New", 9))
        self._code_preview.setStyleSheet(
            "QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;"
            "border:1px solid #3c3c3c;padding:4px}"
        )
        self._code_preview.setPlaceholderText("Generated template code appears here…")
        lay.addWidget(self._code_preview, stretch=2)

        self._result_table = QTableWidget(0, 5)
        self._result_table.setHorizontalHeaderLabels(
            ["part_number", "quantity", "total_price", "unit_price", "description"]
        )
        self._result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._result_table.setVisible(False)
        lay.addWidget(self._result_table, stretch=1)
        return w

    # ── Logic ──────────────────────────────────────────────────────────────────

    def _browse_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Invoice PDF", str(Path.home()), "PDF Files (*.pdf)"
        )
        if not path:
            return
        self._pdf_path.setText(path)
        self._analyze_btn.setEnabled(True)

    def _analyze(self):
        path = self._pdf_path.text()
        if not path:
            return
        try:
            text, tables = extract_pdf(path)
        except ImportError:
            if _try_install("pdfplumber", self):
                text, tables = extract_pdf(path)
            else:
                return
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read PDF:\n{e}")
            return

        self._pdf_text = text
        self._tables   = tables
        self._raw_text.setPlainText(text)

        # Column detection
        self._col_mapping   = detect_column_mapping(tables)
        self._table_headers = get_table_headers(tables)
        self._populate_col_combos()

        # Keyword suggestions
        supplier = guess_supplier_name(text)
        self._supplier_edit.setText(supplier)
        self._populate_keywords(supplier)

        # Pattern detection
        self._populate_patterns()

        # Info
        n_tables = len(tables)
        n_cols   = len(self._col_mapping)
        self._load_info.setText(
            f"✓  {len(text):,} chars extracted  ·  {n_tables} table(s) found  "
            f"·  {n_cols} column(s) auto-mapped"
        )
        self._tabs.setCurrentIndex(1)

    def _populate_col_combos(self):
        headers = self._table_headers or []
        detected = bool(headers)

        if detected:
            self._col_info.setText(
                f"Detected {len(self._tables)} table(s). Headers: {', '.join(headers[:8])}"
            )
        else:
            self._col_info.setText("No tables detected — template will use regex line extraction.")
            self._use_tables.setChecked(False)

        for field, cb in self._col_combos.items():
            cb.clear()
            cb.addItem("— not mapped —")
            for i, h in enumerate(headers):
                cb.addItem(f"Col {i}: {h}", i)
            # Auto-select
            if field in self._col_mapping:
                idx = self._col_mapping[field]
                cb.setCurrentIndex(idx + 1)  # +1 for "not mapped" row

    def _populate_keywords(self, supplier: str):
        self._kw_list.clear()
        for kw in suggest_keywords(self._pdf_text, supplier):
            item = QListWidgetItem(kw)
            item.setCheckState(Qt.CheckState.Checked)
            self._kw_list.addItem(item)

    def _populate_patterns(self):
        inv_matches = find_pattern_matches(self._pdf_text, INVOICE_NUM_PATTERNS)
        po_matches  = find_pattern_matches(self._pdf_text, PO_NUM_PATTERNS)

        self._inv_combo.clear()
        self._inv_combo.addItem("")
        for label, pat, example in inv_matches:
            self._inv_combo.addItem(f"{label}  →  {example}", pat)
        if inv_matches:
            self._inv_combo.setCurrentIndex(1)

        self._po_combo.clear()
        self._po_combo.addItem("")
        for label, pat, example in po_matches:
            self._po_combo.addItem(f"{label}  →  {example}", pat)
        if po_matches:
            self._po_combo.setCurrentIndex(1)

    def _update_inv_preview(self):
        pat = self._inv_combo.currentData() or self._inv_combo.currentText()
        if pat and self._pdf_text:
            try:
                m = re.search(pat, self._pdf_text, re.IGNORECASE | re.MULTILINE)
                val = (m.group(1) if m and m.lastindex else m.group(0)) if m else "no match"
                self._inv_preview.setText(f"Example: {val}")
            except Exception:
                self._inv_preview.setText("Invalid pattern")

    def _update_po_preview(self):
        pat = self._po_combo.currentData() or self._po_combo.currentText()
        if pat and self._pdf_text:
            try:
                m = re.search(pat, self._pdf_text, re.IGNORECASE | re.MULTILINE)
                val = (m.group(1) if m and m.lastindex else m.group(0)) if m else "no match"
                self._po_preview.setText(f"Example: {val}")
            except Exception:
                self._po_preview.setText("Invalid pattern")

    def _add_keyword(self):
        kw = self._kw_edit.text().strip()
        if kw:
            item = QListWidgetItem(kw.lower())
            item.setCheckState(Qt.CheckState.Checked)
            self._kw_list.addItem(item)
            self._kw_edit.clear()

    def _remove_keywords(self):
        for item in self._kw_list.selectedItems():
            self._kw_list.takeItem(self._kw_list.row(item))

    def _auto_module_name(self, text: str):
        if not self._module_edit.text() or self._module_edit.text() == self._module_edit.placeholderText():
            self._module_edit.setPlaceholderText(_to_module_name(text) + ".py")

    def _collect_keywords(self) -> List[str]:
        out = []
        for i in range(self._kw_list.count()):
            item = self._kw_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out

    def _collect_col_mapping(self) -> Dict[str, int]:
        mapping = {}
        for field, cb in self._col_combos.items():
            data = cb.currentData()
            if data is not None:
                mapping[field] = data
        return mapping

    def _generate(self):
        supplier = self._supplier_edit.text().strip()
        if not supplier:
            QMessageBox.warning(self, "Missing", "Enter a supplier name first.")
            return

        module   = self._module_edit.text().strip() or _to_module_name(supplier)
        module   = module.replace(".py", "")
        cls_name = _to_class_name(supplier)
        client   = self._client_edit.text().strip() or "Universal"
        country  = self._country_cb.currentText()
        keywords = self._collect_keywords()
        col_map  = self._collect_col_mapping()
        extra    = [k for k, cb in self._extra_checks.items() if cb.isChecked()]
        use_tbl  = self._use_tables.isChecked() and bool(col_map)

        inv_pat = (self._inv_combo.currentData() or self._inv_combo.currentText()).strip()
        po_pat  = (self._po_combo.currentData()  or self._po_combo.currentText()).strip()

        code = generate_template_code(
            class_name=cls_name,
            module_name=module,
            supplier=supplier,
            client=client,
            country=country,
            keywords=keywords,
            inv_pattern=inv_pat,
            po_pattern=po_pat,
            col_mapping=col_map,
            table_headers=self._table_headers,
            extra_cols=extra,
            use_table_extraction=use_tbl,
        )

        self._generated_code = code
        self._module_name    = module
        self._code_preview.setPlainText(code)
        self._save_btn.setEnabled(True)
        self._test_btn.setEnabled(True)
        self._tabs.setCurrentIndex(5)

    def _save(self):
        code = self._code_preview.toPlainText().strip()
        if not code:
            QMessageBox.warning(self, "No Code", "Generate a template first.")
            return

        module = getattr(self, '_module_name', _to_module_name(self._supplier_edit.text().strip()))
        templates_dir = Path(__file__).parent / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        file_path = templates_dir / f"{module}.py"

        if file_path.exists():
            reply = QMessageBox.question(
                self, "Overwrite?", f"{module}.py already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        file_path.write_text(code, encoding="utf-8")
        QMessageBox.information(self, "Saved", f"Template saved to:\n{file_path}")
        self.template_created.emit(module, str(file_path))

    def _test(self):
        code = self._code_preview.toPlainText().strip()
        if not code or not self._pdf_text:
            QMessageBox.warning(self, "Nothing to test", "Load a PDF and generate a template first.")
            return

        # Execute the generated code in a restricted namespace
        # Only expose safe builtins needed for template code
        safe_builtins = {
            k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
            for k in (
                'True', 'False', 'None', 'int', 'float', 'str', 'bool', 'list',
                'dict', 'tuple', 'set', 'len', 'range', 'enumerate', 'zip', 'map',
                'filter', 'sorted', 'min', 'max', 'sum', 'abs', 'round', 'isinstance',
                'hasattr', 'getattr', 'setattr', 'property', 'staticmethod',
                'classmethod', 'super', 'type', 'object', 'print', 'repr',
                'ValueError', 'TypeError', 'KeyError', 'IndexError', 'AttributeError',
                'Exception', 'StopIteration',
            )
            if (isinstance(__builtins__, dict) and k in __builtins__) or
               (not isinstance(__builtins__, dict) and hasattr(__builtins__, k))
        }
        # Allow imports needed by templates (re, pdfplumber, etc.)
        safe_builtins['__import__'] = __builtins__['__import__'] if isinstance(__builtins__, dict) else __builtins__.__import__
        ns: Dict = {'__builtins__': safe_builtins}
        try:
            exec(compile(code, "<template>", "exec"), ns)
        except Exception as e:
            QMessageBox.critical(self, "Syntax Error", f"Template code has errors:\n{e}")
            return

        # Find the template class
        cls = None
        for v in ns.values():
            try:
                if isinstance(v, type) and v.__name__ != "BaseTemplate" and hasattr(v, "extract_all"):
                    cls = v
                    break
            except Exception:
                pass

        if not cls:
            QMessageBox.warning(self, "Not Found", "Could not find template class in generated code.")
            return

        try:
            tmpl = cls()
            inv, po, items = tmpl.extract_all(self._pdf_text, self._tables)
        except Exception as e:
            QMessageBox.critical(self, "Runtime Error", f"Template raised an error:\n{e}")
            return

        # Display results
        self._result_table.setVisible(True)
        self._result_table.setRowCount(len(items))
        for row_idx, item in enumerate(items):
            for col_idx, key in enumerate(["part_number","quantity","total_price","unit_price","description"]):
                self._result_table.setItem(row_idx, col_idx, QTableWidgetItem(str(item.get(key,""))))

        QMessageBox.information(
            self, "Test Complete",
            f"Invoice #: {inv}\nPO #: {po}\nLine items extracted: {len(items)}"
        )


# ── Standalone smoke-test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    dlg = TemplateWizardDialog()
    dlg.show()
    sys.exit(app.exec())
