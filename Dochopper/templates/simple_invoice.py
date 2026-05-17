"""
Simple Invoice Template

Template for simple, minimal invoices with basic line item information.
Handles invoices that may have fewer fields or less structured formats.
"""

import re
from typing import List, Dict
from .base_template import BaseTemplate


class SimpleInvoiceTemplate(BaseTemplate):
    """
    Template for simple invoice formats.

    Best for:
    - Basic invoices with minimal fields
    - Less structured documents
    - Invoices without complex tables
    """

    name = "Simple Invoice"
    description = "Simple invoice format with basic part, quantity, and price fields"
    client = "Universal"
    version = "1.0.0"
    enabled = True

    extra_columns = ['description']

    def can_process(self, text: str) -> bool:
        """Check if this is a simple invoice format."""
        text_lower = text.lower()

        # Must have invoice indicator
        has_invoice = 'invoice' in text_lower or 'bill' in text_lower

        # Must have some numeric values (prices/quantities)
        has_numbers = bool(re.search(r'\d+\.?\d*', text))

        # Simple check - not too many structured elements
        structured_elements = sum([
            'hs code' in text_lower,
            'country of origin' in text_lower,
            'net weight' in text_lower,
            'gross weight' in text_lower,
        ])

        return has_invoice and has_numbers and structured_elements < 2

    def get_confidence_score(self, text: str) -> float:
        """Return confidence score - lower than specialized templates."""
        if not self.can_process(text):
            return 0.0

        score = 0.3  # Base score
        text_lower = text.lower()

        if 'invoice' in text_lower:
            score += 0.1

        # Count line items to boost confidence
        lines = text.split('\n')
        item_lines = sum(1 for line in lines if re.search(r'\d+\.?\d*\s+\$?\d', line))
        if item_lines >= 2:
            score += 0.1
        if item_lines >= 5:
            score += 0.1

        return min(score, 0.55)

    def extract_invoice_number(self, text: str) -> str:
        """Extract invoice number from various formats."""
        patterns = [
            r'Invoice\s*(?:No\.?|#|Number)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Bill\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Ref[:\s]*([A-Z0-9][\w\-/]+)',
            r'(?:No|#)[:\s]*([A-Z0-9][\w\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result = match.group(1).strip()
                # Filter out common false positives
                if result.lower() not in ['of', 'the', 'and', 'or']:
                    return result

        return "UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        """Extract PO/order number."""
        patterns = [
            r'P\.?O\.?\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Order[:\s]*([A-Z0-9][\w\-/]+)',
            r'Ref(?:erence)?[:\s]*([A-Z0-9][\w\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def extract_line_items(self, text: str) -> List[Dict]:
        """Extract line items using flexible patterns."""
        items = []
        seen = set()
        lines = text.split('\n')

        # Multiple patterns to try, from most to least specific

        # Pattern 1: Part/Item, Description, Qty, Price
        pattern1 = re.compile(
            r'([A-Z0-9][\w\-/\.]+)\s+'     # Part number
            r'(.{5,50}?)\s+'                # Description (5-50 chars)
            r'(\d+(?:\.\d+)?)\s+'           # Quantity
            r'\$?([\d,]+\.?\d*)',           # Price
            re.IGNORECASE
        )

        # Pattern 2: Part/Item, Qty, Price (no description)
        pattern2 = re.compile(
            r'([A-Z0-9][\w\-/\.]{2,})\s+'  # Part number (at least 3 chars)
            r'(\d+(?:\.\d+)?)\s+'           # Quantity
            r'\$?([\d,]+\.?\d*)',           # Price
            re.IGNORECASE
        )

        # Pattern 3: Just look for numeric patterns (Qty x Price or similar)
        pattern3 = re.compile(
            r'(\d+)\s*(?:x|@|pcs?|ea|units?)?\s*'  # Quantity
            r'\$?([\d,]+\.?\d{2})',                 # Price (with cents)
            re.IGNORECASE
        )

        for line in lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue

            # Skip header/total lines
            if re.search(r'^(item|part|qty|quantity|price|total|subtotal|tax|description|#)\s*$',
                        line, re.IGNORECASE):
                continue
            if re.search(r'^(total|subtotal|grand total|tax|shipping)', line, re.IGNORECASE):
                continue

            # Try pattern 1 (most detailed)
            match = pattern1.search(line)
            if match:
                part_num = match.group(1)
                desc = match.group(2).strip()
                qty = match.group(3)
                price = match.group(4).replace(',', '')

                key = f"{part_num}_{qty}_{price}"
                if key not in seen and self._is_valid_price(price):
                    seen.add(key)
                    items.append({
                        'part_number': part_num,
                        'description': desc,
                        'quantity': qty,
                        'total_price': price,
                    })
                continue

            # Try pattern 2 (no description)
            match = pattern2.search(line)
            if match:
                part_num = match.group(1)
                qty = match.group(2)
                price = match.group(3).replace(',', '')

                key = f"{part_num}_{qty}_{price}"
                if key not in seen and self._is_valid_price(price):
                    seen.add(key)
                    items.append({
                        'part_number': part_num,
                        'description': '',
                        'quantity': qty,
                        'total_price': price,
                    })

        # If no items found with part numbers, try generic extraction
        if not items:
            items = self._extract_generic_items(lines)

        return items

    def _extract_generic_items(self, lines: List[str]) -> List[Dict]:
        """Fallback extraction for very simple formats."""
        items = []
        item_num = 1

        for line in lines:
            line = line.strip()

            # Look for lines with quantity and price
            match = re.search(
                r'(\d+)\s*(?:x|@|pcs?|ea|units?)?\s*\$?([\d,]+\.\d{2})',
                line, re.IGNORECASE
            )
            if match:
                qty = match.group(1)
                price = match.group(2).replace(',', '')

                if self._is_valid_price(price):
                    items.append({
                        'part_number': f"ITEM-{item_num:03d}",
                        'description': line[:50].strip(),
                        'quantity': qty,
                        'total_price': price,
                    })
                    item_num += 1

        return items

    def _is_valid_price(self, price: str) -> bool:
        """Check if a price value is reasonable."""
        try:
            val = float(price)
            return 0.01 <= val <= 10000000  # Reasonable price range
        except (ValueError, TypeError):
            return False

    def is_packing_list(self, text: str) -> bool:
        """Check if this is a packing list."""
        text_lower = text.lower()
        return 'packing list' in text_lower and 'invoice' not in text_lower
