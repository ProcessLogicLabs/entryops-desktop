"""
Template Generator Module for DocHopper
Generates invoice templates from sample PDF documents offline.

Usage:
    from template_generator import TemplateGenerator

    generator = TemplateGenerator()
    generator.analyze_pdf('/path/to/sample.pdf')
    generator.generate_template('new_supplier', output_dir='templates/')
"""

import re
import os
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


@dataclass
class FieldPattern:
    """Represents a detected field pattern in the invoice."""
    name: str
    pattern: str
    sample_matches: List[str] = field(default_factory=list)
    confidence: float = 0.0
    field_type: str = "text"  # text, number, currency, date, code


@dataclass
class LineItemPattern:
    """Represents a detected line item pattern."""
    pattern: str
    field_names: List[str]
    sample_matches: List[Dict] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class InvoiceAnalysis:
    """Results of analyzing an invoice PDF."""
    supplier_name: str = ""
    supplier_indicators: List[str] = field(default_factory=list)
    invoice_number_pattern: Optional[FieldPattern] = None
    project_number_pattern: Optional[FieldPattern] = None
    line_item_pattern: Optional[LineItemPattern] = None
    extra_fields: Dict[str, FieldPattern] = field(default_factory=dict)
    raw_text: str = ""
    sample_lines: List[str] = field(default_factory=list)


