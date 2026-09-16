"""The decoding pipeline from message to SensorEvent (ADR-006).

These tests use a synthetic protocol rather than a real one: phase 2 delivers
the machinery, and the first real specification follows in phase 3. The point
here is that the steps happen in the right order and that a failure anywhere
returns None instead of reaching the caller.
"""

from __future__ import annotations

import logging

import pytest

from signalduino.decoders import spec as spec_module
from signalduino.decoders.crc import crc8
from signalduino.decoders.pipeline import (
    DecodeError,
    SensorDecoder,
    decode_with_spec,
    hex_to_bits,
    strip_preamble,
)
from signalduino.decoders.registry import DecoderRegistry
from signalduino.types import DecodedMessage, RawFrame

# Synthetic payload: 2 bytes id, 1 byte value, 1 byte CRC8 over the first three.
PAYLOAD_BODY = "1234A0"
PAYLOAD = PAYLOAD_BODY + f"{crc8(bytes.fromhex(PAYLOAD_BODY)):02X}"

SPEC_DOCUMENT = {
    "protocol_id": "900",
    "model": "TEST_900",
    "sensor_type": "Synthetic test device",
    "prematch": "^12",
    "crc": {
        "algorithm": "crc8",
        "data": {"from": 0, "to": 5},
        "check": {"from": 6, "to": 7},
    },
    "fields": {
        "id": {"source": "hex", "from": 0, "to": 1, "type": "str"},
        "channel": {"source": "hex", "from": 2, "to": 2},
        "temperature": {
            "source": "hex", "from": 4, "to": 5,
            "type": "float", "scale": 0.5, "unit": "°C",
        },
    },
    "limits": {"temperature": [-40, 100]},
}


def message(payload=None, bits=None, protocol_id="900"):
    return DecodedMessage(
        protocol_id=protocol_id,
        payload=payload if payload is not None else f"W900#{PAYLOAD}",
        raw=RawFrame(line="raw"),
        metadata={"bits": bits, "rssi": -60.5} if bits else {"rssi": -60.5},
    )


@pytest.fixture
def spec():
    return spec_module.from_dict(SPEC_DOCUMENT, "test")


class TestHelpers:

    def test_strip_preamble_removes_a_known_preamble(self):
        assert strip_preamble("W125#ABCD", "W125#") == "ABCD"

    def test_strip_preamble_falls_back_to_the_hash(self):
        assert strip_preamble("W125#ABCD", "") == "ABCD"

    def test_strip_preamble_leaves_a_plain_payload_alone(self):
        assert strip_preamble("ABCD", "") == "ABCD"

    def test_hex_to_bits_expands_every_nibble(self):
        assert hex_to_bits("2A") == "00101010"

    def test_hex_to_bits_rejects_non_hex(self):
        with pytest.raises(DecodeError, match="not hex"):
            hex_to_bits("XY")


