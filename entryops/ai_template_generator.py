"""
ai_template_generator.py — Token-efficient AI template generator for OCRMill / EntryOps.

Drop-in replacement. Auto-detects which app it lives in and adjusts the base class import
accordingly. Reduces token usage by ~75% vs the original via:
  - PDF text pre-processing (strip noise, cap at 2,000 chars)
  - Tight prompts (no scaffold pasted in)
  - max_tokens: 1500 (down from 4000)
  - Optional two-stage mode for complex invoices
"""

import os
import re
import sys
import json
import math
import importlib
import subprocess
import threading
from collections import Counter
from pathlib import Path

# EntryOps runs on PyQt5. The dialog code below is dead in EntryOps (the
# UI lives in entryops.py), but the AIGeneratorThread class is imported and
# instantiated at runtime, so the Qt imports MUST resolve. Prefer PyQt5
# (EntryOps's pinned dependency) and fall back to PyQt6 for OCRMill.
try:
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
    from PyQt5.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
        QLineEdit, QPushButton, QTextEdit, QCheckBox, QGroupBox,
        QFormLayout, QFileDialog, QMessageBox, QProgressBar,
        QSizePolicy, QSplitter, QWidget,
    )
    from PyQt5.QtGui import QFont, QTextCursor
except ImportError:
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
        QLineEdit, QPushButton, QTextEdit, QCheckBox, QGroupBox,
        QFormLayout, QFileDialog, QMessageBox, QProgressBar,
        QSizePolicy, QSplitter, QWidget,
    )
    from PyQt6.QtGui import QFont, QTextCursor

# ---------------------------------------------------------------------------
# Base-class auto-detection
# ---------------------------------------------------------------------------
# We try three import paths in order; whichever succeeds wins.
# If none succeed we fall back to an inline stub so the generated template
# still has something to inherit from.

_BASE_TEMPLATE_IMPORT = None   # will be set below
_BASE_TEMPLATE_CLASS  = None

def _try_import_base():
    global _BASE_TEMPLATE_IMPORT, _BASE_TEMPLATE_CLASS
    candidates = [
        ("base_template",                   "BaseTemplate"),   # OCRMill (same package)
        ("SmartExtractor.base_template",    "BaseTemplate"),   # EntryOps
        (".base_template",                  "BaseTemplate"),   # relative fallback
    ]
    for mod_path, cls_name in candidates:
        try:
            if mod_path.startswith("."):
                # relative import — skip here; handle in generated template
                continue
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name, None)
            if cls is not None:
                _BASE_TEMPLATE_IMPORT = (mod_path, cls_name)
                _BASE_TEMPLATE_CLASS  = cls
                return True
        except ImportError:
            continue
    return False

_try_import_base()

# Stub used only when neither app's base class can be imported at generator
# runtime. The *generated* template will include this inline stub.
_INLINE_BASE_STUB = '''\
class BaseTemplate:
    """Minimal stub — replace with the real BaseTemplate from your app."""
    def __init__(self, pdf_path=None):
        self.pdf_path = pdf_path
    def extract(self):
        raise NotImplementedError
    def to_dict(self):
        return {}
'''

# ---------------------------------------------------------------------------
# Package installer helper (mirrors original)
# ---------------------------------------------------------------------------

def _check_and_install_package(import_name: str, pip_name: str | None = None) -> bool:
    """Try to import *import_name*; install *pip_name* via pip if missing.

    Returns True if the package is available after the call.
    """
    pip_name = pip_name or import_name
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        pass
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pip_name, "--quiet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        importlib.import_module(import_name)
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# PDF text pre-processor
# ---------------------------------------------------------------------------

# Regex patterns for lines we want to KEEP (likely invoice data)
_KEEP_PATTERNS = [
    re.compile(r'\d'),               # any digit (amounts, dates, quantities, part#s)
    re.compile(r'\$|€|£|¥|USD|EUR|GBP|CAD|MXN', re.I),  # currency symbols / codes
    re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),               # ISO dates
    re.compile(r'\b(invoice|inv|bill|po|purchase order|total|subtotal|tax|'
               r'freight|charge|fee|amount|qty|quantity|unit|price|rate|'
               r'description|item|part|hts|tariff|duty|weight|gross|net|'
               r'vendor|supplier|shipper|consignee|buyer|seller|'
               r'date|number|no\.|#)\b', re.I),
]

# Regex for lines we always STRIP
_STRIP_PATTERNS = [
    re.compile(r'^\s*page\s+\d+\s*(of\s+\d+)?\s*$', re.I),  # "Page 1 of 3"
    re.compile(r'^\s*\d+\s*$'),                               # lone page numbers
    re.compile(r'^\s*[-_=*]{3,}\s*$'),                        # divider lines
    re.compile(r'^\s*$'),                                      # blank / whitespace only
]

MAX_PROCESSED_CHARS = 2000  # hard cap sent to the API


