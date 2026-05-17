# DocHopper Dependency List

**Application:** DocHopper v1.3.5
**Python Version:** 3.11
**Generated:** 2026-04-16

---

## Core Dependencies

| Package | Version | Purpose | License | Security Notes |
|---|---|---|---|---|
| PyQt5 | 5.15.11 | GUI framework | GPL v3 | Mature, widely audited |
| pandas | 2.3.3 | Data processing & analysis | BSD 3-Clause | Standard data library |
| openpyxl | 3.1.5 | Excel (.xlsx) read/write | MIT | No network activity |
| pdfplumber | 0.11.8 | PDF text & table extraction | MIT | Read-only PDF processing |
| pdfminer.six | 20251107 | PDF parsing (pdfplumber dep) | MIT | Read-only |
| PyMuPDF | 1.27.1 | PDF rendering (fallback) | AGPL v3 | Read-only |
| Pillow | 12.0.0 | Image processing | HPND | No network activity |
| requests | 2.32.5 | HTTP client | Apache 2.0 | Used for update check only |
| pywin32 | 311 | Windows COM/API integration | PSF | Windows platform integration |

## Build Dependencies (not shipped at runtime)

| Package | Version | Purpose |
|---|---|---|
| pyinstaller | 6.17.0 | Executable bundling |
| pyinstaller-hooks-contrib | 2025.10 | PyInstaller hooks |

## Optional Dependencies (AI features)

| Package | Version | Purpose | When Active |
|---|---|---|---|
| anthropic | 0.75.0 | Claude API client | Only if AI template generation enabled |
| openai | 2.24.0 | OpenAI API client | Only if AI template generation enabled |

## Transitive Dependencies

| Package | Version | Required By |
|---|---|---|
| certifi | 2025.11.12 | requests (TLS certificates) |
| charset-normalizer | 3.4.4 | requests |
| cryptography | 46.0.3 | anthropic/openai (HTTPS) |
| idna | 3.11 | requests |
| numpy | 2.3.5 | pandas |
| urllib3 | 2.6.2 | requests |
| python-dateutil | 2.9.0 | pandas |
| pytz | 2025.2 | pandas |
| httpx | 0.28.1 | anthropic/openai |
| pydantic | 2.12.5 | anthropic/openai |
| typing_extensions | 4.15.0 | pydantic |

---

## Supply Chain Security

- All packages sourced from **PyPI** (Python Package Index)
- Versions pinned at build time
- Application is bundled into a standalone executable via **PyInstaller** — no runtime package downloads
- No post-install package fetching (except optional AI library install, admin-initiated only)
