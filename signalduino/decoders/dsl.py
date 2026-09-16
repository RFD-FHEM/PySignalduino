"""Evaluates the field rules of a decoder specification (ADR-006).

The FHEM client modules extract their values with small closures over bit
offsets - take bits 18 to 27, subtract 1024 if bit 17 is set, divide by ten.
That is mechanical enough to describe as data, and this module is the
interpreter for that description.

Indices are always inclusive and zero based, matching SD_WS_binaryToNumber in
14_SD_WS.pm: ``from`` 18 and ``to`` 27 is a ten bit field. For ``hex`` they
index the characters of the payload instead.

The order of operations is fixed: extract, decode BCD, apply the sign, add the
offset, scale, round, map, derive. It is chosen so a rule reads like the FHEM
line it replaces.
"""

from __future__ import annotations

import math
from typing import Any, Optional

WIND_DIRECTIONS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


class FieldError(ValueError):
    """A field rule could not be applied to this message."""


def _slice(field: dict, bits: str, raw_hex: str) -> str:
    source = field["source"]
    data = bits if source == "bits" else raw_hex
    start, end = field["from"], field["to"]
    if start > end:
        raise FieldError(f"from {start} is behind to {end}")
    if end >= len(data):
        raise FieldError(
            f"{source} range {start}..{end} exceeds the message ({len(data)} available)"
        )
    return data[start:end + 1]


def _to_number(chunk: str, source: str, bcd: bool) -> int:
    if bcd:
        digits = chunk
        if source == "bits":
            if len(chunk) % 4:
                raise FieldError("BCD on bits needs a multiple of four bits")
            digits = "".join(
                f"{int(chunk[i:i + 4], 2):X}" for i in range(0, len(chunk), 4)
            )
        if any(char not in "0123456789" for char in digits):
            raise FieldError(f"Not a valid BCD value: {digits}")
        return int(digits, 10)
    try:
        return int(chunk, 2 if source == "bits" else 16)
    except ValueError as error:
        raise FieldError(f"Cannot read '{chunk}' as a number") from error


def _apply_sign(value: int, field: dict, bits: str, raw_hex: str) -> float:
    sign_bit = field.get("sign_bit")
    if sign_bit is None:
        return value

    source = field["source"]
    data = bits if source == "bits" else raw_hex
    if sign_bit >= len(data):
        raise FieldError(f"Sign bit {sign_bit} is outside the message")
    if source != "bits":
        raise FieldError("sign_bit is only meaningful on bits")

    is_negative = data[sign_bit] == field.get("sign_value", "1")
    style = field.get("sign_style", "negate")

    if style == "twos_complement":
        width = field["to"] - field["from"] + 1
        return value - (1 << width) if is_negative else value
    if not is_negative:
        return value
    if style == "offset":
        if "sign_offset" not in field:
            raise FieldError("sign_style 'offset' requires sign_offset")
        return value - field["sign_offset"]
    return -value


def _derive(name: str, value: Any) -> Any:
    if name == "wind_dir_text":
        try:
            index = int(round(float(value) / 22.5)) % 16
        except (TypeError, ValueError) as error:
            raise FieldError(f"wind_dir_text needs a number, got {value!r}") from error
        return WIND_DIRECTIONS[index]
    raise FieldError(f"Unknown derivation '{name}'")


def evaluate_field(field: dict, bits: str, raw_hex: str,
                   decoded: Optional[dict[str, Any]] = None) -> Any:
    """Applies one field rule and returns the resulting value.

    Args:
        field: The rule, already validated against the schema.
        bits: The demodulated bit string.
        raw_hex: The payload without its preamble.
        decoded: Fields decoded so far, for rules using ``derive_from``.

    Raises:
        FieldError: if the rule does not fit this message.
    """
    source_field = field.get("derive_from")
    if source_field is not None:
        if not decoded or source_field not in decoded:
            raise FieldError(f"derive_from references unknown field '{source_field}'")
        value = decoded[source_field]
        if "derive" in field:
            value = _derive(field["derive"], value)
        return value

    chunk = _slice(field, bits, raw_hex)
    value_type = field.get("type", "int")

    # A plain string field hands back the slice as it stands, which is how
    # sensor ids are read. As soon as the rule asks for arithmetic, the value
    # goes through the numeric path and is stringified at the end - silently
    # dropping a scale here would be a trap for whoever writes the spec.
    transforms = ("bcd", "map", "scale", "offset", "sign_bit", "round", "derive")
    if value_type == "str" and not any(key in field for key in transforms):
        return chunk

    number = _to_number(chunk, field["source"], field.get("bcd", False))

    if "map" in field:
        mapping = field["map"]
        key = str(number)
        if key not in mapping:
            raise FieldError(f"No mapping for value {key} in {sorted(mapping)}")
        return mapping[key]

    value: float = _apply_sign(number, field, bits, raw_hex)
    value = (value + field.get("offset", 0)) * field.get("scale", 1)

    if "round" in field:
        value = round(value, field["round"])
    elif isinstance(value, float) and not value.is_integer():
        # Scaling by 0.1 and friends leaves binary noise behind; the FHEM
        # values this is compared against never carry it.
        value = round(value, 10)

    if "derive" in field:
        return _derive(field["derive"], value)

    if value_type == "int":
        if isinstance(value, float) and not float(value).is_integer():
            raise FieldError(f"Value {value} is not an integer")
        return int(value)
    if value_type == "bool":
        return bool(value)
    if value_type == "str":
        return str(value)

    result = float(value)
    if math.isnan(result) or math.isinf(result):
        raise FieldError("Value is not finite")
    return result
