# -*- mode: python ; coding: utf-8 -*-
"""
DocHopper PyInstaller Spec File - Standard Edition
Build command: pyinstaller dochopper.spec
"""

import os
import sys

block_cipher = None

from PyInstaller.utils.hooks import collect_all

# Collect pytz/tzdata metadata and data files to prevent version detection failures
pytz_datas, pytz_binaries, pytz_hiddenimports = collect_all('pytz')
tzdata_datas, tzdata_binaries, tzdata_hiddenimports = collect_all('tzdata')

# OCR fallback dependencies. collect_all() (not just hiddenimports) is
# required because TesseractBackend defers `import pytesseract` and
# `import pymupdf` into its constructor — PyInstaller's static analysis
# can't follow those without the full package tree being pulled in.
# `fitz` is pymupdf's shim module; it must be collected separately on
# pymupdf >= 1.24 or the shim is missing at runtime.
_ocr_datas = []
_ocr_binaries = []
_ocr_hiddenimports = []
for _pkg in ('pytesseract', 'pymupdf', 'fitz', 'PIL'):
    try:
        _d, _b, _h = collect_all(_pkg)
        _ocr_datas += _d
        _ocr_binaries += _b
        _ocr_hiddenimports += _h
    except Exception:
        pass

# XLSX/XLS commercial-invoice support for OCRMill PDF Processing
# (added v1.6.0). xlrd is the legacy binary .xls reader and is imported
# lazily inside ocrmill_processor.load_xlsx_as_text_and_tables, so its
# package tree must be pulled in explicitly here. openpyxl handles .xlsx
# and is already in hiddenimports below.
#
# (Playwright was previously bundled here for the ISF Filing tab; that
# tab was retired in v1.6.1 and Playwright is no longer needed by
# DocHopper. Reintroduce only if a future feature needs it.)
_isf_datas = []
_isf_binaries = []
_isf_hiddenimports = []
for _pkg in ('xlrd',):
    try:
        _d, _b, _h = collect_all(_pkg)
        _isf_datas += _d
        _isf_binaries += _b
        _isf_hiddenimports += _h
    except Exception:
        pass

# Get the absolute path to the Dochopper directory
dochopper_dir = os.path.join(os.path.dirname(os.path.abspath(SPEC)), 'Dochopper')

# Find Python DLLs to include
python_dir = os.path.dirname(sys.executable)
python_dlls = []
for dll_name in ['python3.dll', 'python312.dll', 'python313.dll', 'vcruntime140.dll', 'vcruntime140_1.dll']:
    dll_path = os.path.join(python_dir, dll_name)
    if os.path.exists(dll_path):
        python_dlls.append((dll_path, '.'))

