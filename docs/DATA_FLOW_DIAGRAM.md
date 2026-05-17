# DocHopper Data Flow Diagram

**Version:** 1.3.5 | **Date:** 2026-04-16

---

## Processing Pipeline

```
 INPUT                      PROCESSING                     OUTPUT
 -----                      ----------                     ------

 +------------------+
 | PDF Invoices     |
 | (Commercial      |---+
 |  Invoice,        |   |
 |  Packing List,   |   |
 |  Bill of Lading) |   |
 +------------------+   |
                         |    +------------------------+
                         +--->| Template Engine        |
                              | (pdfplumber extraction)|
                              | - Text parsing         |
                              | - Table extraction     |
                              | - Invoice detection    |
                              +----------+-------------+
                                         |
                                    Extracted Items:
                                    - Part numbers
                                    - Quantities
                                    - Prices
                                    - Country of origin
                                         |
                              +----------v-------------+      +------------------+
                              | Enrichment Pipeline    |<---->| SQLite Database  |
                              | - Parts master lookup  |      | (dochopper.db)  |
                              | - HTS code validation  |      |                  |
                              | - MID resolution       |      | - parts_master   |
                              | - Country normalization|      | - mid_table      |
                              | - Section 232 calc     |      | - tariff_232     |
                              | - Weight distribution  |      | - hts_units      |
                              | - Quantity calculation  |      | - country_codes  |
                              +----------+-------------+      | - billing_records|
                                                              | - template_stats |
                                                              +------------------+
                                         |
                                    Enriched Data:
                                    - HTS codes
                                    - Duty rates
                                    - Metal percentages
                                    - Country declarations
                                    - Calculated weights
                                         |
                              +----------v-------------+
                              | Export Engine          |
                              | - Profile-based output |
                              | - Column mapping       |
                              | - Split by invoice     |
                              +----------+-------------+
                                         |
                         +---------------+---------------+
                         |                               |
                +--------v---------+           +---------v--------+
                | XLSX Export      |           | Preview Table    |
                | (to network     |           | (in-app display) |
                |  share or local)|           +------------------+
                +------------------+
```

---

## Data Classification by Stage

| Stage | Data Elements | Classification |
|---|---|---|
| Input | Supplier invoices, packing lists | Business Confidential |
| Extraction | Part numbers, quantities, prices | Business Confidential |
| Enrichment | HTS codes, duty calculations, MIDs | Business Confidential |
| Output | Customs entry data (XLSX) | Business Confidential |
| Database | Parts master, supplier info, billing records, processing stats | Business Confidential |
| Auth | User roles, assigned clients, domain auth list | Internal |
| Logs | User actions, export history | Internal |
| Config | Display preferences, database path (config.ini) | Internal |

---

## External Data Flows

```
                    +-------------------+
                    |   DocHopper      |
                    |   Workstation     |
                    +---+-------+---+---+
                        |       |   |
           HTTPS 443    |       |   |    SMB 445
          (outbound)    |       |   |   (internal)
                        |       |   |
               +--------v--+   |   +--v--------------+
               | GitHub API |   |   | File Server     |
               |            |   |   | (Windows Share) |
               | - Version  |   |   |                 |
               |   check    |   |   | - Shared DB     |
               | - Auth     |   |   | - Templates     |
               |   users    |   |   | - Export files  |
               +------------+   |   | - auth_users.json|
               +------------+   |   +-----------------+
                                |
                     +----------v----------+
                     | Gumroad API         |
                     | (license check,     |
                     |  activation only)   |
                     +---------------------+
```

### Data Transmitted Externally

| Destination | Direction | Data | NOT Transmitted |
|---|---|---|---|
| GitHub API | Outbound | App version, auth token | Customer data, part numbers, invoices |
| Gumroad API | Outbound | License key | Customer data, part numbers, invoices |
| File Server | Bidirectional | Database, templates, exports | Only via standard Windows SMB |
