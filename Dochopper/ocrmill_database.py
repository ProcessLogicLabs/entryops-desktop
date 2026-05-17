"""
OCRMill Database Extensions for DocHopper
Extends DocHopper's database with OCR invoice processing capabilities.
"""

import sqlite3
import threading
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import pandas as pd
import re


class PartDescriptionExtractor:
    """
    Extracts product descriptions from part numbers and maps to HTS codes.
    """

    PREFIX_DESCRIPTIONS = {
        'SL': 'Seat/Seating element',
        'SLE': 'Seat element',
        'SLU': 'Seating unit',
        'BTT': 'Bench',
        'BEN': 'Bench',
        'STE': 'Bicycle stand/rack',
        'BIKE': 'Bicycle rack',
        'LPU': 'Planter/Flower pot',
        'PLT': 'Planter',
        'ND': 'Bollard',
        'BOL': 'Bollard',
        'PQA': 'Table',
        'TAB': 'Table',
        'TBL': 'Table',
        'KSA': 'Litter bin/Waste receptacle',
        'BIN': 'Litter bin',
        'WASTE': 'Waste receptacle',
        'MRU': 'Tree grate',
        'TREE': 'Tree grate',
        'BAR': 'Barrier',
        'FENCE': 'Fence/Fencing',
        'LIGHT': 'Light/Lighting',
        'LAMP': 'Lamp',
        'ACC': 'Accessory',
        'MOUNT': 'Mounting accessory',
        'ANCHOR': 'Anchor/Fixing',
        'OBAL': 'Packaging/Crating',
        'SIGN': 'Signage',
        'POST': 'Post',
    }

    DESCRIPTION_TO_HTS = {
        'SEAT': '9403.20.0080',
        'BENCH': '9401.69.8031',
        'BICYCLE': '9403.20.0082',
        'BIKE': '9403.20.0082',
        'STAND': '9403.20.0082',
        'RACK': '9403.20.0082',
        'PLANTER': '9403.20.0080',
        'FLOWER': '9403.20.0080',
        'POT': '9403.20.0080',
        'BOLLARD': '7308.90.6000',
        'TABLE': '9403.20.0080',
        'LITTER': '7310.29.0050',
        'WASTE': '7310.29.0050',
        'BIN': '7310.29.0050',
        'RECEPTACLE': '7310.29.0050',
        'TREE GRATE': '7326.90.8688',
        'GRATE': '7326.90.8688',
        'BARRIER': '7308.90.9590',
        'FENCE': '7308.90.9590',
        'FENCING': '7308.90.9590',
        'LIGHT': '9405.40.8000',
        'LAMP': '9405.40.8000',
        'LIGHTING': '9405.40.8000',
        'SIGN': '9405.60.8000',
        'SIGNAGE': '9405.60.8000',
        'POST': '7308.90.3000',
        'ANCHOR': '7318.15.2095',
        'BOLT': '7318.15.2095',
        'FIXING': '7318.15.2095',
        'MOUNT': '7326.90.8688',
    }

    def extract_description(self, part_number: str) -> str:
        """Extract description from part number."""
        if not part_number:
            return ""

        part_upper = part_number.upper()

        for prefix in sorted(self.PREFIX_DESCRIPTIONS.keys(), key=len, reverse=True):
            if part_upper.startswith(prefix):
                base_desc = self.PREFIX_DESCRIPTIONS[prefix]
                details = self._extract_details(part_number, prefix)
                if details:
                    return f"{base_desc} - {details}"
                return base_desc

        return f"Product {part_number}"

    def _extract_details(self, part_number: str, prefix: str) -> str:
        """Extract additional details from part number."""
        detail_part = part_number[len(prefix):]
        model_match = re.search(r'(\d{3,4})', detail_part)
        if model_match:
            return f"Model {model_match.group(1)}"
        return ""

    def find_hts_from_description(self, description: str) -> Optional[str]:
        """Find HTS code based on product description."""
        if not description:
            return None

        desc_upper = description.upper()
        for keyword in sorted(self.DESCRIPTION_TO_HTS.keys(), key=len, reverse=True):
            if keyword in desc_upper:
                return self.DESCRIPTION_TO_HTS[keyword]
        return None

    def match_with_hts_database(self, description: str, hts_database: List[Dict]) -> Optional[str]:
        """Match description against HTS database entries."""
        if not description or not hts_database:
            return None

        desc_words = set(description.upper().split())
        best_match = None
        best_score = 0

        for entry in hts_database:
            hts_desc = entry.get('description', '')
            if not hts_desc:
                continue

            hts_words = set(hts_desc.upper().split())
            overlap = len(desc_words & hts_words)

            if overlap > best_score:
                best_score = overlap
                best_match = entry.get('hts_code')

        return best_match if best_score > 0 else None


