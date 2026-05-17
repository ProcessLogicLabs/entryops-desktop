"""Build the dict that gets handed to the Playwright runner.

Takes the raw ISF dict produced by `ISF10Plus2Template.extract_line_items()`
and normalizes it for the e2open ISF web UI:

- Country names → ISO 2-letter codes (via the existing `country_codes` table).
- Dates → MM/DD/YYYY (already canonical from the loader, but defensive).
- Stable list of `isf_htsus_codes` (always present, possibly empty).
- One pass to fill any "_full" address fallback for fields that wrap weirdly.

The returned dict's keys exactly match the `fields.*` keys used by
`field_map.json` — that one-to-one mapping is what lets the field map drive
the form fill without a separate translation layer.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


_ADDRESS_PREFIXES = ("importer", "seller", "manufacturer", "buyer", "shipto", "stuffing", "consolidator")
_IMPORTER_PROFILES_PATH = Path(__file__).parent / "importers.json"


def _normalize_match_key(value: str) -> str:
    """Reduce a company name to a comparison key: uppercase, strip
    punctuation and excess whitespace. ``"Sigma Corporation,"`` and
    ``"SIGMA CORPORATION"`` collapse to the same key."""
    if not value:
        return ""
    cleaned = re.sub(r"[^A-Z0-9 ]+", " ", value.upper())
    return re.sub(r"\s+", " ", cleaned).strip()


def _read_profiles_file(path: Path) -> Dict[str, Dict[str, str]]:
    """Parse one importers.json-shaped file. Empty dict on any read error so
    callers can layer multiple sources without aborting on a missing one."""
    profiles: Dict[str, Dict[str, str]] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.info("ISF importer profiles not loaded (%s): %s", path, exc)
        return profiles

    for entry in data.get("profiles", []) or []:
        match_raw = entry.get("match", "")
        match_key = _normalize_match_key(match_raw)
        fields = entry.get("fields", {}) or {}
        if match_key and isinstance(fields, dict):
            profiles[match_key] = {k: ("" if v is None else str(v)) for k, v in fields.items()}
    return profiles


def _load_importer_profiles(path: Path = _IMPORTER_PROFILES_PATH) -> Dict[str, Dict[str, str]]:
    """Load ISF importer-of-record profiles, with overlay support.

    Resolution order (later wins so an admin can override a bundled entry):
      1. The bundled `importers.json` next to this module.
      2. (optional) An external file referenced by the `isf_importers_path`
         billing setting — lets a private deployment ship its real importer
         profiles outside the source tree without forking the repo.

    Returns ``{normalized_match_name: {field: value, ...}}``. Empty dict if
    nothing is configured / readable — the system degrades gracefully and
    just uses the supplier-form values verbatim.
    """
    profiles: Dict[str, Dict[str, str]] = {}
    profiles.update(_read_profiles_file(path))

    overlay_path = _resolve_overlay_path()
    if overlay_path is not None:
        overlay = _read_profiles_file(overlay_path)
        if overlay:
            logger.info("ISF importer profiles overlay applied from %s (%d entries)",
                        overlay_path, len(overlay))
            profiles.update(overlay)

    return profiles


def _resolve_overlay_path() -> Optional[Path]:
    """Read the `isf_importers_path` billing setting and return a Path if it
    resolves to an existing file. Tolerates a missing DB or table — overlay
    is strictly optional. Reads the table directly (no DocHopper import)
    to avoid a circular dependency at module-load time."""
    try:
        try:
            from Dochopper.dochopper import DB_PATH
        except ImportError:
            from dochopper import DB_PATH  # type: ignore[no-redef]
    except Exception:
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            c = conn.cursor()
            c.execute("SELECT value FROM billing_settings WHERE key = ?", ("isf_importers_path",))
            row = c.fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    raw = (row[0] or "").strip() if row else ""
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_file() else None


def _load_country_codes(db_path: Path) -> Dict[str, str]:
    """Read country_name → ISO 2-letter mapping from the shared DocHopper DB.
    Returns {} if the DB or table is unavailable so callers can degrade gracefully.
    """
    out: Dict[str, str] = {}
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            c = conn.cursor()
            c.execute("SELECT country_name, country_code FROM country_codes")
            for name, code in c.fetchall():
                if name and code:
                    out[name.strip().upper()] = code.strip().upper()
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    return out


def _normalize_country(value: str, lookup: Dict[str, str]) -> str:
    """Map a supplier-supplied country string to an ISO 2-letter code.

    Looks up ``country_codes`` in the shared DocHopper DB; passes through
    unchanged when no match is found. Pre-normalizes a few common variants
    that real supplier ISFs use (and that DBs typically don't list verbatim):
    ``U.S.A``/``U.S.A.``/``U.S.`` → ``USA``, and the singular-typo
    ``UNITED STATE OF AMERICA`` → ``UNITED STATES OF AMERICA``.
    """
    if not value:
        return ""
    v = value.strip()
    if len(v) == 2 and v.isalpha():
        return v.upper()

    upper = v.upper().strip().rstrip(".").strip()
    # Collapse "U.S.A", "U.S.A.", "U S A" variants → "USA" (which is in the DB)
    if re.fullmatch(r"U\.?\s*S\.?\s*A\.?", upper):
        upper = "USA"
    elif re.fullmatch(r"U\.?\s*S\.?", upper):
        upper = "US"
    elif upper in ("UNITED STATE OF AMERICA", "UNITED STATE"):
        upper = "UNITED STATES OF AMERICA"

    return lookup.get(upper, v)


def _normalize_date(value: str) -> str:
    """Coerce common ISF date formats to MM/DD/YYYY; pass through if unparseable.

    Supplier date conventions vary (US suppliers send MM/DD/YYYY, Indian /
    European suppliers send DD-MM-YY). We try 4-digit-year formats first
    (preferred), then 2-digit-year. For ambiguous tokens like '04-04-26'
    the order picks MM-first; for '24-04-26' the day=24 forces a fall-
    through to DD-MM-YY.
    """
    if not value:
        return ""
    v = value.strip()
    for fmt in (
        "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
        "%m/%d/%y", "%m-%d-%y", "%d/%m/%y", "%d-%m-%y",
        "%b.%d,%Y", "%b %d, %Y",
    ):
        try:
            return datetime.strptime(v, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return v


@dataclass
class ISFPayload:
    """Normalized ISF data ready to drive a form-fill."""
    fields: Dict[str, str] = field(default_factory=dict)
    htsus_codes: List[str] = field(default_factory=list)
    source_path: Optional[Path] = None
    importer_ref: str = ""

    @classmethod
    def from_extracted(cls, item: Dict, *, db_path: Path, source_path: Optional[Path] = None) -> "ISFPayload":
        """Build a normalized payload from the dict returned by the ISF template."""
        country_lookup = _load_country_codes(db_path)

        out: Dict[str, str] = {}

        SCALARS = (
            "isf_etd", "isf_eta", "isf_vessel",
            "isf_hbl", "isf_hbl_scac", "isf_hbl_number",
            "isf_mbl", "isf_mbl_scac", "isf_mbl_number",
            "isf_port_of_discharge", "isf_port_name", "isf_port_code",
            "isf_country_of_origin", "isf_commodity_description",
            "isf_importer_ref", "isf_htsus_raw",
        )
        for k in SCALARS:
            v = item.get(k, "")
            if isinstance(v, str):
                out[k] = v.strip()
            elif v is None:
                out[k] = ""
            else:
                out[k] = str(v).strip()

        out["isf_etd"] = _normalize_date(out.get("isf_etd", ""))
        out["isf_eta"] = _normalize_date(out.get("isf_eta", ""))
        out["isf_country_of_origin"] = _normalize_country(out.get("isf_country_of_origin", ""), country_lookup)

        for prefix in _ADDRESS_PREFIXES:
            for sub in ("name", "addr1", "addr2", "addr_full", "city", "state", "zip", "country"):
                key = f"isf_{prefix}_{sub}"
                raw = item.get(key, "")
                v = raw.strip() if isinstance(raw, str) else ("" if raw is None else str(raw).strip())
                if sub == "country":
                    v = _normalize_country(v, country_lookup)
                out[key] = v

            full_key = f"isf_{prefix}_addr_full"
            if not out.get(full_key):
                pieces = [out.get(f"isf_{prefix}_addr1", ""), out.get(f"isf_{prefix}_addr2", "")]
                out[full_key] = " ".join(p for p in pieces if p).strip()

        codes_raw = item.get("isf_htsus_codes", [])
        if isinstance(codes_raw, list):
            codes = [str(c).strip() for c in codes_raw if str(c).strip()]
        elif isinstance(codes_raw, str):
            codes = [c.strip() for c in re.split(r"[/,;]", codes_raw) if c.strip()]
        else:
            codes = []
        out["isf_htsus_codes_joined"] = ", ".join(codes)

        # Importer profile lookup. When the supplier's importer name matches
        # a known importer (importers.json), force the importer_* fields to
        # the canonical address. Real-world driver: suppliers occasionally
        # list a Sigma facility (e.g., Sauk Village, IL) as importer of
        # record when the actual IOR address is the Cream Ridge, NJ HQ.
        profiles = _load_importer_profiles()
        importer_match_key = _normalize_match_key(out.get("isf_importer_name", ""))
        if profiles and importer_match_key in profiles:
            canonical = profiles[importer_match_key]
            for k, v in canonical.items():
                out[k] = v
            # Recompute importer addr_full after override
            pieces = [out.get("isf_importer_addr1", ""), out.get("isf_importer_addr2", "")]
            out["isf_importer_addr_full"] = " ".join(p for p in pieces if p).strip()
            logger.info(
                "ISF importer profile match: %s — overrode supplier address with canonical entry",
                out.get("isf_importer_name", ""),
            )

        # Buyer = importer in 99% of cases. If the buyer's company name is
        # blank or matches the importer's name, mirror all importer_* fields
        # to buyer_*. The 1% case (genuinely different buyer) is handled by
        # the operator editing the review table after extraction.
        importer_name_key = _normalize_match_key(out.get("isf_importer_name", ""))
        buyer_name_key = _normalize_match_key(out.get("isf_buyer_name", ""))
        if importer_name_key and (not buyer_name_key or buyer_name_key == importer_name_key):
            for sub in ("name", "addr1", "addr2", "addr_full", "city", "state", "zip", "country"):
                out[f"isf_buyer_{sub}"] = out.get(f"isf_importer_{sub}", "")

        return cls(
            fields=out,
            htsus_codes=codes,
            source_path=Path(source_path) if source_path else None,
            importer_ref=out.get("isf_importer_ref", ""),
        )

    def to_form_dict(self) -> Dict[str, object]:
        """Return a single dict containing scalar fields + htsus list, suitable
        for the runner to look up by key matching `field_map.json`."""
        d: Dict[str, object] = dict(self.fields)
        d["isf_htsus_codes"] = list(self.htsus_codes)
        return d
