"""Loading and validation of decoder specifications (ADR-006).

A specification is JSON validated against spec_schema.json. Validating at load
time rather than at decode time means a typo surfaces once at startup with the
offending path named, instead of silently dropping a field of every telegram.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dataclass_field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import jsonschema

SCHEMA_PATH = Path(__file__).parent / "spec_schema.json"


class SpecError(ValueError):
    """A specification is malformed."""


@lru_cache(maxsize=1)
def _schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True)
class DecoderSpec:
    """One protocol's decoding rules."""

    protocol_id: str
    model: str
    fields: dict[str, dict]
    sensor_type: str = ""
    prematch: Optional[str] = None
    crc: Optional[dict] = None
    variant_selector: Optional[dict] = None
    variants: dict[str, dict] = dataclass_field(default_factory=dict)
    limits: dict[str, list] = dataclass_field(default_factory=dict)
    id_field: str = "id"
    channel_field: str = "channel"
    source: str = "<memory>"

    def variant(self, key: str) -> Optional[dict]:
        """The variant block for a selector value, if one is defined."""
        return self.variants.get(key)

    def fields_for(self, variant_key: Optional[str]) -> dict[str, dict]:
        """Common fields, overlaid with the selected variant's fields."""
        merged = dict(self.fields)
        if variant_key is not None:
            block = self.variants.get(variant_key)
            if block:
                merged.update(block.get("fields", {}))
        return merged

    def limits_for(self, variant_key: Optional[str]) -> dict[str, list]:
        merged = dict(self.limits)
        if variant_key is not None:
            block = self.variants.get(variant_key)
            if block:
                merged.update(block.get("limits", {}))
        return merged


def validate(document: dict, source: str = "<memory>") -> None:
    """Validates a raw specification document.

    Raises:
        SpecError: with the failing property path.
    """
    try:
        jsonschema.validate(instance=document, schema=_schema())
    except jsonschema.ValidationError as error:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise SpecError(f"{source}: invalid at '{location}': {error.message}") from error

    if "variants" in document and "variant_selector" not in document:
        raise SpecError(f"{source}: variants require a variant_selector")


def from_dict(document: dict, source: str = "<memory>") -> DecoderSpec:
    """Validates and converts a raw document into a DecoderSpec."""
    validate(document, source)
    known = {
        "protocol_id", "model", "sensor_type", "prematch", "crc",
        "variant_selector", "variants", "fields", "limits",
        "id_field", "channel_field",
    }
    payload: dict[str, Any] = {k: v for k, v in document.items() if k in known}
    payload.setdefault("sensor_type", "")
    return DecoderSpec(source=source, **payload)


def load_file(path: Path) -> DecoderSpec:
    """Loads one specification file.

    Raises:
        SpecError: if the file is not readable JSON or fails validation.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
    except json.JSONDecodeError as error:
        raise SpecError(f"{path.name}: not valid JSON: {error}") from error
    return from_dict(document, source=path.name)
