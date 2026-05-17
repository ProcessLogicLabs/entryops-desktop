"""
Invoice processing and row expansion logic.

This module handles the core transformation of invoice data:
- Material ratio expansion (splitting rows by steel/aluminum/copper/wood/auto content)
- Weight calculations (proportional distribution)
- Quantity calculations (Qty1, Qty2 based on unit type)
- Section 232 flag assignment
"""

import pandas as pd
from typing import Optional, Dict, Any, Callable, Tuple
from .tariff import TariffLookup, get_232_info


class InvoiceProcessingResult:
    """Container for processed invoice data and metadata."""

    def __init__(
        self,
        data: pd.DataFrame,
        original_row_count: int,
        expanded_row_count: int,
        total_value: float,
        total_weight: float
    ):
        self.data = data
        self.original_row_count = original_row_count
        self.expanded_row_count = expanded_row_count
        self.total_value = total_value
        self.total_weight = total_weight

    def __repr__(self):
        return (
            f"InvoiceProcessingResult("
            f"rows={self.expanded_row_count}, "
            f"value=${self.total_value:,.2f}, "
            f"weight={self.total_weight:.2f}kg)"
        )


def process_invoice_data(
    df: pd.DataFrame,
    net_weight: float,
    mid: str = "",
    tariff_lookup: Optional[TariffLookup] = None,
    tariff_lookup_func: Optional[Callable[[str], Tuple[Optional[str], str, str]]] = None
) -> InvoiceProcessingResult:
    """
    Process invoice data with material ratio expansion and calculations.

    This function transforms raw invoice data by:
    1. Expanding rows based on material content ratios (steel, aluminum, copper, wood, auto, non-232)
    2. Calculating proportional weight distribution
    3. Computing Qty1 and Qty2 based on qty_unit type
    4. Assigning Section 232 flags and declaration codes
    5. Setting country codes from data or MID prefix

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
            - country_of_melt: Country code for melt origin (optional)
            - country_of_cast: Country code for cast origin (optional)
            - country_of_smelt: Country code for smelt origin (optional)
            - Sec301_Exclusion_Tariff: Section 301 exclusion tariff (optional)
            - invoice_number: Invoice number for split export (optional)

        net_weight: Total net weight in kilograms to distribute

        mid: Manufacturer ID - used for country code fallback (first 2 chars)

        tariff_lookup: TariffLookup instance for Section 232 lookups.
                      If None and tariff_lookup_func is None, basic material
                      detection is skipped for items without ratios set.

        tariff_lookup_func: Alternative callable for tariff lookups.
                           Signature: (hts_code) -> (material, dec_code, smelt_flag)

    Returns:
        InvoiceProcessingResult containing:
        - data: Processed DataFrame with expanded rows and calculated fields
        - original_row_count: Number of rows before expansion
        - expanded_row_count: Number of rows after expansion
        - total_value: Sum of all value_usd
        - total_weight: The net_weight parameter passed in

    Example:
        >>> from invoice_processor.core import process_invoice_data, TariffLookup
        >>> tariff = TariffLookup.from_database("dochopper.db")
        >>> result = process_invoice_data(invoice_df, net_weight=1000.0, mid="USABC12345", tariff_lookup=tariff)
        >>> result.data  # Processed DataFrame
        >>> result.expanded_row_count  # Number of output rows
    """
    df = df.copy()

    # Define the tariff lookup function to use
    def lookup_tariff(hts_code: str) -> Tuple[Optional[str], str, str]:
        if tariff_lookup_func:
            return tariff_lookup_func(hts_code)
        elif tariff_lookup:
            return tariff_lookup.get_info(hts_code)
        else:
            return None, "", ""

    # Helper function to safely get column or default
    def safe_get_column(col_name: str, default: float = 0.0) -> pd.Series:
        if col_name in df.columns:
            return pd.to_numeric(df[col_name], errors='coerce').fillna(default)
        return pd.Series([default] * len(df), index=df.index)

    # Extract material ratios (stored as percentages 0-100)
    df['SteelPercentage'] = safe_get_column('steel_pct', 0.0)
    df['AluminumPercentage'] = safe_get_column('aluminum_pct', 0.0)
    df['CopperPercentage'] = safe_get_column('copper_pct', 0.0)
    df['WoodPercentage'] = safe_get_column('wood_pct', 0.0)
    df['AutoPercentage'] = safe_get_column('auto_pct', 0.0)
    df['NonSteelPercentage'] = safe_get_column('non_steel_pct', 0.0)

    # Expand rows by material content
    original_row_count = len(df)
    expanded_rows = []

    for _, row in df.iterrows():
        steel_pct = row['SteelPercentage']
        aluminum_pct = row['AluminumPercentage']
        copper_pct = row['CopperPercentage']
        wood_pct = row['WoodPercentage']
        auto_pct = row['AutoPercentage']
        non_steel_pct = row['NonSteelPercentage']
        original_value = row['value_usd']

        # If no percentages are set, use HTS lookup to determine material type
        if steel_pct == 0 and aluminum_pct == 0 and copper_pct == 0 and wood_pct == 0 and auto_pct == 0 and non_steel_pct == 0:
            hts = row.get('hts_code', '')
            material, _, _ = lookup_tariff(hts)
            if material == 'Aluminum':
                aluminum_pct = 100.0
            elif material == 'Copper':
                copper_pct = 100.0
            elif material == 'Wood':
                wood_pct = 100.0
            elif material == 'Auto':
                auto_pct = 100.0
            elif material == 'Steel':
                steel_pct = 100.0
            else:
                # Default to 100% steel for backward compatibility
                steel_pct = 100.0

        # Create derivative rows in order: Steel, Aluminum, Copper, Wood, Auto, Non-232
        material_configs = [
            ('steel', steel_pct, 'SteelPercentage'),
            ('aluminum', aluminum_pct, 'AluminumPercentage'),
            ('copper', copper_pct, 'CopperPercentage'),
            ('wood', wood_pct, 'WoodPercentage'),
            ('auto', auto_pct, 'AutoPercentage'),
            ('non_232', non_steel_pct, 'NonSteelPercentage'),
        ]

        for content_type, pct, ratio_col in material_configs:
            if pct > 0:
                new_row = row.copy()
                new_row['value_usd'] = original_value * pct / 100.0
                # Zero out all ratios except the current one
                new_row['SteelPercentage'] = 0.0
                new_row['AluminumPercentage'] = 0.0
                new_row['CopperPercentage'] = 0.0
                new_row['WoodPercentage'] = 0.0
                new_row['AutoPercentage'] = 0.0
                new_row['NonSteelPercentage'] = 0.0
                new_row[ratio_col] = pct
                new_row['_content_type'] = content_type
                expanded_rows.append(new_row)

    # Rebuild dataframe from expanded rows
    df = pd.DataFrame(expanded_rows).reset_index(drop=True)

    # Calculate CalcWtNet based on value proportion
    total_value = df['value_usd'].sum()
    if total_value == 0:
        df['CalcWtNet'] = 0.0
    else:
        df['CalcWtNet'] = (df['value_usd'] / total_value) * net_weight

    # Calculate Qty1 and Qty2 based on qty_unit type
    df['Qty1'] = df.apply(_get_qty1, axis=1)
    df['Qty2'] = df.apply(_get_qty2, axis=1)
    df['cbp_qty'] = df['Qty1']  # Backward compatibility

    # Set HTSCode and MID
    df['HTSCode'] = df['hts_code'] if 'hts_code' in df.columns else ''
    df['MID'] = mid
    melt_default = str(mid)[:2] if mid else ''

    # Calculate derivative fields (declaration codes, country codes, flags)
    dec_type_list = []
    country_melt_list = []
    country_cast_list = []
    prim_country_smelt_list = []
    prim_smelt_flag_list = []
    flag_list = []

    for _, r in df.iterrows():
        content_type = r.get('_content_type', '')
        hts = r.get('hts_code', '')
        material, dec_type, smelt_flag = lookup_tariff(hts)

        # Set flag and declaration code based on content type
        if content_type == 'steel':
            flag = '232_Steel'
            dec_type_list.append(dec_type if dec_type else '08')
        elif content_type == 'aluminum':
            flag = '232_Aluminum'
            dec_type_list.append(dec_type if dec_type else '07')
        elif content_type == 'copper':
            flag = '232_Copper'
            dec_type_list.append(dec_type if dec_type else '11')
        elif content_type == 'wood':
            flag = '232_Wood'
            dec_type_list.append(dec_type if dec_type else '10')
        elif content_type == 'auto':
            flag = '232_Auto'
            dec_type_list.append(dec_type if dec_type else '')
        elif content_type == 'non_232':
            flag = 'Non_232'
            dec_type_list.append(dec_type)
        else:
            flag = f"232_{material}" if material else ''
            dec_type_list.append(dec_type)

        # Use imported country codes if available, otherwise fall back to MID-based default
        country_of_melt = r.get('country_of_melt', '')
        country_of_cast = r.get('country_of_cast', '')
        country_of_smelt = r.get('country_of_smelt', '')

        melt_code = country_of_melt if pd.notna(country_of_melt) and str(country_of_melt).strip() else melt_default
        cast_code = country_of_cast if pd.notna(country_of_cast) and str(country_of_cast).strip() else melt_default
        smelt_code = country_of_smelt if pd.notna(country_of_smelt) and str(country_of_smelt).strip() else melt_default

        country_melt_list.append(melt_code)
        country_cast_list.append(cast_code)
        prim_country_smelt_list.append(smelt_code)
        prim_smelt_flag_list.append(smelt_flag)
        flag_list.append(flag)

    df['DecTypeCd'] = dec_type_list
    df['CountryofMelt'] = country_melt_list
    df['CountryOfCast'] = country_cast_list
    df['PrimCountryOfSmelt'] = prim_country_smelt_list
    df['DeclarationFlag'] = prim_smelt_flag_list
    df['_232_flag'] = flag_list

    # Rename columns for output
    df['Product No'] = df['part_number']
    df['ValueUSD'] = df['value_usd']

    # Ensure optional columns exist
    if 'quantity' not in df.columns:
        df['quantity'] = ''
    if '_not_in_db' not in df.columns:
        df['_not_in_db'] = False
    if 'Sec301_Exclusion_Tariff' not in df.columns:
        df['Sec301_Exclusion_Tariff'] = ''

    return InvoiceProcessingResult(
        data=df,
        original_row_count=original_row_count,
        expanded_row_count=len(df),
        total_value=total_value,
        total_weight=net_weight
    )


