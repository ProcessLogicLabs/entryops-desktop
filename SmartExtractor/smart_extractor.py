"""
Smart Line Item Extractor for EntryOps

A practical approach to extracting line items from commercial invoices
that handles inconsistent formats by recognizing DATA TYPES, not positions.

Key insight from analyzing real invoices:
- Every line item has: PART_CODE + QUANTITY + PRICE
- The ORDER of these varies by supplier
- But the DATA SHAPES are consistent:
  - Part codes: alphanumeric with dashes (DMF124, DTK8, X-101-054)
  - Quantities: integers, sometimes with units (48, 4 PCS, 824.00 ks)
  - Prices: decimals with 2-3 places ($265.81, 1,234.56 USD)

This extractor finds line items by identifying rows with these data shapes.
"""

import re
import sqlite3
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
from pathlib import Path

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


def get_database_path() -> Path:
    """Get the path to the EntryOps database."""
    # Try multiple locations
    candidates = [
        Path(__file__).parent / "Resources" / "entryops.db",
        Path(__file__).parent.parent / "Resources" / "entryops.db",
        Path.home() / ".entryops" / "entryops.db",
    ]
    for path in candidates:
        if path.exists():
            return path
    # Return default even if doesn't exist
    return candidates[0]


def load_known_part_numbers(db_path: Path = None) -> Set[str]:
    """Load all known part numbers from parts_master database."""
    if db_path is None:
        db_path = get_database_path()

    known_parts = set()
    if not db_path.exists():
        return known_parts

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT part_number FROM parts_master")
        for row in cursor.fetchall():
            if row[0]:
                # Store both original and uppercase for matching
                known_parts.add(row[0].strip())
                known_parts.add(row[0].strip().upper())
        conn.close()
    except Exception as e:
        print(f"Warning: Could not load parts database: {e}")

    return known_parts


@dataclass
class LineItem:
    """Extracted line item from invoice."""
    part_number: str
    quantity: str
    description: str = ""
    unit_price: str = ""
    total_price: str = ""
    raw_line: str = ""
    confidence: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'part_number': self.part_number,
            'quantity': self.quantity,
            'description': self.description,
            'unit_price': self.unit_price,
            'total_price': self.total_price,
        }


@dataclass
class ExtractionResult:
    """Results from extracting invoice data."""
    invoice_number: str = ""
    po_numbers: List[str] = field(default_factory=list)
    supplier_name: str = ""
    line_items: List[LineItem] = field(default_factory=list)
    raw_text: str = ""


