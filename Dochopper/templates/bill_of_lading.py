"""
Bill of Lading Template - Extracts gross weight from BOL documents
Used to populate net_weight for invoice line items when invoices lack weight data.
"""

import re
from typing import Optional
from .base_template import BaseTemplate


class BillOfLadingTemplate(BaseTemplate):
    """
    Template for detecting and extracting data from Bill of Lading documents.

    Identifies BOL documents within PDFs and extracts gross weight information
    that will be used as net_weight for associated invoice line items.
    """

    # === METADATA ===
    name = "Bill of Lading"
    description = "Extracts gross weight from Bill of Lading documents"
    client = "Universal BOL"
    version = "1.0.0"
    enabled = True

    # BOL doesn't produce line items - it provides metadata
    extra_columns = []

    def can_process(self, text: str) -> bool:
        """
        Check if this document is a Bill of Lading.

        Looks for common BOL identifiers:
        - "Bill of Lading" header
        - Common BOL fields (SHIPPER, CONSIGNEE, GROSS WEIGHT)
        - Shipping-specific terminology
        """
        text_lower = text.lower()

        # Primary identifier
        has_bol_header = 'bill of lading' in text_lower

        # Supporting indicators
        has_shipper = 'shipper' in text_lower or 'exporter' in text_lower
        has_consignee = 'consignee' in text_lower
        has_gross_weight = 'gross weight' in text_lower

        # Additional shipping indicators
        has_shipping_terms = any(term in text_lower for term in [
            'port of loading',
            'port of discharge',
            'container',
            'vessel name',
            'freight prepaid',
            'shipped on board'
        ])

        # Need BOL header and at least 2 supporting indicators
        if has_bol_header:
            supporting_count = sum([
                has_shipper,
                has_consignee,
                has_gross_weight,
                has_shipping_terms
            ])
            return supporting_count >= 2

        return False

    def get_confidence_score(self, text: str) -> float:
        """
        Return 0.0 to prevent BOL template from being used as primary template.

        BOL detection and weight extraction is handled separately in ProcessorEngine
        at the PDF processing level (invoice_processor_gui.py lines 133-144).
        This template should never be selected as the primary invoice processor.
        """
        return 0.0

    def extract_gross_weight(self, text: str) -> Optional[str]:
        """
        Extract gross weight from Bill of Lading.

        Common patterns:
        - "4950.000 KG" in table format
        - "GROSS WEIGHT ... 4950.000 KG"
        - "Gross Weight: 4950.000 KG"

        Returns weight as string (e.g., "4950.000") or None if not found.
        """
        # Pattern 1: Look for "GROSS WEIGHT" header followed by weight
        # Matches: "GROSS WEIGHT ... 4950.000 KG"
        pattern1 = r'GROSS\s+WEIGHT\s*[:\-]?\s*(\d+[,.]?\d*)\s*KG'
        match = re.search(pattern1, text, re.IGNORECASE)
        if match:
            weight = match.group(1).replace(',', '.')
            return weight

        # Pattern 2: Look for container/package section with weight
        # Matches: "40HC 4950.000 KG" or "Weight 4950.000 KG"
        pattern2 = r'(?:40HC|Weight|Gross)\s+(\d+[,.]?\d*)\s*KG'
        match = re.search(pattern2, text, re.IGNORECASE)
        if match:
            weight = match.group(1).replace(',', '.')
            return weight

        # Pattern 3: Look for standalone weight value in KG
        # Be more specific to avoid false positives
        # Matches: "4950.000 KG" when preceded by whitespace/newline
        pattern3 = r'[\s\n](\d{3,}[,.]?\d*)\s*KG'
        matches = re.findall(pattern3, text, re.IGNORECASE)
        if matches:
            # Return the largest weight found (typically the gross weight)
            weights = [float(w.replace(',', '.')) for w in matches]
            max_weight = max(weights)
            return f"{max_weight:.3f}".replace('.', '.')

        return None

    def extract_container_number(self, text: str) -> Optional[str]:
        """
        Extract container number for cross-reference.

        Patterns:
        - "TRHU5307730" (container number format)
        - "Container ... TRHU5307730"
        """
        # Pattern: 4 letters followed by 7 digits (standard container format)
        pattern = r'\b([A-Z]{4}\d{7})\b'
        match = re.search(pattern, text)
        if match:
            return match.group(1)
        return None

    def extract_bill_number(self, text: str) -> Optional[str]:
        """
        Extract bill of lading number for cross-reference.

        Patterns:
        - "BILL NUMBER ... 2917362437"
        - "B/L: 2917362437"
        """
        patterns = [
            r'BILL\s+NUMBER\s*[:\-]?\s*(\d+)',
            r'B/L\s*[:\-]?\s*(\d+)',
            r'BL\s*[:\-]?\s*(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    # === BaseTemplate required methods (BOL doesn't produce invoice data) ===

    def extract_invoice_number(self, text: str) -> str:
        """BOL documents don't have invoice numbers."""
        bill_num = self.extract_bill_number(text)
        return f"BOL_{bill_num}" if bill_num else "BOL_UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        """BOL documents don't have project numbers."""
        return "N/A"

    def extract_line_items(self, text: str) -> list:
        """
        BOL documents don't produce line items.
        They provide metadata (gross weight) for invoices.
        """
        return []

    def is_packing_list(self, text: str) -> bool:
        """BOL is not a packing list."""
        return False