class TemplateGenerator:
    """
    Generates invoice templates from sample PDF documents.

    The generator analyzes PDF text to:
    1. Identify supplier/company indicators
    2. Detect invoice number patterns
    3. Detect project/PO number patterns
    4. Identify line item formats and extract field patterns
    5. Generate Python template code
    """

    # Common field patterns to look for
    COMMON_PATTERNS = {
        'invoice_number': [
            (r'INVOICE\s*(?:NO\.?|#|NUMBER)\s*[:\s]*([A-Z0-9][\w\-/]+)', 'INVOICE NO'),
            (r'Invoice\s+n\.?\s*:?\s*(\d+)', 'Invoice n.'),
            (r'INV\.?\s*(?:#|NO\.?)?\s*:?\s*([A-Z0-9][\w\-/]+)', 'INV'),
        ],
        'po_number': [
            (r'PO\.?\s*(?:NO\.?|#)\s*[:\s]*(\d{8})', 'PO NO'),
            (r'P\.?O\.?\s*(?:NUMBER|#)\s*:?\s*(\d+)', 'PO NUMBER'),
            (r'(?:Purchase|Buyer)[\'s]*\s*Order\s*(?:No\.?|#)\s*:?\s*(\d+)', 'Buyer Order'),
            (r'\b(400\d{5})\b', 'Sigma PO format'),
        ],
        'hs_code': [
            (r'\b(\d{4}\.\d{2}\.\d{4})\b', 'Standard HTS'),
            (r'\bHTS#?(\d{10})\b', 'HTS compact'),
            (r'\bHS\s*(?:CODE|#)\s*:?\s*(\d{4}\.?\d{2}\.?\d{4})', 'HS CODE'),
        ],
        'quantity': [
            (r'(\d+(?:,\d{3})*)\s*(?:PCS?|UNITS?|KS|EA)', 'Qty with unit'),
            (r'QTY\.?\s*:?\s*(\d+(?:[.,]\d+)?)', 'QTY field'),
        ],
        'price': [
            (r'\$\s*([\d,]+\.?\d*)', 'USD price'),
            (r'USD\s*([\d,]+\.?\d*)', 'USD amount'),
            (r'([\d,]+\.?\d*)\s*USD', 'Amount USD'),
        ],
        'country': [
            (r'\b(CHINA|INDIA|INDONESIA|BRAZIL|CZECH REPUBLIC)\b', 'Country name'),
        ],
    }

    # Common supplier patterns
    SUPPLIER_INDICATORS = [
        # Company suffixes
        r'(?:PVT\.?\s*)?LTD\.?',
        r'LLC',
        r'INC\.?',
        r'CORP(?:ORATION)?\.?',
        r'CO\.?',
        r'S\.?A\.?',
        r'A\.?S\.?',
        r'P\.?T\.?',
        # Legal identifiers
        r'GSTIN\s*:\s*[\w]+',
        r'VAT\s*(?:NO\.?|#)?\s*:?\s*[\w]+',
        r'IEC\s*(?:NO\.?|#)?\s*:?\s*[\w]+',
    ]

    def __init__(self):
        if not PDF_AVAILABLE:
            raise ImportError("pdfplumber is required. Install with: pip install pdfplumber")

        self.analysis: Optional[InvoiceAnalysis] = None

    def analyze_pdf(self, pdf_path: str, pages: int = 3) -> InvoiceAnalysis:
        """
        Analyze a PDF invoice to detect patterns.

        Args:
            pdf_path: Path to the PDF file
            pages: Number of pages to analyze (default: 3)

        Returns:
            InvoiceAnalysis object with detected patterns
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Extract text
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages[:pages]):
                text += (page.extract_text() or "") + "\n"

        if not text.strip():
            raise ValueError("No text extracted from PDF. It may be a scanned document.")

        analysis = InvoiceAnalysis(raw_text=text)
        analysis.sample_lines = [l.strip() for l in text.split('\n') if l.strip()][:50]

        # Detect supplier
        analysis.supplier_name, analysis.supplier_indicators = self._detect_supplier(text)

        # Detect invoice number pattern
        analysis.invoice_number_pattern = self._detect_field_pattern(
            text, self.COMMON_PATTERNS['invoice_number'], 'invoice_number'
        )

        # Detect PO/project number pattern
        analysis.project_number_pattern = self._detect_field_pattern(
            text, self.COMMON_PATTERNS['po_number'], 'project_number'
        )

        # Detect line item patterns
        analysis.line_item_pattern = self._detect_line_items(text)

        # Detect extra fields
        for field_name in ['hs_code', 'quantity', 'price', 'country']:
            pattern = self._detect_field_pattern(
                text, self.COMMON_PATTERNS[field_name], field_name
            )
            if pattern and pattern.confidence > 0.3:
                analysis.extra_fields[field_name] = pattern

        self.analysis = analysis
        return analysis

    def _detect_supplier(self, text: str) -> Tuple[str, List[str]]:
        """Detect supplier name and identifying indicators."""
        text_upper = text.upper()
        indicators = []

        # Look for company names near common indicators
        for indicator in self.SUPPLIER_INDICATORS:
            matches = re.findall(indicator, text_upper)
            if matches:
                indicators.extend(matches)

        # Try to extract company name from first lines
        lines = text.split('\n')[:15]
        supplier_name = ""

        for line in lines:
            line = line.strip()
            # Skip short lines or lines that look like headers
            if len(line) < 5 or line.isupper() and len(line) < 20:
                continue

            # Look for lines with company suffixes
            if re.search(r'\b(?:LTD|LLC|INC|CORP|CO|PVT|S\.?A\.?|A\.?S\.?|P\.?T\.?)\b', line, re.IGNORECASE):
                supplier_name = line.split('\n')[0][:60]
                break

        # Clean up supplier name
        supplier_name = re.sub(r'\s+', ' ', supplier_name).strip()

        return supplier_name, list(set(indicators))[:5]

    def _detect_field_pattern(self, text: str, patterns: List[Tuple[str, str]],
                              field_name: str) -> Optional[FieldPattern]:
        """Try to detect a field pattern from common patterns."""
        best_pattern = None
        best_confidence = 0

        for pattern, description in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            if matches:
                # Calculate confidence based on match quality
                confidence = min(1.0, len(matches) * 0.3)

                # Prefer patterns that match consistently formatted values
                unique_matches = list(set(matches[:10]))
                if len(unique_matches) < len(matches):
                    confidence += 0.2  # Bonus for repeated pattern

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_pattern = FieldPattern(
                        name=field_name,
                        pattern=pattern,
                        sample_matches=unique_matches[:5],
                        confidence=confidence,
                        field_type=self._infer_field_type(unique_matches)
                    )

        return best_pattern

    def _infer_field_type(self, samples: List[str]) -> str:
        """Infer the type of a field from sample values."""
        if not samples:
            return "text"

        sample = samples[0]

        # Check for currency
        if re.match(r'^[\d,]+\.?\d*$', sample) and ',' in str(samples):
            return "currency"

        # Check for numbers
        if re.match(r'^[\d,]+\.?\d*$', sample):
            return "number"

        # Check for codes (alphanumeric with dashes)
        if re.match(r'^[\w\-]+$', sample) and '-' in sample:
            return "code"

        return "text"

    def _detect_line_items(self, text: str) -> Optional[LineItemPattern]:
        """Detect line item pattern from the invoice."""
        lines = text.split('\n')

        # Look for lines that contain multiple fields
        candidate_patterns = []

        for i, line in enumerate(lines):
            line = line.strip()
            if len(line) < 30:
                continue

            # Count potential field types in the line
            has_code = bool(re.search(r'\b\d{2}-\d{6}\b|\b18-[\w]+\b|\b[A-Z]{2,}\d+', line))
            has_qty = bool(re.search(r'\b\d+(?:,\d{3})*\s*(?:PCS?|UNITS?|KS)', line, re.IGNORECASE))
            has_price = bool(re.search(r'\$[\d,.]+|\d+\.?\d*\s*USD', line))
            has_hs = bool(re.search(r'\d{4}\.\d{2}\.\d{4}', line))

            field_count = sum([has_code, has_qty, has_price, has_hs])

            if field_count >= 2:
                candidate_patterns.append({
                    'line': line,
                    'index': i,
                    'fields': field_count,
                    'has_code': has_code,
                    'has_qty': has_qty,
                    'has_price': has_price,
                    'has_hs': has_hs,
                })

        if not candidate_patterns:
            return None

        # Find the most common pattern
        best_candidate = max(candidate_patterns, key=lambda x: x['fields'])

        # Build pattern from the best candidate
        pattern_parts = []
        field_names = []

        if best_candidate['has_code']:
            # Try to identify the code format
            code_match = re.search(r'(\d{2}-\d{6})', best_candidate['line'])
            if code_match:
                pattern_parts.append(r'(\d{2}-\d{6})')
                field_names.append('part_number')
            else:
                code_match = re.search(r'(18-[\w]+)', best_candidate['line'])
                if code_match:
                    pattern_parts.append(r'(18-[\w]+)')
                    field_names.append('part_number')

        if best_candidate['has_qty']:
            pattern_parts.append(r'(\d+(?:,\d{3})*)\s*(?:PCS?|UNITS?|KS)?')
            field_names.append('quantity')

        if best_candidate['has_hs']:
            pattern_parts.append(r'(\d{4}\.\d{2}\.\d{4})')
            field_names.append('hs_code')

        if best_candidate['has_price']:
            pattern_parts.append(r'\$?([\d,.]+)')
            field_names.append('total_price')

        if pattern_parts:
            # Join with flexible whitespace
            full_pattern = r'\s+'.join(pattern_parts)

            # Test the pattern
            matches = re.findall(full_pattern, text, re.IGNORECASE)

            return LineItemPattern(
                pattern=full_pattern,
                field_names=field_names,
                sample_matches=[dict(zip(field_names, m)) for m in matches[:5]],
                confidence=min(1.0, len(matches) * 0.2)
            )

        return None

    def generate_template(self, template_name: str, output_dir: str = None,
                          class_name: str = None) -> str:
        """
        Generate Python template code from the analysis.

        Args:
            template_name: Name for the template file (without .py)
            output_dir: Directory to save the template (optional)
            class_name: Class name for the template (optional, auto-generated if not provided)

        Returns:
            Generated Python code as string
        """
        if not self.analysis:
            raise ValueError("No analysis available. Call analyze_pdf() first.")

        if not class_name:
            # Convert template_name to CamelCase
            class_name = ''.join(word.capitalize() for word in template_name.replace('-', '_').split('_'))
            class_name += 'Template'

        # Generate the template code
        code = self._generate_template_code(template_name, class_name)

        # Optionally save to file
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            file_path = os.path.join(output_dir, f"{template_name}.py")
            with open(file_path, 'w') as f:
                f.write(code)
            print(f"Template saved to: {file_path}")

        return code

    def _generate_template_code(self, template_name: str, class_name: str) -> str:
        """Generate the actual Python template code."""
        analysis = self.analysis

        # Build supplier indicators for can_process
        indicators = []
        if analysis.supplier_name:
            indicators.append(analysis.supplier_name.lower()[:30])
        for ind in analysis.supplier_indicators[:3]:
            indicators.append(ind.lower())

        # Format patterns
        inv_pattern = analysis.invoice_number_pattern.pattern if analysis.invoice_number_pattern else r'INVOICE\\s*#?\\s*:?\\s*([\\w\\-/]+)'
        proj_pattern = analysis.project_number_pattern.pattern if analysis.project_number_pattern else r'PO\\.?\\s*#?\\s*:?\\s*(\\d+)'

        # Line item pattern
        if analysis.line_item_pattern:
            line_pattern = analysis.line_item_pattern.pattern
            line_fields = analysis.line_item_pattern.field_names
        else:
            line_pattern = r'([A-Z0-9][\\w\\-]+)\\s+(\\d+)\\s+\\$?([\\d,.]+)'
            line_fields = ['part_number', 'quantity', 'total_price']

        # Extra columns
        extra_cols = list(analysis.extra_fields.keys())

        code = f'''"""
{class_name} - Invoice template for {analysis.supplier_name or template_name}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

