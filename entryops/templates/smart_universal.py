"""
Smart Universal Template - Uses SmartExtractor for automatic line item extraction

This template uses data shape recognition to extract line items from any invoice format.
It serves as a universal fallback that works without supplier-specific patterns.

Key features:
- Recognizes part codes, quantities, and prices by their data shapes
- Verifies part numbers against the parts_master database
- Works with inconsistent invoice layouts
- Handles OCR errors in numbers and codes
"""

import re
from typing import List, Dict
from .base_template import BaseTemplate

# Import SmartExtractor
import sys
from pathlib import Path

# Add parent directory to path for imports - handle case where __file__ is not defined
try:
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
except NameError:
    # __file__ not defined (e.g., when running with exec)
    # Try to find the parent directory through sys.path
    current_path = Path.cwd()
    parent_dir = current_path.parent if 'entryops' in current_path.name else current_path
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))

try:
    from smart_extractor import SmartExtractor, ExtractionResult
except ImportError:
    # Fallback for different import contexts
    try:
        from entryops.smart_extractor import SmartExtractor, ExtractionResult
    except ImportError:
        SmartExtractor = None
        ExtractionResult = None


class SmartUniversalTemplate(BaseTemplate):
    """
    Universal template using SmartExtractor for automatic extraction.

    This template can process any commercial invoice by recognizing
    data patterns rather than fixed positions or supplier-specific formats.
    """

    name = "Smart Universal"
    description = "Universal extractor using data shape recognition - works with any invoice format"
    client = "Universal"
    version = "1.0.0"
    enabled = True

    extra_columns = ['unit_price', 'description', 'confidence']

    # Known company patterns that indicate a commercial invoice
    INVOICE_INDICATORS = [
        r'\binvoice\b',
        r'\bcommercial\s+invoice\b',
        r'\bproforma\b',
        r'\btax\s+invoice\b',
        r'\bsales\s+invoice\b',
    ]

    # Patterns that indicate this is NOT an invoice we should process
    EXCLUSION_PATTERNS = [
        r'\bpacking\s+list\b(?!.*invoice)',  # Packing list without invoice
        r'\bshipping\s+label\b',
        r'\bdelivery\s+note\b',
        r'\bquotation\b',
        r'\bpurchase\s+order\b',
    ]

    def __init__(self):
        super().__init__()
        self._extractor = None
        self._last_result = None

    @property
    def extractor(self):
        """Lazy-load the SmartExtractor."""
        if self._extractor is None and SmartExtractor is not None:
            self._extractor = SmartExtractor()
        return self._extractor

    def can_process(self, text: str) -> bool:
        """
        Check if this template can process the invoice.

        This template can process ANY invoice as a fallback, but returns
        a lower confidence score so supplier-specific templates take priority.
        """
        if SmartExtractor is None:
            return False

        text_lower = text.lower()

        # Check for exclusion patterns
        for pattern in self.EXCLUSION_PATTERNS:
            if re.search(pattern, text_lower):
                return False

        # Check for invoice indicators
        for pattern in self.INVOICE_INDICATORS:
            if re.search(pattern, text_lower):
                return True

        # Also accept if we find typical invoice elements
        has_prices = bool(re.search(r'\$[\d,]+\.?\d*|\d+\.\d{2}\b', text))
        has_quantities = bool(re.search(r'\b\d+\s*(?:pcs?|ea|units?|qty)\b', text_lower))

        return has_prices and has_quantities

    def get_confidence_score(self, text: str) -> float:
        """
        Return confidence score for template matching.

        This template returns a moderate confidence (0.3-0.5) so that
        supplier-specific templates with higher confidence take priority.
        """
        if not self.can_process(text):
            return 0.0

        score = 0.3  # Base score - lower than specific templates

        text_lower = text.lower()

        # Increase score based on invoice markers
        if re.search(r'\bcommercial\s+invoice\b', text_lower):
            score += 0.1
        if re.search(r'\binvoice\s*(?:no\.?|#|number)\s*[:\s]', text_lower):
            score += 0.05
        if re.search(r'\bpo\.?\s*(?:no\.?|#)\s*[:\s]*\d+', text_lower):
            score += 0.05

        # Check if SmartExtractor can find items
        if self.extractor:
            try:
                result = self.extractor.extract_from_text(text)
                if len(result.line_items) > 0:
                    score += 0.1
                if len(result.line_items) >= 5:
                    score += 0.05
                # Higher score if database matches found
                if self.extractor.db_matched_count > 0:
                    score += 0.1
            except Exception:
                pass

        return min(score, 0.6)  # Cap at 0.6 to let specific templates win

    def extract_invoice_number(self, text: str) -> str:
        """Extract invoice number using SmartExtractor patterns."""
        if self.extractor and self._last_result:
            if self._last_result.invoice_number:
                return self._last_result.invoice_number

        # Fallback patterns
        patterns = [
            r'Invoice\s*(?:No\.?|#|Number)[:\s]*([A-Z0-9][\w\-/]+)',
            r'INV[:\s#]*([A-Z0-9][\w\-/]+)',
            r'(?:Invoice|Inv)\s+n\.?\s*[:\s]*(\d+)',
            r'INVOICE\s*(?:NO\.?)?\s*[:\s]*([A-Z0-9][\w\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        """Extract PO/project number."""
        if self.extractor and self._last_result:
            if self._last_result.po_numbers:
                return self._last_result.po_numbers[0]

        # Fallback patterns
        patterns = [
            r'P\.?O\.?\s*(?:No\.?|#|Number)?[:\s]*(\d{6,})',
            r'Purchase\s*Order[:\s]*(\d+)',
            r'Order\s*(?:No\.?|#)?[:\s]*(\d+)',
            r'\b(400\d{5})\b',  # Sigma PO format
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def extract_manufacturer_name(self, text: str) -> str:
        """Extract manufacturer/supplier name."""
        if self.extractor and self._last_result:
            if self._last_result.supplier_name:
                return self._last_result.supplier_name

        # Try to find company name in header
        lines = text.split('\n')[:15]
        for line in lines:
            line = line.strip()
            if re.search(r'\b(LTD\.?|LLC|INC\.?|CORP\.?|PVT\.?|CO\.)\b', line, re.IGNORECASE):
                if 5 < len(line) < 80:
                    return line

        return ""

    def extract_line_items(self, text: str) -> List[Dict]:
        """
        Extract line items using SmartExtractor.

        This is the key method that leverages the SmartExtractor's
        data shape recognition capabilities.
        """
        if not self.extractor:
            return []

        try:
            # Use SmartExtractor
            self._last_result = self.extractor.extract_from_text(text)

            # Convert LineItem objects to dicts for template compatibility
            items = []
            for item in self._last_result.line_items:
                items.append({
                    'part_number': item.part_number,
                    'quantity': item.quantity,
                    'total_price': item.total_price,
                    'unit_price': item.unit_price,
                    'description': item.description,
                    'confidence': f"{item.confidence:.0%}",
                })

            return items

        except Exception as e:
            print(f"SmartExtractor error: {e}")
            return []

    def post_process_items(self, items: List[Dict]) -> List[Dict]:
        """Post-process items - deduplicate and validate."""
        if not items:
            return items

        # Deduplicate based on part_number + quantity + total_price
        seen = set()
        unique_items = []

        for item in items:
            key = f"{item['part_number']}_{item['quantity']}_{item['total_price']}"
            if key not in seen:
                seen.add(key)
                unique_items.append(item)

        return unique_items

    def is_packing_list(self, text: str) -> bool:
        """Check if document is only a packing list."""
        text_lower = text.lower()
        if 'packing list' in text_lower:
            # If it also contains invoice, process it
            if 'invoice' in text_lower:
                return False
            return True
        return False