# Unit type categories for Qty1/Qty2 calculation
# Weight-only units (Qty1 = weight in KG)
WEIGHT_UNITS = {'KG', 'G', 'T', 'T ADW', 'T DWB'}

# Count-only units (Qty1 = piece count)
COUNT_UNITS = {'NO', 'PCS', 'DOZ', 'DOZ. PRS', 'DZ PCS', 'GROSS', 'HUNDREDS',
               'THOUSANDS', 'PRS', 'PACK', 'DOSES', 'CARAT'}

# Dual units: first quantity is count, second is weight (Qty1 = count, Qty2 = weight)
DUAL_UNITS = {'NO. AND KG', 'NO/KG', 'NO\KG',
              'CU KG', 'CY KG', 'NI KG', 'PB KG', 'ZN KG', 'KG AMC',
              'AG G', 'AU G', 'IR G', 'OS G', 'PD G', 'PT G', 'RH G', 'RU G'}

# Volume/Area/Length units (use quantity from invoice)
MEASURE_UNITS = {'LITERS', 'PF.LITERS', 'BBL', 'M', 'LIN. M', 'M2', 'CM2', 'M3',
                 'SQUARE', 'FIBER M', 'GBQ', 'MWH', 'THOUSAND M', 'THOUSAND M3'}

