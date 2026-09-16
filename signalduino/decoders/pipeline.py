"""Turns a demodulated message into sensor values (ADR-006, stage 2).

The sequence mirrors SD_WS_Parse in 14_SD_WS.pm: strip the preamble, get hold
of the bits, check the prematch, verify the checksum, pick the variant, read
the fields, check the plausibility limits.

Every failure along the way is a debug log and a None, never an exception that
reaches the caller: stage 2 must not be able to disturb stage 1, and for most
protocols "no specification yet" is simply the normal state.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ..types import DecodedMessage, SensorEvent
from . import crc as crc_module
from .dsl import FieldError, evaluate_field
from .spec import DecoderSpec


class DecodeError(ValueError):
    """The message does not decode with this specification."""


def hex_to_bits(raw_hex: str) -> str:
    """Expands a hex payload into its bit string.

    Needed for MN telegrams, which arrive as hex and never carry a bit string
    of their own, while the field rules address bit positions.
    """
    try:
        return "".join(f"{int(char, 16):04b}" for char in raw_hex)
    except ValueError as error:
        raise DecodeError(f"Payload is not hex: {raw_hex!r}") from error


def strip_preamble(payload: str, preamble: str) -> str:
    """Removes the routing preamble, leaving the raw hex."""
    if preamble and payload.startswith(preamble):
        return payload[len(preamble):]
    if "#" in payload:
        return payload.split("#", 1)[1]
    return payload


def _hex_range(raw_hex: str, bounds: dict) -> bytes:
    start, end = bounds["from"], bounds["to"]
    chunk = raw_hex[start:end + 1]
    if len(chunk) != end - start + 1:
        raise DecodeError(f"Range {start}..{end} exceeds the payload")
    if len(chunk) % 2:
        raise DecodeError(f"Range {start}..{end} is not a whole number of bytes")
    try:
        return bytes.fromhex(chunk)
    except ValueError as error:
        raise DecodeError(f"Range {start}..{end} is not hex") from error


def verify_checksum(spec: DecoderSpec, raw_hex: str) -> None:
    """Checks the specification's checksum, if it defines one.

    Raises:
        DecodeError: if the checksum does not match.
    """
    if not spec.crc:
        return

    definition = spec.crc
    data = _hex_range(raw_hex, definition["data"])
    expected_bytes = _hex_range(raw_hex, definition["check"])
    expected = int.from_bytes(expected_bytes, "big")
    actual = crc_module.compute(definition["algorithm"], data, **definition.get("params", {}))

    if actual != expected:
        raise DecodeError(
            f"{definition['algorithm']} mismatch: computed {actual:#x}, message says {expected:#x}"
        )


def _check_limits(values: dict[str, Any], limits: dict[str, list]) -> None:
    for name, bounds in limits.items():
        if name not in values:
            continue
        value = values[name]
        if not isinstance(value, (int, float)):
            continue
        low, high = bounds
        if not low <= value <= high:
            raise DecodeError(f"{name} {value} is outside {low}..{high}")


def decode_with_spec(spec: DecoderSpec, message: DecodedMessage,
                     preamble: str = "") -> SensorEvent:
    """Applies one specification to one message.

    Raises:
        DecodeError: if the message does not match the specification.
    """
    raw_hex = strip_preamble(message.payload, preamble).upper()
    if not raw_hex:
        raise DecodeError("Empty payload")

    if spec.prematch and not re.search(spec.prematch, raw_hex):
        raise DecodeError(f"Prematch {spec.prematch!r} does not match {raw_hex}")

    verify_checksum(spec, raw_hex)

    bits = message.metadata.get("bits") or hex_to_bits(raw_hex)

    variant_key: Optional[str] = None
    if spec.variant_selector:
        try:
            variant_key = str(evaluate_field(spec.variant_selector, bits, raw_hex))
        except FieldError as error:
            raise DecodeError(f"Variant selector failed: {error}") from error
        if variant_key not in spec.variants:
            raise DecodeError(f"No variant '{variant_key}' in {sorted(spec.variants)}")

    values: dict[str, Any] = {}
    units: dict[str, str] = {}
    for name, rule in spec.fields_for(variant_key).items():
        try:
            values[name] = evaluate_field(rule, bits, raw_hex, values)
        except FieldError as error:
            raise DecodeError(f"Field '{name}': {error}") from error
        if "unit" in rule:
            units[name] = rule["unit"]

    _check_limits(values, spec.limits_for(variant_key))

    model = spec.model
    sensor_type = spec.sensor_type
    if variant_key is not None:
        block = spec.variants[variant_key]
        model = block.get("model", model)
        sensor_type = block.get("sensor_type", sensor_type)

    sensor_id = str(values.get(spec.id_field, ""))
    channel = values.get(spec.channel_field)
    channel = int(channel) if isinstance(channel, (int, float)) else None

    device_id = f"{model}_{sensor_id}" if sensor_id else model
    if channel is not None:
        device_id = f"{device_id}_{channel}"

    return SensorEvent(
        protocol_id=spec.protocol_id,
        model=model,
        sensor_type=sensor_type,
        device_id=device_id,
        sensor_id=sensor_id,
        values=values,
        units=units,
        channel=channel,
        raw_hex=raw_hex,
        dmsg=message.payload,
        rssi=message.metadata.get("rssi"),
    )


class SensorDecoder:
    """Decodes messages using whatever decoders a registry provides."""

    def __init__(self, registry=None, logger: Optional[logging.Logger] = None):
        from .registry import DecoderRegistry  # circular at module level

        self.registry = registry if registry is not None else DecoderRegistry()
        self.logger = logger or logging.getLogger(__name__)

    def decode(self, message: DecodedMessage) -> Optional[SensorEvent]:
        """Returns the sensor values of a message, or None.

        Never raises. A missing decoder, a failing checksum and a broken
        specification all end up as None so that stage 1 keeps working.
        """
        try:
            decoder = self.registry.get(message.protocol_id)
            if decoder is None:
                return None
            return decoder(message)
        except DecodeError as error:
            self.logger.debug(
                "Protocol %s not decoded: %s", message.protocol_id, error
            )
            return None
        except Exception:  # noqa: BLE001 - stage 2 must never break stage 1
            self.logger.exception(
                "Decoder for protocol %s raised unexpectedly", message.protocol_id
            )
            return None

    def attach(self, message: DecodedMessage) -> DecodedMessage:
        """Decodes and stores the result on the message."""
        message.sensor = self.decode(message)
        return message