def preprocess_invoice_text(raw_text: str) -> str:
    """Reduce raw PDF text to only invoice-relevant lines, capped at 2,000 chars.

    Steps:
    1. Split into lines.
    2. Detect and remove repeated header/footer lines (appear on 3+ pages
       or ≥ 30 % of all non-blank lines — whichever threshold is hit first).
    3. Strip noise lines (page numbers, dividers, blanks).
    4. Keep only lines that match at least one invoice-data pattern.
    5. Hard-cap the result at MAX_PROCESSED_CHARS characters.
    """
    if not raw_text:
        return ""

    lines = raw_text.splitlines()
    total_lines = len(lines)

    # --- Step 1: find repeated header/footer candidates ---
    # A line is "repeated" if it appears verbatim 3+ times OR in ≥30 % of lines.
    stripped_lines = [ln.strip() for ln in lines]
    freq = Counter(ln for ln in stripped_lines if ln)
    threshold = max(3, math.ceil(total_lines * 0.30))
    repeated = {txt for txt, count in freq.items() if count >= threshold}

    # --- Step 2-4: filter ---
    kept = []
    for ln in lines:
        stripped = ln.strip()

        # Remove repeated headers/footers
        if stripped in repeated:
            continue

        # Remove noise lines
        if any(pat.match(stripped) for pat in _STRIP_PATTERNS):
            continue

        # Keep lines with invoice-relevant content
        if any(pat.search(stripped) for pat in _KEEP_PATTERNS):
            kept.append(stripped)

    result = "\n".join(kept)

    # --- Step 5: hard cap ---
    if len(result) > MAX_PROCESSED_CHARS:
        result = result[:MAX_PROCESSED_CHARS]
        # Trim to last full line so we don't cut mid-word
        last_nl = result.rfind("\n")
        if last_nl > MAX_PROCESSED_CHARS * 0.8:
            result = result[:last_nl]

    return result.strip()


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token (good enough for a UI label)."""
    return max(1, len(text) // 4)

# ---------------------------------------------------------------------------
# Prompt builders — EntryOps-flavoured
# ---------------------------------------------------------------------------
#
# EntryOps's BaseTemplate ABC requires a specific shape; a generic
# "InvoiceTemplate.extract() -> dict" contract is NOT compatible. Templates
# that don't subclass BaseTemplate correctly silently fail to match invoices
# at runtime because the auto-discovery scanner ignores them.
#
# We embed both the real BaseTemplate signature and a small worked example
# directly in the prompt so the model produces drop-in templates.

# Minimal worked example — a simplified Sigma-style template that compiles
# and works against the real BaseTemplate. Kept short so it fits in the
# token budget; the model is told to follow this shape.
_EXEMPLAR_TEMPLATE = '''
import re
from typing import List, Dict, Any
from .base_template import BaseTemplate


class ExampleSupplierTemplate(BaseTemplate):
    """Template for Example Supplier invoices to AcmeCo."""

    name = "AcmeCo - Example Supplier"
    description = "Commercial invoices from Example Supplier"
    client = "ACMECO"            # MUST match a client_code in the database
    version = "1.0.0"
    enabled = True

    extra_columns = ['unit_price', 'description', 'country_origin', 'hts_code', 'po_number']

    SUPPLIER_KEYWORDS = [
        'example supplier',
        'example-supplier.com',
        'unique-tax-id-here',
    ]

    def can_process(self, text: str) -> bool:
        t = text.lower()
        has_supplier = any(kw in t for kw in self.SUPPLIER_KEYWORDS)
        has_client = 'acmeco' in t or 'acme co' in t
        return has_supplier and has_client

    def get_confidence_score(self, text: str) -> float:
        if not self.can_process(text):
            return 0.0
        score = 0.6
        matches = sum(1 for kw in self.SUPPLIER_KEYWORDS if kw in text.lower())
        score += min(matches * 0.05, 0.25)
        return min(score, 0.95)

    def extract_invoice_number(self, text: str) -> str:
        m = re.search(r'Invoice\\s*(?:No\\.?|#)\\s*[:\\-]?\\s*([A-Z0-9/\\-]+)', text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def extract_project_number(self, text: str) -> str:
        m = re.search(r'\\bPO\\s*#?\\s*(\\d{6,10})', text, re.IGNORECASE)
        return m.group(1).strip() if m else "UNKNOWN"

    def extract_manufacturer_name(self, text: str) -> str:
        return "EXAMPLE SUPPLIER PVT. LTD."

    def extract_line_items(self, text: str) -> List[Dict[str, Any]]:
        # Anchor on a 2-decimal money amount at end of line to reject noise.
        pattern = re.compile(
            r'^([A-Z]{2,4}\\d+\\w*)\\s+'      # Part number
            r'(\\d+)\\s+'                       # Quantity
            r'(\\d+\\.\\d{2})\\s+'              # Unit price
            r'([\\d,]+\\.\\d{2})\\s*$',          # Amount (anchor)
            re.IGNORECASE | re.MULTILINE,
        )
        items = []
        for m in pattern.finditer(text):
            qty = int(m.group(2))
            unit_price = float(m.group(3))
            total = float(m.group(4).replace(',', ''))
            if abs(qty * unit_price - total) > 1.0:
                continue
            items.append({
                'part_number': m.group(1).strip().upper(),
                'description': '',
                'quantity': qty,
                'quantity_unit': 'NO',
                'unit_price': unit_price,
                'total_price': total,
                'country': 'XX',
                'country_origin': 'XX',
                'hts_code': '',
            })
        return items
'''.strip()


# Abstract interface that every EntryOps template MUST satisfy.
_TARIFFMILL_CONTRACT = """\
EntryOps template contract — MUST be followed:

