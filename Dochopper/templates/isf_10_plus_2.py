"""
ISF 10+2 Information Sheet template.

Parses the standardized "Importer Security Filing (ISF) Information Sheet" PDF
that suppliers send before a vessel sails. The form has 17 numbered fields plus
seven address blocks (Importer / Seller / Manufacturer / Buyer / Ship To /
Stuffing / Consolidator). All extracted fields are returned in a single
"line item" dict so this template plugs into the existing template auto-discovery
and ProcessorEngine pipeline.

The presence of `_isf == True` on the returned item signals downstream code
(ISF Filing tab) that this is ISF data, not an invoice line item.
"""

import re
from typing import List, Dict

from .base_template import BaseTemplate


_TITLE_SENTINEL = re.compile(r"Importer Security Filing\s*\(ISF\)\s*Information Sheet", re.I)
_NUMBERED_LINE = re.compile(r"^\s*(\d+)\.\s+(.+)$", re.M)
_HELP_FIELD_LABELS_PRESENT = re.compile(
    r"NAME OF COMPANY:.+ADDRESS:.+CITY:", re.S
)

_S = r"[ \t]"  # whitespace separator on a single line — does NOT match newlines

_SIMPLE_FIELD_PATTERNS = {
    "isf_etd":              rf"^{_S}*1\.{_S}+Estimated sailing date of mother vessel{_S}*\(ETD\){_S}+(.+?){_S}*$",
    "isf_eta":              rf"^{_S}*2\.{_S}+Estimated arrival date{_S}*\(ETA\){_S}+(.+?){_S}*$",
    "isf_vessel":           rf"^{_S}*3\.{_S}+Mother vessel name{_S}*&{_S}*voyage#{_S}+(.+?){_S}*$",
    "isf_hbl":              rf"^{_S}*4\.{_S}+House Bill of Lading[^\n]*?\){_S}+(.+?){_S}*$",
    "isf_mbl":              rf"^{_S}*5\.{_S}+Master Bill of Lading[^\n]*?\){_S}+(.+?){_S}*$",
    "isf_port_of_discharge": rf"^{_S}*6\.{_S}+Port of discharge{_S}+(.+?){_S}*$",
    "isf_country_of_origin": rf"^{_S}*14\.{_S}+Country of origin{_S}+(.+?){_S}*$",
    "isf_commodity_description": rf"^{_S}*15\.{_S}+Commodity{_S}*/{_S}*product description{_S}+(.+?){_S}*$",
    "isf_importer_ref":     rf"^{_S}*16\.{_S}+Importer Reference Number\(s\){_S}+(.+?){_S}*$",
    "isf_htsus_raw":        rf"^{_S}*17\.{_S}+HTSUS[^\n]*?if known{_S}+(.+?){_S}*$",
}

_ADDRESS_SECTIONS = [
    (7,  "importer"),
    (8,  "seller"),
    (9,  "manufacturer"),
    (10, "buyer"),
    (11, "shipto"),
    (12, "stuffing"),
    (13, "consolidator"),
]

_ADDR_LABELS = [
    ("name",      re.compile(r"^\s*NAME OF COMPANY:\s*(.*)$", re.I)),
    ("addr",      re.compile(r"^\s*ADDRESS:\s*(.*)$", re.I)),
    ("city",      re.compile(r"^\s*CITY:\s*(.*)$", re.I)),
    ("state_zip", re.compile(r"^\s*STATE\s*/\s*PROVINCE\s*/\s*ZIP CODE:\s*(.*)$", re.I)),
    ("country",   re.compile(r"^\s*COUNTRY:\s*(.*)$", re.I)),
]

# US states + DC + PR, full names AND 2-letter codes. Used by the address
# parser to promote a state name that the supplier accidentally placed in
# the second ADDRESS line back to the labeled state field.
_US_STATE_TOKENS = {
    'ALABAMA','ALASKA','ARIZONA','ARKANSAS','CALIFORNIA','COLORADO','CONNECTICUT',
    'DELAWARE','FLORIDA','GEORGIA','HAWAII','IDAHO','ILLINOIS','INDIANA','IOWA',
    'KANSAS','KENTUCKY','LOUISIANA','MAINE','MARYLAND','MASSACHUSETTS','MICHIGAN',
    'MINNESOTA','MISSISSIPPI','MISSOURI','MONTANA','NEBRASKA','NEVADA','NEW HAMPSHIRE',
    'NEW JERSEY','NEW MEXICO','NEW YORK','NORTH CAROLINA','NORTH DAKOTA','OHIO','OKLAHOMA',
    'OREGON','PENNSYLVANIA','RHODE ISLAND','SOUTH CAROLINA','SOUTH DAKOTA','TENNESSEE',
    'TEXAS','UTAH','VERMONT','VIRGINIA','WASHINGTON','WEST VIRGINIA','WISCONSIN','WYOMING',
    'DISTRICT OF COLUMBIA','PUERTO RICO',
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS',
    'KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY',
    'NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV',
    'WI','WY','DC','PR',
}


