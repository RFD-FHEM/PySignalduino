"""Stage 1 baseline and the bit string enabler for stage 2 (ADR-006).

Two things are guarded here. First, how many of the FHEM test vectors the
demodulation currently reproduces exactly - if a stage 2 change breaks stage 1,
that number drops and this test fails. Second, that the demodulated bit string
actually reaches DecodedMessage.metadata, because the decoders work on bits and
cannot be built without it.
"""

from __future__ import annotations

import pytest

from signalduino.parser import SignalParser
from signalduino.types import DecodedMessage, SensorEvent

from .fhem_vectors import load_vectors, vectors_for_protocol

# Measured on the vendored sd_ws vectors. Raise it when stage 1 improves,
# never lower it silently - a drop means a regression.
BASELINE_MATCHES = 86
BASELINE_TOTAL = 99

# Protocols in daily use here, which must not regress individually.
REQUIRED_PROTOCOLS = ["27", "50", "85", "125", "126"]


@pytest.fixture(scope="module")
def parser() -> SignalParser:
    return SignalParser()


def _payloads(parser: SignalParser, vector) -> list[str]:
    return [message.payload for message in parser.parse_line(vector.framed_rmsg)]


def test_vectors_are_vendored():
    vectors = load_vectors("sd_ws")
    assert len(vectors) == BASELINE_TOTAL, (
        "Vendored vector count changed - re-run tools/fhem_testdata_import.py "
        "and update the baseline deliberately."
    )


def test_stage1_baseline_is_met(parser):
    """The demodulation must reproduce at least the known number of dmsg strings."""
    matches = sum(
        1 for vector in load_vectors("sd_ws") if vector.dmsg in _payloads(parser, vector)
    )
    assert matches >= BASELINE_MATCHES, (
        f"Stage 1 regression: {matches}/{BASELINE_TOTAL} vectors match, "
        f"baseline is {BASELINE_MATCHES}."
    )


@pytest.mark.parametrize("protocol_id", REQUIRED_PROTOCOLS)
def test_protocols_in_use_decode_completely(parser, protocol_id):
    """Protocols with actual hardware behind them must match every vector."""
    vectors = vectors_for_protocol(protocol_id)
    assert vectors, f"No vectors for protocol {protocol_id}"
    for vector in vectors:
        assert vector.dmsg in _payloads(parser, vector), f"{vector} did not decode"


@pytest.mark.parametrize("protocol_id", ["27", "85"])
def test_bit_string_reaches_metadata(parser, protocol_id):
    """Stage 2 needs the bit string, not just its length."""
    for vector in vectors_for_protocol(protocol_id):
        for message in parser.parse_line(vector.framed_rmsg):
            if message.payload != vector.dmsg:
                continue
            bits = message.metadata.get("bits")
            assert isinstance(bits, str) and bits, f"No bit string for {vector}"
            assert set(bits) <= {"0", "1"}, f"Bit string is not binary: {bits[:32]}"
            assert len(bits) == message.metadata["bit_length"]
            return
    pytest.fail(f"No matching message for protocol {protocol_id}")


def test_decoded_message_has_optional_sensor_field():
    """DecodedMessage carries stage 2 results without changing existing usage."""
    message = DecodedMessage(protocol_id="125", payload="W125#AB", raw=None)
    assert message.sensor is None

    message.sensor = SensorEvent(
        protocol_id="125",
        model="SD_WS_125_TH",
        sensor_type="WH31e",
        device_id="SD_WS_125_TH_02_1",
        sensor_id="02",
        values={"temperature": 21.0},
        units={"temperature": "°C"},
        channel=1,
    )
    assert message.sensor.values["temperature"] == 21.0