# Units that should have BOTH Qty1 and Qty2 empty (measurement-only units per CBP requirements)
NO_QTY_UNITS = {'M', 'M2', 'M3'}


def _get_qty1(row: pd.Series) -> str:
    """
    Calculate Qty1 based on qty_unit type from HTS database.

    Categories:
    - Weight-only: KG, G, T -> Qty1 = CalcWtNet, Qty2 = empty
    - Count-only: NO, PCS, DOZ, etc. -> Qty1 = quantity (pieces), Qty2 = empty
    - Dual (count + weight): NO. AND KG, XX KG, XX G -> Qty1 = quantity, Qty2 = CalcWtNet
    - Other units (volume, area, length): Use quantity if available
    """
    qty_unit = str(row.get('qty_unit', '')).strip().upper() if pd.notna(row.get('qty_unit')) else ''

    if qty_unit == '':
        return ''

    # If qty_unit is in NO_QTY_UNITS, leave Qty1 empty
    if qty_unit in NO_QTY_UNITS:
        return ''

    # Weight-only units: Qty1 is net weight
    if qty_unit in WEIGHT_UNITS:
        return str(int(round(row['CalcWtNet']))) if row['CalcWtNet'] > 0 else ''

    # Count-only units: Qty1 is piece count from invoice
    if qty_unit in COUNT_UNITS:
        qty = row.get('quantity', '')
        if pd.notna(qty) and str(qty).strip():
            try:
                return str(int(float(str(qty).replace(',', '').strip())))
            except (ValueError, TypeError):
                return ''
        return ''

    # Dual units: Qty1 is piece count
    if qty_unit in DUAL_UNITS:
        qty = row.get('quantity', '')
        if pd.notna(qty) and str(qty).strip():
            try:
                return str(int(float(str(qty).replace(',', '').strip())))
            except (ValueError, TypeError):
                return ''
        return ''

    # Measure units: Use quantity from invoice if available
    if qty_unit in MEASURE_UNITS:
        qty = row.get('quantity', '')
        if pd.notna(qty) and str(qty).strip():
            try:
                return str(int(float(str(qty).replace(',', '').strip())))
            except (ValueError, TypeError):
                return ''
        return ''

    # Unknown unit type - try quantity first, fall back to empty
    qty = row.get('quantity', '')
    if pd.notna(qty) and str(qty).strip():
        try:
            return str(int(float(str(qty).replace(',', '').strip())))
        except (ValueError, TypeError):
            return ''
    return ''


