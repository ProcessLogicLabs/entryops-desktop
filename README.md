# DocHopper

**Document-driven workflow automation.** Drop a PDF or Excel file in, get
structured data out, drive the next system. Built for the long tail of
"someone in an office is re-keying data from a PDF into a web form" — customs
brokerage, AP/AR processing, insurance claims intake, government form filing,
any workflow with a paper-to-form bottleneck.

Originally extracted from a production customs-brokerage app, DocHopper ships
with template scaffolding and a handful of generic extractors. Add a template
for your supplier or document format, point at your downstream system, and
the operator review pane handles the rest.

## Why DocHopper

- **Operator-in-the-loop by design.** The app extracts, the human verifies,
  the app drives the downstream system. No silent automation that submits the
  wrong field because a PDF layout changed.
- **Plugin-pattern templates.** Drop a `.py` file into `templates/` and it's
  auto-discovered. Inherit from `BaseTemplate`, override a few regex patterns,
  return line items. No registration step.
- **Web-UI form-fill via Playwright.** For target systems with no API
  (government portals, legacy SaaS), DocHopper opens a real Chromium window,
  pre-fills every field per a JSON selector map, and pauses for the operator
  to verify-and-submit. The runner never clicks Submit itself.
- **OCR fallback.** Image-only PDFs route through Tesseract when text
  extraction fails.

## What it does today

The included generic templates cover:

| Template | What it parses |
|---|---|
| `standard_invoice` | Typical commercial invoice (PO, line items, qty, price) |
| `tabular_invoice` | Invoices with visible table borders / strict columns |
| `simple_invoice` | Minimal-field documents |
| `proforma_invoice` | Pre-shipment proformas |
| `smart_universal` | Data-shape fallback that recognizes part-code / qty / price |
| `bill_of_lading` | Ocean BOL extraction (gross weight) |
| `lacey_act_form` | USDA PPQ Form 505 (wood declarations) |
| `isf_10_plus_2` | CBP ISF Information Sheet (17 numbered fields + 7 address blocks) |
| `newell_aishida` | Real-world supplier example: Aishida → Newell Brands |
| `sample_template` | Starter — copy and edit to add your own |

Plus:
- **Parts master & aliases** — local SQLite store for canonical part numbers,
  HTS codes, country of origin, and Section 232 metal content.
- **Excel/CSV export profiles** — operator-configurable column mappings, so
  the same extraction can feed multiple downstream formats.
- **ISF web-UI driver** (Playwright-based) for filing 10+2s into a customs
  broker's existing portal.

## Quickstart

```bash
git clone https://github.com/ProcessLogicLabs/dochopper.git
cd dochopper
pip install -e .
python -m playwright install chromium    # only needed for ISF web-UI fill
python Dochopper/dochopper.py          # or `dochopper` after `pip install`
```

First launch shows a one-time setup wizard to create an admin account. After
that, drop a PDF onto the **PDF Processing** tab and pick a template.

## Roadmap

- Template marketplace / registry
- Outlook inbox monitor (auto-ingest from a shared mailbox)
- DocuWare REST integration
- More target-system drivers beyond the e2open ISF UI

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). The big areas where help
is most useful:

- **New templates** for specific supplier invoice formats
- **New target-system drivers** (Playwright field-maps for other web UIs)
- **Documentation** — how to use the parts_master / alias / enrichment pipeline

## License

MIT. See [LICENSE](LICENSE).
