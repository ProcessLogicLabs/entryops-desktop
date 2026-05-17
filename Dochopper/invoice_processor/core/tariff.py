"""
Section 232 tariff lookup functionality.

This module provides tariff classification lookups for customs processing,
supporting both database-backed lookups and in-memory data.
"""

import pandas as pd
from typing import Optional, Tuple, Dict, Any


class TariffLookup:
    """
    Section 232 tariff lookup engine.

    Can be initialized with either:
    - A pandas DataFrame containing tariff data
    - A SQLite database path
    - A dictionary of HTS code -> tariff info mappings

    Example:
        # From DataFrame
        tariff = TariffLookup(tariff_df)
        material, dec_code, smelt_flag = tariff.get_info("7208.10.0000")

        # From database
        tariff = TariffLookup.from_database("path/to/db.sqlite")
    """

    def __init__(self, tariff_data: Optional[pd.DataFrame] = None):
        """
        Initialize TariffLookup with tariff data.

        Args:
            tariff_data: DataFrame with columns: hts_code, material, declaration_required
                         If None, lookups will return empty results.
        """
        self._data: Dict[str, Dict[str, Any]] = {}

        if tariff_data is not None and not tariff_data.empty:
            self._load_from_dataframe(tariff_data)

    def _load_from_dataframe(self, df: pd.DataFrame) -> None:
        """Load tariff data from a DataFrame into internal lookup dict."""
        for _, row in df.iterrows():
            hts_code = str(row.get('hts_code', '')).replace(".", "").strip().upper()
            if hts_code:
                self._data[hts_code] = {
                    'material': row.get('material', ''),
                    'declaration_required': row.get('declaration_required', ''),
                }

    @classmethod
    def from_database(cls, db_path: str, table_name: str = 'tariff_232') -> 'TariffLookup':
        """
        Create TariffLookup from a SQLite database.

        Args:
            db_path: Path to SQLite database file
            table_name: Name of tariff table (default: 'tariff_232')

        Returns:
            TariffLookup instance populated with database data
        """
        import sqlite3

        try:
            conn = sqlite3.connect(db_path)
            df = pd.read_sql(f"SELECT hts_code, material, declaration_required FROM {table_name}", conn)
            conn.close()
            return cls(df)
        except Exception as e:
            # Return empty lookup if database read fails
            return cls(None)

    @classmethod
    def from_dict(cls, data: Dict[str, Dict[str, Any]]) -> 'TariffLookup':
        """
        Create TariffLookup from a dictionary.

        Args:
            data: Dict mapping HTS codes to {'material': str, 'declaration_required': str}

        Returns:
            TariffLookup instance
        """
        instance = cls(None)
        instance._data = {
            k.replace(".", "").strip().upper(): v
            for k, v in data.items()
        }
        return instance

    def get_info(self, hts_code: str) -> Tuple[Optional[str], str, str]:
        """
        Lookup Section 232 tariff information for an HTS code.

        Args:
            hts_code: HTS code string (with or without dots)

        Returns:
            Tuple of (material, declaration_code, smelt_flag) where:
            - material: Material type (e.g., "Steel", "Aluminum") or None
            - declaration_code: Tariff code (e.g., "08" for Steel)
            - smelt_flag: "Y" for materials requiring smelting declaration, "" otherwise
        """
        if not hts_code:
            return None, "", ""

        # Normalize HTS code: remove dots, strip whitespace, convert to uppercase
        hts_clean = str(hts_code).replace(".", "").strip().upper()
        hts_8 = hts_clean[:8]
        hts_10 = hts_clean[:10]

        # Try 10-digit match first, then 8-digit
        row = self._data.get(hts_10) or self._data.get(hts_8)

        if row:
            material = row.get('material', '')
            dec_code = row.get('declaration_required', '')
            dec_type = dec_code.split(" - ")[0] if " - " in dec_code else dec_code
            smelt_flag = "Y" if material in ["Aluminum", "Wood", "Copper"] else ""
            return material, dec_type, smelt_flag

        return None, "", ""

    def __len__(self) -> int:
        """Return number of HTS codes in lookup."""
        return len(self._data)

    def __contains__(self, hts_code: str) -> bool:
        """Check if HTS code exists in lookup."""
        hts_clean = str(hts_code).replace(".", "").strip().upper()
        return hts_clean[:10] in self._data or hts_clean[:8] in self._data


def get_232_info(
    hts_code: str,
    tariff_data: Optional[pd.DataFrame] = None,
    db_path: Optional[str] = None
) -> Tuple[Optional[str], str, str]:
    """
    Standalone function to lookup Section 232 tariff information.

    This is a convenience function that creates a temporary TariffLookup.
    For repeated lookups, create a TariffLookup instance instead.

    Args:
        hts_code: HTS code string (with or without dots)
        tariff_data: Optional DataFrame with tariff data
        db_path: Optional path to SQLite database with tariff_232 table

    Returns:
        Tuple of (material, declaration_code, smelt_flag)
    """
    if tariff_data is not None:
        lookup = TariffLookup(tariff_data)
    elif db_path:
        lookup = TariffLookup.from_database(db_path)
    else:
        return None, "", ""

    return lookup.get_info(hts_code)