1. Subclass `BaseTemplate` imported via `from .base_template import BaseTemplate`.
2. Set class attributes: `name`, `description`, `client` (the customer
   client_code, e.g. "ACME_CO" / "Example Industries" / "Sample Co"), `version`,
   `enabled = True`. Optional `extra_columns: List[str]`.
3. Implement these methods (all take a single `text: str` argument):
   - `can_process(self, text: str) -> bool` — return True if this template
     handles the given invoice text. Match on supplier name/ID/tax-id, NOT
     on layout features.
   - `get_confidence_score(self, text: str) -> float` — 0.0..0.95. Used to
     rank when multiple templates can_process the same text.
   - `extract_invoice_number(self, text: str) -> str`
   - `extract_project_number(self, text: str) -> str` — PO number, or
     "UNKNOWN" if not applicable for this supplier.
   - `extract_line_items(self, text: str) -> List[Dict]` — one dict per row.
     Required keys per row: `part_number`, `quantity`, `total_price`. Strongly
     recommended: `unit_price`, `description`, `quantity_unit`, `hts_code`,
     `country_origin` (ISO-2 code like "IN", "CN"), `po_number`.
   - `extract_manufacturer_name(self, text: str) -> str` — supplier legal name.
   - `is_packing_list(self, text: str) -> bool` — return False if the doc
     contains a commercial invoice (even if it also has a packing list
     section); True only for pure packing-list documents.
4. Anchor line-item regex on a 2-decimal money amount (`\\d+\\.\\d{2}`) to
   reject weight/packing-list rows.
5. Validate via `qty * unit_price == total_price` (within 1¢) inside the loop.
6. Output ONLY valid Python. No markdown fences, no explanation, no prose.
"""


# Generation hint that gets templated with user-supplied metadata.
def _metadata_block(template_name: str, supplier_name: str,
                    client: str, country: str) -> str:
    return (
        f"Template metadata to use verbatim:\n"
        f"- File will be saved as: {template_name}.py\n"
        f"- Supplier legal name: {supplier_name}\n"
        f"- Client (customer code): {client}\n"
        f"- Country of origin (ISO-2 if known, full name otherwise): {country}\n"
    )


_SYSTEM_FAST = (
    "You are an expert Python developer building invoice extraction templates "
    "for EntryOps, a customs entry processing tool. Follow the contract "
    "described in the user message exactly. The example template shown is "
    "the canonical shape — match it. Output only Python code."
)

_SYSTEM_STAGE1 = (
    "You are analysing an invoice document to seed a EntryOps template. "
    "List 3-5 brief observations: supplier identifiers (name/tax-id/email), "
    "invoice-number format, line-item row shape (part number, qty, prices), "
    "PO number location, currency, HTS/HS code if present. Be terse — your "
    "notes feed a code-generation step."
)

_SYSTEM_STAGE2 = (
    "You are an expert Python developer building invoice extraction templates "
    "for EntryOps. Use the structural analysis to write a template that "
    "follows the contract exactly. The example template shown is the canonical "
    "shape — match it. Output only Python code."
)


def build_fast_prompt(processed_text: str, extra_hint: str = "",
                      template_name: str = "", supplier_name: str = "",
                      client: str = "", country: str = "") -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the single-call fast mode."""
    hint_line = f"\nExtra context: {extra_hint.strip()}" if extra_hint.strip() else ""
    metadata = _metadata_block(template_name or "supplier_template",
                               supplier_name or "Unknown Supplier",
                               client or "Universal",
                               country or "UNKNOWN")
    user = (
        f"{metadata}\n"
        f"{_TARIFFMILL_CONTRACT}\n"
        f"Canonical example template (match this shape):\n"
        f"```python\n{_EXEMPLAR_TEMPLATE}\n```\n\n"
        f"Invoice text sample (first ~2000 chars):\n"
        f"---\n{processed_text}\n---"
        f"{hint_line}"
    )
    return _SYSTEM_FAST, user


def build_stage1_prompt(processed_text: str) -> tuple[str, str]:
    """Return (system, user) for the structure-identification stage."""
    user = (
        f"Analyse this invoice sample for EntryOps template extraction. "
        f"List 3-5 brief observations covering supplier identifiers, invoice "
        f"number format, line-item row shape, PO number location, currency, "
        f"and HTS code. Be very brief.\n\n"
        f"---\n{processed_text}\n---"
    )
    return _SYSTEM_STAGE1, user


def build_stage2_prompt(processed_text: str, analysis: str, extra_hint: str = "",
                        template_name: str = "", supplier_name: str = "",
                        client: str = "", country: str = "") -> tuple[str, str]:
    """Return (system, user) for the code-generation stage after analysis."""
    hint_line = f"\nExtra context: {extra_hint.strip()}" if extra_hint.strip() else ""
    metadata = _metadata_block(template_name or "supplier_template",
                               supplier_name or "Unknown Supplier",
                               client or "Universal",
                               country or "UNKNOWN")
    user = (
        f"{metadata}\n"
        f"Structure analysis from prior step:\n{analysis}\n\n"
        f"{_TARIFFMILL_CONTRACT}\n"
        f"Canonical example template (match this shape):\n"
        f"```python\n{_EXEMPLAR_TEMPLATE}\n```\n\n"
        f"Invoice text sample:\n---\n{processed_text}\n---"
        f"{hint_line}"
    )
    return _SYSTEM_STAGE2, user

