# Invoice Processor

A portable Python module for processing customs invoices with Section 232 tariff handling.

## Features

- **Material Ratio Expansion**: Split invoice rows by steel, aluminum, copper, wood, automotive, and non-232 content percentages
- **Weight Distribution**: Proportionally distribute net weight based on line item values
- **Quantity Calculations**: Compute CBP Qty1/Qty2 based on unit type (KG, NO, NO/KG)
- **Section 232 Lookups**: Determine material type and declaration codes from HTS codes
- **Styled Excel Export**: Color-coded rows by material type with Section 301 highlighting

## Installation

Copy the `invoice_processor` directory to your project, then install dependencies:

```bash
pip install pandas openpyxl
```

## Quick Start

```python
from invoice_processor import InvoiceProcessor, ExportStyle
import pandas as pd

# Create sample invoice data
invoice_data = pd.DataFrame({
    'part_number': ['ABC123', 'DEF456'],
    'value_usd': [1000.00, 2000.00],
    'hts_code': ['7208.10.0000', '7601.10.0000'],
    'quantity': [100, 200],
    'qty_unit': ['NO', 'KG']
})

# Initialize processor with tariff database
processor = InvoiceProcessor.from_database("entryops.db")

# Process invoice
result = processor.process(invoice_data, net_weight=500.0, mid="USABC12345")

print(f"Original rows: {result.original_row_count}")
print(f"Expanded rows: {result.expanded_row_count}")
print(f"Total value: ${result.total_value:,.2f}")

# Export to Excel
export_result = processor.export(result.data, "output.xlsx")
```

## API Reference

### InvoiceProcessor Class

The main entry point for invoice processing.

#### Constructor Methods

```python
# From SQLite database
processor = InvoiceProcessor.from_database("path/to/db.sqlite")

# From pandas DataFrame
tariff_df = pd.read_csv("tariff_232.csv")
processor = InvoiceProcessor.from_dataframe(tariff_df)

# From dictionary
tariffs = {
    "7208100000": {"material": "Steel", "declaration_required": "08"},
    "7601100000": {"material": "Aluminum", "declaration_required": "07"}
}
processor = InvoiceProcessor.from_dict(tariffs)
```

#### Processing

```python
result = processor.process(
    df,                      # Invoice DataFrame
    net_weight=1000.0,       # Total weight in KG
    mid="USABC12345",        # Manufacturer ID
    parts_df=parts_master    # Optional parts database
)

# Result contains:
result.data                 # Processed DataFrame
result.original_row_count   # Rows before expansion
result.expanded_row_count   # Rows after expansion
result.total_value          # Sum of value_usd
result.total_weight         # The net_weight passed in
```

#### Exporting

```python
# Single file export
export_result = processor.export(
    result.data,
    "output.xlsx",
    columns=['Product No', 'HTSCode', 'ValueUSD', 'CalcWtNet']
)

# Split by invoice number
export_result = processor.export_by_invoice(
    result.data,
    "output_directory/",
    invoice_column='invoice_number'
)
```

### ExportStyle Configuration

Customize Excel output styling:

```python
from invoice_processor import ExportStyle

style = ExportStyle(
    font_name='Arial',
    font_size=11,
    default_font_color='#000000',
    steel_color='#4a4a4a',
    aluminum_color='#6495ED',
    copper_color='#B87333',
    wood_color='#8B4513',
    auto_color='#2F4F4F',
    non232_color='#FF0000',
    sec301_fill_color='#FFCC99',
    landscape=True,
    fit_to_width=True,
    auto_size_columns=True
)

processor.export_style = style
# or
processor.export(df, "output.xlsx", style=style)
```

### Standalone Functions

For lower-level access:

```python
from invoice_processor import (
    process_invoice_data,
    export_to_excel,
    merge_with_parts_data,
    TariffLookup,
    get_232_info
)

# Direct tariff lookup
tariff = TariffLookup.from_database("db.sqlite")
material, dec_code, smelt_flag = tariff.get_info("7208.10.0000")

# Process without class wrapper
result = process_invoice_data(df, net_weight=1000.0, tariff_lookup=tariff)

# Export without class wrapper
export_to_excel(df, "output.xlsx")
```

## Input DataFrame Columns

| Column | Required | Description |
|--------|----------|-------------|
| part_number | Yes | Part/product number |
| value_usd | Yes | Line item value in USD |
| hts_code | No | HTS tariff code |
| quantity | No | Piece count |
| qty_unit | No | Unit type: 'KG', 'NO', or 'NO/KG' |
| steel_pct | No | Steel content % (0-100) |
| aluminum_pct | No | Aluminum content % (0-100) |
| copper_pct | No | Copper content % (0-100) |
| wood_pct | No | Wood content % (0-100) |
| auto_pct | No | Automotive content % (0-100) |
| non_steel_pct | No | Non-232 content % (0-100) |
| country_of_melt | No | Country code for melt origin |
| country_of_cast | No | Country code for cast origin |
| country_of_smelt | No | Country code for smelt origin |
| invoice_number | No | Invoice number (for split export) |

## Output DataFrame Columns

After processing, these columns are added/calculated:

| Column | Description |
|--------|-------------|
| CalcWtNet | Calculated net weight (proportional) |
| Qty1 | CBP Quantity 1 |
| Qty2 | CBP Quantity 2 |
| HTSCode | Normalized HTS code |
| MID | Manufacturer ID |
| DecTypeCd | Declaration type code |
| CountryofMelt | Country of melt origin |
| CountryOfCast | Country of cast origin |
| PrimCountryOfSmelt | Primary country of smelt |
| DeclarationFlag | Smelting declaration flag |
| _232_flag | Section 232 material flag |
| _content_type | Material content type |

## Database Schema

The tariff lookup expects a table with these columns:

```sql
CREATE TABLE tariff_232 (
    hts_code TEXT PRIMARY KEY,
    material TEXT,
    declaration_required TEXT
);
```

## Dependencies

- pandas >= 1.0
- openpyxl >= 3.0

## License

Part of the EntryOps project.
