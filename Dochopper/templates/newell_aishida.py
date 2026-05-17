"""
NewellAishidaTemplate - Invoice template for Aishida Co., Ltd. → Newell Brands.
Commercial invoices for non-stick cookware shipped from China.
"""

import re
from typing import List, Dict
from .base_template import BaseTemplate


class NewellAishidaTemplate(BaseTemplate):
    """
    Invoice template for Aishida Co., Ltd. commercial invoices to Newell Brands
    (via Sunbeam Products, Inc.).
    Handles cookware invoices with PO number, item number, description, qty SETS, USD prices.
    Each line includes HS tariff and container number.

    Supports both pdfplumber and PyMuPDF text extraction formats.
    Also extracts Section 232 aluminum/steel metal content data when present.
    """

    name = "Newell Brands - Aishida"
    description = "Commercial Invoice - Non-Stick Cookware"
    client = "Newell Brands"
    version = "2.0.0"
    enabled = True

    extra_columns = ['description', 'unit_price', 'currency', 'country', 'hts_code',
                     'po_number', 'po_line', 'container_no', 'originating_doc']

    # Section 232 data extracted during processing (sku -> {aluminum_pct, steel_pct, ...})
    _section_232_updates: dict = {}

    def can_process(self, text: str) -> bool:
        """Check if this template can process the invoice."""
        text_lower = text.lower()
        has_aishida = 'aishida' in text_lower
        has_invoice = 'commercial invoice' in text_lower
        has_newell = 'newell' in text_lower or 'sunbeam' in text_lower
        return has_aishida and has_invoice and has_newell

    def get_confidence_score(self, text: str) -> float:
        """Return confidence score for template matching."""
        if not self.can_process(text):
            return 0.0

        score = 0.5
        text_lower = text.lower()

        if 'aishida co., ltd' in text_lower or 'aishida co.,ltd' in text_lower:
            score += 0.2
        if 'sunbeam products' in text_lower:
            score += 0.1
        if 'newell brands' in text_lower:
            score += 0.05
        if 'fob ningbo' in text_lower:
            score += 0.05
        if re.search(r'MG\s+Z\d{4}-\d{3}/\d{2}', text):
            score += 0.1

        return min(score, 1.0)

    def extract_invoice_number(self, text: str) -> str:
        """Extract invoice number (MG ZXXXX-XXX/XX format)."""
        match = re.search(r'(MG\s+Z\d{4}-\d{3}/\d{2})', text)
        if match:
            return match.group(1).strip()
        # Fallback: look for Invoice Number label
        match = re.search(r'Invoice\s+Number\s*:?\s*([\w\s\-/]+?)(?:\n|$)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return "UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        """Extract PO number(s) from the invoice."""
        # Look for 10-digit PO numbers in the line items area
        matches = re.findall(r'(450\d{7})', text)
        if matches:
            return ', '.join(dict.fromkeys(matches))
        return "UNKNOWN"

    def extract_manufacturer_name(self, text: str) -> str:
        """Extract manufacturer name."""
        return "AISHIDA CO., LTD"

    def extract_line_items(self, text: str) -> List[Dict]:
        """Extract line items from invoice text.

        pdfplumber format (single line per item):
        4504479135 00030 2172347 PREMIER NS 13PC SET RBT13 406 SETS $88.36 $35,874.16 8000400401 7615103025 TCNU3814963

        PyMuPDF format may split fields across lines.
        """
        items = self._extract_pdfplumber_format(text)
        if items:
            return items
        return self._extract_pymupdf_format(text)

    def _extract_pdfplumber_format(self, text: str) -> List[Dict]:
        r"""Extract items from pdfplumber text format.

        Each line: PO(10) POLine(5) ItemNo(7) Description Qty UNIT $UnitPrice $Total OrigDoc(10) HSTariff(10) ContainerNo

        pdfplumber may concatenate adjacent numeric columns when their visual
        spacing is tight — observed in PDF 4296966 where PO + POLine merged
        into a single 15-digit run (`450448970700030`) with no whitespace.
        Use `\s*` between PO and POLine so both spaced and concatenated forms
        match. The 7-digit item number is always preceded by whitespace because
        it has its own column.
        """
        line_items = []
        seen_items = set()

        # Pattern matches the full line item format. Use re.DOTALL so the
        # description capture (.*?) can span newlines, since pdfplumber
        # sometimes wraps a long description onto the line ABOVE the data row.
        pattern = re.compile(
            r'(\d{10})\s*'              # PO number — `\s*` because pdfplumber
            r'(\d{5})\s+'              # PO line     may concat with PO line
            r'(\d{7})\s+'              # Item number
            r'(.*?)'                   # Description (may span lines, may be empty)
            r'(\d[\d,]+)\s*'           # Quantity (1+ digits, optional space before unit)
            r'(SETS?|PCS?|UN(?:IT)?S?|EA|CTN?S?)\s+'  # UOM
            r'\$\s*([\d,]+\.?\d*)\s+'  # Unit price
            r'\$([\d,]+\.\d{2})\s+'   # Total amount
            r'(\d{10})\s+'            # Originating document
            r'(\d{10})\s+'            # HS tariff
            r'([A-Z]{4}\d{7})',       # Container number
            re.IGNORECASE | re.DOTALL
        )

        # Pre-split text into lines for the orphan-description lookup below.
        text_lines = text.split('\n')
        line_starts = []
        running = 0
        for ln in text_lines:
            line_starts.append(running)
            running += len(ln) + 1  # +1 for the '\n' joiner

        def _line_index_for_offset(offset: int) -> int:
            # Binary-search-ish: find the line that contains this character offset.
            for i in range(len(line_starts) - 1, -1, -1):
                if line_starts[i] <= offset:
                    return i
            return 0

        # Lines that look like headers / table noise — skip these when
        # backfilling an empty description from the prior line.
        _SKIP_PREV_LINE = re.compile(
            r'(NON\s*-?\s*STICK|COMMERCIAL\s+INVOICE|PACKING\s+LIST|TOTAL|'
            r'^\s*$|^\s*Page\b|Country of origin|HS\s*Tariff|Container)',
            re.IGNORECASE
        )

        for match in pattern.finditer(text):
            po_number = match.group(1)
            po_line = match.group(2)
            item_number = match.group(3)
            description = ' '.join(match.group(4).split()).strip()
            quantity = match.group(5).replace(',', '')
            quantity_unit = match.group(6).upper()
            unit_price = match.group(7).replace(',', '')
            total_price = match.group(8).replace(',', '')
            originating_doc = match.group(9)
            hts_code = match.group(10)
            container_no = match.group(11)

            # If pdfplumber wrapped a long description onto the line ABOVE
            # the data row (and possibly continued onto the line BELOW), our
            # main regex captures empty. Look at neighbouring lines and stitch
            # the description back together. Observed in PDF 4296966 with
            # "PREM COOK CER 8PC SET BX RDA8 MD" split across 3 lines.
            if not description:
                match_line_idx = _line_index_for_offset(match.start())
                # Collect candidate fragments from the previous line and the
                # line right after the data row (only if it looks like a short
                # word/abbreviation continuation, not a fresh row).
                fragments = []
                if match_line_idx > 0:
                    prev = text_lines[match_line_idx - 1].strip()
                    if prev and not _SKIP_PREV_LINE.search(prev) \
                            and not re.match(r'^\d{10}', prev):
                        fragments.append(prev)
                if match_line_idx + 1 < len(text_lines):
                    nxt = text_lines[match_line_idx + 1].strip()
                    # Only stitch if the line is short (e.g., trailing token like "MD")
                    # AND doesn't look like a new data row.
                    if 0 < len(nxt) <= 6 and not re.match(r'^\d{10}', nxt) \
                            and not _SKIP_PREV_LINE.search(nxt):
                        fragments.append(nxt)
                if fragments:
                    description = ' '.join(fragments)

            item_key = f"{item_number}_{quantity}_{container_no}"
            if item_key not in seen_items:
                seen_items.add(item_key)
                line_items.append({
                    'part_number': item_number,
                    'description': description,
                    'quantity': quantity,
                    'quantity_unit': quantity_unit,
                    'total_price': total_price,
                    'unit_price': unit_price,
                    'currency': 'USD',
                    'country': 'CHINA',
                    'hts_code': hts_code,
                    'po_number': po_number,
                    'po_line': po_line,
                    'container_no': container_no,
                    'originating_doc': originating_doc,
                })

        return line_items

    def _extract_pymupdf_format(self, text: str) -> List[Dict]:
        """Extract items from PyMuPDF text format (fields may be on separate lines).

        Fallback: look for item number + quantity + dollar amount patterns.
        """
        line_items = []
        seen_items = set()
        lines = text.split('\n')

        # In PyMuPDF format, look for lines that start with a 10-digit PO number
        # followed by a 5-digit PO line on the same or next line
        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Try to find PO number + PO line + Item number on a single line
            match = re.match(r'^(\d{10})\s+(\d{5})\s+(\d{7})\s+(.+)', line)
            if match:
                po_number = match.group(1)
                po_line = match.group(2)
                item_number = match.group(3)
                rest = match.group(4).strip()

                # Parse the rest of the line for description, qty, prices
                item = self._parse_item_rest(rest, po_number, po_line, item_number, lines, i)
                if item:
                    item_key = f"{item['part_number']}_{item['quantity']}_{item.get('container_no', '')}"
                    if item_key not in seen_items:
                        seen_items.add(item_key)
                        line_items.append(item)

            i += 1

        return line_items

    def _parse_item_rest(self, rest: str, po_number: str, po_line: str,
                         item_number: str, lines: List[str], line_idx: int) -> Dict:
        """Parse the remaining portion of a line item after PO/Line/Item."""
        # Try to extract: Description Qty UNIT $UnitPrice $Total OrigDoc HSTariff Container
        match = re.search(
            r'(.+?)\s+(\d[\d,]*)\s+'
            r'(SETS?|PCS?|UN(?:IT)?S?|EA|CTN?S?)\s+'
            r'\$\s*([\d,]+\.?\d*)\s+'
            r'\$([\d,]+\.\d{2})\s+'
            r'(\d{10})\s+'
            r'(\d{10})\s+'
            r'([A-Z]{4}\d{7})',
            rest, re.IGNORECASE
        )
        if match:
            return {
                'part_number': item_number,
                'description': match.group(1).strip(),
                'quantity': match.group(2).replace(',', ''),
                'quantity_unit': match.group(3).upper(),
                'total_price': match.group(5).replace(',', ''),
                'unit_price': match.group(4).replace(',', ''),
                'currency': 'USD',
                'country': 'CHINA',
                'hts_code': match.group(7),
                'po_number': po_number,
                'po_line': po_line,
                'container_no': match.group(8),
                'originating_doc': match.group(6),
            }

        # Simpler fallback: just find qty + dollar amounts
        match = re.search(
            r'(.+?)\s+(\d[\d,]*)\s+(SETS?|PCS?|UN(?:IT)?S?|EA|CTN?S?)\s+\$\s*([\d,]+\.?\d*)\s+\$([\d,]+\.\d{2})',
            rest, re.IGNORECASE
        )
        if match:
            return {
                'part_number': item_number,
                'description': match.group(1).strip(),
                'quantity': match.group(2).replace(',', ''),
                'quantity_unit': match.group(3).upper(),
                'total_price': match.group(5).replace(',', ''),
                'unit_price': match.group(4).replace(',', ''),
                'currency': 'USD',
                'country': 'CHINA',
                'po_number': po_number,
                'po_line': po_line,
            }

        return {}

    def extract_all(self, text: str, tables=None):
        """Override to also extract Section 232 metal content data from declaration tables."""
        invoice_number, project_number, items = super().extract_all(text, tables)
        self._section_232_updates = {}
        if tables:
            self._section_232_updates = self._parse_section_232_tables(tables)
        return invoice_number, project_number, items

    def _parse_section_232_tables(self, tables: list) -> dict:
        """Parse Section 232 aluminum and steel declaration tables.

        Extracts raw per-unit dollar values from the form instead of calculating
        percentages. The enrichment pipeline uses these values × quantity to
        split invoice lines into metal vs non-metal portions.

        Aluminum form (14 cols): col1=sku, col4=primary_smelt, col5=secondary_smelt,
            col6=recent_cast, col7=po_value, col8=acq_cost_aluminum,
            col9=non_metal_cost, col10=aluminum_kg
        Steel form (12 cols): col1=sku, col4=where_melted, col5=po_value,
            col6=acq_cost_steel, col7=non_metal_cost, col8=steel_kg

        Returns:
            dict: {sku: {'acq_cost_aluminum': float, 'po_value': float,
                         'non_metal_cost': float, 'aluminum_kg': str,
                         'country_of_smelt': str, ...}}
        """
        updates = {}

        def _safe_float(val):
            if val is None:
                return None
            cleaned = str(val).replace('$', '').replace(',', '').strip()
            if not cleaned:
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None

        for table in tables:
            if not table or len(table) < 2:
                continue
            header = table[0]
            if not header:
                continue
            header_text = ' '.join(str(c or '').lower() for c in header)

            # Must have Sku/Material column to be a 232 form
            if 'sku' not in header_text and 'material' not in header_text:
                continue

            ncols = len(header)
            is_aluminum = ncols >= 13 and ('aluminum' in header_text or 'alumin' in header_text)
            is_steel = 'steel' in header_text

            if not is_aluminum and not is_steel:
                continue

            for row in table[1:]:
                if not row or len(row) < 6:
                    continue
                sku = str(row[1] or '').strip()
                if not sku or not re.match(r'^\d{5,8}$', sku):
                    continue

                try:
                    if is_aluminum and ncols >= 13:
                        # Aluminum form column mapping:
                        # col4=primary smelt, col5=secondary smelt, col6=most recent cast
                        # col7=PO value per unit, col8=acq cost aluminum per unit
                        # col9=non-metal cost per unit, col10=aluminum kg
                        po_val = _safe_float(row[7])
                        acq_cost = _safe_float(row[8])
                        non_metal = _safe_float(row[9])
                        primary_smelt = str(row[4] or '').strip()
                        secondary_smelt = str(row[5] or '').strip() if len(row) > 5 else ''
                        recent_cast = str(row[6] or '').strip() if len(row) > 6 else ''
                        al_kg = str(row[10] or '').strip()
                        if po_val and po_val > 0 and acq_cost is not None:
                            if sku not in updates:
                                updates[sku] = {}
                            updates[sku]['acq_cost_aluminum'] = acq_cost
                            updates[sku]['po_value'] = po_val
                            if non_metal is not None:
                                updates[sku]['non_metal_cost'] = non_metal
                            else:
                                updates[sku]['non_metal_cost'] = round(po_val - acq_cost, 2)
                            updates[sku]['country_of_smelt'] = primary_smelt
                            if secondary_smelt:
                                updates[sku]['country_of_smelt_secondary'] = secondary_smelt
                            if recent_cast:
                                updates[sku]['country_of_cast'] = recent_cast
                            if al_kg:
                                updates[sku]['aluminum_kg'] = al_kg

                    elif is_steel and ncols >= 9:
                        # Steel form column mapping:
                        # col4=where originally melted and poured
                        # col5=PO value per unit, col6=acq cost steel per unit
                        # col7=non-metal cost per unit, col8=steel kg
                        po_val = _safe_float(row[5])
                        acq_cost = _safe_float(row[6])
                        non_metal = _safe_float(row[7])
                        melt_country = str(row[4] or '').strip()
                        st_kg = str(row[8] or '').strip()
                        if po_val and po_val > 0 and acq_cost is not None:
                            if sku not in updates:
                                updates[sku] = {}
                            updates[sku]['acq_cost_steel'] = acq_cost
                            updates[sku]['po_value'] = po_val
                            if non_metal is not None:
                                updates[sku]['non_metal_cost'] = non_metal
                            else:
                                updates[sku]['non_metal_cost'] = round(po_val - acq_cost, 2)
                            updates[sku]['country_of_melt'] = melt_country
                            if st_kg:
                                updates[sku]['steel_kg'] = st_kg
                except (ValueError, TypeError, IndexError):
                    continue

        return updates

    def is_packing_list(self, text: str) -> bool:
        """Check if document is a packing list (should be skipped).

        For multi-page doc sets, the full text may contain both commercial invoice
        and packing list/manifest pages. If commercial invoice is present,
        this is NOT a packing list — the processor should extract from the invoice.
        """
        text_lower = text.lower()
        # If commercial invoice text is present, always process (not a packing list)
        if 'commercial invoice' in text_lower:
            return False
        # Only skip if no commercial invoice found
        if 'packing list' in text_lower:
            return True
        if 'manifest' in text_lower and 'dhl order management' in text_lower:
            return True
        if 'fcr no' in text_lower:
            return True
        if 'waybill' in text_lower:
            return True
        if 'container inspection' in text_lower:
            return True
        if 'section 232' in text_lower:
            return True
        return False
