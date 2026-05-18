# DocHopper

Import process documentation automation. Extracts line-item data from shipper / vendor PDFs (commercial invoices, packing lists, bills of lading), validates it against a parts master and HTS reference database, and exports a structured XLSX worksheet for a downstream customs entry process.

Built for US import customs brokers and in-house import logistics teams. Extracted from a production customs-brokerage app.

## Workflow

1. Drop one or more PDFs (or Excel / CSV invoices, or a ZIP) on the PDF Processing tab.
2. The template engine picks a parser by document layout and extracts part numbers, quantities, unit prices, country of origin, PO numbers, and weights.
3. Each part is looked up in the parts_master. HTS code, CBP quantity unit, MID, country of origin, Section 232 metal percentages, and Section 301 exclusion code come from the master record. Parts missing from the database — or in the database but missing required fields — surface in a pre-export dialog.
4. Enrichment: split line values by material percentage (steel / aluminum / copper / wood / auto), allocate weights proportionally, normalize country fields to ISO 2-letter codes, compute CBP Qty1 / Qty2 from `hts_units`.
5. Export to XLSX via an operator-configured column-mapping profile. Output is a worksheet ready to hand off to an entry tool.

The operator reviews and edits the preview table before export.

## Components

- **Template engine.** Plugin pattern — drop a `.py` into `Dochopper/templates/`, inherit from `BaseTemplate`, return line items. Auto-discovered at startup. Eight generic templates ship today:

  | Template | Parses |
  |---|---|
  | `standard_invoice` | Commercial invoice (PO, line items, qty, price) |
  | `tabular_invoice` | Invoices with table borders / strict columns |
  | `simple_invoice` | Minimal-field documents |
  | `proforma_invoice` | Pre-shipment proformas |
  | `smart_universal` | Data-shape fallback (part-code / qty / price) |
  | `bill_of_lading` | Ocean BOL gross weight |
  | `lacey_act_form` | USDA PPQ Form 505 |
  | `sample_template` | Starter — copy and edit |

- **parts_master** — local SQLite. Canonical part number, HTS code, CBP qty unit, country of origin, MID, Section 232 metal percentages, country of melt / cast / smelt, Section 301 exclusion code.
- **HTS reference DB** — bundled `hts.db` for Qty1 / Qty2 unit lookups.
- **MID list** — managed in Settings.
- **Export profiles** — column-mapping presets per downstream system.
- **Folder profiles** — saved input / output folder pairs per client.
- **OCR fallback** — Tesseract for image-only PDFs. No-op if Tesseract is not installed.

## Quickstart

```bash
git clone https://github.com/ProcessLogicLabs/dochopper.git
cd dochopper
pip install -e .
python Dochopper/dochopper.py
```

First launch runs a setup wizard for the initial admin account.

1. Settings → set default input / output folders.
2. Parts Import tab → bulk-load parts_master from CSV.
3. PDF Processing tab → drop a vendor PDF, pick a template (or let it auto-match), export.

## Roadmap

- Section 232 / 301 / 122 chapter 99 routing per current CSMS guidance
- Shared mailbox auto-ingest (Outlook)
- Template registry for sharing supplier formats
- DMS integrations (DocuWare, etc.)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Most useful contributions:

- New templates for specific supplier invoice formats
- parts_master / HTS / Section 232 setup walkthroughs
- Test coverage for the enrichment pipeline

## License

MIT. See [LICENSE](LICENSE).