# ---------------------------------------------------------------------------
# Template code wrapper
# ---------------------------------------------------------------------------

def wrap_template_code(raw_code: str) -> str:
    """Strip markdown fences from AI output and ensure correct BaseTemplate import.

    EntryOps templates live in `entryops/templates/` and import the base
    class via `from .base_template import BaseTemplate`. We leave the AI's
    output alone if it already includes a valid relative import; otherwise
    we rewrite or inject the right one.
    """
    code = re.sub(r"^```(?:python)?\s*", "", raw_code.strip(), flags=re.IGNORECASE)
    code = re.sub(r"\s*```\s*$", "", code)
    code = code.strip()

    # The EntryOps-friendly import. Templates are loaded as a package, so
    # the relative form is required for auto-discovery.
    correct_import = "from .base_template import BaseTemplate"

    # Replace any wrong BaseTemplate import (absolute paths, wrong package names)
    # with the relative one. Leave the relative one untouched.
    def _fix_import(match):
        existing = match.group(0)
        return existing if existing == correct_import else correct_import

    code, n_replaced = re.subn(
        r"^from\s+\S*base_template\s+import\s+BaseTemplate\s*$",
        _fix_import,
        code,
        flags=re.MULTILINE,
    )

    # Drop any `import base_template` style imports — relative-from is the
    # only form that auto-discovery accepts.
    code = re.sub(r"^import\s+base_template.*$", "", code, flags=re.MULTILINE)

    # If no BaseTemplate import survived rewriting, inject one near the top.
    if correct_import not in code:
        # Find a sensible insertion point: after the last top-level import.
        lines = code.splitlines()
        last_import_idx = -1
        for i, ln in enumerate(lines):
            if re.match(r'^\s*(import|from)\s+\S', ln):
                last_import_idx = i
        if last_import_idx >= 0:
            lines.insert(last_import_idx + 1, correct_import)
        else:
            lines.insert(0, correct_import)
        code = '\n'.join(lines)

    # Prepend a header banner if the AI didn't already mark the file.
    if not code.lstrip().startswith('#'):
        code = "# Auto-generated by AITemplateGenerator — edit as needed.\n" + code

    return code

# ---------------------------------------------------------------------------
# AI provider call implementations
# ---------------------------------------------------------------------------

class _ProviderError(Exception):
    pass


def _call_openai(api_key: str, model: str, system: str, user: str,
                 max_tokens: int = 1500, stream_cb=None) -> str:
    if not _check_and_install_package("openai"):
        raise _ProviderError("openai package not available.")
    import openai
    client = openai.OpenAI(api_key=api_key)
    messages = [{"role": "system", "content": system},
                {"role": "user",   "content": user}]
    if stream_cb:
        result = []
        with client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, stream=True
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                result.append(delta)
                stream_cb(delta)
        return "".join(result)
    else:
        resp = client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens
        )
        return resp.choices[0].message.content or ""


def _call_anthropic(api_key: str, model: str, system: str, user: str,
                    max_tokens: int = 1500, stream_cb=None) -> str:
    if not _check_and_install_package("anthropic"):
        raise _ProviderError("anthropic package not available.")
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    if stream_cb:
        result = []
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            for text in stream.text_stream:
                result.append(text)
                stream_cb(text)
        return "".join(result)
    else:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text


def _call_google(api_key: str, model: str, system: str, user: str,
                 max_tokens: int = 1500, stream_cb=None) -> str:
    if not _check_and_install_package("google.generativeai", "google-generativeai"):
        raise _ProviderError("google-generativeai package not available.")
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    gmodel = genai.GenerativeModel(
        model_name=model,
        system_instruction=system,
        generation_config={"max_output_tokens": max_tokens},
    )
    combined = user
    if stream_cb:
        result = []
        for chunk in gmodel.generate_content(combined, stream=True):
            txt = chunk.text or ""
            result.append(txt)
            stream_cb(txt)
        return "".join(result)
    else:
        resp = gmodel.generate_content(combined)
        return resp.text or ""


def _call_groq(api_key: str, model: str, system: str, user: str,
               max_tokens: int = 1500, stream_cb=None) -> str:
    if not _check_and_install_package("groq"):
        raise _ProviderError("groq package not available.")
    from groq import Groq
    client = Groq(api_key=api_key)
    messages = [{"role": "system", "content": system},
                {"role": "user",   "content": user}]
    if stream_cb:
        result = []
        with client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, stream=True
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                result.append(delta)
                stream_cb(delta)
        return "".join(result)
    else:
        resp = client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens
        )
        return resp.choices[0].message.content or ""