def _split_state_zip(value: str) -> Dict[str, str]:
    """Split a 'STATE / PROVINCE / ZIP CODE' value into state and zip components.

    Tolerates supplier formatting variants:
        'NJ 08514'             -> ('NJ',          '08514')
        'TEXAS 77093'          -> ('TEXAS',       '77093')
        'Henan 476431'         -> ('Henan',       '476431')
        'N.J.08514'            -> ('N.J.',        '08514')    # no space
        '77093'                -> ('',            '77093')    # purely numeric
        '062150'               -> ('',            '062150')   # leading-zero
        '700 001'              -> ('',            '700001')   # Indian postal w/ internal space
        'WEST BENGAL - 711106' -> ('WEST BENGAL', '711106')   # dash separator
        'TEXAS'                -> ('TEXAS',       '')
    """
    value = value.strip()
    if not value:
        return {"state": "", "zip": ""}

    # Pure-numeric with optional internal whitespace/dashes — a postal code
    # only. Indian postal codes are commonly written as "NNN NNN", strip the
    # space so e2open's form gets a single token.
    if re.fullmatch(r"\d[\d\s\-]*\d", value) or re.fullmatch(r"\d+", value):
        return {"state": "", "zip": re.sub(r"\s+", "", value)}

    # State + dash + zip, e.g. "WEST BENGAL - 711106" / "Karnataka–560001".
    m = re.match(r"^(.+?)\s*[-–]\s*(\d[\d\-]*)\s*$", value)
    if m:
        return {"state": m.group(1).strip(), "zip": m.group(2).strip()}

    if " " in value or "\t" in value:
        parts = value.rsplit(maxsplit=1)
        if len(parts) == 2 and re.search(r"\d", parts[1]):
            state = parts[0].strip().rstrip("-,").strip()
            return {"state": state, "zip": parts[1].strip()}

    if re.fullmatch(r"\d[\d-]*", value):
        return {"state": "", "zip": value}

    m = re.match(r"^(.+?[A-Za-z\.])\s*(\d[\d-]*)$", value)
    if m:
        return {"state": m.group(1).strip(), "zip": m.group(2).strip()}

    return {"state": value, "zip": ""}


