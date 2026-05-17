# DocHopper Flowcharts & Documentation

This directory contains flowcharts and diagrams documenting the DocHopper application workflows and architecture.

## Flowcharts

| Document | Description |
|----------|-------------|
| [01 - Invoice Processing Workflow](01_invoice_processing_workflow.md) | Complete flow from file upload to export |
| [02 - Parts Master Data Flow](02_parts_master_data_flow.md) | How parts data is managed and used |
| [03 - PDF Processing Template System](03_ocrmill_template_processing.md) | Template matching and data extraction (includes v1.4 OCR fallback) |
| [04 - Section 232 / 301 / 122 Tariff Detection](04_section_232_301_tariff_detection.md) | Note 16 chapter 99 routing, Section 122 Reciprocal Tariff, cast iron exception |
| [05 - Application Architecture](05_application_architecture.md) | System components and database schema |
| [06 - User Workflow](06_user_workflow.md) | End-to-end user journey |

Section 122 PDF reference: [tariff-flow-charts-with-section-122.pdf](tariff-flow-charts-with-section-122.pdf) (NCBFAA flowchart, April 2026)

## Viewing Flowcharts

These flowcharts use [Mermaid](https://mermaid.js.org/) diagram syntax. To view them:

### GitHub
GitHub automatically renders Mermaid diagrams in markdown files.

### VS Code
Install the "Markdown Preview Mermaid Support" extension.

### Online
Copy the Mermaid code blocks to [Mermaid Live Editor](https://mermaid.live/).

## Quick Links

- [Main README](../../README.md)
- [License](../../LICENSE)
- [Releases](https://github.com/ProcessLogicLabs/DocHopper/releases)

## Version

Documentation updated for DocHopper v1.6.17 (May 2026)