import re
from typing import List, Dict
from .base_template import BaseTemplate


class {class_name}(BaseTemplate):
    """
    Invoice template for {analysis.supplier_name or template_name}.
    Generated by Template Generator.
    """

    name = "{template_name.replace('_', ' ').title()}"
    description = "Commercial Invoice"
    client = "{analysis.supplier_name or template_name}"
    version = "1.0.0"
    enabled = True

    extra_columns = {repr(extra_cols)}

    def can_process(self, text: str) -> bool:
        """Check if this template can process the invoice."""
        text_lower = text.lower()
        indicators = {repr(indicators)}
        return any(ind in text_lower for ind in indicators)

    def get_confidence_score(self, text: str) -> float:
        """Return confidence score for template matching."""
        if not self.can_process(text):
            return 0.0

        score = 0.5
        text_lower = text.lower()

        # Add confidence based on multiple indicators
        indicators = {repr(indicators)}
        for ind in indicators:
            if ind in text_lower:
                score += 0.15

        # Check for invoice pattern
        if re.search(r'{inv_pattern}', text, re.IGNORECASE):
            score += 0.1

        return min(score, 1.0)

    def extract_invoice_number(self, text: str) -> str:
        """Extract invoice number."""
        pattern = r'{inv_pattern}'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip() if match.lastindex else match.group(0).strip()
        return "UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        """Extract project number."""
        pattern = r'{proj_pattern}'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip() if match.lastindex else match.group(0).strip()
        return "UNKNOWN"

    def extract_manufacturer_name(self, text: str) -> str:
        """Extract manufacturer name."""
        return "{analysis.supplier_name or ''}"

    def extract_line_items(self, text: str) -> List[Dict]:
        """Extract line items from invoice."""
        line_items = []
        seen_items = set()

        # Line item pattern
        pattern = re.compile(r'{line_pattern}', re.MULTILINE | re.IGNORECASE)

        for match in pattern.finditer(text):
            try:
                groups = match.groups()
                {self._generate_field_extraction(line_fields)}

                # Clean numeric values
                quantity = re.sub(r'[^\\d.]', '', str(quantity))
                total_price = re.sub(r'[^\\d.]', '', str(total_price))

                # Deduplication
                item_key = f"{{part_number}}_{{quantity}}_{{total_price}}"
                if item_key not in seen_items and part_number:
                    seen_items.add(item_key)

                    qty = float(quantity) if quantity else 1
                    price = float(total_price) if total_price else 0
                    unit_price = price / qty if qty > 0 else price

                    line_items.append({{
                        'part_number': part_number,
                        'quantity': quantity,
                        'total_price': total_price,
                        'unit_price': f"{{unit_price:.2f}}",
                    }})

            except (ValueError, IndexError):
                continue

        return line_items

    def is_packing_list(self, text: str) -> bool:
        """Check if document is a packing list."""
        text_lower = text.lower()
        if 'packing list' in text_lower or 'packing slip' in text_lower:
            if 'invoice' not in text_lower:
                return True
        return False
'''
        return code

    def _generate_field_extraction(self, field_names: List[str]) -> str:
        """Generate field extraction code for line items."""
        lines = []
        for i, field in enumerate(field_names):
            lines.append(f"{field} = groups[{i}] if len(groups) > {i} else ''")
        return '\n                '.join(lines)

    def print_analysis(self):
        """Print a summary of the analysis."""
        if not self.analysis:
            print("No analysis available. Call analyze_pdf() first.")
            return

        a = self.analysis

        print("\n" + "="*60)
        print("INVOICE ANALYSIS SUMMARY")
        print("="*60)

        print(f"\nSupplier: {a.supplier_name or 'Unknown'}")
        print(f"Indicators: {', '.join(a.supplier_indicators) or 'None detected'}")

        if a.invoice_number_pattern:
            print(f"\nInvoice # Pattern: {a.invoice_number_pattern.pattern}")
            print(f"  Samples: {a.invoice_number_pattern.sample_matches}")
            print(f"  Confidence: {a.invoice_number_pattern.confidence:.2f}")

        if a.project_number_pattern:
            print(f"\nProject/PO Pattern: {a.project_number_pattern.pattern}")
            print(f"  Samples: {a.project_number_pattern.sample_matches}")
            print(f"  Confidence: {a.project_number_pattern.confidence:.2f}")

        if a.line_item_pattern:
            print(f"\nLine Item Pattern: {a.line_item_pattern.pattern}")
            print(f"  Fields: {a.line_item_pattern.field_names}")
            print(f"  Samples: {a.line_item_pattern.sample_matches[:2]}")
            print(f"  Confidence: {a.line_item_pattern.confidence:.2f}")

        if a.extra_fields:
            print(f"\nExtra Fields Detected:")
            for name, pattern in a.extra_fields.items():
                print(f"  {name}: {pattern.sample_matches[:3]}")

        print("\nSample Lines:")
        for line in a.sample_lines[:10]:
            print(f"  {line[:80]}")

        print("="*60)


def main():
    """Command-line interface for template generator."""
    import argparse

    parser = argparse.ArgumentParser(description='Generate invoice templates from PDF samples')
    parser.add_argument('pdf_path', help='Path to sample PDF invoice')
    parser.add_argument('--name', '-n', help='Template name', default='new_template')
    parser.add_argument('--output', '-o', help='Output directory', default=None)
    parser.add_argument('--analyze-only', '-a', action='store_true', help='Only analyze, do not generate')

    args = parser.parse_args()

    generator = TemplateGenerator()

    print(f"Analyzing: {args.pdf_path}")
    generator.analyze_pdf(args.pdf_path)
    generator.print_analysis()

    if not args.analyze_only:
        code = generator.generate_template(args.name, output_dir=args.output)
        if not args.output:
            print("\n" + "="*60)
            print("GENERATED TEMPLATE CODE")
            print("="*60)
            print(code)


if __name__ == '__main__':
    main()