class TestDecodeWithSpec:

    def test_decodes_all_fields(self, spec):
        event = decode_with_spec(spec, message(), "W900#")
        assert event.values == {"id": "12", "channel": 3, "temperature": 80.0}

    def test_reports_units(self, spec):
        event = decode_with_spec(spec, message(), "W900#")
        assert event.units == {"temperature": "°C"}

    def test_builds_the_device_id_from_model_id_and_channel(self, spec):
        event = decode_with_spec(spec, message(), "W900#")
        assert event.device_id == "TEST_900_12_3"

    def test_carries_metadata_through(self, spec):
        event = decode_with_spec(spec, message(), "W900#")
        assert event.protocol_id == "900"
        assert event.sensor_type == "Synthetic test device"
        assert event.raw_hex == PAYLOAD
        assert event.dmsg == f"W900#{PAYLOAD}"
        assert event.rssi == -60.5

    def test_uses_the_bit_string_when_present(self, spec):
        document = dict(SPEC_DOCUMENT, fields={
            "id": {"source": "bits", "from": 0, "to": 7},
        })
        bit_spec = spec_module.from_dict(document, "test")
        event = decode_with_spec(bit_spec, message(bits="11110000"), "W900#")
        assert event.values["id"] == 240

    def test_falls_back_to_bits_derived_from_hex(self, spec):
        """MN telegrams arrive as hex and carry no bit string of their own."""
        document = dict(SPEC_DOCUMENT, crc=None, fields={
            "id": {"source": "bits", "from": 0, "to": 7},
        })
        document.pop("crc")
        bit_spec = spec_module.from_dict(document, "test")
        event = decode_with_spec(bit_spec, message(), "W900#")
        assert event.values["id"] == 0x12

    def test_failing_prematch_is_rejected(self, spec):
        with pytest.raises(DecodeError, match="Prematch"):
            decode_with_spec(spec, message(payload="W900#9934A0FF"), "W900#")

    def test_wrong_checksum_is_rejected(self, spec):
        broken = f"W900#{PAYLOAD_BODY}FF"
        with pytest.raises(DecodeError, match="mismatch"):
            decode_with_spec(spec, message(payload=broken), "W900#")

    def test_value_outside_its_limits_discards_the_telegram(self):
        document = dict(SPEC_DOCUMENT, limits={"temperature": [-40, 20]})
        narrow = spec_module.from_dict(document, "test")
        with pytest.raises(DecodeError, match="outside"):
            decode_with_spec(narrow, message(), "W900#")

    def test_empty_payload_is_rejected(self, spec):
        with pytest.raises(DecodeError, match="Empty"):
            decode_with_spec(spec, message(payload="W900#"), "W900#")


class TestVariants:

    @pytest.fixture
    def spec(self):
        document = dict(
            SPEC_DOCUMENT,
            variant_selector={"source": "hex", "from": 2, "to": 2},
            variants={
                "3": {
                    "model": "TEST_900_TH",
                    "fields": {"humidity": {"source": "hex", "from": 4, "to": 5}},
                },
            },
        )
        return spec_module.from_dict(document, "test")

    def test_variant_fields_are_decoded(self, spec):
        event = decode_with_spec(spec, message(), "W900#")
        assert event.values["humidity"] == 0xA0

    def test_variant_overrides_the_model(self, spec):
        event = decode_with_spec(spec, message(), "W900#")
        assert event.model == "TEST_900_TH"
        assert event.device_id.startswith("TEST_900_TH_")

    def test_unknown_variant_is_rejected(self, spec):
        payload = "1274A0"
        full = f"W900#{payload}{crc8(bytes.fromhex(payload)):02X}"
        with pytest.raises(DecodeError, match="No variant"):
            decode_with_spec(spec, message(payload=full), "W900#")


class TestSensorDecoder:
    """The outer layer, which must never raise."""

    @pytest.fixture
    def decoder(self, tmp_path):
        import json
        (tmp_path / "test_900.json").write_text(json.dumps(SPEC_DOCUMENT), encoding="utf-8")
        return SensorDecoder(registry=DecoderRegistry(specs_dir=tmp_path))

    def test_decodes_a_known_protocol(self, decoder):
        event = decoder.decode(message(payload=PAYLOAD))
        assert event is not None
        assert event.values["temperature"] == 80.0

    def test_unknown_protocol_yields_none(self, decoder):
        assert decoder.decode(message(protocol_id="4711")) is None

    def test_bad_checksum_yields_none_instead_of_raising(self, decoder):
        assert decoder.decode(message(payload=f"{PAYLOAD_BODY}FF")) is None

    def test_a_raising_decoder_is_contained(self, decoder, caplog):
        def explode(_message):
            raise RuntimeError("decoder is broken")

        decoder.registry.custom["900"] = explode
        with caplog.at_level(logging.ERROR):
            assert decoder.decode(message()) is None
        assert "raised unexpectedly" in caplog.text

    def test_attach_stores_the_result_on_the_message(self, decoder):
        result = decoder.attach(message(payload=PAYLOAD))
        assert result.sensor is not None
        assert result.sensor.model == "TEST_900"

    def test_attach_sets_none_for_an_unknown_protocol(self, decoder):
        result = decoder.attach(message(protocol_id="4711"))
        assert result.sensor is None
