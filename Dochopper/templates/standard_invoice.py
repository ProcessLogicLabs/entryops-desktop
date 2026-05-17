"""
Standard Invoice Template

A general-purpose template for standard commercial invoices with common formats.
Handles invoices with typical layouts: header info, line items in table format,
and totals at the bottom.
"""

import re
from typing import List, Dict
from .base_template import BaseTemplate


class StandardInvoiceTemplate(BaseTemplate):
    """
    Template for standard commercial invoices.

    Designed for invoices with:
    - Invoice number and date in header
    - PO/Order reference
    - Line items with part number, description, quantity, unit price, total
    - Standard table format
    """

    name = "Standard Invoice"
    description = "Standard commercial invoice format with tabular line items"
    client = "Universal"
    version = "1.0.0"
    enabled = True

    extra_columns = ['unit_price', 'description']

    def can_process(self, text: str) -> bool:
        """Check if this is a standard commercial invoice."""
        text_lower = text.lower()

        # Must have invoice indicator
        has_invoice = any([
            'commercial invoice' in text_lower,
            'tax invoice' in text_lower,
            re.search(r'\binvoice\s*(?:no|#|number)', text_lower),
        ])

        # Must have price indicators
        has_prices = bool(re.search(r'\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?', text))

        # Must have quantity indicators
        has_qty = bool(re.search(r'\b(?:qty|quantity|pcs|units?|ea)\b', text_lower))

        return has_invoice and has_prices and has_qty

    def get_confidence_score(self, text: str) -> float:
        """Return confidence score."""
        if not self.can_process(text):
            return 0.0

        score = 0.4
        text_lower = text.lower()

        if 'commercial invoice' in text_lower:
            score += 0.1
        if re.search(r'part\s*(?:no|#|number)', text_lower):
            score += 0.1
        if re.search(r'unit\s*price', text_lower):
            score += 0.05
        if re.search(r'total\s*(?:amount|price|value)', text_lower):
            score += 0.05

        return min(score, 0.7)

    def extract_invoice_number(self, text: str) -> str:
        """Extract invoice number."""
        patterns = [
            r'Invoice\s*(?:No\.?|#|Number)[:\s]*([A-Z0-9][\w\-/]+)',
            r'INV[:\s\-#]*([A-Z0-9][\w\-/]+)',
            r'Invoice[:\s]+([A-Z0-9][\w\-/]+)',
            r'(?:Ref|Reference)\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        """Extract PO/project number."""
        patterns = [
            r'P\.?O\.?\s*(?:No\.?|#|Number)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Purchase\s*Order[:\s]*([A-Z0-9][\w\-/]+)',
            r'Order\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Customer\s*(?:Ref|Reference)[:\s]*([A-Z0-9][\w\-/]+)',
            r'Your\s*(?:Ref|Reference)[:\s]*([A-Z0-9][\w\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def extract_line_items(self, text: str) -> List[Dict]:
        """Extract line items from standard invoice format."""
        items = []
        seen = set()
        lines = text.split('\n')

        # Pattern for typical line item: Part# Description Qty UnitPrice Total
        line_pattern = re.compile(
            r'^([A-Z0-9][\w\-/\.]+)\s+'          # Part number
            r'(.+?)\s+'                           # Description
            r'(\d+(?:\.\d+)?)\s+'                 # Quantity
            r'\$?([\d,]+\.?\d*)\s+'              # Unit price
            r'\$?([\d,]+\.?\d*)',                # Total price
            re.IGNORECASE
        )

        # Simpler pattern: Part# Qty Total
        simple_pattern = re.compile(
            r'^([A-Z0-9][\w\-/\.]+)\s+'          # Part number
            r'(\d+(?:\.\d+)?)\s+'                 # Quantity
            r'\$?([\d,]+\.?\d*)',                # Total price
            re.IGNORECASE
        )

        for line in lines:
            line = line.strip()
            if not line or len(line) < 10:
                continue

            # Try detailed pattern first
            match = line_pattern.match(line)
            if match:
                part_num = match.group(1)
                desc = match.group(2).strip()
                qty = match.group(3)
                unit_price = match.group(4).replace(',', '')
                total = match.group(5).replace(',', '')

                key = f"{part_num}_{qty}_{total}"
                if key not in seen:
                    seen.add(key)
                    items.append({
                        'part_number': part_num,
                        'description': desc,
                        'quantity': qty,
                        'unit_price': unit_price,
                        'total_price': total,
                    })
                continue

            # Try simple pattern
            match = simple_pattern.match(line)
            if match:
                part_num = match.group(1)
                qty = match.group(2)
                total = match.group(3).replace(',', '')

                key = f"{part_num}_{qty}_{total}"
                if key not in seen:
                    seen.add(key)
                    items.append({
                        'part_number': part_num,
                        'description': '',
                        'quantity': qty,
                        'unit_price': '',
                        'total_price': total,
                    })

        return items

    def is_packing_list(self, text: str) -> bool:
        """Check if this is a packing list."""
        text_lower = text.lower()
        if 'packing list' in text_lower or 'packing slip' in text_lower:
            if 'invoice' not in text_lower:
                return True
        return False
