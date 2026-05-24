"""
Tabular Invoice Template

Template for invoices with clearly defined table structures.
Uses table detection to extract line items from structured formats.
"""

import re
from typing import List, Dict
from .base_template import BaseTemplate


class TabularInvoiceTemplate(BaseTemplate):
    """
    Template for invoices with clear table structures.

    Best for:
    - Invoices with visible table borders/gridlines
    - Consistent column alignment
    - Clear header rows
    """

    name = "Tabular Invoice"
    description = "Invoice with structured table layout and clear columns"
    client = "Universal"
    version = "1.0.0"
    enabled = True

    extra_columns = ['unit_price', 'description', 'uom']

    # Expected table headers (case-insensitive matching)
    EXPECTED_HEADERS = [
        'item', 'part', 'code', 'sku', 'product',
        'qty', 'quantity',
        'price', 'amount', 'total', 'value'
    ]

    def can_process(self, text: str) -> bool:
        """Check if this invoice has a tabular format."""
        text_lower = text.lower()

        # Must have invoice indicator
        has_invoice = 'invoice' in text_lower

        # Look for table header indicators
        header_count = sum(1 for h in self.EXPECTED_HEADERS if h in text_lower)

        # Must have price values
        has_prices = bool(re.search(r'\d+\.?\d*', text))

        return has_invoice and header_count >= 3 and has_prices

    def get_confidence_score(self, text: str) -> float:
        """Return confidence score based on table structure detection."""
        if not self.can_process(text):
            return 0.0

        score = 0.35
        text_lower = text.lower()

        # Check for table structure indicators
        header_count = sum(1 for h in self.EXPECTED_HEADERS if h in text_lower)
        score += min(header_count * 0.05, 0.25)

        # Check for consistent formatting (multiple lines with similar patterns)
        lines = text.split('\n')
        numeric_lines = sum(1 for line in lines if re.search(r'\d+\.?\d*\s+\d+\.?\d*', line))
        if numeric_lines >= 3:
            score += 0.1

        return min(score, 0.65)

    def extract_invoice_number(self, text: str) -> str:
        """Extract invoice number."""
        patterns = [
            r'Invoice\s*(?:No\.?|#|Number|ID)[:\s]*([A-Z0-9][\w\-/]+)',
            r'Document\s*(?:No\.?|#)[:\s]*([A-Z0-9][\w\-/]+)',
            r'Bill\s*(?:No\.?|#)[:\s]*([A-Z0-9][\w\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        """Extract PO/project number."""
        patterns = [
            r'P\.?O\.?\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Order\s*(?:No\.?|#|Number)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Ref(?:erence)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Job\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def extract_from_tables(self, tables: List[List[List[str]]], text: str) -> List[Dict]:
        """Extract items from detected tables.

        Handles continuation tables (no header row) by reusing the column
        mapping from the previous table if the column count matches.
        """
        items = []
        last_col_map = None
        last_col_count = 0

        for table in tables:
            if not table or len(table) < 1:
                continue

            # Find header row
            header_row = self.detect_table_header_row(table, self.EXPECTED_HEADERS)

            if header_row >= 0:
                # Table has its own header — build new column mapping
                header = table[header_row]
                col_map = self._build_column_mapping(header)
                if not col_map.get('part_number') and not col_map.get('quantity'):
                    continue
                last_col_map = col_map
                last_col_count = len(header)
                data_start = header_row + 1
            elif last_col_map and len(table[0]) == last_col_count:
                # Continuation table (no header) — reuse previous mapping
                col_map = last_col_map
                data_start = 0
            else:
                continue

            # Extract rows
            for row_idx in range(data_start, len(table)):
                row = table[row_idx]
                if not row or all(not cell for cell in row):
                    continue

                item = self._extract_row_data(row, col_map)
                if item and item.get('part_number'):
                    items.append(item)

        return items

    def _build_column_mapping(self, header: List[str]) -> Dict[str, int]:
        """Build mapping from field names to column indices."""
        mapping = {}
        header_lower = [str(h or '').lower() for h in header]

        # Part number column
        for i, h in enumerate(header_lower):
            if any(k in h for k in ['part', 'item', 'code', 'sku', 'product', 'article']):
                mapping['part_number'] = i
                break

        # Description column
        for i, h in enumerate(header_lower):
            if any(k in h for k in ['desc', 'name', 'specification']):
                mapping['description'] = i
                break

        # Quantity column (handles Q'ty, Qty, Quantity, etc.)
        for i, h in enumerate(header_lower):
            if any(k in h for k in ['qty', 'quantity', 'pcs', 'units', "q'ty"]):
                if 'carton' not in h and 'ctn' not in h:
                    mapping['quantity'] = i
                    break

        # Unit of measure
        for i, h in enumerate(header_lower):
            if any(k in h for k in ['uom', 'unit', 'measure']):
                mapping['uom'] = i
                break

        # Unit price column
        for i, h in enumerate(header_lower):
            if any(k in h for k in ['unit price', 'rate', 'price/unit', 'unit cost']):
                mapping['unit_price'] = i
                break

        # Total price column (check from right side, skip non-monetary totals)
        for i in range(len(header_lower) - 1, -1, -1):
            h = header_lower[i]
            if any(k in h for k in ['total price', 'total amount', 'total value', 'ext', 'amount']):
                mapping['total_price'] = i
                break
        if 'total_price' not in mapping:
            for i in range(len(header_lower) - 1, -1, -1):
                h = header_lower[i]
                if 'total' in h and 'wt' not in h and 'weight' not in h:
                    mapping['total_price'] = i
                    break

        # PO number column
        for i, h in enumerate(header_lower):
            if any(k in h for k in ['p.o.', 'po#', 'po no', 'purchase order']):
                mapping['po_number'] = i
                break

        return mapping

    def _extract_row_data(self, row: List[str], col_map: Dict[str, int]) -> Dict:
        """Extract data from a single row using column mapping."""
        item = {
            'part_number': '',
            'description': '',
            'quantity': '',
            'unit_price': '',
            'total_price': '',
            'uom': '',
            'po_number': '',
        }

        for field, col_idx in col_map.items():
            if col_idx < len(row):
                value = str(row[col_idx] or '').strip()
                if field in ['quantity', 'unit_price', 'total_price']:
                    # Clean numeric values
                    value = re.sub(r'[^\d.,]', '', value)
                    value = value.replace(',', '')
                item[field] = value

        return item

    def extract_line_items(self, text: str) -> List[Dict]:
        """Fallback text-based extraction for tabular invoices."""
        items = []
        seen = set()
        lines = text.split('\n')

        # Look for consistent patterns with multiple numeric columns
        pattern = re.compile(
            r'([A-Z0-9][\w\-/\.]{2,})\s+'       # Part/item code
            r'(.+?)\s+'                          # Description
            r'(\d+(?:\.\d+)?)\s+'                # Quantity
            r'\$?([\d,]+\.?\d*)\s*'              # Price 1
            r'\$?([\d,]+\.?\d*)?',               # Price 2 (optional total)
            re.IGNORECASE
        )

        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = pattern.search(line)
            if match:
                part_num = match.group(1)
                desc = match.group(2).strip()
                qty = match.group(3)
                price1 = match.group(4).replace(',', '')
                price2 = match.group(5).replace(',', '') if match.group(5) else ''

                # Determine which is unit price vs total
                if price2:
                    unit_price = price1
                    total = price2
                else:
                    unit_price = ''
                    total = price1

                key = f"{part_num}_{qty}_{total}"
                if key not in seen:
                    seen.add(key)
                    items.append({
                        'part_number': part_num,
                        'description': desc,
                        'quantity': qty,
                        'unit_price': unit_price,
                        'total_price': total,
                        'uom': '',
                    })

        return items

    def is_packing_list(self, text: str) -> bool:
        """Check if this is a packing list only."""
        text_lower = text.lower()
        return 'packing list' in text_lower and 'invoice' not in text_lower
