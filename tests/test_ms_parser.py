from unittest.mock import MagicMock

import pytest

from signalduino.parser.ms import MSParser
from signalduino.types import RawFrame


@pytest.fixture
def ms_parser(mock_protocols, logger):
    return MSParser(protocols=mock_protocols, logger=logger)


@pytest.mark.parametrize(
    "line, expected_protocol, expected_payload, expected_rssi",
    [
        (
            "MS;P1=502;P2=-9212;P3=-1939;P4=-3669;D=12131413141414131313131313141313131313131314141414141413131313141413131413;CP=1;SP=2;R=42;",
            "2",
            "sA018185020",
            -53.0,
        ),
        # Add more valid test cases here
    ],
)
def test_ms_parser_valid_messages(ms_parser, mock_protocols, line, expected_protocol, expected_payload, expected_rssi):
    """Test valid MS messages."""
    frame = RawFrame(line=line)
    demodulated = [{"protocol_id": expected_protocol, "payload": expected_payload}]
    mock_protocols.demodulate.return_value = demodulated

    result = list(ms_parser.parse(frame))

    mock_protocols.demodulate.assert_called_once()
    assert len(result) == 1
    assert result[0].protocol_id == expected_protocol
    assert result[0].payload == expected_payload
    assert frame.rssi == expected_rssi


@pytest.mark.parametrize(
    "line, log_message",
    [
        ("MS;P1=-8043;D=212123;CP=2;SP=1;R=1q;", "Could not parse RSSI value: 1q"),
        ("MS;P1=1;CP=1;R=42;", "Ignoring MS message without data (D)"),
        ("FOO;P1=1;D=1;", "Not an MS message"),
    ],
)
def test_ms_parser_corrupt_messages(ms_parser, mock_protocols, caplog, line, log_message):
    """Test corrupt or invalid MS messages."""
    frame = RawFrame(line=line)

    with caplog.at_level("DEBUG"):
        result = list(ms_parser.parse(frame))

    assert not result
    assert log_message in caplog.text