# Analysis configuration
a = Analysis(
    [os.path.join(dochopper_dir, 'dochopper.py')],
    pathex=[dochopper_dir],
    binaries=python_dlls + pytz_binaries + tzdata_binaries + _ocr_binaries + _isf_binaries,
    datas=[
        # Resources
        (os.path.join(dochopper_dir, 'Resources', 'icon.ico'), 'Resources'),
        (os.path.join(dochopper_dir, 'Resources', 'dochopper_logo_small.svg'), 'Resources'),
        (os.path.join(dochopper_dir, 'Resources', 'dochopper_logo_small_dark.svg'), 'Resources'),
        (os.path.join(dochopper_dir, 'Resources', 'dochopper_icon.svg'), 'Resources'),
        # Reference files
        (os.path.join(dochopper_dir, 'Resources', 'References', 'hts.db'), 'Resources/References'),
        (os.path.join(dochopper_dir, 'Resources', 'References', 'CBP_232_tariffs.xlsx'), 'Resources/References'),
        (os.path.join(dochopper_dir, 'Resources', 'References', 'SEC232.txt'), 'Resources/References'),
        (os.path.join(dochopper_dir, 'Resources', 'References', 'Attachment 2_Auto Parts HTS List.txt'), 'Resources/References'),
        (os.path.join(dochopper_dir, 'Resources', 'References', 'parts_master_template.csv'), 'Resources/References'),
        (os.path.join(dochopper_dir, 'Resources', 'References', 'tariff_232_import_template.csv'), 'Resources/References'),
        # Templates directory
        (os.path.join(dochopper_dir, 'templates'), 'templates'),
        # OCR subpackage (pure Python, but PyInstaller doesn't auto-bundle
        # nested packages that aren't imported at startup).
        (os.path.join(dochopper_dir, 'ocr'), 'ocr'),
        # ISF Filing subpackage retired from DocHopper UI in v1.6.1; the
        # package files remain in the repo as the seed for the standalone
        # ISF agent's lift-out, but they're no longer bundled into the
        # DocHopper installer (no code path consumes them).
    ] + pytz_datas + tzdata_datas + _ocr_datas + _isf_datas,
    hiddenimports=[
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtSvg',
        'pandas',
        'pandas._libs',
        'pandas._libs.tslibs',
        'numpy',
        'openpyxl',
        'openpyxl.styles',
        # OCRMill XLSX/XLS invoice support added in v1.6.0 — load_workbook
        # path imports these submodules at first use; PyInstaller's static
        # analysis sometimes misses the lazy load triggered by data_only=True
        # + read_only=True, so list them explicitly.
        'openpyxl.cell',
        'openpyxl.workbook',
        'openpyxl.reader.excel',
        'pdfplumber',
        'pdfplumber.utils',
        'pdfminer',
        'pdfminer.high_level',
        'pdfminer.layout',
        'pdfminer.pdfparser',
        'pdfminer.pdfdocument',
        'pdfminer.pdfpage',
        'pdfminer.pdfinterp',
        'pdfminer.converter',
        'pdfminer.cmapdb',
        'pdfminer.psparser',
        'PIL',
        'PIL.Image',
        'requests',
        'sqlite3',
        'json',
        'csv',
        'xml.etree.ElementTree',
        'xml.dom.minidom',
        'configparser',
        'hashlib',
        'threading',
        'concurrent.futures',
        'dataclasses',
        'typing',
        'pathlib',
        'pytz',
        'tzdata',
        'tempfile',
        'webbrowser',
        'socket',
        'getpass',
        # AI providers
        'anthropic',
        'anthropic._client',
        'anthropic._base_client',
        'anthropic.resources',
        'anthropic.types',
        'httpx',
        'httpcore',
        'anyio',
        'sniffio',
        'h11',
        'certifi',
        'httpx._transports',
        'httpx._transports.default',
        # DocHopper modules
        'ai_template_generator',
        'ai_agent_core',
        'ai_agent_tools',
        'ai_agent_ui',
        'ai_agent_integration',
        'animated_splash',
        'auto_template_generator_dialog',
        'auto_update',
        'ollama_helper',
        'ocrmill_processor',
        'ocrmill_database',
        'ocrmill_worker',
        'ocrmill_enrichment',
        'ocrmill_exporter',
        'settings_manager',
        'settings_dialog',
        'template_generator',
        'version',
        # Templates
        'templates',
        'templates.base_template',
        'templates.bill_of_lading',
        'templates.lacey_act_form',
        'templates.sample_template',
        # OCR subpackage — pure Python, but TesseractBackend does its heavy
        # imports lazily, so the modules must be explicitly listed.
        'ocr',
        'ocr.base',
        'ocr.preprocess',
        'ocr.tesseract',
        'ocr.docuware',
        # xlrd is lazy-imported inside ocrmill_processor.load_xlsx_as_text_and_tables
        # for legacy .xls commercial invoices (added v1.6.0). Listed explicitly
        # because PyInstaller's static analysis sometimes misses suffix-dispatched
        # imports.
        'xlrd',
    ] + _ocr_hiddenimports + _isf_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# PYZ archive
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Executable
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DocHopper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(dochopper_dir, 'Resources', 'icon.ico'),
)

# Collect files
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DocHopper',
)