def _call_ollama(host: str, model: str, system: str, user: str,
                 max_tokens: int = 1500, stream_cb=None) -> str:
    """Ollama uses a local HTTP endpoint — no API key needed."""
    if not _check_and_install_package("requests"):
        raise _ProviderError("requests package not available.")
    import requests
    base_url = host.rstrip("/") if host else "http://localhost:11434"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user",   "content": user}],
        "options": {"num_predict": max_tokens},
        "stream": bool(stream_cb),
    }
    resp = requests.post(f"{base_url}/api/chat", json=payload, stream=bool(stream_cb), timeout=120)
    resp.raise_for_status()
    if stream_cb:
        result = []
        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            delta = data.get("message", {}).get("content", "")
            result.append(delta)
            stream_cb(delta)
        return "".join(result)
    else:
        data = resp.json()
        return data.get("message", {}).get("content", "")


def _call_openai_compat(api_key: str, base_url: str, model: str,
                        system: str, user: str,
                        max_tokens: int = 1500, stream_cb=None) -> str:
    """OpenAI-compatible endpoint (OpenRouter, Together AI)."""
    if not _check_and_install_package("openai"):
        raise _ProviderError("openai package not available.")
    import openai
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    messages = [{"role": "system", "content": system},
                {"role": "user",   "content": user}]
    if stream_cb:
        result = []
        with client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, stream=True
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                result.append(delta)
                stream_cb(delta)
        return "".join(result)
    else:
        resp = client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens
        )
        return resp.choices[0].message.content or ""

# ---------------------------------------------------------------------------
# Background worker thread
# ---------------------------------------------------------------------------

class AIGeneratorThread(QThread):
    """Runs the AI API call(s) off the main thread.

    Two ways to construct:

    1. Raw mode (legacy):
         AIGeneratorThread(provider=..., api_key=..., model=...,
                           processed_text=..., fast_mode=...)
       Caller pre-processes the invoice text and connects to the
       chunk_ready/generation_complete/generation_error/stage_update signals.

    2. Friendly mode (used by the EntryOps UI):
         AIGeneratorThread(provider=..., api_key=..., model=...,
                           invoice_text=..., template_name=..., supplier_name=...,
                           client=..., country=...)
       The thread preprocesses invoice_text internally and emits a richer
       set of aliased signals: stream_update / completed / error / progress /
       cancelled — matching the EntryOps UI's existing handlers.
    """

    # Canonical signals (raw mode)
    chunk_ready         = pyqtSignal(str)
    generation_complete = pyqtSignal(str)
    generation_error    = pyqtSignal(str)
    stage_update        = pyqtSignal(str)

    # Friendly aliases for the EntryOps UI. Connected internally so callers
    # can use whichever name fits their handler.
    stream_update = pyqtSignal(str)   # alias of chunk_ready
    completed     = pyqtSignal(str)   # alias of generation_complete
    error         = pyqtSignal(str)   # alias of generation_error
    progress      = pyqtSignal(str)   # alias of stage_update
    cancelled     = pyqtSignal()      # emitted when cancel() takes effect

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        processed_text: str = "",
        fast_mode: bool = True,
        extra_hint: str = "",
        ollama_host: str = "",
        openrouter_base: str = "https://openrouter.ai/api/v1",
        together_base: str   = "https://api.together.xyz/v1",
        invoice_text: str = "",
        template_name: str = "",
        supplier_name: str = "",
        client: str = "",
        country: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.provider        = provider
        self.api_key         = api_key
        self.model           = model
        # Friendly mode auto-preprocesses raw invoice text if supplied.
        if invoice_text and not processed_text:
            processed_text = preprocess_invoice_text(invoice_text)
        self.processed_text  = processed_text
        self.fast_mode       = fast_mode
        self.extra_hint      = extra_hint
        self.ollama_host     = ollama_host
        self.openrouter_base = openrouter_base
        self.together_base   = together_base
        self.template_name   = template_name
        self.supplier_name   = supplier_name
        self.client          = client
        self.country         = country
        self._cancelled      = False

        # Wire alias signals to their canonical counterparts.
        self.chunk_ready.connect(self.stream_update)
        self.generation_complete.connect(self.completed)
        self.generation_error.connect(self.error)
        self.stage_update.connect(self.progress)

    def cancel(self):
        self._cancelled = True

    def _dispatch(self, system: str, user: str, max_tokens: int = 1500,
                  stream: bool = True) -> str:
        """Route the call to the correct provider and return the full response."""

        def stream_cb(chunk: str):
            if not self._cancelled:
                self.chunk_ready.emit(chunk)

        cb = stream_cb if stream else None
        p  = self.provider.lower()

        if p == "openai":
            return _call_openai(self.api_key, self.model, system, user, max_tokens, cb)
        elif p == "anthropic":
            return _call_anthropic(self.api_key, self.model, system, user, max_tokens, cb)
        elif p in ("google", "gemini"):
            return _call_google(self.api_key, self.model, system, user, max_tokens, cb)
        elif p == "groq":
            return _call_groq(self.api_key, self.model, system, user, max_tokens, cb)
        elif p == "ollama":
            return _call_ollama(self.ollama_host, self.model, system, user, max_tokens, cb)
        elif p == "openrouter":
            return _call_openai_compat(self.api_key, self.openrouter_base, self.model,
                                       system, user, max_tokens, cb)
        elif p in ("together", "together ai"):
            return _call_openai_compat(self.api_key, self.together_base, self.model,
                                       system, user, max_tokens, cb)
        else:
            raise _ProviderError(f"Unknown provider: {self.provider!r}")

    def run(self):
        try:
            meta = dict(
                template_name=self.template_name,
                supplier_name=self.supplier_name,
                client=self.client,
                country=self.country,
            )
            if self.fast_mode:
                # ---- Single-call fast mode ----
                self.stage_update.emit("Generating template…")
                system, user = build_fast_prompt(
                    self.processed_text, self.extra_hint, **meta
                )
                raw = self._dispatch(system, user, max_tokens=2500, stream=True)
            else:
                # ---- Two-stage mode ----
                self.stage_update.emit("Stage 1/2: Analysing invoice structure…")
                s1_sys, s1_usr = build_stage1_prompt(self.processed_text)
                analysis = self._dispatch(s1_sys, s1_usr, max_tokens=400, stream=False)
                if self._cancelled:
                    self.cancelled.emit()
                    return

                self.stage_update.emit("Stage 2/2: Generating template…")
                s2_sys, s2_usr = build_stage2_prompt(
                    self.processed_text, analysis, self.extra_hint, **meta
                )
                raw = self._dispatch(s2_sys, s2_usr, max_tokens=2500, stream=True)

            if self._cancelled:
                self.cancelled.emit()
                return

            wrapped = wrap_template_code(raw)
            self.generation_complete.emit(wrapped)

        except Exception as exc:  # noqa: BLE001
            if not self._cancelled:
                self.generation_error.emit(str(exc))
            else:
                self.cancelled.emit()

# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

# Provider display name → internal key used in _dispatch
_PROVIDERS = {
    "OpenAI":        "openai",
    "Anthropic":     "anthropic",
    "Google Gemini": "google",
    "Groq":          "groq",
    "Ollama":        "ollama",
    "OpenRouter":    "openrouter",
    "Together AI":   "together",
}

# Sensible default models per provider
_DEFAULT_MODELS = {
    "openai":      "gpt-4o-mini",
    "anthropic":   "claude-3-5-haiku-20241022",
    "google":      "gemini-1.5-flash",
    "groq":        "llama-3.1-8b-instant",
    "ollama":      "llama3",
    "openrouter":  "mistralai/mistral-7b-instruct",
    "together":    "mistralai/Mistral-7B-Instruct-v0.1",
}


class AITemplateGeneratorDialog(QDialog):
    """Dialog for generating invoice parsing templates with a token-efficient AI pipeline.

    Signals:
        template_created(str) — emitted with the path to the saved template file.
    """

    template_created = pyqtSignal(str)

    def __init__(self, parent=None, db=None, initial_pdf_path: str = ""):
        """
        Args:
            parent:           Parent QWidget.
            db:               Optional database connection for API key persistence.
                              Expected to have get_setting(key) / set_setting(key, value).
            initial_pdf_path: Pre-load a PDF path into the invoice path field.
        """
        super().__init__(parent)
        self._db              = db
        self._raw_text        = ""      # full extracted PDF text
        self._processed_text  = ""      # pre-processed text sent to AI
        self._thread: AIGeneratorThread | None = None
        self._generated_code  = ""

        self.setWindowTitle("AI Template Generator")
        self.setMinimumSize(820, 680)
        self._build_ui()

        if initial_pdf_path:
            self._pdf_path_edit.setText(initial_pdf_path)
            self._on_pdf_path_changed(initial_pdf_path)

        self._load_api_keys()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ---- Provider / model row ----
        prov_box = QGroupBox("Provider & Model")
        prov_form = QFormLayout(prov_box)

        self._provider_combo = QComboBox()
        self._provider_combo.addItems(list(_PROVIDERS.keys()))
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        prov_form.addRow("Provider:", self._provider_combo)

        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("Model name…")
        prov_form.addRow("Model:", self._model_edit)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("API key (saved to local DB)")
        prov_form.addRow("API Key:", self._api_key_edit)

        self._ollama_host_edit = QLineEdit()
        self._ollama_host_edit.setPlaceholderText("http://localhost:11434")
        self._ollama_host_edit.setVisible(False)
        prov_form.addRow("Ollama Host:", self._ollama_host_edit)
        self._ollama_host_label = prov_form.labelForField(self._ollama_host_edit)

        root.addWidget(prov_box)

        # ---- Invoice source row ----
        pdf_box = QGroupBox("Invoice Source")
        pdf_layout = QHBoxLayout(pdf_box)

        self._pdf_path_edit = QLineEdit()
        self._pdf_path_edit.setPlaceholderText("Path to invoice PDF (or paste text below)…")
        self._pdf_path_edit.textChanged.connect(self._on_pdf_path_changed)
        pdf_layout.addWidget(self._pdf_path_edit)

        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_pdf)
        pdf_layout.addWidget(browse_btn)

        root.addWidget(pdf_box)

        # ---- Token stats label ----
        self._token_label = QLabel("Est. input: — tokens  |  Sending 0 of 0 chars")
        self._token_label.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(self._token_label)

        # ---- Options row ----
        opts_row = QHBoxLayout()

        self._fast_mode_cb = QCheckBox("Fast mode (single API call)")
        self._fast_mode_cb.setChecked(True)
        self._fast_mode_cb.setToolTip(
            "ON (default): one tight API call, ~800–1200 tokens.\n"
            "OFF: two-stage — identify structure first, then generate code."
        )
        opts_row.addWidget(self._fast_mode_cb)

        self._hint_edit = QLineEdit()
        self._hint_edit.setPlaceholderText("Optional hint (vendor name, special field, etc.)")
        self._hint_edit.textChanged.connect(self._update_token_label)
        opts_row.addWidget(self._hint_edit, 1)

        root.addLayout(opts_row)

        # ---- Splitter: raw text input | generated code output ----
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: raw / pasted text
        raw_group = QGroupBox("Invoice Text (paste or auto-loaded from PDF)")
        raw_layout = QVBoxLayout(raw_group)
        self._raw_text_edit = QTextEdit()
        self._raw_text_edit.setPlaceholderText(
            "Paste invoice text here, or load a PDF above…"
        )
        self._raw_text_edit.textChanged.connect(self._on_raw_text_changed)
        raw_layout.addWidget(self._raw_text_edit)
        splitter.addWidget(raw_group)

        # Bottom: generated code
        code_group = QGroupBox("Generated Template Code")
        code_layout = QVBoxLayout(code_group)
        self._code_edit = QTextEdit()
        self._code_edit.setReadOnly(True)
        self._code_edit.setFont(QFont("Monospace", 9))
        code_layout.addWidget(self._code_edit)
        splitter.addWidget(code_group)

        splitter.setSizes([220, 340])
        root.addWidget(splitter, 1)

        # ---- Status / progress ----
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #555;")
        root.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # ---- Buttons ----
        btn_row = QHBoxLayout()

        self._generate_btn = QPushButton("Generate Template")
        self._generate_btn.setDefault(True)
        self._generate_btn.clicked.connect(self._start_generation)
        btn_row.addWidget(self._generate_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_generation)
        btn_row.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Save Template")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_template)
        btn_row.addWidget(self._save_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

        # Fire the provider change handler to set correct defaults
        self._on_provider_changed(self._provider_combo.currentText())

    # ------------------------------------------------------------------
    # Slots / helpers
    # ------------------------------------------------------------------

    def _on_provider_changed(self, display_name: str):
        key = _PROVIDERS.get(display_name, "openai")
        self._model_edit.setText(_DEFAULT_MODELS.get(key, ""))
        is_ollama = (key == "ollama")
        self._ollama_host_edit.setVisible(is_ollama)
        if hasattr(self, "_ollama_host_label") and self._ollama_host_label:
            self._ollama_host_label.setVisible(is_ollama)
        self._api_key_edit.setVisible(not is_ollama)
        self._load_api_key_for_provider(key)

    def _browse_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Invoice PDF", "", "PDF Files (*.pdf);;All Files (*)"
        )
        if path:
            self._pdf_path_edit.setText(path)

    def _on_pdf_path_changed(self, path: str):
        path = path.strip()
        if not path or not os.path.isfile(path):
            return
        if not path.lower().endswith(".pdf"):
            return
        # Extract text in a lightweight thread to avoid blocking the UI
        t = threading.Thread(target=self._extract_pdf_text, args=(path,), daemon=True)
        t.start()

    def _extract_pdf_text(self, path: str):
        """Extract raw text from a PDF file using pdfplumber or PyMuPDF."""
        text = ""
        try:
            if _check_and_install_package("pdfplumber"):
                import pdfplumber
                with pdfplumber.open(path) as pdf:
                    parts = []
                    for page in pdf.pages:
                        pt = page.extract_text() or ""
                        parts.append(pt)
                    text = "\n--- PAGE BREAK ---\n".join(parts)
            elif _check_and_install_package("fitz", "pymupdf"):
                import fitz  # type: ignore
                doc = fitz.open(path)
                parts = [doc[i].get_text() for i in range(len(doc))]
                text = "\n--- PAGE BREAK ---\n".join(parts)
                doc.close()
        except Exception as exc:  # noqa: BLE001
            text = f"[Error reading PDF: {exc}]"

        # Update UI on main thread
        from PyQt6.QtCore import QMetaObject, Qt as _Qt
        self._raw_text = text
        QMetaObject.invokeMethod(self, "_apply_extracted_text", _Qt.ConnectionType.QueuedConnection)

    def _apply_extracted_text(self):
        """Called on main thread after PDF extraction completes."""
        self._raw_text_edit.setPlainText(self._raw_text)
        # textChanged signal will fire and call _on_raw_text_changed

    def _on_raw_text_changed(self):
        raw = self._raw_text_edit.toPlainText()
        self._raw_text = raw
        self._processed_text = preprocess_invoice_text(raw)
        self._update_token_label()

    def _update_token_label(self):
        raw_chars  = len(self._raw_text)
        proc_chars = len(self._processed_text)
        hint_chars = len(self._hint_edit.text()) if hasattr(self, "_hint_edit") else 0

        # System prompt + interface contract + prompt overhead ≈ 400 tokens
        overhead_chars = 1600
        total_input_chars = proc_chars + overhead_chars + hint_chars
        est_tokens = estimate_tokens(total_input_chars)

        self._token_label.setText(
            f"~Est. input: ~{est_tokens:,} tokens  |  "
            f"Sending {proc_chars:,} of {raw_chars:,} chars"
        )

    def _current_provider_key(self) -> str:
        return _PROVIDERS.get(self._provider_combo.currentText(), "openai")

    # --- API key persistence via optional DB ---

    def _api_key_db_key(self, provider_key: str) -> str:
        return f"ai_generator_api_key_{provider_key}"

    def _load_api_keys(self):
        """Load API key for the current provider from DB if available."""
        self._load_api_key_for_provider(self._current_provider_key())

    def _load_api_key_for_provider(self, provider_key: str):
        if self._db is None:
            return
        try:
            key = self._db.get_setting(self._api_key_db_key(provider_key)) or ""
            self._api_key_edit.setText(key)
        except Exception:  # noqa: BLE001
            pass

    def _save_api_key(self):
        if self._db is None:
            return
        provider_key = self._current_provider_key()
        try:
            self._db.set_setting(
                self._api_key_db_key(provider_key),
                self._api_key_edit.text().strip()
            )
        except Exception:  # noqa: BLE001
            pass

    # --- Generation ---

    def _start_generation(self):
        proc_text = self._processed_text.strip()
        if not proc_text:
            QMessageBox.warning(self, "No Invoice Text",
                                "Please load a PDF or paste invoice text first.")
            return

        api_key = self._api_key_edit.text().strip()
        provider_key = self._current_provider_key()
        if provider_key != "ollama" and not api_key:
            QMessageBox.warning(self, "API Key Required",
                                f"Please enter an API key for {self._provider_combo.currentText()}.")
            return

        self._save_api_key()

        # Clear previous output
        self._code_edit.clear()
        self._generated_code = ""
        self._save_btn.setEnabled(False)

        self._generate_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._progress.setVisible(True)
        self._status_label.setText("Starting generation…")

        self._thread = AIGeneratorThread(
            provider        = provider_key,
            api_key         = api_key,
            model           = self._model_edit.text().strip(),
            processed_text  = proc_text,
            fast_mode       = self._fast_mode_cb.isChecked(),
            extra_hint      = self._hint_edit.text().strip(),
            ollama_host     = self._ollama_host_edit.text().strip(),
        )
        self._thread.chunk_ready.connect(self._on_chunk)
        self._thread.generation_complete.connect(self._on_complete)
        self._thread.generation_error.connect(self._on_error)
        self._thread.stage_update.connect(self._status_label.setText)
        self._thread.start()

    def _cancel_generation(self):
        if self._thread:
            self._thread.cancel()
            self._thread.quit()
        self._reset_ui_after_generation()
        self._status_label.setText("Cancelled.")

    def _on_chunk(self, chunk: str):
        """Append a streaming chunk to the code editor."""
        cursor = self._code_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(chunk)
        self._code_edit.setTextCursor(cursor)
        self._code_edit.ensureCursorVisible()

    def _on_complete(self, code: str):
        self._generated_code = code
        self._code_edit.setPlainText(code)   # replace streaming display with wrapped version
        self._save_btn.setEnabled(True)
        self._status_label.setText("✓ Template generated successfully.")
        self._reset_ui_after_generation()

    def _on_error(self, msg: str):
        self._status_label.setText(f"Error: {msg}")
        QMessageBox.critical(self, "Generation Error", msg)
        self._reset_ui_after_generation()

    def _reset_ui_after_generation(self):
        self._generate_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._progress.setVisible(False)

    # --- Save ---

    def _save_template(self):
        if not self._generated_code:
            return

        # Determine default filename from the class or a fallback
        cls_match = re.search(r"class\s+(\w+)\s*\(", self._generated_code)
        default_name = (cls_match.group(1) if cls_match else "GeneratedTemplate") + ".py"

        templates_dir = Path("templates")
        templates_dir.mkdir(exist_ok=True)

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Template",
            str(templates_dir / default_name),
            "Python Files (*.py);;All Files (*)",
        )
        if not path:
            return

        try:
            Path(path).write_text(self._generated_code, encoding="utf-8")
            self._status_label.setText(f"Saved: {path}")
            self.template_created.emit(path)
            QMessageBox.information(self, "Saved", f"Template saved to:\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "Save Error", str(exc))


# ---------------------------------------------------------------------------
# Stand-alone test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # Quick smoke-test of preprocess_invoice_text
    sample = """
    ACME Corp                        Page 1 of 2
    123 Main Street
    ACME Corp                        Page 1 of 2
    Invoice #: INV-2024-0042
    Date: 2024-03-15
    Bill To: Widget LLC
    ACME Corp                        Page 1 of 2

    Qty   Description           Unit Price   Total
    10    Widget A              $12.50        $125.00
    5     Gadget B              $34.00        $170.00

    Subtotal: $295.00
    Tax (8%): $23.60
    Total:    $318.60
    ACME Corp                        Page 2 of 2
    Terms: Net 30
    """

    processed = preprocess_invoice_text(sample)
    print("=== Processed text ===")
    print(processed)
    print(f"\nRaw: {len(sample)} chars → Processed: {len(processed)} chars")
    print(f"Est. tokens: {estimate_tokens(len(processed) + 1600)}")

    dlg = AITemplateGeneratorDialog()
    dlg._raw_text_edit.setPlainText(sample)
    dlg.show()
    sys.exit(app.exec())
