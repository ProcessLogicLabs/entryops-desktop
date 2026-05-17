"""
Sample Template - Use as a starting point for new invoice formats
Copy this file and modify for your specific invoice format.
"""

import re
from typing import List, Dict
from .base_template import BaseTemplate


class SampleTemplate(BaseTemplate):
    """
    Sample template demonstrating how to create a new invoice template.
    
    INSTRUCTIONS:
    1. Copy this file and rename it (e.g., 'acme_corp.py')
    2. Rename the class (e.g., 'AcmeCorpTemplate')
    3. Update the metadata (name, description, client, version)
    4. Implement the can_process() method to identify your invoice format
    5. Implement extraction methods for invoice_number, project_number, and line_items
    6. Add any extra columns your format provides
    7. Register in templates/__init__.py:
       
       from .acme_corp import AcmeCorpTemplate
       
       TEMPLATE_REGISTRY = {
           ...existing templates...
           'acme_corp': AcmeCorpTemplate,
       }
    """
    
    # === METADATA - Update these for your template ===
    name = "Sample Template"
    description = "Sample template - not for production use"
    client = "Sample Client"
    version = "1.0.0"
    
    # Disable by default (this is just a sample)
    enabled = False
    
    # Define any additional columns your template extracts
    # Standard columns (invoice_number, project_number, part_number, quantity, total_price)
    # are always included
    extra_columns = [
        # 'net_weight',  # Item/invoice weight in kg (can be populated from BOL)
        # 'bol_gross_weight',  # Total BOL shipment weight in kg (for proration)
        # 'unit_price',
        # 'tax_rate',
        # 'custom_field'
    ]
    
    def can_process(self, text: str) -> bool:
        """
        Check if this template can process the given PDF text.
        
        Look for unique identifiers in your invoice format:
        - Company name
        - Specific field labels
        - Document format markers
        
        Returns True if this template should be used.
        """
        # Example: Check for company name and invoice format markers
        indicators = [
            'sample company' in text.lower(),
            'invoice #' in text.lower(),
        ]
        return all(indicators)
    
    def get_confidence_score(self, text: str) -> float:
        """
        Return confidence score (0.0 to 1.0) for how well this matches.
        Higher scores win when multiple templates match.
        """
        if not self.can_process(text):
            return 0.0
        
        score = 0.5
        # Add points for additional markers
        if 'specific marker' in text.lower():
            score += 0.2
        return min(score, 1.0)
    
    def extract_invoice_number(self, text: str) -> str:
        """
        Extract the invoice number from your invoice format.
        
        Common patterns:
        - "Invoice #: 12345"
        - "Invoice Number: INV-2024-001"
        - "Ref: ABC123"
        """
        patterns = [
            r'Invoice\s*#\s*:?\s*(\w+)',
            r'Invoice\s+Number\s*:?\s*(\w+)',
            r'Ref\s*:?\s*(\w+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return "UNKNOWN"
    
    def extract_project_number(self, text: str) -> str:
        """
        Extract the project/PO number from your invoice format.
        """
        patterns = [
            r'Project\s*:?\s*(\w+)',
            r'PO\s*#?\s*:?\s*(\w+)',
            r'Order\s*:?\s*(\w+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return "UNKNOWN"
    
    def extract_line_items(self, text: str) -> List[Dict]:
        """
        Extract line items from your invoice format.
        
        Each item dict must include at minimum:
        - part_number: str
        - quantity: str (numeric)
        - total_price: str (numeric, typically in USD)
        
        Add any fields listed in extra_columns.
        """
        line_items = []
        seen_items = set()  # For deduplication
        
        lines = text.split('\n')
        
        # Example pattern - customize for your format
        # This example expects: "PART-123    10    $99.99"
        line_pattern = re.compile(
            r'^([A-Z0-9\-]+)\s+'      # Part number
            r'(\d+(?:\.\d+)?)\s+'      # Quantity
            r'\$?([\d,]+\.?\d*)',      # Price
            re.IGNORECASE
        )
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            match = line_pattern.match(line)
            if match:
                part_number = match.group(1)
                quantity = match.group(2)
                price = match.group(3).replace(',', '')
                
                # Create unique key for deduplication
                item_key = f"{part_number}_{quantity}_{price}"
                if item_key not in seen_items:
                    seen_items.add(item_key)
                    line_items.append({
                        'part_number': part_number,
                        'quantity': quantity,
                        'total_price': price,
                        # Add extra columns here:
                        # 'unit_price': unit_price,
                    })
        
        return line_items
    
    def is_packing_list(self, text: str) -> bool:
        """
        Check if this document is a packing list (should be skipped).
        Override if your format has packing lists.
        """
        return 'packing list' in text.lower() or 'packing slip' in text.lower()
