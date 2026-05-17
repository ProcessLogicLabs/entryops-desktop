# DocHopper v0.1.0 — Initial Public Release

**Document-driven workflow automation.** Drop a PDF or Excel file in, get structured data out, drive the next system. Originally extracted from a production customs-brokerage app and sanitized for public release under the MIT License.

## What you get in v0.1.0

- **PyQt5 desktop app** with five tabs: PDF Processing (drag-and-drop OCRMill), Invoice Processing, Parts View, Parts Detail Lookup, ISF Filing
- **Plugin-pattern template engine** with auto-discovery — drop a `.py` into `Dochopper/templates/` and it loads on startup
- **Ten generic templates** ready to use:
  - `standard_invoice`, `tabular_invoice`, `simple_invoice`, `proforma_invoice`
  - `smart_universal` — data-shape fallback that recognizes part-code / qty / price by pattern
  - `bill_of_lading` — ocean BOL gross-weight extraction
  - `lacey_act_form` — USDA PPQ Form 505
  - `isf_10_plus_2` — CBP ISF Information Sheet (17 numbered fields + 7 address blocks)
  - `newell_aishida` — real-world supplier example (Aishida Co. Ltd → Newell Brands)
  - `sample_template` — starter to copy
- **OCR fallback** via Tesseract for image-only PDFs (degrades to no-op if Tesseract isn't installed)
- **Parts master + alias table** — local SQLite store for canonical part numbers, HTS codes, country of origin, Section 232 metal content
- **Profile-based XLSX export** with operator-configurable column mappings
- **Playwright-based ISF web-UI driver** for filing 10+2s into e2open's customs-broker portal (operator-in-the-loop — never auto-submits)
- **First-run setup wizard** — creates an initial admin account on first launch (no auth_users.json bootstrap needed)
- **Importer-profile overlay** — point `billing_settings.isf_importers_path` at an external JSON file to keep proprietary importer data outside the source tree

## Install

Windows installer attached below (built via the CI workflow). Or from source:

```bash
git clone https://github.com/ProcessLogicLabs/dochopper.git
cd dochopper
pip install -e .
python -m playwright install chromium    # only needed for ISF web-UI fill
python Dochopper/dochopper.py
```

## Known limitations

- No automated tests yet — coverage is on the roadmap
- The auto-update mechanism polls `ProcessLogicLabs/dochopper` releases (the repo this lives in)
- Tesseract OCR not bundled — install separately if you need scanned-PDF support
- This is a single-file 33K-line PyQt5 app; splitting it into smaller modules is on the roadmap

## License

MIT. See [LICENSE](LICENSE).