def _parse_address_block(block: str) -> Dict[str, str]:
    """Parse a single 7-13 address section into structured fields.

    Tolerant of pdfplumber's quirks where long values wrap across lines and
    can appear before/after the labeled line. Help text under section headers
    (e.g. "Name and address of the entity that last manufacturers...") is discarded.
    """
    tagged = []
    for line in block.splitlines():
        if re.match(r"^\s*\d+\.\s+", line):
            tagged.append(("section_header", ""))
            continue
        if not line.strip():
            tagged.append(("blank", ""))
            continue
        matched = False
        for key, rgx in _ADDR_LABELS:
            m = rgx.match(line)
            if m:
                tagged.append((key, m.group(1).strip()))
                matched = True
                break
        if not matched:
            tagged.append(("orphan", line.strip()))

    fields = {"name": "", "addr_lines": [], "city": "", "state": "", "zip": "", "country": ""}
    current = None
    pending = []
    seen_first_label = False

    def attach(key: str, value: str) -> None:
        value = value.strip()
        if not value:
            return
        if key == "addr":
            fields["addr_lines"].append(value)
        elif key == "state_zip":
            sz = _split_state_zip(value)
            if not fields["state"]:
                fields["state"] = sz["state"]
            if not fields["zip"]:
                fields["zip"] = sz["zip"]
        else:
            if not fields[key]:
                fields[key] = value
            else:
                fields[key] = (fields[key] + " " + value).strip()

    for tag, val in tagged:
        if tag in ("section_header", "blank"):
            continue
        if tag == "orphan":
            if seen_first_label:
                pending.append(val)
            continue
        # tag is one of the label keys
        if val:
            if pending and current is not None:
                attach(current, " ".join(pending))
                pending = []
            current = tag
            seen_first_label = True
            attach(tag, val)
        else:
            seen_first_label = True
            if pending:
                attach(tag, " ".join(pending))
                pending = []
            current = tag

    if current is not None and pending:
        attach(current, " ".join(pending))

    addr_lines = fields.pop("addr_lines")
    fields["addr1"] = addr_lines[0] if len(addr_lines) >= 1 else ""
    fields["addr2"] = addr_lines[1] if len(addr_lines) >= 2 else ""
    fields["addr_full"] = " ".join(addr_lines).strip()

    # Repair shape #1: state+zip ended up in the CITY field, real city in addr2.
    #     ADDRESS:  P.O. BOX 300, 700 GOLDMAN DRIVE
    #     ADDRESS:  CREAM RIDGE,
    #     CITY:     NJ 08514            <- actually state+zip
    #     STATE/PROVINCE/ZIP CODE:      <- blank
    # Only fires when state+zip are both blank AND the CITY value parses as
    # state+zip, so a normal "CITY: HOWRAH" is never disturbed.
    if not fields["state"] and not fields["zip"] and fields["city"]:
        sz = _split_state_zip(fields["city"])
        if sz["state"] and sz["zip"]:
            fields["state"] = sz["state"]
            fields["zip"] = sz["zip"]
            if fields["addr2"]:
                fields["city"] = fields["addr2"].rstrip(",").strip()
                fields["addr2"] = ""
                fields["addr_full"] = fields["addr1"]
            else:
                fields["city"] = ""

    # Repair shape #2: city slot has "City, State/Province" and the labeled
    # state field is blank.
    #     CITY: XI'AN, SHAANXI PROVINCE
    #     STATE/PROVINCE/ZIP CODE: 710048
    # Splits the city on the last comma when state is blank and the trailing
    # piece looks like a state name (no digits).
    if not fields["state"] and "," in fields["city"]:
        head, tail = fields["city"].rsplit(",", 1)
        head, tail = head.strip(), tail.strip()
        if head and tail and not re.search(r"\d", tail):
            fields["city"] = head
            fields["state"] = tail

    # Strip trailing " PROVINCE" / " STATE" from state values
    # ("SHAANXI PROVINCE" → "SHAANXI"). e2open's state field generally
    # wants the bare name.
    if fields["state"]:
        fields["state"] = re.sub(
            r"\s+(PROVINCE|STATE)\s*$", "",
            fields["state"], flags=re.IGNORECASE,
        ).strip()

    # Repair shape #3: a US state name landed in the second ADDRESS line.
    #     ADDRESS: 21699 TORRENCE AVE
    #     ADDRESS: ILLINOIS              <- actual state
    #     CITY:    SAUK VILLAGE
    #     STATE/PROVINCE/ZIP CODE: 60411 <- zip only
    # If the state field is blank and addr2 (uppercased, stripped of trailing
    # punctuation) is a recognized US state, promote it.
    if not fields["state"] and fields["addr2"]:
        candidate = fields["addr2"].strip().rstrip(",.").strip().upper()
        if candidate in _US_STATE_TOKENS:
            fields["state"] = candidate
            fields["addr2"] = ""
            fields["addr_full"] = fields["addr1"]

    return fields