class OCRMillDatabase:
    """
    Database extensions for OCRMill invoice processing.
    Uses DocHopper's existing database with additional OCRMill tables.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.description_extractor = PartDescriptionExtractor()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def add_part_occurrence(self, part_data: Dict) -> bool:
        """
        Add a new part occurrence from invoice processing.

        Args:
            part_data: Dictionary containing part information

        Returns:
            bool: True if successful
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            part_number = part_data.get('part_number')
            if not part_number:
                conn.close()
                return False

            # Extract description if not provided
            if not part_data.get('description'):
                part_data['description'] = self.description_extractor.extract_description(part_number)

            # Check for FSC certification in description
            description = part_data.get('description', '')
            if 'FSC 100%' in description or 'FSC100%' in description.replace(' ', ''):
                part_data['fsc_certified'] = 'FSC 100%'
                part_data['fsc_certificate_code'] = 'PBN-COC-065387'
            elif 'FSC' in description.upper():
                part_data['fsc_certified'] = 'FSC'

            # Try to find HTS code if not provided
            if not part_data.get('hts_code'):
                hts_code = self.description_extractor.find_hts_from_description(part_data['description'])
                if not hts_code:
                    cursor.execute("SELECT * FROM hts_codes")
                    hts_database = [dict(row) for row in cursor.fetchall()]
                    hts_code = self.description_extractor.match_with_hts_database(
                        part_data['description'], hts_database
                    )
                if hts_code:
                    part_data['hts_code'] = hts_code

            # Calculate unit price if not provided
            unit_price = part_data.get('unit_price')
            if not unit_price and part_data.get('total_price') and part_data.get('quantity'):
                try:
                    unit_price = float(part_data['total_price']) / float(part_data['quantity'])
                except (ValueError, ZeroDivisionError):
                    unit_price = None

            # Insert occurrence
            cursor.execute("""
                INSERT INTO part_occurrences (
                    part_number, invoice_number, project_number, quantity, total_price, unit_price,
                    steel_pct, steel_kg, steel_value,
                    aluminum_pct, aluminum_kg, aluminum_value,
                    net_weight, ncm_code, hts_code, processed_date, source_file, mid, client_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                part_number,
                part_data.get('invoice_number'),
                part_data.get('project_number'),
                part_data.get('quantity'),
                part_data.get('total_price'),
                unit_price,
                part_data.get('steel_pct'),
                part_data.get('steel_kg'),
                part_data.get('steel_value'),
                part_data.get('aluminum_pct'),
                part_data.get('aluminum_kg'),
                part_data.get('aluminum_value'),
                part_data.get('net_weight'),
                part_data.get('ncm_code'),
                part_data.get('hts_code'),
                datetime.now().isoformat(),
                part_data.get('source_file'),
                part_data.get('mid'),
                part_data.get('client_code')
            ))

            # Update or create part master record
            self._update_part_master(cursor, part_number, part_data)

            conn.commit()
            conn.close()
            return True

    def _update_part_master(self, cursor, part_number: str, part_data: Dict):
        """Update the parts_master table with latest occurrence data.

        NOTE: This function only UPDATES existing parts. New parts are NOT automatically
        added to the database - they will appear as "Not Found" in the preview and must
        be explicitly added by the user.
        """
        # Check if part exists
        cursor.execute("SELECT part_number FROM parts_master WHERE part_number = ?", (part_number,))
        exists = cursor.fetchone() is not None

        # Only update existing parts - do NOT auto-add new parts
        if not exists:
            return  # Part will show as "Not Found" - user must approve adding it

        # Get latest material percentages from most recent occurrence
        cursor.execute("""
            SELECT steel_pct, aluminum_pct, processed_date
            FROM part_occurrences
            WHERE part_number = ?
            ORDER BY processed_date DESC
            LIMIT 1
        """, (part_number,))
        latest = cursor.fetchone()

        # Update existing part - HTS_CODE is NEVER updated from PDF (database is master)
        def clean_value(value):
            if value is None:
                return None
            str_val = str(value).strip()
            return str_val if str_val else None

        new_mid = clean_value(part_data.get('mid'))
        new_country = clean_value(part_data.get('country_origin'))
        new_client = clean_value(part_data.get('client_code'))
        new_fsc_cert = clean_value(part_data.get('fsc_certified'))
        new_fsc_code = clean_value(part_data.get('fsc_certificate_code'))
        new_description = clean_value(part_data.get('description'))

        # Convert percentages to DocHopper's 0-100 format if needed
        steel_pct = latest['steel_pct'] if latest else part_data.get('steel_pct')
        aluminum_pct = latest['aluminum_pct'] if latest else part_data.get('aluminum_pct')

        cursor.execute("""
            UPDATE parts_master SET
                description = COALESCE(?, description),
                steel_pct = COALESCE(?, steel_pct),
                aluminum_pct = COALESCE(?, aluminum_pct),
                mid = COALESCE(?, mid),
                country_origin = COALESCE(?, country_origin),
                client_code = COALESCE(?, client_code),
                fsc_certified = COALESCE(?, fsc_certified),
                fsc_certificate_code = COALESCE(?, fsc_certificate_code),
                last_updated = ?
            WHERE part_number = ?
        """, (
            new_description,
            steel_pct,
            aluminum_pct,
            new_mid,
            new_country,
            new_client,
            new_fsc_cert,
            new_fsc_code,
            datetime.now().isoformat(),
            part_number
        ))

    def search_parts(self, search_term: str) -> List[Dict]:
        """Search parts by part number or description."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM parts_master
            WHERE part_number LIKE ? OR description LIKE ?
            ORDER BY part_number
        """, (f'%{search_term}%', f'%{search_term}%'))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def find_hts_code(self, part_number: str, description: str = "") -> Optional[str]:
        """Find HTS code for a part using fuzzy matching."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # First check if part already has HTS code in parts_master
        cursor.execute("SELECT hts_code FROM parts_master WHERE part_number = ? AND hts_code IS NOT NULL", (part_number,))
        result = cursor.fetchone()
        if result and result['hts_code']:
            conn.close()
            return result['hts_code']

        # Try to match based on description keywords
        if description:
            keywords = description.upper().split()
            for keyword in keywords:
                if len(keyword) > 3:
                    cursor.execute("""
                        SELECT hts_code, description
                        FROM hts_codes
                        WHERE UPPER(description) LIKE ?
                        ORDER BY LENGTH(description)
                        LIMIT 1
                    """, (f'%{keyword}%',))
                    result = cursor.fetchone()
                    if result:
                        conn.close()
                        return result['hts_code']

        conn.close()

        # Use description extractor as fallback
        return self.description_extractor.find_hts_from_description(description)

    def load_hts_mapping(self, xlsx_path: Path) -> bool:
        """Load HTS code mapping from Excel file."""
        try:
            df = pd.read_excel(xlsx_path)
            conn = self._get_connection()
            cursor = conn.cursor()

            seen_hts = set()

            for _, row in df.iterrows():
                hts_code = str(row.get('HTS', row.get('hts_code', '')))
                if hts_code in seen_hts or not hts_code:
                    continue

                seen_hts.add(hts_code)

                cursor.execute("""
                    INSERT OR REPLACE INTO hts_codes (hts_code, description, suggested, last_updated)
                    VALUES (?, ?, ?, ?)
                """, (
                    hts_code,
                    str(row.get('DESCRIPTION', row.get('description', ''))),
                    str(row.get('SUGGESTED', row.get('suggested', ''))),
                    datetime.now().isoformat()
                ))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error loading HTS mapping: {e}")
            return False

    def get_manufacturer_by_name(self, company_name: str) -> Optional[Dict]:
        """Get manufacturer by company name from mid_table.

        Matching strategy (in order):
        1. Exact match (accent/case insensitive)
        2. Exact match after company abbreviation expansion (Ltd→Limited, etc.)
        3. Substring containment
        4. Word-token Jaccard overlap >= 0.5 (handles Ltd. vs Limited, extra words)
        """
        if not company_name:
            return None

        import unicodedata
        import re as _re

        # Common company suffix abbreviations → canonical forms
        _ABBREV = [
            (_re.compile(r'\bltd\.?\b', _re.IGNORECASE), 'limited'),
            (_re.compile(r'\bllc\.?\b', _re.IGNORECASE), 'llc'),
            (_re.compile(r'\binc\.?\b', _re.IGNORECASE), 'incorporated'),
            (_re.compile(r'\bcorp\.?\b', _re.IGNORECASE), 'corporation'),
            (_re.compile(r'\bco\.?\b', _re.IGNORECASE), 'company'),
            (_re.compile(r'\bpvt\.?\b', _re.IGNORECASE), 'private'),
            (_re.compile(r'\bmfg\.?\b', _re.IGNORECASE), 'manufacturing'),
            (_re.compile(r'\bintl\.?\b', _re.IGNORECASE), 'international'),
        ]

        def normalize(s):
            s = ''.join(
                c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn'
            ).lower()
            # Strip punctuation except spaces
            s = _re.sub(r'[^\w\s]', '', s)
            return s.strip()

        def expand_abbrevs(s):
            for pattern, replacement in _ABBREV:
                s = pattern.sub(replacement, s)
            return s

        def tokenize(s):
            return set(s.split())

        def jaccard(a_tokens, b_tokens):
            if not a_tokens or not b_tokens:
                return 0.0
            inter = len(a_tokens & b_tokens)
            union = len(a_tokens | b_tokens)
            return inter / union if union else 0.0

        norm_search = normalize(company_name)
        exp_search = normalize(expand_abbrevs(company_name))
        tok_search = tokenize(exp_search)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM mid_table")

        best_score = 0.0
        best_row = None

        for row in cursor.fetchall():
            db_name = row['manufacturer_name'] or ''
            norm_db = normalize(db_name)
            exp_db = normalize(expand_abbrevs(db_name))

            # 1. Exact match (normalized)
            if norm_db == norm_search or exp_db == exp_search:
                conn.close()
                return dict(row)

            # 2. Substring containment — score by length ratio
            if norm_search in norm_db or norm_db in norm_search or \
               exp_search in exp_db or exp_db in exp_search:
                score = min(len(exp_search), len(exp_db)) / max(len(exp_search), len(exp_db), 1)
                if score > best_score:
                    best_score = score
                    best_row = row

            # 3. Word-token Jaccard >= 0.5
            tok_db = tokenize(exp_db)
            j = jaccard(tok_search, tok_db)
            if j >= 0.5 and j > best_score:
                best_score = j
                best_row = row

        conn.close()

        return dict(best_row) if best_row else None

    def get_manufacturer_by_mid(self, mid: str) -> Optional[Dict]:
        """Get manufacturer by MID from mid_table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM mid_table WHERE mid = ?", (mid,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None

    def ensure_template_stats_table(self):
        """Create the template_stats table if it doesn't exist."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS template_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_name TEXT NOT NULL,
                    pdf_file TEXT,
                    items_extracted INTEGER DEFAULT 0,
                    confidence_score REAL,
                    processing_time_ms INTEGER,
                    success INTEGER DEFAULT 1,
                    error_message TEXT,
                    processed_date TEXT NOT NULL,
                    username TEXT
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_template_stats_name ON template_stats(template_name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_template_stats_date ON template_stats(processed_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_template_stats_user ON template_stats(username)
            """)
            # Add username column if it doesn't exist (for migration from older versions)
            try:
                cursor.execute("ALTER TABLE template_stats ADD COLUMN username TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            conn.commit()
            conn.close()

    def record_template_usage(self, template_name: str, pdf_file: str = None,
                              items_extracted: int = 0, confidence_score: float = None,
                              processing_time_ms: int = None, success: bool = True,
                              error_message: str = None, username: str = None):
        """Record template usage statistics."""
        self.ensure_template_stats_table()
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO template_stats (
                        template_name, pdf_file, items_extracted, confidence_score,
                        processing_time_ms, success, error_message, processed_date, username
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    template_name,
                    pdf_file,
                    items_extracted,
                    confidence_score,
                    processing_time_ms,
                    1 if success else 0,
                    error_message,
                    datetime.now().isoformat(),
                    username
                ))
            except sqlite3.OperationalError:
                # Fallback: insert without username if column doesn't exist
                cursor.execute("""
                    INSERT INTO template_stats (
                        template_name, pdf_file, items_extracted, confidence_score,
                        processing_time_ms, success, error_message, processed_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    template_name,
                    pdf_file,
                    items_extracted,
                    confidence_score,
                    processing_time_ms,
                    1 if success else 0,
                    error_message,
                    datetime.now().isoformat(),
                ))
            conn.commit()
            conn.close()

    def get_template_statistics(self) -> List[Dict]:
        """Get aggregated template usage statistics."""
        self.ensure_template_stats_table()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                template_name,
                COUNT(*) as total_uses,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_uses,
                SUM(items_extracted) as total_items,
                ROUND(AVG(confidence_score), 2) as avg_confidence,
                ROUND(AVG(processing_time_ms), 0) as avg_time_ms,
                MAX(processed_date) as last_used
            FROM template_stats
            GROUP BY template_name
            ORDER BY total_uses DESC
        """)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_template_usage_history(self, template_name: str, limit: int = 50) -> List[Dict]:
        """Get recent usage history for a specific template."""
        self.ensure_template_stats_table()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM template_stats
            WHERE template_name = ?
            ORDER BY processed_date DESC
            LIMIT ?
        """, (template_name, limit))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_processing_stats_summary(self) -> Dict:
        """Get overall processing statistics summary."""
        self.ensure_template_stats_table()
        conn = self._get_connection()
        cursor = conn.cursor()

        # Overall stats
        cursor.execute("""
            SELECT
                COUNT(*) as total_processed,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                SUM(items_extracted) as total_items,
                COUNT(DISTINCT template_name) as templates_used,
                ROUND(AVG(confidence_score), 2) as avg_confidence
            FROM template_stats
        """)
        overall = dict(cursor.fetchone())

        # Today's stats
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("""
            SELECT
                COUNT(*) as processed_today,
                SUM(items_extracted) as items_today
            FROM template_stats
            WHERE processed_date LIKE ?
        """, (f'{today}%',))
        today_stats = dict(cursor.fetchone())

        # This week's stats
        cursor.execute("""
            SELECT
                COUNT(*) as processed_week,
                SUM(items_extracted) as items_week
            FROM template_stats
            WHERE processed_date >= date('now', '-7 days')
        """)
        week_stats = dict(cursor.fetchone())

        conn.close()

        return {
            **overall,
            **today_stats,
            **week_stats
        }

    def get_user_statistics(self) -> List[Dict]:
        """Get aggregated statistics by user for admin dashboard.

        Usernames are normalized — domain prefix stripped and uppercased — so
        "DMUSA\\hpayne", "hpayne", and "HPAYNE" collapse into one bucket.
        """
        self.ensure_template_stats_table()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COALESCE(UPPER(
                    CASE WHEN instr(username, '\\') > 0
                         THEN substr(username, instr(username, '\\') + 1)
                         ELSE username END), 'Unknown') as username,
                COUNT(*) as total_processed,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
                SUM(items_extracted) as total_items,
                ROUND(AVG(confidence_score), 2) as avg_confidence,
                ROUND(AVG(processing_time_ms), 0) as avg_time_ms,
                MAX(processed_date) as last_activity,
                COUNT(DISTINCT template_name) as templates_used,
                COUNT(DISTINCT DATE(processed_date)) as active_days
            FROM template_stats
            GROUP BY COALESCE(UPPER(
                CASE WHEN instr(username, '\\') > 0
                     THEN substr(username, instr(username, '\\') + 1)
                     ELSE username END), 'Unknown')
            ORDER BY total_processed DESC
        """)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_user_activity_history(self, username: str = None, days: int = 30) -> List[Dict]:
        """Get daily activity history, optionally filtered by user."""
        self.ensure_template_stats_table()
        conn = self._get_connection()
        cursor = conn.cursor()

        if username:
            cursor.execute("""
                SELECT
                    DATE(processed_date) as date,
                    COUNT(*) as pdfs_processed,
                    SUM(items_extracted) as items_extracted,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed
                FROM template_stats
                WHERE username = ? AND processed_date >= date('now', ?)
                GROUP BY DATE(processed_date)
                ORDER BY date DESC
            """, (username, f'-{days} days'))
        else:
            cursor.execute("""
                SELECT
                    DATE(processed_date) as date,
                    COUNT(*) as pdfs_processed,
                    SUM(items_extracted) as items_extracted,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
                    COUNT(DISTINCT username) as active_users
                FROM template_stats
                WHERE processed_date >= date('now', ?)
                GROUP BY DATE(processed_date)
                ORDER BY date DESC
            """, (f'-{days} days',))

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_all_time_totals(self) -> Dict:
        """Get all-time totals for the admin dashboard."""
        self.ensure_template_stats_table()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total_pdfs,
                SUM(items_extracted) as total_items,
                COUNT(DISTINCT username) as total_users,
                COUNT(DISTINCT template_name) as total_templates,
                ROUND(100.0 * SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as success_rate,
                MIN(processed_date) as first_activity,
                MAX(processed_date) as last_activity
            FROM template_stats
        """)
        result = dict(cursor.fetchone())
        conn.close()
        return result

    def ensure_corrections_table(self):
        """Create the extraction_corrections table if it doesn't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS extraction_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_name TEXT NOT NULL,
                pdf_file TEXT,
                field_name TEXT NOT NULL,
                original_value TEXT,
                corrected_value TEXT,
                part_number TEXT,
                correction_date TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_corrections_template ON extraction_corrections(template_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_corrections_field ON extraction_corrections(field_name)
        """)
        conn.commit()
        conn.close()

    def record_correction(self, template_name: str, pdf_file: str = None,
                          field_name: str = None, original_value: str = None,
                          corrected_value: str = None, part_number: str = None):
        """Record a user correction for learning purposes."""
        self.ensure_corrections_table()
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO extraction_corrections (
                    template_name, pdf_file, field_name, original_value,
                    corrected_value, part_number, correction_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                template_name,
                pdf_file,
                field_name,
                original_value,
                corrected_value,
                part_number,
                datetime.now().isoformat()
            ))
            conn.commit()
            conn.close()

    def get_common_corrections(self, template_name: str = None, limit: int = 50) -> List[Dict]:
        """Get common corrections for a template to identify improvement patterns."""
        self.ensure_corrections_table()
        conn = self._get_connection()
        cursor = conn.cursor()

        if template_name:
            cursor.execute("""
                SELECT field_name, original_value, corrected_value, COUNT(*) as frequency
                FROM extraction_corrections
                WHERE template_name = ?
                GROUP BY field_name, original_value, corrected_value
                ORDER BY frequency DESC
                LIMIT ?
            """, (template_name, limit))
        else:
            cursor.execute("""
                SELECT template_name, field_name, original_value, corrected_value, COUNT(*) as frequency
                FROM extraction_corrections
                GROUP BY template_name, field_name, original_value, corrected_value
                ORDER BY frequency DESC
                LIMIT ?
            """, (limit,))

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_correction_stats(self) -> Dict:
        """Get statistics about corrections."""
        self.ensure_corrections_table()
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total_corrections,
                COUNT(DISTINCT template_name) as templates_with_corrections,
                COUNT(DISTINCT field_name) as fields_corrected
            FROM extraction_corrections
        """)
        stats = dict(cursor.fetchone())

        # Most corrected templates
        cursor.execute("""
            SELECT template_name, COUNT(*) as correction_count
            FROM extraction_corrections
            GROUP BY template_name
            ORDER BY correction_count DESC
            LIMIT 5
        """)
        stats['top_templates'] = [dict(row) for row in cursor.fetchall()]

        # Most corrected fields
        cursor.execute("""
            SELECT field_name, COUNT(*) as correction_count
            FROM extraction_corrections
            GROUP BY field_name
            ORDER BY correction_count DESC
            LIMIT 5
        """)
        stats['top_fields'] = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return stats

    def suggest_correction(self, template_name: str, field_name: str, value: str) -> Optional[str]:
        """
        Suggest a correction based on learned patterns.

        Args:
            template_name: Name of the template
            field_name: Name of the field being extracted
            value: The extracted value

        Returns:
            Suggested corrected value if a pattern is found, None otherwise
        """
        self.ensure_corrections_table()
        conn = self._get_connection()
        cursor = conn.cursor()

        # Look for exact match corrections
        cursor.execute("""
            SELECT corrected_value, COUNT(*) as frequency
            FROM extraction_corrections
            WHERE template_name = ? AND field_name = ? AND original_value = ?
            GROUP BY corrected_value
            ORDER BY frequency DESC
            LIMIT 1
        """, (template_name, field_name, value))

        result = cursor.fetchone()
        conn.close()

        if result and result['frequency'] >= 2:  # At least 2 occurrences
            return result['corrected_value']

        return None
