"""
Invoice Processor - Portable invoice processing module for customs documentation.

This module provides functionality for:
- Processing invoice data with Section 232 material ratio expansion
- Weight and quantity calculations
- Excel export with material type styling
- Section 232 tariff lookups

Example usage:
    from invoice_processor import InvoiceProcessor, ExportStyle

    # Initialize processor with tariff database
    processor = InvoiceProcessor.from_database("dochopper.db")

    # Process invoice data
    result = processor.process(invoice_df, net_weight=1000.0, mid="USABC12345")

    # Export to Excel with custom styling
    style = ExportStyle(steel_color='#333333')
    export_result = processor.export(result.data, "output.xlsx", style=style)
"""

__version__ = "0.1.0"

import pandas as pd
from pathlib import Path
from typing import Optional, List, Union, Callable, Tuple

from .core.processor import (
    process_invoice_data,
    merge_with_parts_data,
    InvoiceProcessingResult
)
from .core.exporter import (
    export_to_excel,
    export_split_by_invoice,
    ExportStyle,
    ExportResult
)
from .core.tariff import (
    TariffLookup,
    get_232_info
)


class InvoiceProcessor:
    """
    High-level interface for invoice processing and export.

    This class provides a convenient API for:
    - Loading tariff data from various sources
    - Processing invoices with material ratio expansion
    - Exporting results to formatted Excel files

    Example:
        # From database
        processor = InvoiceProcessor.from_database("path/to/db.sqlite")

        # Process invoice
        result = processor.process(df, net_weight=500.0)
        print(f"Processed {result.expanded_row_count} rows")

        # Export with styling
        processor.export(result.data, "output.xlsx")
    """

    def __init__(self, tariff_lookup: Optional[TariffLookup] = None):
        """
        Initialize InvoiceProcessor.

        Args:
            tariff_lookup: TariffLookup instance for Section 232 lookups.
                          If None, material detection will be skipped for
                          items without explicit ratio values.
        """
        self._tariff_lookup = tariff_lookup
        self._export_style = ExportStyle()

    @classmethod
    def from_database(cls, db_path: str, table_name: str = 'tariff_232') -> 'InvoiceProcessor':
        """
        Create InvoiceProcessor with tariff data from SQLite database.

        Args:
            db_path: Path to SQLite database file
            table_name: Name of tariff table (default: 'tariff_232')

        Returns:
            InvoiceProcessor instance

        Example:
            processor = InvoiceProcessor.from_database("dochopper.db")
        """
        tariff = TariffLookup.from_database(db_path, table_name)
        return cls(tariff)

    @classmethod
    def from_dataframe(cls, tariff_df: pd.DataFrame) -> 'InvoiceProcessor':
        """
        Create InvoiceProcessor with tariff data from DataFrame.

        Args:
            tariff_df: DataFrame with columns: hts_code, material, declaration_required

        Returns:
            InvoiceProcessor instance

        Example:
            tariff_data = pd.read_csv("tariff_232.csv")
            processor = InvoiceProcessor.from_dataframe(tariff_data)
        """
        tariff = TariffLookup(tariff_df)
        return cls(tariff)

    @classmethod
    def from_dict(cls, tariff_dict: dict) -> 'InvoiceProcessor':
        """
        Create InvoiceProcessor with tariff data from dictionary.

        Args:
            tariff_dict: Dict mapping HTS codes to tariff info

        Returns:
            InvoiceProcessor instance

        Example:
            tariffs = {
                "7208100000": {"material": "Steel", "declaration_required": "08"},
                "7601100000": {"material": "Aluminum", "declaration_required": "07"}
            }
            processor = InvoiceProcessor.from_dict(tariffs)
        """
        tariff = TariffLookup.from_dict(tariff_dict)
        return cls(tariff)

    @property
    def export_style(self) -> ExportStyle:
        """Get the current export style configuration."""
        return self._export_style

    @export_style.setter
    def export_style(self, style: ExportStyle):
        """Set the export style configuration."""
        self._export_style = style

    def process(
        self,
        df: pd.DataFrame,
        net_weight: float,
        mid: str = "",
        parts_df: Optional[pd.DataFrame] = None
    ) -> InvoiceProcessingResult:
        """
        Process invoice data with material ratio expansion.

        This method:
        1. Optionally merges with parts master data
        2. Expands rows based on material content ratios
        3. Calculates proportional weight distribution
        4. Computes Qty1/Qty2 based on unit type
        5. Assigns Section 232 flags and declaration codes

        Args:
            df: DataFrame with invoice data. Expected columns:
                - part_number: Part/product number (required)
                - value_usd: Line item value in USD (required)
                - hts_code: HTS tariff code (optional)
                - quantity: Piece count (optional)
                - qty_unit: Unit type - 'KG', 'NO', or 'NO/KG' (optional)
                - steel_pct: Steel content percentage 0-100 (optional)
                - aluminum_pct: Aluminum content percentage 0-100 (optional)
                - copper_pct: Copper content percentage 0-100 (optional)
                - wood_pct: Wood content percentage 0-100 (optional)
                - auto_pct: Automotive content percentage 0-100 (optional)
                - non_steel_pct: Non-232 content percentage 0-100 (optional)

            net_weight: Total net weight in kilograms to distribute

            mid: Manufacturer ID - used for country code fallback (first 2 chars)

            parts_df: Optional parts master DataFrame to merge with.
                     If provided, will update invoice data with parts database values.

        Returns:
            InvoiceProcessingResult containing processed DataFrame and metadata

        Example:
            result = processor.process(invoice_df, net_weight=1000.0, mid="USABC12345")
            print(f"Original rows: {result.original_row_count}")
            print(f"Expanded rows: {result.expanded_row_count}")
            print(f"Total value: ${result.total_value:,.2f}")
        """
        # Merge with parts data if provided
        if parts_df is not None:
            df = merge_with_parts_data(df, parts_df)

        return process_invoice_data(
            df=df,
            net_weight=net_weight,
            mid=mid,
            tariff_lookup=self._tariff_lookup
        )

    def export(
        self,
        df: pd.DataFrame,
        output_path: Union[str, Path],
        columns: Optional[List[str]] = None,
        style: Optional[ExportStyle] = None
    ) -> ExportResult:
        """
        Export processed DataFrame to Excel with styling.

        Args:
            df: DataFrame to export (typically from process() result)
            output_path: Path for the output Excel file
            columns: List of column names to export. If None, exports all columns.
            style: ExportStyle configuration. If None, uses instance default.

        Returns:
            ExportResult with success status and file information

        Example:
            result = processor.process(invoice_df, net_weight=1000.0)
            export_result = processor.export(result.data, "output.xlsx")
            if export_result.success:
                print(f"Exported to {export_result.file_path}")
        """
        return export_to_excel(
            df=df,
            output_path=output_path,
            columns=columns,
            style=style or self._export_style
        )

    def export_by_invoice(
        self,
        df: pd.DataFrame,
        output_dir: Union[str, Path],
        invoice_column: str = 'invoice_number',
        columns: Optional[List[str]] = None,
        style: Optional[ExportStyle] = None
    ) -> ExportResult:
        """
        Export DataFrame split into separate files by invoice number.

        Args:
            df: DataFrame to export
            output_dir: Directory for output files
            invoice_column: Column name containing invoice numbers
            columns: List of column names to export. If None, exports all columns.
            style: ExportStyle configuration. If None, uses instance default.

        Returns:
            ExportResult with success status and list of created files

        Example:
            result = processor.export_by_invoice(df, "output/", invoice_column='InvoiceNo')
            for file in result.files_created:
                print(f"Created: {file}")
        """
        return export_split_by_invoice(
            df=df,
            output_dir=output_dir,
            invoice_column=invoice_column,
            columns=columns,
            style=style or self._export_style
        )

    def lookup_tariff(self, hts_code: str) -> Tuple[Optional[str], str, str]:
        """
        Look up Section 232 tariff information for an HTS code.

        Args:
            hts_code: HTS code string (with or without dots)

        Returns:
            Tuple of (material, declaration_code, smelt_flag) where:
            - material: Material type (e.g., "Steel", "Aluminum") or None
            - declaration_code: Tariff code (e.g., "08" for Steel)
            - smelt_flag: "Y" for materials requiring smelting declaration

        Example:
            material, dec_code, smelt = processor.lookup_tariff("7208.10.0000")
            if material == "Steel":
                print(f"Steel item, declaration code: {dec_code}")
        """
        if self._tariff_lookup:
            return self._tariff_lookup.get_info(hts_code)
        return None, "", ""

    def __repr__(self):
        tariff_count = len(self._tariff_lookup) if self._tariff_lookup else 0
        return f"InvoiceProcessor(tariff_codes={tariff_count})"


# Public API
__all__ = [
    # Main class
    'InvoiceProcessor',
    # Data classes
    'InvoiceProcessingResult',
    'ExportResult',
    'ExportStyle',
    # Standalone functions
    'process_invoice_data',
    'export_to_excel',
    'export_split_by_invoice',
    'merge_with_parts_data',
    # Tariff utilities
    'TariffLookup',
    'get_232_info',
]