def _get_qty2(row: pd.Series) -> str:
    """
    Calculate Qty2 based on qty_unit type.
    CBP requires Qty2 (weight) for ALL Section 232 material types.
    Other dual units (NO. AND KG, metal+weight) also populate Qty2 with weight.
    """
    qty_unit = str(row.get('qty_unit', '')).strip().upper() if pd.notna(row.get('qty_unit')) else ''

    # If qty_unit is in NO_QTY_UNITS, leave Qty2 empty
    if qty_unit in NO_QTY_UNITS:
        return ''

    # Get content_type safely - handle NaN, None, and various string formats
    content_type_raw = row.get('_content_type', '')
    if pd.notna(content_type_raw) and content_type_raw:
        content_type = str(content_type_raw).strip().lower()
    else:
        content_type = ''

    # Get HTS code to check material type by chapter
    hts_raw = row.get('hts_code', '')
    hts_code = str(hts_raw).replace('.', '').strip() if pd.notna(hts_raw) else ''
    hts_chapter = hts_code[:2] if len(hts_code) >= 2 else ''

    # Get CalcWtNet safely
    calc_wt = row.get('CalcWtNet', 0)
    if pd.isna(calc_wt):
        calc_wt = 0

    # CBP requires Qty2 (weight) for ALL derivative rows (including non_232)
    # This includes steel, aluminum, copper, wood, auto, AND non_232 portions
    # Also applies to items in specific HTS chapters:
    # - Aluminum = HTS Chapter 76
    # - Steel = HTS Chapters 72, 73
    # - Copper = HTS Chapter 74
    is_derivative_row = content_type in ['steel', 'aluminum', 'copper', 'wood', 'auto', 'non_232']
    is_aluminum_hts = hts_chapter == '76'
    is_steel_hts = hts_chapter in ['72', '73']
    is_copper_hts = hts_chapter == '74'

    # Include Qty2 for any derivative row OR specific HTS chapters
    if is_derivative_row or is_aluminum_hts or is_steel_hts or is_copper_hts:
        if calc_wt > 0:
            return str(int(round(calc_wt)))
        return ''

    # Dual units: Qty2 is net weight
    if qty_unit in DUAL_UNITS:
        if calc_wt > 0:
            return str(int(round(calc_wt)))
        return ''

    # All other cases: Qty2 is empty
    return ''


def merge_with_parts_data(
    invoice_df: pd.DataFrame,
    parts_df: pd.DataFrame,
    merge_column: str = 'part_number'
) -> pd.DataFrame:
    """
    Merge invoice data with parts master data.

    Args:
        invoice_df: Invoice DataFrame with part_number column
        parts_df: Parts master DataFrame with part data
        merge_column: Column to merge on (default: 'part_number')

    Returns:
        Merged DataFrame with parts data columns added
    """
    if parts_df is None or parts_df.empty:
        return invoice_df

    # Columns to take from parts database
    parts_columns = [
        'part_number', 'hts_code', 'steel_pct', 'aluminum_pct',
        'copper_pct', 'wood_pct', 'auto_pct', 'non_steel_pct',
        'qty_unit', 'country_of_melt', 'country_of_cast', 'country_of_smelt',
        'Sec301_Exclusion_Tariff'
    ]

    # Filter to available columns
    available_cols = [c for c in parts_columns if c in parts_df.columns]
    parts_subset = parts_df[available_cols].copy()

    # Merge with indicator
    merged = invoice_df.merge(
        parts_subset,
        on=merge_column,
        how='left',
        suffixes=('', '_db'),
        indicator=True
    )

    # Mark rows not found in database
    merged['_not_in_db'] = merged['_merge'] == 'left_only'
    merged = merged.drop(columns=['_merge'])

    # For columns that exist in both, prefer database value if available
    for col in ['hts_code', 'steel_pct', 'aluminum_pct', 'copper_pct',
                'wood_pct', 'auto_pct', 'non_steel_pct', 'qty_unit',
                'country_of_melt', 'country_of_cast', 'country_of_smelt',
                'Sec301_Exclusion_Tariff']:
        db_col = f'{col}_db'
        if db_col in merged.columns:
            # Use database value if it exists and is not empty
            if col in merged.columns:
                merged[col] = merged.apply(
                    lambda r: r[db_col] if pd.notna(r[db_col]) and str(r[db_col]).strip() else r.get(col, ''),
                    axis=1
                )
            else:
                merged[col] = merged[db_col]
            merged = merged.drop(columns=[db_col])

    return merged
