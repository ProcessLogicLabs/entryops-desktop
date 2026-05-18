# DocHopper v0.1.7

**Document-driven workflow automation.** Drop a PDF or Excel file in, get structured data out, drive the next system. Originally extracted from a production customs-brokerage app and sanitized for public release under the MIT License.

## What's in v0.1.7

- **PyQt5 desktop app** with tabs for PDF Processing (drag-and-drop OCRMill), Invoice Processing, Parts View, and Parts Detail Lookup.
- **Plugin-pattern template engine** with auto-discovery — drop a `.py` into `Dochopper/templates/` and it loads on startup.
- **Eight generic templates** ready to use:
  - `standard_invoice`, `tabular_invoice`, `simple_invoice`, `proforma_invoice`
  - `smart_universal` — data-shape fallback that recognizes part-code / qty / price by pattern
  - `bill_of_lading` — ocean BOL gross-weight extraction
  - `lacey_act_form` — USDA PPQ Form 505
  - `sample_template` — starter to copy
- **OCR fallback** via Tesseract for image-only PDFs (degrades to no-op if Tesseract isn't installed). The bundled installer pulls Tesseract 5.5.0 from the upstream `tesseract-ocr/tesseract` GitHub release.
- **Parts master + alias table** — local SQLite store for canonical part numbers, HTS codes, country of origin, Section 232 metal content.
- **Profile-based XLSX export** with operator-configurable column mappings.
- **First-run setup wizard** — creates an initial admin account on first launch (no `auth_users.json` bootstrap needed).
- **Importer-profile overlay** — point `billing_settings.isf_importers_path` at an external JSON file to keep proprietary importer data outside the source tree.

## What changed since v0.1.0

See [CHANGELOG.md](CHANGELOG.md) for the full 0.1.x history. Highlights:

- ISF Filing subsystem removed from the OSS distribution (was dormant since the internal v1.6.1).
- `newell_aishida` real-world example template removed; use `sample_template.py` or the included generic templates as starting points.
- Splash screen rebrand and tagline now driven by `_branding.py`.
- Several PyInstaller / Inno Setup fixes so the Windows installer build runs cleanly out of the box.

## Install

Windows installer attached below (built via the CI workflow). Or from source:

```bash
git clone https://github.com/ProcessLogicLabs/dochopper.git
cd dochopper
pip install -e .
python Dochopper/dochopper.py
```

## Known limitations

- No automated tests yet — coverage is on the roadmap.
- The auto-update mechanism polls `ProcessLogicLabs/dochopper` releases.
- Tesseract OCR not bundled — install separately if you need scanned-PDF support (the Inno Setup installer downloads it during install on Windows).
- DocHopper is a single-file 33K-line PyQt5 app; splitting it into smaller modules is on the roadmap.
- The `docs/` tree is currently a snapshot from the internal 1.x line. Many features it describes (Section 122 routing, the MID Required dialog, the cast-iron exception, OCR fallback metadata) are not yet in the 0.1.x OSS build. See the notice at the top of each `docs/` file.

## License

MIT. See [LICENSE](LICENSE).
