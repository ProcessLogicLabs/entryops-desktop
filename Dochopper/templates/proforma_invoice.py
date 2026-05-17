"""
Proforma Invoice Template

Template for proforma invoices which are commonly used for customs declarations
and advance payment requests before final commercial invoices.
"""

import re
from typing import List, Dict
from .base_template import BaseTemplate


class ProformaInvoiceTemplate(BaseTemplate):
    """
    Template for proforma invoices.

    Best for:
    - Proforma invoices for customs
    - Advance payment requests
    - Quotations converted to proforma
    - Pre-shipment documentation
    """

    name = "Proforma Invoice"
    description = "Proforma invoice for customs and pre-shipment documentation"
    client = "Universal"
    version = "1.0.0"
    enabled = True

    extra_columns = ['unit_price', 'description', 'hs_code']

    def can_process(self, text: str) -> bool:
        """Check if this is a proforma invoice."""
        text_lower = text.lower()

        # Must have proforma indicator
        has_proforma = any([
            'proforma' in text_lower,
            'pro forma' in text_lower,
            'pro-forma' in text_lower,
        ])

        # Should have price/value information
        has_values = bool(re.search(r'\d+\.?\d*', text))

        return has_proforma and has_values

    def get_confidence_score(self, text: str) -> float:
        """Return confidence score for proforma invoices."""
        if not self.can_process(text):
            return 0.0

        score = 0.5  # Higher base score for proforma detection
        text_lower = text.lower()

        if 'proforma invoice' in text_lower or 'pro forma invoice' in text_lower:
            score += 0.15
        if 'customs' in text_lower:
            score += 0.05
        if 'advance payment' in text_lower or 'prepayment' in text_lower:
            score += 0.05
        if re.search(r'validity|valid until|expiry', text_lower):
            score += 0.05

        return min(score, 0.8)

    def extract_invoice_number(self, text: str) -> str:
        """Extract proforma/invoice number."""
        patterns = [
            r'Proforma\s*(?:Invoice)?\s*(?:No\.?|#|Number)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Pro[\-\s]?forma\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'PI\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Invoice\s*(?:No\.?|#|Number)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Reference[:\s]*([A-Z0-9][\w\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        """Extract PO/order reference."""
        patterns = [
            r'P\.?O\.?\s*(?:No\.?|#|Number)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Order\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Your\s*(?:Ref|Reference)[:\s]*([A-Z0-9][\w\-/]+)',
            r'Customer\s*(?:Ref|Reference)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Quotation\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
            r'Quote\s*(?:No\.?|#)?[:\s]*([A-Z0-9][\w\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def _extract_validity_date(self, text: str) -> str:
        """Extract validity/expiry date if present."""
        patterns = [
            r'Valid(?:ity)?\s*(?:until|till|through)?[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})',
            r'Expir(?:y|es)[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})',
            r'Valid\s*(?:for)?\s*(\d+)\s*days?',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return ""

    def extract_line_items(self, text: str) -> List[Dict]:
        """Extract line items from proforma invoice."""
        items = []
        seen = set()
        lines = text.split('\n')

        # Proforma invoices often have detailed descriptions
        # Pattern: Part#, Description, Qty, Unit Price, Total
        detailed_pattern = re.compile(
            r'([A-Z0-9][\w\-/\.]+)\s+'         # Part/Item code
            r'(.{5,80}?)\s+'                   # Description
            r'(\d+(?:\.\d+)?)\s+'              # Quantity
            r'[\$\€\£]?([\d,]+\.?\d*)\s+'     # Unit price
            r'[\$\€\£]?([\d,]+\.?\d*)',        # Total
            re.IGNORECASE
        )

        # Simpler pattern for basic proformas
        simple_pattern = re.compile(
            r'([A-Z0-9][\w\-/\.]+)\s+'         # Part/Item code
            r'(.{5,50}?)\s+'                   # Description
            r'(\d+(?:\.\d+)?)\s+'              # Quantity
            r'[\$\€\£]?([\d,]+\.?\d*)',        # Total/Price
            re.IGNORECASE
        )

        # Minimal pattern
        minimal_pattern = re.compile(
            r'([A-Z0-9][\w\-/\.]{2,})\s+'      # Part code (3+ chars)
            r'(\d+(?:\.\d+)?)\s+'               # Quantity
            r'[\$\€\£]?([\d,]+\.?\d*)',        # Price
            re.IGNORECASE
        )

        for line in lines:
            line = line.strip()
            if not line or len(line) < 8:
                continue

            # Skip headers and totals
            if re.search(r'^(item|code|part|description|qty|price|total|subtotal|tax)',
                        line, re.IGNORECASE):
                continue
            if re.search(r'^(total|subtotal|grand|shipping|freight|discount)',
                        line, re.IGNORECASE):
                continue

            # Try detailed pattern
            match = detailed_pattern.search(line)
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
                        'hs_code': self._extract_hs_from_line(line),
                    })
                continue

            # Try simple pattern
            match = simple_pattern.search(line)
            if match:
                part_num = match.group(1)
                desc = match.group(2).strip()
                qty = match.group(3)
                price = match.group(4).replace(',', '')

                key = f"{part_num}_{qty}_{price}"
                if key not in seen:
                    seen.add(key)
                    items.append({
                        'part_number': part_num,
                        'description': desc,
                        'quantity': qty,
                        'unit_price': '',
                        'total_price': price,
                        'hs_code': self._extract_hs_from_line(line),
                    })
                continue

            # Try minimal pattern
            match = minimal_pattern.search(line)
            if match:
                part_num = match.group(1)
                qty = match.group(2)
                price = match.group(3).replace(',', '')

                key = f"{part_num}_{qty}_{price}"
                if key not in seen:
                    seen.add(key)
                    items.append({
                        'part_number': part_num,
                        'description': '',
                        'quantity': qty,
                        'unit_price': '',
                        'total_price': price,
                        'hs_code': self._extract_hs_from_line(line),
                    })

        return items

    def _extract_hs_from_line(self, line: str) -> str:
        """Extract HS code from a line if present."""
        # Look for HS code patterns
        match = re.search(r'\b(\d{4}\.\d{2}(?:\.\d{2,4})?)\b', line)
        if match:
            return match.group(1)

        match = re.search(r'\b(\d{6,10})\b', line)
        if match:
            code = match.group(1)
            # Validate it's likely an HS code (not just a price or qty)
            if len(code) >= 6 and not code.endswith('00'):
                return code

        return ""

    def is_packing_list(self, text: str) -> bool:
        """Check if this is a packing list."""
        text_lower = text.lower()
        # Proforma invoices are not packing lists
        if 'proforma' in text_lower or 'pro forma' in text_lower:
            return False
        return 'packing list' in text_lower and 'invoice' not in text_lower

    def post_process_items(self, items: List[Dict]) -> List[Dict]:
        """Post-process items to clean up and validate."""
        processed = []

        for item in items:
            # Skip items with invalid data
            if not item.get('part_number'):
                continue

            # Clean up description
            if item.get('description'):
                item['description'] = re.sub(r'\s+', ' ', item['description']).strip()

            # Validate price is reasonable
            try:
                price = float(item.get('total_price', '0') or '0')
                if price <= 0 or price > 10000000:
                    continue
            except (ValueError, TypeError):
                continue

            processed.append(item)

        return processed