class SmartExtractor:
    """
    Extracts line items from commercial invoices using data shape recognition.

    Works by:
    1. Splitting each line into tokens
    2. Classifying each token (code, quantity, price, text)
    3. Finding lines that have the right mix of types
    4. Extracting values by type, not position
    """

    # Patterns for recognizing data types
    PATTERNS = {
        # Prices: $123.45 or 1,234.56 or 123.456 (3 decimal = unit price)
        # Also handle OCR errors like 6s.080 -> 65.080, 45S.56 -> 455.56
        # Handle USD prefix/suffix, European format (1.534,94), $ prices
        'price': re.compile(
            r'^(?:USD\s*)?\$[\d,]+\.?\d*$|'           # $265.81, $44,232.30
            r'^[\d,sS]+\.[\d,sSOo]{2,3}$|'            # 265.81, 6s.080
            r'^\d{1,3}(?:\.\d{3})*,\d{2}\s*(?:USD|CZK)?$|'  # European: 1.534,94 USD
            r'^(?:USD\s*)?[\d,]+\.[\d]{2}(?:\s*USD)?$',  # USD 2676.00
            re.IGNORECASE
        ),

        # Quantities: integers (possibly with comma thousands) or European whole numbers
        # European qty: 824,00 ks means 824 pcs - but these end in ,00
        'quantity': re.compile(r'^\d+$'),  # Simple integers only

        # European quantities with ,00 (like 824,00 = 824)
        'euro_quantity': re.compile(r'^\d+,00$'),

        # Part codes: alphanumeric with optional dashes, min 3 chars
        # Examples: DMF124, DTK8, X-101-054, NDZ04, DFB1890, NMS-V-004
        # Also HTS#-prefixed descriptions: HTS#8432900020-HUB
        'part_code': re.compile(
            r'^[A-Z]{1,4}[\w\-\.]+\d+[\w\-]*$|'  # DMF124, DFB1890
            r'^\d{1,2}-\d{5,}$|'                   # 18-123456
            r'^[A-Z]+\d+[A-Z]?$|'                  # NDZ04, DTK8
            r'^[A-Z]-\d{3}-\d{3}$|'                # X-101-054
            r'^[A-Z]+-[A-Z]-\d+$|'                 # NMS-V-004
            r'^HTS#\d+-[\w]+$',                    # HTS#8432900020-HUB
            re.IGNORECASE
        ),

        # Bracketed codes: [DMF124] or (DMF124) - common in invoices
        # Also handle OCR errors: lDMF124l (L instead of bracket), IDTP4]
        'bracketed_code': re.compile(r'^[\[\(lI][A-Z0-9][\w\-\.]+[\]\)lI]$', re.IGNORECASE),

        # PO numbers: 8 digits starting with 400 (Sigma format) or with suffix like -7, -9
        'po_number': re.compile(r'^400\d{5}(?:-\d+)?$'),

        # Units: PCS, KS, EA, etc.
        'unit': re.compile(r'^(PCS?|KS|EA|UNITS?|NOS?|SETS?|KGS?)\.?$', re.IGNORECASE),

        # HTS codes
        'hts': re.compile(r'^\d{4}\.\d{2}\.\d{2,4}$|^\d{8,10}$'),
    }

    # Common invoice number patterns
    INVOICE_PATTERNS = [
        r'Invoice\s*(?:No\.?|#|Number)[:\s]*([A-Z0-9][\w\-/]+)',
        r'INV[:\s#]*([A-Z0-9][\w\-/]+)',
        r'(?:Invoice|Inv)\s+n\.?\s*[:\s]*(\d+)',
    ]

    def __init__(self, db_path: Path = None):
        self.result = ExtractionResult()
        self.known_parts = load_known_part_numbers(db_path)
        self.db_matched_count = 0  # Track how many items matched database

    def extract_from_pdf(self, pdf_path: str, pages: int = 5) -> ExtractionResult:
        """Extract line items from a PDF invoice."""
        if not HAS_PDF:
            raise ImportError("pdfplumber required: pip install pdfplumber")

        if not Path(pdf_path).exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Extract text
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:pages]:
                text = page.extract_text() or ""
                text_parts.append(text)

        full_text = "\n".join(text_parts)
        return self.extract_from_text(full_text)

    def extract_from_text(self, text: str) -> ExtractionResult:
        """Extract line items from invoice text."""
        self.result = ExtractionResult(raw_text=text)

        # Extract header info
        self._extract_invoice_number(text)
        self._extract_po_numbers(text)
        self._extract_supplier(text)

        # Extract line items
        self._extract_line_items(text)

        return self.result

    def _extract_invoice_number(self, text: str):
        """Extract invoice number."""
        for pattern in self.INVOICE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                self.result.invoice_number = match.group(1).strip()
                return

    def _extract_po_numbers(self, text: str):
        """Extract PO numbers (Sigma format: 400XXXXX)."""
        matches = re.findall(r'\b(400\d{5})\b', text)
        self.result.po_numbers = list(set(matches))

    def _extract_supplier(self, text: str):
        """Try to extract supplier name from header."""
        lines = text.split('\n')[:15]
        for line in lines:
            line = line.strip()
            if re.search(r'\b(LTD|LLC|INC|CORP|PVT|CO\.)\b', line, re.IGNORECASE):
                if 5 < len(line) < 80:
                    self.result.supplier_name = line
                    break

    def _extract_line_items(self, text: str):
        """Extract line items using data shape recognition."""
        lines = text.split('\n')

        for line in lines:
            line = line.strip()
            if len(line) < 15:  # Too short to be a line item
                continue

            # Tokenize the line
            tokens = self._tokenize(line)

            # Classify each token
            classified = [(t, self._classify(t)) for t in tokens]

            # Check if this looks like a line item
            types = [c[1] for c in classified]

            # Must have at least: code + price (quantity can be missing or 1)
            has_code = 'part_code' in types or 'bracketed_code' in types
            has_qty = 'quantity' in types
            has_price = 'price' in types

            # Also count lines with code + multiple prices (unit price + total)
            price_count = types.count('price')

            if has_code and has_price and (has_qty or price_count >= 2):
                item = self._extract_item_from_tokens(classified, line)
                if item:
                    self.result.line_items.append(item)

    def _tokenize(self, line: str) -> List[str]:
        """Split line into tokens for classification."""
        # Try splitting by 2+ spaces first (column separators)
        tokens = re.split(r'\s{2,}', line)

        result = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue

            # Split each column group by single spaces
            parts = token.split()

            for part in parts:
                part = part.strip()
                if part:
                    result.append(part)

        return result

    def _classify(self, token: str) -> str:
        """Classify a token by its data shape."""
        token = token.strip()

        # Check each pattern in priority order
        # Check bracketed code first (most specific)
        if self.PATTERNS['bracketed_code'].match(token):
            return 'bracketed_code'

        # Check euro quantity FIRST (824,00 = 824 pcs) - before price!
        if self.PATTERNS['euro_quantity'].match(token):
            return 'quantity'

        # Check price
        if self.PATTERNS['price'].match(token):
            return 'price'

        # Check PO number
        if self.PATTERNS['po_number'].match(token):
            return 'po_number'

        # Check HTS
        if self.PATTERNS['hts'].match(token):
            return 'hts'

        # Check quantity (must be after PO to avoid false matches)
        if self.PATTERNS['quantity'].match(token):
            return 'quantity'

        # Check unit
        if self.PATTERNS['unit'].match(token):
            return 'unit'

        # Check part code (least specific alphanumeric)
        if self.PATTERNS['part_code'].match(token):
            return 'part_code'

        # Default to text
        return 'text'

    def _clean_ocr_number(self, value: str) -> str:
        """Fix common OCR errors in numbers."""
        # Common OCR substitutions: s/S -> 5, O/o -> 0
        result = value.replace('$', '')
        result = result.replace('s', '5').replace('S', '5')
        result = result.replace('O', '0').replace('o', '0')
        result = result.replace(',', '')
        return result

    def _clean_bracketed_code(self, value: str) -> str:
        """Extract code from brackets, handling OCR errors."""
        # Remove brackets (including OCR'd lowercase L)
        result = value.strip('[]()lI')
        return result

    def _extract_item_from_tokens(self, classified: List[Tuple[str, str]], raw_line: str) -> Optional[LineItem]:
        """Extract a LineItem from classified tokens."""
        part_number = ""
        quantity = ""
        prices = []
        texts = []
        all_part_codes = []  # Collect all part codes found

        # First pass: look for bracketed codes (most reliable part numbers)
        for token, dtype in classified:
            if dtype == 'bracketed_code':
                part_number = self._clean_bracketed_code(token)
                break

        # Second pass: collect all values
        for token, dtype in classified:
            if dtype == 'part_code':
                # Skip class codes (C153, C110)
                if not re.match(r'^C\d{2,3}$', token, re.IGNORECASE):
                    all_part_codes.append(token)
            elif dtype == 'quantity' and not quantity:
                # Only use if it looks like a reasonable quantity (< 100000)
                try:
                    # Handle European format: 824,00 -> 824
                    clean = token.replace(',00', '').replace(',', '')
                    val = int(clean)
                    if val < 100000:
                        quantity = clean
                except:
                    pass
            elif dtype == 'price':
                prices.append(self._clean_ocr_number(token))
            elif dtype == 'text' and len(token) > 3:
                texts.append(token)

        # If no bracketed code, choose from part codes
        # PRIORITY 1: Check if any code matches the parts_master database
        # PRIORITY 2: Prefer shorter/simpler codes as they're typically the ITEMNO
        if not part_number and all_part_codes:
            db_matched = None
            for code in all_part_codes:
                if code in self.known_parts or code.upper() in self.known_parts:
                    db_matched = code
                    self.db_matched_count += 1
                    break

            if db_matched:
                # Use the database-verified part number
                part_number = db_matched
                # Add other codes to description
                for code in all_part_codes:
                    if code != db_matched and code not in texts:
                        texts.insert(0, code)
            else:
                # No database match - fall back to heuristics
                # Sort by: codes with + go last, then by length (shorter first)
                def code_priority(code):
                    has_plus = '+' in code
                    dash_count = code.count('-')
                    return (has_plus, dash_count > 1, len(code))

                all_part_codes.sort(key=code_priority)
                part_number = all_part_codes[0]

                # Add remaining codes to description
                for code in all_part_codes[1:]:
                    if code not in texts:
                        texts.insert(0, code)

        # Must have the basics
        if not part_number or not prices:
            return None

        # Default quantity to 1 if not found
        if not quantity:
            quantity = "1"

        # Determine unit price vs total price
        unit_price = ""
        total_price = ""

        if len(prices) >= 2:
            # Usually: unit_price first, total_price last
            unit_price = prices[0].replace('$', '').replace(',', '')
            total_price = prices[-1].replace('$', '').replace(',', '')
        elif len(prices) == 1:
            total_price = prices[0].replace('$', '').replace(',', '')

        # Build description from text parts
        description = ' '.join(texts)

        # Calculate confidence
        confidence = 0.5
        if part_number and quantity and total_price:
            confidence = 0.8
        if unit_price:
            confidence = 0.9
        if description:
            confidence = min(1.0, confidence + 0.05)

        # Boost confidence if part number was verified against database
        is_db_verified = part_number in self.known_parts or part_number.upper() in self.known_parts
        if is_db_verified:
            confidence = min(1.0, confidence + 0.1)

        return LineItem(
            part_number=part_number,
            quantity=quantity,
            description=description[:100],  # Truncate long descriptions
            unit_price=unit_price,
            total_price=total_price,
            raw_line=raw_line,
            confidence=confidence
        )

    def print_results(self):
        """Print extraction results."""
        r = self.result

        print("\n" + "=" * 70)
        print("EXTRACTION RESULTS")
        print("=" * 70)

        print(f"\nSupplier: {r.supplier_name or 'Unknown'}")
        print(f"Invoice #: {r.invoice_number or 'Not found'}")
        print(f"PO Numbers: {', '.join(r.po_numbers) if r.po_numbers else 'None found'}")
        print(f"Parts Database: {len(self.known_parts)} known parts loaded")
        if self.db_matched_count > 0:
            print(f"Database Matches: {self.db_matched_count} of {len(r.line_items)} items verified")

        print(f"\nLine Items Found: {len(r.line_items)}")
        print("-" * 70)

        for i, item in enumerate(r.line_items[:20], 1):  # Show first 20
            print(f"{i:3}. {item.part_number:<15} Qty: {item.quantity:<8} "
                  f"Price: {item.total_price:<12} Conf: {item.confidence:.0%}")
            if item.description:
                print(f"     Desc: {item.description[:60]}")

        if len(r.line_items) > 20:
            print(f"     ... and {len(r.line_items) - 20} more items")

        print("=" * 70)


def extract_invoice(pdf_path: str) -> ExtractionResult:
    """Convenience function to extract from a PDF."""
    extractor = SmartExtractor()
    return extractor.extract_from_pdf(pdf_path)


def main():
    """Test with sample invoices."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python smart_extractor.py <pdf_path>")
        sys.exit(1)

    extractor = SmartExtractor()
    result = extractor.extract_from_pdf(sys.argv[1])
    extractor.print_results()


if __name__ == '__main__':
    main()
