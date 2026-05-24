"""
OCRMill Enrichment Pipeline

Standalone enrichment module that takes raw extracted invoice data and produces
fully enriched output (material splits, Qty1/Qty2, declaration codes, etc.).
Adapts the logic from entryops.py's _process_with_complete_data() for
headless (no UI) operation.
"""

import logging
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class EnrichmentPipeline:
    """
    Enriches raw invoice extraction data with parts_master lookups,
    material row splitting, quantity calculations, and declaration codes.
    """

    def __init__(self, db_path: Path, log_callback=None):
        self.db_path = Path(db_path)
        self.log_callback = log_callback
        # Pre-load tariff_232 table for repeated lookups
        self._tariff_cache = {}
        self._load_tariff_cache()
        # Pre-load country name → ISO 2-letter code mapping
        self._country_codes = self._load_country_codes()
        # Tracking: unresolved country values and HTS lookup stats
        self._unresolved_countries = set()
        self._hts_hits = 0
        self._hts_misses = 0
        self._parts_not_found = 0

    def _log(self, msg: str):
        logger.info(msg)
        if self.log_callback:
            self.log_callback(msg)

    def _load_country_codes(self) -> dict:
        """Load country_name → country_code mapping from DB."""
        codes = {}
        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute("SELECT country_name, country_code FROM country_codes")
            for name, code in c.fetchall():
                codes[name.strip().upper()] = code.strip().upper()
            conn.close()
        except Exception:
            pass
        return codes

    def normalize_country(self, value: str) -> str:
        """Convert a country name or code to ISO 2-letter code.
        If already 2 letters, return as-is. If found in table, convert.
        Otherwise return the raw value unchanged and track as unresolved."""
        if not value:
            return value
        v = str(value).strip().upper()
        if len(v) == 2 and v.isalpha():
            return v  # Already a 2-letter code
        code = self._country_codes.get(v)
        if code:
            return code
        # Track unresolved country values for validation summary
        if v and v not in ('', 'NAN', 'NONE', 'UNKNOWN'):
            self._unresolved_countries.add(v)
            logger.warning(f"Unresolved country value: '{v}'")
        return v

    def get_unresolved_countries(self) -> set:
        """Return set of country values that could not be resolved to ISO codes."""
        return self._unresolved_countries

    def get_enrichment_stats(self) -> dict:
        """Return enrichment statistics for validation summary."""
        return {
            'hts_hits': self._hts_hits,
            'hts_misses': self._hts_misses,
            'parts_not_found': self._parts_not_found,
            'unresolved_countries': list(self._unresolved_countries),
        }

    def _load_tariff_cache(self):
        """Load tariff_232 table into memory for fast lookups."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute("SELECT hts_code, material, declaration_required FROM tariff_232")
            for row in c.fetchall():
                self._tariff_cache[row[0]] = (row[1], row[2])
            conn.close()
            self._log(f"Loaded {len(self._tariff_cache)} tariff_232 entries")
        except Exception as e:
            logger.error(f"Failed to load tariff_232 cache: {e}")

    def get_232_info(self, hts_code) -> Tuple[Optional[str], str, str]:
        """
        Lookup Section 232 tariff information for an HTS code.

        Returns:
            Tuple of (material, declaration_code, smelt_flag)
        """
        try:
            if hts_code is None or pd.isna(hts_code) or str(hts_code).strip() == '':
                return None, "", ""
        except (ValueError, TypeError):
            if not hts_code or str(hts_code).strip() == '':
                return None, "", ""

        hts_clean = str(hts_code).replace(".", "").strip().upper()
        hts_10 = hts_clean[:10]
        hts_8 = hts_clean[:8]

        # Try 10-digit first, then 8-digit
        row = self._tariff_cache.get(hts_10) or self._tariff_cache.get(hts_8)

        if row:
            material = row[0]
            dec_code = row[1] if row[1] else ""
            dec_type = dec_code.split(" - ")[0] if " - " in dec_code else dec_code
            smelt_flag = "Y" if material in ["Aluminum", "Wood", "Copper"] else ""
            return material, dec_type, smelt_flag

        return None, "", ""

    # ===== Section 232 Ch99 Heading Logic (April 2026 Proclamation) =====

    def _load_ch99_cache(self):
        """Load tariff_232_ch99 mappings into memory.

        Keys are stored at multiple lengths for prefix matching:
        e.g., HTS '7206.00.0000' creates keys: '7206000000', '72060000', '720600', '7206'
        This allows matching '7206.10.0000' → '7206' (chapter heading covers all subheadings).
        """
        cache = {}
        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute("SELECT hts_code, material, ch99_heading, product_type, rate_pct FROM tariff_232_ch99")
            for row in c.fetchall():
                entry = {
                    'material': row[1], 'ch99_heading': row[2],
                    'product_type': row[3], 'rate_pct': row[4]
                }
                key = row[0].replace('.', '')  # normalize to digits
                if key not in cache:
                    cache[key] = []
                cache[key].append(entry)

                # For chapter-level codes (e.g., 7206000000), also store under 4-digit heading
                # so that 7206100000 can match via prefix fallback
                if key.endswith('000000') and len(key) == 10:
                    heading_key = key[:4]
                    if heading_key not in cache:
                        cache[heading_key] = []
                    # Avoid duplicates
                    if entry not in cache[heading_key]:
                        cache[heading_key].append(entry)
                elif key.endswith('0000') and len(key) == 8:
                    heading_key = key[:4]
                    if heading_key not in cache:
                        cache[heading_key] = []
                    if entry not in cache[heading_key]:
                        cache[heading_key].append(entry)

            conn.close()
        except Exception as e:
            logger.warning(f"Failed to load ch99 cache: {e}")
        return cache

    def resolve_single_duty_material(self, hts_code: str, steel_pct: float,
                                      aluminum_pct: float, copper_pct: float) -> str:
        """For HTS codes listed under multiple metals, determine the single applicable material.

        Rules per proclamation: goods listed as derivatives of more than one metal shall only
        be subject to one duty rate. Pick the metal with the highest percentage.
        Tie-breaker: higher duty rate (conservative).
        """
        metals = []
        if steel_pct > 0:
            metals.append(('Steel', steel_pct))
        if aluminum_pct > 0:
            metals.append(('Aluminum', aluminum_pct))
        if copper_pct > 0:
            metals.append(('Copper', copper_pct))

        if not metals:
            # Fall back to tariff_232 material lookup
            material, _, _ = self.get_232_info(hts_code)
            return material or ''

        if len(metals) == 1:
            return metals[0][0]

        # Sort by percentage (desc), then by duty priority (Steel > Copper > Aluminum)
        duty_priority = {'Steel': 3, 'Copper': 2, 'Aluminum': 1}
        metals.sort(key=lambda m: (m[1], duty_priority.get(m[0], 0)), reverse=True)
        return metals[0][0]

    def evaluate_weight_threshold(self, row, net_weight_per_line: float) -> dict:
        """Check if article qualifies for 15% weight exemption (9903.82.03).

        Articles outside Chapters 72/73/74/76 with aggregate metal weight <15%
        of total article weight are exempt.

        Returns dict with 'exempt' (bool), 'metal_weight_pct' (float), 'metal_weight_kg' (float).
        """
        # NB: ``value or ''`` raises "boolean value of NA is ambiguous" when
        # value is pd.NA (which happens for parts the user added via the
        # missing-parts dialog with blank fields). Always pd.notna-guard
        # before any boolean coercion of a Series value.
        hts_raw = row.get('hts_code', '')
        hts = (str(hts_raw) if pd.notna(hts_raw) else '').replace('.', '').strip()
        if len(hts) < 2:
            return {'exempt': False, 'zero_metal': False,
                    'metal_weight_pct': 0.0, 'metal_weight_kg': 0.0}

        chapter = int(hts[:2]) if hts[:2].isdigit() else 0

        # Calculate aggregate metal percentage from parts_master.
        def _safe_pct(val):
            if not pd.notna(val):
                return 0.0
            try:
                return float(val) if val != '' else 0.0
            except (ValueError, TypeError):
                return 0.0

        steel_pct = _safe_pct(row.get('steel_pct', 0))
        aluminum_pct = _safe_pct(row.get('aluminum_pct', 0))
        copper_pct = _safe_pct(row.get('copper_pct', 0))
        non_steel_pct = _safe_pct(row.get('non_steel_pct', 0))

        # When the PDF's Section 232 form provided per-unit dollar values for
        # this row (merged in via _merge_232_form_data), compute the metal pct
        # straight from the document and use it INSTEAD of the parts_master
        # percentages. The CBP-mandated formula is:
        #     metal_pct = acq_cost_metal / po_value × 100   (CSMS#65236645)
        # The document is the authoritative shipment record — parts_master is
        # the historical fallback for shipments without a 232 form. This fixes
        # the case where parts_master shows the part as non_steel_pct=100 but
        # the 232 form on the actual shipment declares aluminum content (e.g.,
        # part 2199788 in PDF 4296966 — parts_master had 0% aluminum, 232 form
        # said 22.3%, classifier was misrouting to 9903.82.01 instead of
        # 9903.82.09).
        acq_cost = _safe_pct(row.get('_232_acq_cost', 0))
        po_value_232 = _safe_pct(row.get('_232_po_value', 0))
        _mt = row.get('_232_metal_type', '')
        metal_type = (str(_mt).strip().lower() if pd.notna(_mt) else '')
        if acq_cost > 0 and po_value_232 > 0 and metal_type in ('aluminum', 'steel'):
            pct_from_form = round(min(acq_cost / po_value_232 * 100.0, 100.0), 2)
            # Reset all metals to zero, then set the declared one.
            steel_pct = pct_from_form if metal_type == 'steel' else 0.0
            aluminum_pct = pct_from_form if metal_type == 'aluminum' else 0.0
            copper_pct = 0.0
            non_steel_pct = max(0.0, round(100.0 - pct_from_form, 2))

        aggregate_metal_pct_pre = steel_pct + aluminum_pct + copper_pct

        # Chapters 72/73/74/76 are by default the metal article (chapter 73 =
        # iron/steel articles, chapter 76 = aluminum, etc.) — but if the user
        # has explicitly declared the part is NOT made of the regulated metal
        # via parts_master (non_steel_pct >= 100 with all metals at 0), we
        # respect that. This handles cast iron parts in chapter 73 (e.g.,
        # HTS 7307.19.3070 cast iron pipe fittings, 7303.00.0090 cast iron
        # tubes) which file under the new 9903.82.01 heading per BIS FRN
        # 2026-08297 because they don't contain steel.
        if chapter in (72, 73, 74, 76):
            if non_steel_pct >= 100 and aggregate_metal_pct_pre == 0:
                return {'exempt': False, 'zero_metal': True,
                        'metal_weight_pct': 0.0, 'metal_weight_kg': 0.0}
            # Default: article IS the regulated metal. Use parts_master pct
            # if explicitly set; otherwise treat as 100%.
            if aggregate_metal_pct_pre > 0:
                kg = round(aggregate_metal_pct_pre / 100.0 * net_weight_per_line, 2) if net_weight_per_line > 0 else 0.0
                return {'exempt': False, 'zero_metal': False,
                        'metal_weight_pct': aggregate_metal_pct_pre, 'metal_weight_kg': kg}
            return {'exempt': False, 'zero_metal': False,
                    'metal_weight_pct': 100.0, 'metal_weight_kg': net_weight_per_line}

        # Only include metals that are listed for this HTS in the annex
        # For simplicity, use total metal percentage as proxy
        aggregate_metal_pct = steel_pct + aluminum_pct + copper_pct
        metal_weight_kg = round(aggregate_metal_pct / 100.0 * net_weight_per_line, 2) if net_weight_per_line > 0 else 0.0

        # Two distinct paths for derivative articles outside ch 72/73/74/76:
        #
        #   metal_pct == 0  → 9903.82.01 (NEW heading, BIS Federal Register
        #                     notice 2026-08297, effective Apr 6, 2026).
        #                     "Articles in subdivision (c) of Note 16 that
        #                     do not contain any aluminum, steel, or copper."
        #                     Supersedes the NCBFAA Apr 10 stopgap that had
        #                     advised 9903.82.03 with 0 KG for this case.
        #
        #   0 < pct < 15    → 9903.82.03 (existing AGG WGT MTL <15% WGT).
        #
        #   pct >= 15       → 9903.82.09 / 9903.82.02 etc. (table lookup).
        zero_metal = aggregate_metal_pct == 0
        exempt = 0 < aggregate_metal_pct < 15.0
        return {
            'exempt': exempt,
            'zero_metal': zero_metal,
            'metal_weight_pct': round(aggregate_metal_pct, 2),
            'metal_weight_kg': metal_weight_kg
        }

    def determine_ch99_heading(self, hts_code: str, material: str, country_origin: str,
                                is_primary: bool, country_of_smelt: str = '',
                                country_of_cast: str = '', country_of_melt: str = '',
                                is_exempt: bool = False, is_zero_metal: bool = False,
                                ch99_entries: list = None) -> Tuple[str, float]:
        """Determine the correct 9903.82.XX heading and duty rate for a line item.

        Uses tariff_232_ch99 table lookup first, then country-based rules.
        Per April 2026 Proclamation (CSMS#68253075) and BIS Federal Register
        notice 2026-08297 (effective Apr 6, 2026) which added 9903.82.01 for
        derivatives that contain none of Al/Steel/Cu.
        """
        if not material:
            return '', 0.0

        country = (country_origin or '').strip().upper()[:2]

        # 1a. Zero-metal derivative — articles in subdivision (c) of Note 16
        # that do not contain any aluminum/steel/copper. New heading per BIS
        # FRN 2026-08297 effective Apr 6, 2026; supersedes the NCBFAA Apr 10
        # 2026 stopgap that used 9903.82.03 for this case.
        if is_zero_metal:
            return '9903.82.01', 0.0

        # 1b. Weight exemption (0 < pct < 15)
        if is_exempt:
            return '9903.82.03', 0.0

        # 2. Russia — special rules
        if country == 'RU':
            if material == 'Aluminum':
                return '9903.85.68', 200.0  # Russia aluminum stays at 200%
            # Check ch99 table for Russia-specific headings
            if ch99_entries:
                ru_headings = [e for e in ch99_entries if e['material'] == material
                               and e['ch99_heading'] in ('9903.82.14', '9903.82.15', '9903.82.16', '9903.82.17')]
                if ru_headings:
                    # Pick the most specific heading (highest number = more specific)
                    ru_headings.sort(key=lambda e: e['ch99_heading'], reverse=True)
                    return ru_headings[0]['ch99_heading'], ru_headings[0]['rate_pct']
            return '9903.82.14', 50.0  # default Russia

        # 3. UK — check if listed under UK headings
        if country == 'GB':
            if ch99_entries:
                uk_headings = [e for e in ch99_entries if e['material'] == material
                               and e['ch99_heading'] in ('9903.82.04', '9903.82.05')]
                if uk_headings:
                    uk_headings.sort(key=lambda e: e['ch99_heading'])
                    return uk_headings[0]['ch99_heading'], uk_headings[0]['rate_pct']
            return ('9903.82.04', 25.0) if is_primary else ('9903.82.05', 15.0)

        # 4. US content — derive from country fields
        us_countries = {'US'}
        smelt_us = (country_of_smelt or '').strip().upper()[:2] in us_countries
        cast_us = (country_of_cast or '').strip().upper()[:2] in us_countries
        melt_us = (country_of_melt or '').strip().upper()[:2] in us_countries

        is_us_content = False
        if material == 'Steel' and melt_us:
            is_us_content = True
        elif material == 'Aluminum' and smelt_us and cast_us:
            is_us_content = True
        elif material == 'Copper' and smelt_us and cast_us:
            is_us_content = True

        if is_us_content:
            if ch99_entries:
                us_headings = [e for e in ch99_entries if e['material'] == material
                               and e['ch99_heading'] == '9903.82.06']
                if us_headings:
                    return '9903.82.06', 10.0

        # 4b. Chapter 72/73/74/76 short-circuit (added v1.6.13 2026-05-06).
        # Per Note 16(c), HTS codes in chapters 72/73/74/76 are enumerated in
        # subdivisions (c)(i)–(v), all of which route to 9903.82.02 at +50%.
        # This explicit short-circuit guarantees correctness regardless of
        # what the tariff_232_ch99 cache returns — defensive against the
        # case (seen on a user workstation 2026-05-06) where the running
        # app's cache priority somehow returned 9903.82.09 instead of
        # 9903.82.02 for HTS 7325.99.5000 from CN despite the table
        # containing the correct .02 entry. Country-specific rules above
        # (Russia, UK, US-content) already returned for those cases, so by
        # this point we know we're routing for an "all other country"
        # article in a primary-metal chapter.
        hts_digits_now = (hts_code or '').replace('.', '').strip()
        chapter_now = int(hts_digits_now[:2]) if len(hts_digits_now) >= 2 and hts_digits_now[:2].isdigit() else 0
        if chapter_now in (72, 73, 74, 76):
            return '9903.82.02', 50.0

        # 5. Use tariff_232_ch99 table: find the applicable heading for all countries
        # Priority: 9903.82.02 (50%) > 9903.82.09 (25%) > others
        if ch99_entries:
            material_entries = [e for e in ch99_entries if e['material'] == material]
            # Check for 9903.82.02 first (primary + derivative articles at 50%)
            if any(e['ch99_heading'] == '9903.82.02' for e in material_entries):
                return '9903.82.02', 50.0
            # Then 9903.82.09 (derivatives at 25%)
            if any(e['ch99_heading'] == '9903.82.09' for e in material_entries):
                return '9903.82.09', 25.0
            # Any other heading
            if material_entries:
                # Pick the heading with highest rate (conservative)
                material_entries.sort(key=lambda e: e['rate_pct'], reverse=True)
                return material_entries[0]['ch99_heading'], material_entries[0]['rate_pct']

        # 6. Fallback decision tree (no ch99 table data) — chapter-aware.
        # Note 16(c) divides Section 232 articles into 10 lists. The HTS
        # chapter is a reliable proxy for which list an article falls under:
        #   chapters 72/73/74/76 → primary metals + derivatives in (c)(i)–(v)
        #     → 9903.82.02 at +50% per the heading description for that range
        #   other chapters (83, 84, 85, 87, 94 …) → derivative subdivisions
        #     (c)(vi)–(viii) → 9903.82.09 at +25%
        # Reaching this fallback means the tariff_232_ch99 cache lookup
        # returned no rows — usually because the running app is reading from
        # a stale local DB that doesn't have the table populated. Verified
        # 2026-05-05 against the user's HTS 7325.99.5000 case: shared DB had
        # 73259950 → 9903.82.02 entries, but the local app DB lacked the
        # tariff_232_ch99 table entirely, so the fallback fired and routed
        # the row to 9903.82.09 (wrong — compliance team confirmed 9903.82.02
        # per Note 16(c)(iv)).
        hts_digits = (hts_code or '').replace('.', '').strip()
        chapter = int(hts_digits[:2]) if len(hts_digits) >= 2 and hts_digits[:2].isdigit() else 0
        if chapter in (72, 73, 74, 76) or is_primary:
            return '9903.82.02', 50.0
        return '9903.82.09', 25.0

    def lookup_parts_master(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Left-join with parts_master. Database values take precedence over invoice values.
        """
        df = df.copy()

        conn = sqlite3.connect(str(self.db_path))
        parts = pd.read_sql(
            "SELECT part_number, hts_code, steel_pct, aluminum_pct, copper_pct, "
            "wood_pct, auto_pct, non_steel_pct, qty_unit, country_origin, "
            "country_of_melt, country_of_cast, country_of_smelt, "
            "Sec301_Exclusion_Tariff, pga_code, client_code, mid "
            "FROM parts_master", conn
        )
        conn.close()

        # Apply part number corrections (user-defined remappings)
        try:
            conn2 = sqlite3.connect(str(self.db_path))
            corrections = pd.read_sql("SELECT original_part, corrected_part FROM part_number_corrections", conn2)
            conn2.close()
            if not corrections.empty:
                corrections['original_part'] = corrections['original_part'].str.strip().str.upper()
                corrections['corrected_part'] = corrections['corrected_part'].str.strip().str.upper()
                raw_map = dict(zip(corrections['original_part'], corrections['corrected_part']))

                # Resolve transitive chains: A→X, X→Z should give A→Z so a single
                # replace() produces the final value (pandas replace doesn't chain).
                def _resolve(key, seen=None):
                    if seen is None:
                        seen = set()
                    if key in seen or key not in raw_map:
                        return key
                    seen.add(key)
                    return _resolve(raw_map[key], seen)

                corr_map = {k: _resolve(v) for k, v in raw_map.items()}
                df['part_number'] = df['part_number'].astype(str).str.strip().str.upper().replace(corr_map)
                applied = df['part_number'].isin(corr_map.values()).sum()
                if applied:
                    self._log(f"  Applied {len(corr_map)} part number correction(s)")
        except Exception:
            pass  # Table may not exist in older DBs

        # Normalize part numbers
        df['part_number'] = df['part_number'].astype(str).str.strip().str.upper()
        parts['part_number'] = parts['part_number'].astype(str).str.strip().str.upper()

        df = df.merge(parts, on='part_number', how='left', suffixes=('', '_master'), indicator=True)
        df['_not_in_db'] = df['_merge'] == 'left_only'
        df = df.drop(columns=['_merge'])

        not_found_count = df['_not_in_db'].sum()
        if not_found_count > 0:
            self._log(f"  {not_found_count} part(s) not found in parts_master")

        # Merge strategy: DB values take precedence over invoice values.
        # Exception: 'mid' uses invoice value first (supplier on invoice may differ
        # from parts_master MID — same part can come from multiple suppliers).
        merge_fields = [
            'hts_code', 'steel_pct', 'aluminum_pct', 'copper_pct', 'wood_pct',
            'auto_pct', 'non_steel_pct', 'qty_unit', 'country_origin',
            'country_of_melt', 'country_of_cast', 'country_of_smelt',
            'Sec301_Exclusion_Tariff', 'pga_code', 'client_code', 'mid'
        ]
        # Fields where the invoice value takes priority over parts_master
        invoice_priority_fields = {'mid', 'country_origin'}
        pct_fields = {'steel_pct', 'aluminum_pct', 'copper_pct', 'wood_pct', 'auto_pct', 'non_steel_pct'}

        for field in merge_fields:
            master_col = f'{field}_master'
            if master_col in df.columns:
                if field in pct_fields:
                    master_vals = pd.to_numeric(df[master_col], errors='coerce')
                    invoice_vals = pd.to_numeric(df[field], errors='coerce') if field in df.columns else pd.Series([pd.NA] * len(df))
                    df[field] = master_vals.combine_first(invoice_vals)
                else:
                    master_series = df[master_col].replace('', pd.NA)
                    invoice_series = df[field].replace('', pd.NA) if field in df.columns else pd.Series([pd.NA] * len(df))
                    if field in invoice_priority_fields:
                        # Invoice value wins (e.g. MID from invoice supplier lookup)
                        df[field] = invoice_series.combine_first(master_series)
                    else:
                        df[field] = master_series.combine_first(invoice_series)
                df = df.drop(columns=[master_col])
            elif field not in df.columns:
                if field in pct_fields:
                    df[field] = 0.0
                else:
                    df[field] = ''

        # Ensure ratio fields are numeric
        for field in pct_fields:
            df[field] = pd.to_numeric(df[field], errors='coerce').fillna(0.0)

        # Derive client_code from mid via mid_table when client_code is missing.
        #
        # Real-world driver: parts_master sometimes carries a row with `mid`
        # set but `client_code` blank (e.g., a part added via Add/Update
        # Parts that didn't fill in the client). Without this step, that row
        # gets flagged Incomplete by classify_material's check (line ~556),
        # the Add/Update Parts dialog re-opens, and the operator types in a
        # value that mid_table already knows. Filling it in here removes the
        # avoidable round-trip.
        #
        # Safe single-source-of-truth lookup: mid_table is 1:1 between mid
        # and customer_id (verified 2026-05-01: 203 MIDs, 203 distinct
        # customer_ids), so there's no disambiguation needed.
        try:
            conn3 = sqlite3.connect(str(self.db_path))
            mid_lookup = pd.read_sql(
                "SELECT mid, customer_id FROM mid_table "
                "WHERE mid IS NOT NULL AND customer_id IS NOT NULL",
                conn3,
            )
            conn3.close()
            if not mid_lookup.empty and 'mid' in df.columns and 'client_code' in df.columns:
                mid_to_client = dict(zip(
                    mid_lookup['mid'].astype(str).str.strip().str.upper(),
                    mid_lookup['customer_id'].astype(str).str.strip(),
                ))
                cc_empty = df['client_code'].fillna('').astype(str).str.strip().eq('')
                mid_present = df['mid'].fillna('').astype(str).str.strip().ne('')
                candidates = cc_empty & mid_present
                if candidates.any():
                    derived = (
                        df.loc[candidates, 'mid']
                        .astype(str).str.strip().str.upper()
                        .map(mid_to_client).fillna('')
                    )
                    df.loc[candidates, 'client_code'] = derived
                    filled = int((derived != '').sum())
                    if filled:
                        self._log(
                            f"  Derived client_code from MID for {filled} part(s) "
                            f"via mid_table lookup"
                        )
        except sqlite3.Error as exc:
            self._log(f"  Note: mid_table lookup failed ({exc}) — client_code derivation skipped")

        # Track HTS lookup stats for validation summary
        self._parts_not_found = int(df['_not_in_db'].sum())
        in_db = ~df['_not_in_db']
        hts_present = df['hts_code'].fillna('').astype(str).str.strip().ne('')
        self._hts_hits = int((in_db & hts_present).sum())
        self._hts_misses = int((in_db & ~hts_present).sum())

        return df

    def _merge_232_form_data(self, df: pd.DataFrame, updates: dict):
        """Merge Section 232 form per-unit dollar values into DataFrame rows.

        Matches by part_number (SKU). Adds columns:
        _232_acq_cost, _232_non_metal_cost, _232_po_value, _232_metal_kg, _232_metal_type
        """
        # Initialize columns
        df['_232_acq_cost'] = 0.0
        df['_232_non_metal_cost'] = 0.0
        df['_232_po_value'] = 0.0
        df['_232_metal_kg'] = ''
        df['_232_metal_type'] = ''

        matched = 0
        for idx, row in df.iterrows():
            pn = str(row.get('part_number', '')).strip().upper()
            if pn in updates:
                data = updates[pn]
                if 'acq_cost_aluminum' in data:
                    df.at[idx, '_232_acq_cost'] = data['acq_cost_aluminum']
                    df.at[idx, '_232_metal_type'] = 'aluminum'
                    df.at[idx, '_232_metal_kg'] = data.get('aluminum_kg', '')
                elif 'acq_cost_steel' in data:
                    df.at[idx, '_232_acq_cost'] = data['acq_cost_steel']
                    df.at[idx, '_232_metal_type'] = 'steel'
                    df.at[idx, '_232_metal_kg'] = data.get('steel_kg', '')
                df.at[idx, '_232_po_value'] = data.get('po_value', 0.0)
                df.at[idx, '_232_non_metal_cost'] = data.get('non_metal_cost', 0.0)
                matched += 1

        if matched:
            self._log(f"  Section 232 form data merged for {matched} row(s)")

    def classify_material(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Classify each row's material type WITHOUT splitting rows.
        Per CSMS#68253075: Section 232 duties apply to the FULL customs value.
        One invoice line = one output row at full value with single Ch99 heading.
        """
        df = df.copy()
        df['SteelPercentage'] = pd.to_numeric(df.get('steel_pct', 0.0), errors='coerce').fillna(0.0)
        df['AluminumPercentage'] = pd.to_numeric(df.get('aluminum_pct', 0.0), errors='coerce').fillna(0.0)
        df['CopperPercentage'] = pd.to_numeric(df.get('copper_pct', 0.0), errors='coerce').fillna(0.0)
        df['WoodPercentage'] = pd.to_numeric(df.get('wood_pct', 0.0), errors='coerce').fillna(0.0)
        df['AutoPercentage'] = pd.to_numeric(df.get('auto_pct', 0.0), errors='coerce').fillna(0.0)
        df['NonSteelPercentage'] = pd.to_numeric(df.get('non_steel_pct', 0.0), errors='coerce').fillna(0.0)

        # Classify each row's dominant material type (no row splitting)
        content_types = []
        dual_flags = []

        for idx, row in df.iterrows():
            steel_pct = row['SteelPercentage']
            aluminum_pct = row['AluminumPercentage']
            copper_pct = row['CopperPercentage']
            wood_pct = row['WoodPercentage']
            auto_pct = row['AutoPercentage']
            non_steel_pct = row['NonSteelPercentage']

            not_in_db = bool(row.get('_not_in_db', False)) if pd.notna(row.get('_not_in_db', False)) else False

            # Check for incomplete data
            hts = row.get('hts_code', '')
            hts_clean = str(hts).strip() if pd.notna(hts) else ''
            qty_unit = row.get('qty_unit', '')
            qty_unit_clean = str(qty_unit).strip() if pd.notna(qty_unit) else ''
            client_code = row.get('client_code', '')
            client_code_clean = str(client_code).strip() if pd.notna(client_code) else ''

            if not not_in_db and (not hts_clean or not qty_unit_clean or not client_code_clean):
                content_types.append('incomplete')
                dual_flags.append(False)
                continue

            if not_in_db:
                content_types.append('not_found')
                dual_flags.append(False)
                continue

            # If ALL ratios are 0 (including non_steel_pct), the part has
            # no content data at all — look up material type from HTS and
            # auto-fill. If the user has set non_steel_pct > 0 (e.g.,
            # non_steel_pct=100 for cast iron parts in chapter 73), we
            # respect that explicit declaration and leave metals at 0 so
            # the row routes to 9903.82.01 (per BIS FRN 2026-08297).
            #
            # 100% auto-fill is ONLY correct for primary metal chapters
            # (72/73/74/76) where the entire article IS the metal. For
            # derivative articles (e.g. chapter 84 valve bodies) the duty
            # is on actual metal content per CBP CSMS #65236645.
            if (steel_pct == 0 and aluminum_pct == 0 and copper_pct == 0
                and wood_pct == 0 and auto_pct == 0 and non_steel_pct == 0):
                if hts_clean:
                    material, _, _ = self.get_232_info(hts)
                    hts_digits = str(hts).replace('.', '').strip()
                    chapter = int(hts_digits[:2]) if len(hts_digits) >= 2 and hts_digits[:2].isdigit() else 0
                    is_primary_chapter = chapter in (72, 73, 74, 76)

                    if is_primary_chapter and material == 'Aluminum':
                        df.at[idx, 'AluminumPercentage'] = 100.0
                        df.at[idx, 'NonSteelPercentage'] = 0.0
                    elif is_primary_chapter and material == 'Copper':
                        df.at[idx, 'CopperPercentage'] = 100.0
                        df.at[idx, 'NonSteelPercentage'] = 0.0
                    elif is_primary_chapter and material == 'Steel':
                        df.at[idx, 'SteelPercentage'] = 100.0
                        df.at[idx, 'NonSteelPercentage'] = 0.0
                    elif material == 'Wood':
                        df.at[idx, 'WoodPercentage'] = 100.0
                        df.at[idx, 'NonSteelPercentage'] = 0.0
                    elif material == 'Auto':
                        df.at[idx, 'AutoPercentage'] = 100.0
                        df.at[idx, 'NonSteelPercentage'] = 0.0
                    elif material in ('Aluminum', 'Copper', 'Steel'):
                        # Derivative metal HTS — leave metal pcts at 0 so
                        # the export shows MetalWeightPct=0 / MetalWeightKG=0
                        # and Ch99Heading=9903.82.03 (per CBP <15% rule).
                        # Don't touch NonSteelPercentage here; the row will
                        # still be classified 232_<material> below.
                        pass
                    else:
                        df.at[idx, 'NonSteelPercentage'] = 100.0
                    # Re-read after update
                    steel_pct = df.at[idx, 'SteelPercentage']
                    aluminum_pct = df.at[idx, 'AluminumPercentage']
                    copper_pct = df.at[idx, 'CopperPercentage']
                    wood_pct = df.at[idx, 'WoodPercentage']
                    auto_pct = df.at[idx, 'AutoPercentage']

            # Determine dominant material (single duty rule)
            is_dual = steel_pct > 0 and aluminum_pct > 0
            dual_flags.append(is_dual)

            metal_pcts = [
                (steel_pct, 'steel'), (aluminum_pct, 'aluminum'),
                (copper_pct, 'copper'), (wood_pct, 'wood'), (auto_pct, 'auto')
            ]
            metal_pcts = [(p, m) for p, m in metal_pcts if p > 0]

            if metal_pcts:
                # Pick the metal with highest percentage
                metal_pcts.sort(key=lambda x: x[0], reverse=True)
                content_types.append(metal_pcts[0][1])
            elif hts_clean:
                # Derivative metal HTS (chapter 84 valve bodies, etc.) with
                # no metal content data still needs to flag as 232_<material>
                # so the filer sees the duty regime — the row goes out under
                # 9903.82.03 with 0 KG per CBP guidance.
                fallback_material, _, _ = self.get_232_info(hts)
                if fallback_material in ('Aluminum', 'Copper', 'Steel', 'Wood', 'Auto'):
                    content_types.append(fallback_material.lower())
                else:
                    content_types.append('non_232')
            else:
                content_types.append('non_232')

        df['_content_type'] = content_types
        df['_is_dual_declaration'] = dual_flags

        self._log(f"  Row classification: {len(df)} rows (no split, full value per line)")
        return df

    def calculate_weights(self, df: pd.DataFrame, net_weight: float) -> pd.DataFrame:
        """Calculate CalcWtNet — prefer template-provided per-item net_weight,
        else allocate the document-level net_weight proportionally by value.

        Templates handling multi-invoice PDFs (e.g. sigmac_karmen) populate
        item['net_weight'] directly with per-invoice allocations — using the
        doc-level value-proportional split there would mix one invoice's
        weight into the other's items.
        """
        df = df.copy()
        # Coerce value_usd to a plain float Series so .sum() and comparisons
        # don't return pd.NA (which raises "boolean value of NA is ambiguous"
        # when fed to `if` / `and`). Hits when an upstream template extracts
        # rows with no prices (e.g. a CBP 7501 form mis-classified as an
        # invoice — all value_usd are NA/0).
        if 'value_usd' in df.columns:
            value_series = pd.to_numeric(df['value_usd'], errors='coerce').fillna(0.0)
        else:
            value_series = pd.Series([0.0] * len(df), index=df.index)
        total_value = float(value_series.sum())

        has_template_weights = False
        if 'net_weight' in df.columns:
            nw_series = pd.to_numeric(df['net_weight'], errors='coerce').fillna(0.0)
            has_template_weights = bool((nw_series > 0).any())
        else:
            nw_series = None

        if has_template_weights:
            calc = nw_series.copy()
            # Fill any zero/missing rows with value-proportional share of the
            # doc-level weight as a defensive fallback.
            mask_zero = calc <= 0
            if bool(mask_zero.any()) and total_value > 0 and net_weight and net_weight > 0:
                calc.loc[mask_zero] = (value_series.loc[mask_zero] / total_value) * net_weight
            df['CalcWtNet'] = calc
        elif total_value == 0:
            df['CalcWtNet'] = 0.0
        else:
            df['CalcWtNet'] = (value_series / total_value) * net_weight

        # LineNetWeight: alias of CalcWtNet for output profiles needing per-line net weight
        df['LineNetWeight'] = df['CalcWtNet'].round(2)

        return df

    def calculate_quantities(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Qty1 and Qty2 based on qty_unit type from HTS database."""
        df = df.copy()

        WEIGHT_UNITS = {'KG', 'G', 'T', 'T ADW', 'T DWB'}
        COUNT_UNITS = {'NO', 'PCS', 'DOZ', 'DOZ. PRS', 'DZ PCS', 'GR', 'GROSS', 'HUNDREDS',
                       'THOUSANDS', 'PRS', 'PACK', 'DOSES', 'CARAT'}
        DUAL_UNITS = {'NO. AND KG', 'NO/KG', 'NO\\KG', 'NO., KG', 'NO. KG', 'NO KG',
                      'CU KG', 'CY KG', 'NI KG', 'PB KG', 'ZN KG', 'KG AMC',
                      'AG G', 'AU G', 'IR G', 'OS G', 'PD G', 'PT G', 'RH G', 'RU G',
                      'DOZ., KG', 'DOZ. KG', 'DOZ KG', 'PRS., KG', 'PRS. KG', 'PRS KG'}
        MEASURE_UNITS = {'LITERS', 'PF.LITERS', 'BBL', 'M', 'LIN. M', 'M2', 'CM2', 'M3',
                         'SQUARE', 'FIBER M', 'GBQ', 'MWH', 'THOUSAND M', 'THOUSAND M3'}
        NO_QTY_UNITS = {'M', 'M2', 'M3'}

        def get_qty1(row):
            qty_unit = str(row.get('qty_unit', '')).strip().upper() if pd.notna(row.get('qty_unit')) else ''
            if qty_unit == '' or qty_unit in NO_QTY_UNITS:
                return ''

            if qty_unit in WEIGHT_UNITS:
                # Prefer template-provided per-item net_weight over calculated
                item_wt = row.get('net_weight', None)
                if pd.notna(item_wt) and item_wt not in (None, '', 0):
                    wt = int(round(float(item_wt)))
                else:
                    wt = int(round(row['CalcWtNet']))
                return str(max(wt, 1))

            if qty_unit in COUNT_UNITS:
                qty = row.get('quantity', '')
                if pd.notna(qty) and str(qty).strip():
                    try:
                        raw_qty = float(str(qty).replace(',', '').strip())
                        if qty_unit in ('GR', 'GROSS'):
                            converted = raw_qty / 144.0
                        elif qty_unit in ('DOZ', 'DOZ. PRS', 'DZ PCS'):
                            converted = raw_qty / 12.0
                        elif qty_unit == 'HUNDREDS':
                            converted = raw_qty / 100.0
                        elif qty_unit == 'THOUSANDS':
                            converted = raw_qty / 1000.0
                        elif qty_unit == 'PRS':
                            converted = raw_qty / 2.0
                        else:
                            converted = raw_qty
                        if converted == int(converted):
                            return str(max(int(converted), 1))
                        return str(max(round(converted, 2), 0.01))
                    except (ValueError, TypeError):
                        return ''
                return ''

            if qty_unit in DUAL_UNITS:
                qty = row.get('quantity', '')
                if pd.notna(qty) and str(qty).strip():
                    try:
                        qty_val = float(str(qty).replace(',', '').strip())
                        if 'DOZ' in qty_unit:
                            converted = qty_val / 12.0
                            return f"{max(converted, 0.01):.2f}"
                        if 'PRS' in qty_unit:
                            qty_val = qty_val / 2.0
                        result = max(int(round(qty_val)), 1)
                        return str(result)
                    except (ValueError, TypeError):
                        return ''
                if 'NO' in qty_unit:
                    return '1'
                return ''

            if qty_unit in MEASURE_UNITS:
                qty = row.get('quantity', '')
                if pd.notna(qty) and str(qty).strip():
                    try:
                        return str(int(float(str(qty).replace(',', '').strip())))
                    except (ValueError, TypeError):
                        return ''
                return ''

            # Unknown unit
            qty = row.get('quantity', '')
            if pd.notna(qty) and str(qty).strip():
                try:
                    return str(int(float(str(qty).replace(',', '').strip())))
                except (ValueError, TypeError):
                    return ''
            return ''

        def get_qty2(row):
            qty_unit = str(row.get('qty_unit', '')).strip().upper() if pd.notna(row.get('qty_unit')) else ''
            if qty_unit in NO_QTY_UNITS:
                return ''
            if qty_unit in WEIGHT_UNITS or qty_unit in COUNT_UNITS:
                return ''
            if qty_unit in DUAL_UNITS:
                # Prefer template-provided per-item net_weight over calculated
                item_wt = row.get('net_weight', None)
                if pd.notna(item_wt) and item_wt not in (None, '', 0):
                    wt = int(round(float(item_wt)))
                else:
                    item_wt = row.get('CalcWtNet', 0)
                    if pd.isna(item_wt):
                        item_wt = 0
                    wt = int(round(item_wt))
                return str(max(wt, 1))
            return ''

        df['Qty1'] = df.apply(get_qty1, axis=1)
        df['Qty2'] = df.apply(get_qty2, axis=1)

        return df

    def calculate_declarations(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate declaration codes, country fields, and 232 flags.
        Uses per-row MID with parts_master country_origin taking priority.
        """
        df = df.copy()

        # Set HTSCode from hts_code
        df['HTSCode'] = df['hts_code'].fillna('').astype(str).replace('nan', '')

        # Per-row MID (already enriched from template extraction + parts_master)
        df['MID'] = df['mid'].fillna('').astype(str).replace('nan', '') if 'mid' in df.columns else ''

        dec_type_list = []
        country_melt_list = []
        country_cast_list = []
        prim_country_smelt_list = []
        prim_smelt_flag_list = []
        flag_list = []
        ch99_heading_list = []
        ch99_rate_list = []
        metal_weight_pct_list = []
        metal_weight_kg_list = []

        # Load Ch99 cache for product_type lookups
        ch99_cache = self._load_ch99_cache()

        for _, r in df.iterrows():
            content_type = r.get('_content_type', '')
            hts = r.get('hts_code', '')
            material, dec_type, smelt_flag = self.get_232_info(hts)

            # Fallback: if HTS not in tariff_232 but content_type indicates a metal,
            # derive declaration type from the content_type (e.g., chapter-level HTS codes)
            if not dec_type and content_type in ('steel', 'aluminum', 'copper', 'wood', 'auto'):
                dec_type_defaults = {'steel': '08', 'aluminum': '07', 'copper': '07', 'wood': '09', 'auto': '12'}
                dec_type = dec_type_defaults.get(content_type, '')
                smelt_flag = 'Y' if content_type in ('aluminum', 'copper', 'wood') else ''
                if not material:
                    material = content_type.capitalize()

            # Determine 232 flag
            flag_map = {
                'not_found': 'Not_Found',
                'incomplete': 'Incomplete',
                'steel': '232_Steel',
                'aluminum': '232_Aluminum',
                'copper': '232_Copper',
                'wood': '232_Wood',
                'auto': '232_Auto',
                'non_232': 'Non_232',
            }
            flag = flag_map.get(content_type, f"232_{material}" if material else '')

            # Dual declaration (both steel AND aluminum)
            is_dual = bool(r.get('_is_dual_declaration', False)) if pd.notna(r.get('_is_dual_declaration', False)) else False
            if is_dual and content_type in ('steel', 'aluminum'):
                dec_type = "07, 08"
                smelt_flag = "Y"

            dec_type_list.append(dec_type)

            # Country priority: 1) invoice line item country_origin, 2) MID[:2], 3) parts_master country_origin
            row_mid = str(r.get('MID', ''))
            mid_country = self.normalize_country(row_mid[:2]) if row_mid else ''

            # country_origin at this point reflects the merge priority (invoice > parts_master)
            resolved_country = r.get('country_origin', '')
            resolved_country = str(resolved_country).strip() if pd.notna(resolved_country) else ''
            resolved_country = self.normalize_country(resolved_country)

            # Final default: resolved country_origin > MID prefix
            default_country = resolved_country if resolved_country else mid_country

            # Per-field overrides from parts_master (only if explicitly set)
            country_of_melt = r.get('country_of_melt', '')
            country_of_cast = r.get('country_of_cast', '')
            country_of_smelt = r.get('country_of_smelt', '')

            melt_raw = str(country_of_melt).strip() if pd.notna(country_of_melt) and str(country_of_melt).strip() else default_country
            cast_raw = str(country_of_cast).strip() if pd.notna(country_of_cast) and str(country_of_cast).strip() else default_country
            smelt_raw = str(country_of_smelt).strip() if pd.notna(country_of_smelt) and str(country_of_smelt).strip() else default_country

            melt_code = self.normalize_country(melt_raw)
            cast_code = self.normalize_country(cast_raw)
            smelt_code = self.normalize_country(smelt_raw)

            country_melt_list.append(melt_code)
            country_cast_list.append(cast_code)
            prim_country_smelt_list.append(smelt_code)
            prim_smelt_flag_list.append(smelt_flag)
            flag_list.append(flag)

            # Ch99 Heading determination (April 2026 Proclamation)
            steel_pct = float(r.get('steel_pct', 0) or 0) if pd.notna(r.get('steel_pct', 0)) else 0.0
            aluminum_pct = float(r.get('aluminum_pct', 0) or 0) if pd.notna(r.get('aluminum_pct', 0)) else 0.0
            copper_pct = float(r.get('copper_pct', 0) or 0) if pd.notna(r.get('copper_pct', 0)) else 0.0

            # Single duty rule: resolve which metal applies
            resolved_material = self.resolve_single_duty_material(
                hts, steel_pct, aluminum_pct, copper_pct) if material else ''

            # 15% weight threshold check
            calc_wt = float(r.get('CalcWtNet', 0) or 0) if pd.notna(r.get('CalcWtNet', 0)) else 0.0
            wt_result = self.evaluate_weight_threshold(r, calc_wt)
            metal_weight_pct_list.append(wt_result['metal_weight_pct'])
            metal_weight_kg_list.append(wt_result['metal_weight_kg'])

            # Determine if primary or derivative from ch99 cache
            # Try 10-digit, 8-digit, 6-digit, 4-digit keys (table may store shorter codes)
            hts_digits = str(hts).replace('.', '')[:10]
            ch99_entries = ch99_cache.get(hts_digits, [])
            if not ch99_entries and len(hts_digits) > 8:
                ch99_entries = ch99_cache.get(hts_digits[:8], [])
            if not ch99_entries and len(hts_digits) > 6:
                ch99_entries = ch99_cache.get(hts_digits[:6], [])
            if not ch99_entries and len(hts_digits) > 4:
                ch99_entries = ch99_cache.get(hts_digits[:4], [])
            is_primary = any(e['product_type'] == 'primary' and e['material'] == resolved_material
                           for e in ch99_entries)

            # Get Ch99 heading — pass ch99_entries for table-based lookup
            ch99_heading, ch99_rate = self.determine_ch99_heading(
                hts_code=hts, material=resolved_material, country_origin=default_country,
                is_primary=is_primary, country_of_smelt=smelt_code,
                country_of_cast=cast_code, country_of_melt=melt_code,
                is_exempt=wt_result['exempt'],
                is_zero_metal=wt_result.get('zero_metal', False),
                ch99_entries=ch99_entries
            )
            ch99_heading_list.append(ch99_heading)
            ch99_rate_list.append(ch99_rate)

        df['DecTypeCd'] = dec_type_list
        df['CountryofMelt'] = country_melt_list
        df['CountryOfCast'] = country_cast_list
        df['PrimCountryOfSmelt'] = prim_country_smelt_list
        df['DeclarationFlag'] = prim_smelt_flag_list
        df['_232_flag'] = flag_list
        df['Ch99Heading'] = ch99_heading_list
        df['Ch99Rate'] = ch99_rate_list
        df['MetalWeightPct'] = metal_weight_pct_list
        df['MetalWeightKG'] = metal_weight_kg_list

        # Section 122 HTS — Temporary Worldwide Tariff (Reciprocal Tariffs).
        # Per the NCBFAA Sec. 122 flowchart bullet 3:
        #   "Except for products claiming exemption 9903.82.03, products
        #    SUBJECT TO steel, aluminum, or copper tariffs continue to be
        #    exempt from Section 122 tariffs under HTSUS 9903.03.06."
        #
        # The phrase "SUBJECT TO" is the operative qualifier — a row only
        # claims 9903.03.06 if it's actually paying the Section 232 metal
        # duty. Two cases file under the Sec 232 subchapter but DON'T pay:
        #   • 9903.82.01 — zero-metal derivatives (cast iron pipe fittings,
        #     non-steel articles in metal chapters) — 0% rate per BIS FRN
        #     2026-08297. NOT considered steel/aluminum/copper by US Customs.
        #   • 9903.82.03 — <15% weight exemption — 0% rate, article doesn't
        #     reach the metal-weight threshold for the duty.
        # Both default to 9903.03.01 (Sec 122 dutiable, +10%).
        #
        # Other Section 232 actions (semiconductors 9903.79.x, auto 9903.94.x,
        # timber 9903.76.x) similarly need a "subject to duty" check, but for
        # now we treat any non-empty heading in those subchapters as paying.
        # Operator overrides specific exemptions (9903.79.02-.09 semi
        # exemptions, 9903.94.04 25-year vehicles, 9903.76.04 non-kitchen
        # wood) in the exported XLSX when needed.
        SEC232_EXEMPT_FROM_DUTY = {'9903.82.01', '9903.82.03'}
        sec122_list = []
        for ch99 in ch99_heading_list:
            ch99_str = (ch99 or '').strip()
            if ch99_str in SEC232_EXEMPT_FROM_DUTY:
                sec122_list.append('9903.03.01')  # Filed under Sec 232 but not paying → Sec 122 still owed
            elif ch99_str.startswith('9903.82.'):
                sec122_list.append('9903.03.06')  # Sec 232 metals (actually paying) → exempt
            elif ch99_str.startswith(('9903.79.', '9903.94.', '9903.76.')):
                sec122_list.append('9903.03.06')  # Sec 232 semi/auto/timber → exempt
            else:
                sec122_list.append('9903.03.01')  # Default reciprocal tariff
        df['Sec122HTS'] = sec122_list

        # ReviewFlag — surfaces rows that need operator follow-up after export.
        # Filter/sort by this column in the XLSX to find what to fix.
        # Priorities (later wins, so most-actionable label is shown):
        #   "" (clean, lowest)
        #   "INCOMPLETE" — in parts_master but missing hts_code/qty_unit/client_code
        #   "NOT_IN_DB"  — canonical part not in parts_master at all
        #   "UNMAPPED_ALIAS" — alias part with no canonical mapping (highest —
        #     fix the part_aliases row first, then the rest cascades).
        # Local helper: NA-safe string coercion. `row.get(k, '') or ''` is
        # *not* safe when row[k] is pd.NA — the `or` triggers bool(pd.NA)
        # which raises "boolean value of NA is ambiguous". This bites when
        # a part isn't in parts_master (hts_code, qty_unit, client_code all
        # land as NA after the merge).
        def _safe_str(val) -> str:
            if val is None or pd.isna(val):
                return ''
            return str(val).strip()

        review_flags = []
        for _, row in df.iterrows():
            flag = ''
            # Incomplete in parts_master (in DB but missing required fields)
            hts = _safe_str(row.get('hts_code'))
            qty_unit = _safe_str(row.get('qty_unit'))
            client_code = _safe_str(row.get('client_code'))
            not_in_db = bool(row.get('_not_in_db', False)) if pd.notna(row.get('_not_in_db', False)) else False
            if not not_in_db and (not hts or not qty_unit or not client_code):
                flag = 'INCOMPLETE'
            if not_in_db:
                flag = 'NOT_IN_DB'
            # Alias-fallback heuristic: some templates fall back to using the
            # alias value as part_number when the part_aliases lookup fails.
            # Detect that by checking whether alias_part_number == part_number
            # AND the part_number starts with a recognizable alias prefix
            # ("MS" for a deployment's MSI line). When true, the canonical-side
            # data is suspect — surface a more actionable label.
            alias = _safe_str(row.get('alias_part_number') or row.get('msi_part_number')).upper()
            pn = _safe_str(row.get('part_number')).upper()
            if alias and pn and alias == pn and alias.startswith('MS'):
                flag = 'UNMAPPED_ALIAS'
            review_flags.append(flag)
        df['ReviewFlag'] = review_flags

        # Map Section 232 form raw values to output columns
        if '_232_acq_cost' in df.columns:
            df['AcquisitionCostPerUnit'] = df['_232_acq_cost'].apply(
                lambda x: x if pd.notna(x) and x > 0 else '')
            df['NonMetalCostPerUnit'] = df['_232_non_metal_cost'].apply(
                lambda x: x if pd.notna(x) and x > 0 else '')
            df['MetalWeightKG'] = df['_232_metal_kg'].apply(
                lambda x: x if pd.notna(x) and str(x).strip() else '')

        return df

    def enrich(self, items: List[Dict], net_weight: float, override_mid: str = '',
               section_232_updates: dict = None) -> pd.DataFrame:
        """
        Full enrichment pipeline: raw items -> enriched DataFrame.

        Args:
            items: List of extracted line items from template
            net_weight: Total net weight in kg
            override_mid: If set, force this MID on every row (overrides parts_master)
            section_232_updates: Optional dict {sku: {acq_cost_aluminum, po_value, ...}} from 232 forms

        Returns:
            Fully enriched DataFrame ready for export
        """
        if not items:
            return pd.DataFrame()

        # Apply user-selected MID override before any lookup so invoice_priority_fields wins
        if override_mid:
            for item in items:
                item['mid'] = override_mid
            self._log(f"  MID override applied: {override_mid} → all {len(items)} rows")

        self._log(f"Enriching {len(items)} items with net weight {net_weight} kg")

        # Convert to DataFrame
        df = pd.DataFrame(items)

        # Ensure required columns exist
        if 'value_usd' not in df.columns and 'total_price' in df.columns:
            df['value_usd'] = pd.to_numeric(df['total_price'], errors='coerce').fillna(0)
        elif 'value_usd' not in df.columns:
            df['value_usd'] = 0.0

        df['value_usd'] = pd.to_numeric(df['value_usd'], errors='coerce').fillna(0)

        # Normalize part numbers
        if 'part_number' in df.columns:
            df['part_number'] = df['part_number'].astype(str).str.strip().str.upper()

        # Filter out rows without part numbers
        if 'part_number' in df.columns:
            initial = len(df)
            df = df[df['part_number'].notna() & (df['part_number'].astype(str).str.strip() != '')]
            filtered = initial - len(df)
            if filtered > 0:
                self._log(f"  Filtered {filtered} rows without part numbers")

        # Step 1: Parts master lookup
        df = self.lookup_parts_master(df)

        # Step 1.5: Merge Section 232 form data (per-unit dollar values)
        if section_232_updates:
            self._merge_232_form_data(df, section_232_updates)

        # Step 2: Material row splitting
        df = self.classify_material(df)

        # Step 3: Weight calculation
        df = self.calculate_weights(df, net_weight)

        # Step 4: Quantity calculation
        df = self.calculate_quantities(df)

        # Step 5: Declaration codes
        df = self.calculate_declarations(df)

        # Add CustomerRef from project_number (PO number), not invoice_number
        if 'project_number' in df.columns:
            df['CustomerRef'] = df['project_number'].fillna('').astype(str)
        elif 'invoice_number' in df.columns:
            df['CustomerRef'] = df['invoice_number'].fillna('').astype(str)

        # Add CommercialQty (raw piece count from invoice)
        if 'quantity' in df.columns:
            df['CommercialQty'] = df['quantity'].fillna('').astype(str)

        # Map Product No
        if 'part_number' in df.columns:
            df['Product No'] = df['part_number']

        # Map ValueUSD
        df['ValueUSD'] = df['value_usd']

        # Add 232_Status from _232_flag
        df['232_Status'] = df['_232_flag']

        # Map GrossWeight per line.
        #   1) Prefer per-item gross_weight if the template extracted one.
        #   2) Else, if the template provided a document-level total_gross_weight
        #      (e.g. the Sanford LP - Newell Europe template parses the "EU
        #      TOTALS" summary row), prorate that total across rows by value
        #      so the per-line GrossWeight sums to the document total.
        #   3) Otherwise leave blank.
        if 'gross_weight' in df.columns and df['gross_weight'].notna().any() and (pd.to_numeric(df['gross_weight'], errors='coerce').fillna(0) > 0).any():
            df['GrossWeight'] = pd.to_numeric(df['gross_weight'], errors='coerce').fillna('').replace(0, '')
        elif 'total_gross_weight' in df.columns:
            doc_gross = pd.to_numeric(df['total_gross_weight'], errors='coerce').fillna(0.0)
            doc_gross_total = float(doc_gross.max()) if len(doc_gross) else 0.0
            value_series = pd.to_numeric(df.get('value_usd', 0), errors='coerce').fillna(0.0) if 'value_usd' in df.columns else pd.Series([0.0] * len(df), index=df.index)
            value_total = float(value_series.sum())
            if doc_gross_total > 0 and value_total > 0:
                df['GrossWeight'] = ((value_series / value_total) * doc_gross_total).round(3)
            else:
                df['GrossWeight'] = ''
        else:
            df['GrossWeight'] = ''

        # Map RelatedParties from mid_table based on MID
        if 'mid' in df.columns:
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT mid, related_parties FROM mid_table")
                rp_map = {row[0]: (row[1] or 'N').strip().upper() for row in c.fetchall()}
                conn.close()
                df['RelatedParties'] = df['mid'].map(lambda m: rp_map.get(m, 'N') if pd.notna(m) and m else 'N')
            except Exception:
                df['RelatedParties'] = 'N'
        else:
            df['RelatedParties'] = 'N'

        # Add InvoiceQtyUnit
        if 'quantity_unit' in df.columns:
            df['InvoiceQtyUnit'] = df['quantity_unit'].fillna('').astype(str)
        elif 'qty_unit' in df.columns:
            df['InvoiceQtyUnit'] = df['qty_unit'].fillna('').astype(str)

        # Add InvoiceUOM (normalized to CBP UOM codes)
        try:
            from entryops.entryops import normalize_invoice_uom
        except ImportError:
            from entryops import normalize_invoice_uom
        uom_source = df.get('quantity_unit', df.get('qty_unit', pd.Series([''] * len(df))))
        df['InvoiceUOM'] = uom_source.apply(lambda x: normalize_invoice_uom(x, db_path=str(self.db_path)))

        self._log(f"  Enrichment complete: {len(df)} rows")

        # Log enrichment stats
        total_parts = self._hts_hits + self._hts_misses
        if total_parts > 0:
            hit_rate = self._hts_hits / total_parts * 100
            self._log(f"  HTS lookup: {self._hts_hits}/{total_parts} ({hit_rate:.0f}% hit rate)")
        if self._parts_not_found:
            self._log(f"  Parts not in DB: {self._parts_not_found}")
        if self._unresolved_countries:
            self._log(f"  WARNING: {len(self._unresolved_countries)} unresolved country value(s): {', '.join(sorted(self._unresolved_countries))}")

        return df
