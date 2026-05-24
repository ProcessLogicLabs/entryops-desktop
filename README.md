# EntryOps (desktop)

**Operations platform for customs entry filing.** Drop a PDF or Excel
file in, get a CBP-ready entry summary out. Built for licensed customs
brokers, in-house trade-compliance teams, and anyone whose day starts
with re-keying line items off a supplier's commercial invoice.

EntryOps ships as two products under one wordmark:

| Edition | License | Where |
|---|---|---|
| **EntryOps (cloud)** | Proprietary multi-tenant SaaS | <https://entryops.us> |
| **EntryOps (desktop)** | MIT — this repo | <https://github.com/ProcessLogicLabs/entryops-desktop> |

The desktop edition is the open-source ancestor of the cloud product
and remains under active development. Both share the same extraction
core, template catalog, parts-master enrichment, and CBP-compliant
Section 232 / 301 handling.

## Why EntryOps

- **Operator-in-the-loop by design.** The app extracts, the human
  verifies, the app drives the downstream system. No silent automation
  that submits the wrong field because a PDF layout changed.
- **Plugin-pattern templates.** Drop a `.py` file into `templates/`
  and it's auto-discovered. Inherit from `BaseTemplate`, override a
  few regex patterns, return line items. No registration step.
- **AI Template Assistant.** Optional chat-side panel that drafts
  new supplier templates against a sample invoice. Provider SDKs
  install on demand — bring your own Anthropic / OpenAI / Ollama key.
- **OCR fallback.** Image-only PDFs route through Tesseract when
  text extraction fails. Cache sidecar keeps reprocessing fast.
- **CBP-compliant Section 232 + 301.** Built-in handlers for the
  cast-iron / aluminum / steel content rules under CSMS #65236645,
  with separate cell-pill highlighting for 301 exception part numbers
  so the operator sees both signals at once.

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
| `sample_template` | Starter — copy and edit to add your own |

Plus:
- **Parts master & aliases** — local SQLite store for canonical part
  numbers, HTS codes, country of origin, and Section 232 metal
  content.
- **Excel/CSV export profiles** — operator-configurable column
  mappings so the same extraction can feed multiple downstream
  formats.
- **Section 232 metal-content workflow** — value-based duty
  calculations per CSMS #65236645 with both aluminum and steel
  smelter / cast / melt country tracking.

## Quickstart

```bash
git clone https://github.com/ProcessLogicLabs/entryops-desktop.git
cd entryops-desktop
pip install -e .
entryops          # or `python entryops.py`
```

First launch shows a one-time setup wizard to create an admin
account. After that, drop a PDF onto the **Invoice Processing** tab
and pick a template.

## Roadmap

- Template marketplace / registry
- Outlook inbox monitor (auto-ingest from a shared mailbox)
- DocuWare REST integration
- Hand-off to the cloud edition for shared workflows

## Contributing

PRs welcome. The highest-impact areas:

- **New supplier templates** — drop a `.py` file in `templates/` and
  open a PR. The auto-discovery loader picks it up.
- **Documentation** — the parts-master / alias / enrichment pipeline
  could use more worked examples.
- **Downstream-system drivers** — anything that takes the extracted
  rows and posts them somewhere useful.

## License

MIT. See [LICENSE](LICENSE).
