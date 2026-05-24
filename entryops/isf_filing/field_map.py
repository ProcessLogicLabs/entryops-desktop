"""Loader / validator for `field_map.json`.

The field map is the bridge between EntryOps's normalized ISF payload keys
(e.g. `isf_etd`) and the e2open ISF web UI's actual form selectors. It is
edited by hand after running a one-time Playwright codegen recording session
(see RECORDING.md). Keeping selectors out of code lets us patch the map
without redeploying the app when e2open tweaks the UI.

Schema (all top-level keys optional except `version`):

    {
      "version": "<recording-tag>",
      "isf_url": "https://isf.e2open.com/kc/app/isf",
      "actions": {
        "<action_name>": { "selector": "...", "type": "click" }
      },
      "fields": {
        "<isf_payload_key>": {
          "selector": "...",
          "type": "fill | select_option | check | click_then_fill",
          "format": "MM/DD/YYYY",         // optional; date format hint
          "value_map": { "USA": "US" },   // optional; pre-substitute values
          "row_template": { ... }         // optional; for list_fill (HTSUS)
        }
      }
    }

Unknown extra keys are tolerated for forward-compat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


# Action types the runner supports. Keep in sync with runner.py's dispatch.
SUPPORTED_FIELD_TYPES = {"fill", "select_option", "check", "uncheck", "click_then_fill", "list_fill"}
SUPPORTED_ACTION_TYPES = {"click", "navigate"}


@dataclass
class FieldEntry:
    key: str
    selector: str
    type: str
    format: Optional[str] = None
    value_map: Optional[Dict[str, str]] = None
    row_template: Optional[Dict[str, Any]] = None
    optional: bool = False
    raw: Optional[Dict[str, Any]] = None


@dataclass
class ActionEntry:
    key: str
    selector: str
    type: str
    raw: Optional[Dict[str, Any]] = None


@dataclass
class FieldMap:
    version: str
    isf_url: str
    actions: Dict[str, ActionEntry]
    fields: Dict[str, FieldEntry]
    raw: Dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "FieldMap":
        p = Path(path)
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldMap":
        version = str(data.get("version", "unspecified"))
        isf_url = str(data.get("isf_url", "https://isf.e2open.com/kc/app/isf"))

        actions: Dict[str, ActionEntry] = {}
        for key, entry in (data.get("actions") or {}).items():
            actions[key] = ActionEntry(
                key=key,
                selector=str(entry.get("selector", "")),
                type=str(entry.get("type", "click")),
                raw=entry,
            )

        fields: Dict[str, FieldEntry] = {}
        for key, entry in (data.get("fields") or {}).items():
            fields[key] = FieldEntry(
                key=key,
                selector=str(entry.get("selector", "")),
                type=str(entry.get("type", "fill")),
                format=entry.get("format"),
                value_map=entry.get("value_map"),
                row_template=entry.get("row_template"),
                optional=bool(entry.get("optional", False)),
                raw=entry,
            )

        return cls(version=version, isf_url=isf_url, actions=actions, fields=fields, raw=data)

    def validate(self) -> List[str]:
        """Return a list of human-readable issues; empty list means all good."""
        issues: List[str] = []
        for name, action in self.actions.items():
            if not action.selector:
                issues.append(f"action '{name}' has empty selector")
            if action.type not in SUPPORTED_ACTION_TYPES:
                issues.append(f"action '{name}' has unsupported type {action.type!r}")
        for name, fld in self.fields.items():
            if not fld.selector:
                issues.append(f"field '{name}' has empty selector")
            if fld.type not in SUPPORTED_FIELD_TYPES:
                issues.append(f"field '{name}' has unsupported type {fld.type!r}")
        return issues