def _parse_isf_text(text: str) -> Dict:
    """Parse the full 10+2 PDF text into a flat dict of ISF fields."""
    result: Dict = {}

    for key, pat in _SIMPLE_FIELD_PATTERNS.items():
        m = re.search(pat, text, re.MULTILINE)
        if m:
            result[key] = m.group(1).strip()
        else:
            result[key] = ""

    pod = result.get("isf_port_of_discharge", "")
    pod_match = re.match(r"(.+?)\((\d+)\)\s*$", pod)
    if pod_match:
        result["isf_port_name"] = pod_match.group(1).strip().rstrip(",")
        result["isf_port_code"] = pod_match.group(2).strip()
    else:
        # Strip trailing country tokens — "NORFOLK,  USA" → "NORFOLK".
        # Suppliers often append the country which the e2open form
        # doesn't want in the port-name slot (it has its own country
        # field on the line item).
        pod_clean = re.sub(
            r",\s*(USA|U\.S\.A\.|US|UNITED\s+STATES(?:\s+OF\s+AMERICA)?|CANADA)\s*$",
            "",
            pod,
            flags=re.IGNORECASE,
        ).strip()
        result["isf_port_name"] = pod_clean.rstrip(",").strip()
        result["isf_port_code"] = ""

    for key in ("hbl", "mbl"):
        full = result.get(f"isf_{key}", "")
        m = re.match(r"^([A-Z]{4})(.+)$", full)
        if m:
            result[f"isf_{key}_scac"] = m.group(1)
            number = m.group(2).strip()
            # Strip trailing ", SCAC" or ",SCAC" artifacts some suppliers
            # append after the BL number (e.g., "MEDUXO486161 ,MSCU").
            number = re.sub(r"[,;]\s*[A-Z]{4}\s*$", "", number).strip()
            result[f"isf_{key}_number"] = number
        else:
            result[f"isf_{key}_scac"] = ""
            result[f"isf_{key}_number"] = full

    htsus_raw = result.get("isf_htsus_raw", "")
    result["isf_htsus_codes"] = [c.strip() for c in re.split(r"[/,;]", htsus_raw) if c.strip()]

    section_starts: Dict[int, int] = {}
    for m in _NUMBERED_LINE.finditer(text):
        section_starts[int(m.group(1))] = m.start()

    sorted_nums = sorted(section_starts.keys())
    for num, prefix in _ADDRESS_SECTIONS:
        if num not in section_starts:
            continue
        start = section_starts[num]
        next_nums = [n for n in sorted_nums if n > num]
        end = section_starts[next_nums[0]] if next_nums else len(text)
        block = text[start:end]
        addr = _parse_address_block(block)
        for k, v in addr.items():
            result[f"isf_{prefix}_{k}"] = v

    return result


class ISF10Plus2Template(BaseTemplate):
    """Template for the supplier-issued 10+2 Information Sheet PDF.

    NOTE: Disabled in v1.6.1 — DocHopper's ISF Filing tab was retired in
    favor of a separate inbox-monitoring agent. This template stays in the
    repo as the seed for the standalone agent's lift-out and so existing
    fixtures / tests keep working when imported directly. Auto-discovery
    skips this class because of `enabled = False`, so dropping an ISF PDF
    into the OCRMill PDF Processing tab no longer accidentally produces a
    bogus "line item" with `_isf=True`.
    """

    name = "ISF 10+2 Information Sheet"
    description = "Importer Security Filing 10+2 Information Sheet (17-field form)"
    client = "Generic"
    version = "1.0.0"
    enabled = False  # Retired from DocHopper UI in v1.6.1; reserved for ISF agent

    extra_columns: List[str] = [
        "isf_etd", "isf_eta", "isf_vessel",
        "isf_hbl", "isf_hbl_scac", "isf_hbl_number",
        "isf_mbl", "isf_mbl_scac", "isf_mbl_number",
        "isf_port_of_discharge", "isf_port_name", "isf_port_code",
        "isf_country_of_origin", "isf_commodity_description",
        "isf_importer_ref", "isf_htsus_raw",
    ]

    def can_process(self, text: str) -> bool:
        if not _TITLE_SENTINEL.search(text):
            return False
        numbered = {int(m.group(1)) for m in _NUMBERED_LINE.finditer(text)}
        return numbered.issuperset({1, 2, 3, 6, 14}) and bool(
            _HELP_FIELD_LABELS_PRESENT.search(text)
        )

    def is_packing_list(self, text: str) -> bool:
        return False

    def get_confidence_score(self, text: str) -> float:
        if not self.can_process(text):
            return 0.0
        return 0.95

    def extract_invoice_number(self, text: str) -> str:
        m = re.search(_SIMPLE_FIELD_PATTERNS["isf_importer_ref"], text, re.MULTILINE)
        return m.group(1).strip() if m else "UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        return ""

    def extract_line_items(self, text: str) -> List[Dict]:
        parsed = _parse_isf_text(text)
        item: Dict = {
            "_isf": True,
            "part_number": parsed.get("isf_importer_ref", "ISF"),
            "quantity": "1",
            "total_price": "0",
        }
        item.update(parsed)
        return [item]
