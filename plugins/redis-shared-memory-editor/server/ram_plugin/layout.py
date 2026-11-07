"""How management records are laid out in Redis Agent Memory custom memory types.

The management code works with one logical record shape: flat attributes on two
logical memory types, ``organizational_state`` observations and
``organizational_state_projection`` projections. RAM can store that shape in one
of two layouts:

``compact`` (default)
    One custom memory type, ``organizational_state``, with nine fields: the seven
    fields that searches filter on, ``record_kind``, and one ``details`` object
    holding every other attribute. It is short enough to enter by hand in the
    Redis Cloud console, which is the only way to register custom types there.

``expanded``
    The original two custom types, with every attribute as its own field.

``RAMClient`` encodes writes and search filters for the configured layout and
decodes every read, whichever layout wrote it, so the projector, agenda,
promotion, and reconciliation code see the same flat records in both layouts.
This module is standard-library only.
"""

from __future__ import annotations

import json
from typing import Any


OBSERVATION_TYPE = "organizational_state"
PROJECTION_TYPE = "organizational_state_projection"
PROJECTION_SCHEMA = "organizational-state-projection-v1"
MANAGEMENT_TYPES = frozenset({OBSERVATION_TYPE, PROJECTION_TYPE})

COMPACT = "compact"
EXPANDED = "expanded"
LAYOUTS = (COMPACT, EXPANDED)
DEFAULT_LAYOUT = COMPACT

COMPACT_TYPE = OBSERVATION_TYPE
# Attributes that searches filter on server-side; they stay top-level fields.
FILTER_FIELDS = (
    "schema_version",
    "state_kind",
    "lifecycle_status",
    "project_id",
    "meeting_id",
    "accountable_entity_id",
    "conflict_status",
)
COMPACT_FIELDS = (*FILTER_FIELDS, "record_kind", "details")
_TYPED = {"string", "number", "boolean", "strings", "numbers", "booleans", "object"}


def physical_type(logical_type: str, layout: str) -> str:
    """The custom memory type a logical management type is stored under."""

    if layout == COMPACT and logical_type in MANAGEMENT_TYPES:
        return COMPACT_TYPE
    return logical_type


def _plain(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        key, nested = next(iter(value.items()))
        if key in _TYPED:
            return nested
    return value


def _details(value: Any) -> dict[str, Any]:
    value = _plain(value)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def encode_record(memory: dict[str, Any], layout: str) -> dict[str, Any]:
    """Return a management record in the stored shape for ``layout``."""

    logical = memory.get("memoryType")
    if layout != COMPACT or logical not in MANAGEMENT_TYPES:
        return memory
    attributes = memory.get("attributes") or {}
    stored = {name: attributes[name] for name in FILTER_FIELDS if name in attributes}
    stored["record_kind"] = "projection" if logical == PROJECTION_TYPE else "observation"
    stored["details"] = {
        name: value for name, value in attributes.items() if name not in FILTER_FIELDS
    }
    return {**memory, "memoryType": COMPACT_TYPE, "attributes": stored}


def decode_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a stored record in the logical flat shape, whatever layout wrote it."""

    attributes = record.get("attributes")
    if (
        record.get("memoryType") != COMPACT_TYPE
        or not isinstance(attributes, dict)
        or not ({"details", "record_kind"} & set(attributes))
    ):
        return record
    flat = {name: value for name, value in attributes.items() if name not in {"details", "record_kind"}}
    for name, value in _details(attributes.get("details")).items():
        flat.setdefault(name, value)  # top-level filter fields win
    projection = (
        _plain(attributes.get("record_kind")) == "projection"
        or _plain(flat.get("schema_version")) == PROJECTION_SCHEMA
    )
    if not projection and _plain(flat.get("conflict_status")) in {"", None}:
        flat.pop("conflict_status", None)  # extraction fills every field; observations have none
    return {
        **record,
        "memoryType": PROJECTION_TYPE if projection else OBSERVATION_TYPE,
        "attributes": flat,
    }


def encode_filter(filter_: dict[str, Any], layout: str) -> dict[str, Any]:
    """Return a search filter for the stored layout.

    Raises ``ValueError`` when a compact-layout search filters on an attribute
    that lives inside ``details``, which RAM cannot filter on.
    """

    clause = filter_.get("memoryType")
    if (
        layout != COMPACT
        or not isinstance(clause, dict)
        or clause.get("eq") not in MANAGEMENT_TYPES
    ):
        return filter_
    attributes = filter_.get("attributes") or {}
    unsupported = sorted(set(attributes) - set(FILTER_FIELDS))
    if unsupported:
        raise ValueError(f"compact layout cannot filter on {', '.join(unsupported)}")
    return {**filter_, "memoryType": {**clause, "eq": COMPACT_TYPE}}
