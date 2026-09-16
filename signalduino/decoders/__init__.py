"""Sensor value decoding, the second stage of the receive chain (ADR-006).

Stage 1, in signalduino/parser and sd_protocols, turns pulses into a payload.
This package turns that payload into measurements: temperature, humidity,
battery state, sensor id, channel.

Most protocols are described declaratively in specs/*.json and evaluated by
dsl.py; the irregular ones register a Python decoder in custom/. Either way
the result is a SensorEvent, which the output adapters render into the FHEM,
rtl_433 and Home Assistant formats.
"""

from .pipeline import DecodeError, SensorDecoder, decode_with_spec
from .registry import DecoderRegistry, register_decoder
from .spec import DecoderSpec, SpecError

__all__ = [
    "DecodeError",
    "DecoderRegistry",
    "DecoderSpec",
    "SensorDecoder",
    "SpecError",
    "decode_with_spec",
    "register_decoder",
]
