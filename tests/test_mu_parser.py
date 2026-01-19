from unittest.mock import MagicMock

import pytest

from signalduino.parser.mu import MUParser
from signalduino.types import RawFrame


@pytest.fixture
def mu_parser(mock_protocols, logger):
    return MUParser(protocols=mock_protocols, logger=logger)


@pytest.mark.parametrize(
    "line, expected_protocol, expected_rssi",
    [
        ("MU;P0=32001;P1=-1939;P2=1967;D=0121;CP=2;R=39;", "44", -54.5),
        ("MU;P0=-21520;P1=235;P2=-855;D=0121;CP=1;R=217;", "84", -19.5),
    ],
)
def test_mu_parser_valid_messages(mu_parser, mock_protocols, line, expected_protocol, expected_rssi):
    """Test valid MU messages."""
    
    # Mock Protokolldaten
    MOCKED_PROTOCOLS = {
        "44": {"name": "IT-V1_V3", "preamble": "W44#", "format": "BITS", "clock": 250},
        "84": {"name": "Bresser-3_1", "preamble": "W84#", "format": "BITS", "clock": 330},
    }
    mock_protocols.get_protocol_list.return_value = MOCKED_PROTOCOLS
    
    # Erwartete Payloads (Roh-Payload enthält Präambel, gereinigte Payload nicht)
    if expected_protocol == "44":
        raw_payload = "W44#123456"
        expected_clean_payload = "123456"
        expected_protocol_meta = MOCKED_PROTOCOLS["44"]
    else: # expected_protocol == "84"
        raw_payload = "W84#ABCDEF"
        expected_clean_payload = "ABCDEF"
        expected_protocol_meta = MOCKED_PROTOCOLS["84"]

    frame = RawFrame(line=line)
    demodulated = [{"protocol_id": expected_protocol, "payload": raw_payload}]
    mock_protocols.demodulate.return_value = demodulated

    result = list(mu_parser.parse(frame))

    mock_protocols.demodulate.assert_called_once()
    assert len(result) == 1
    
    # Neue/geänderte Assertions
    assert result[0].protocol["id"] == expected_protocol
    assert result[0].data == expected_clean_payload
    assert result[0].raw == line
    
    # Protokoll-Metadaten Assertions
    assert result[0].protocol["id"] == expected_protocol
    assert result[0].protocol["name"] == expected_protocol_meta["name"]
    assert result[0].protocol["preamble"] == expected_protocol_meta["preamble"]
    
    # Correct the expected RSSI value for R=217
    if expected_protocol == "84":
        assert frame.rssi == -93.5
    else:
        assert frame.rssi == expected_rssi


@pytest.mark.parametrize(
    "line, log_message",
    [
        ("MU;P0=-370;D=1;CP=4;R=foo;", "MU message failed regex validation"),
        ("MU;P0=-370;CP=4;R=42;", "MU message failed regex validation"),
        ("FOO;P0=1;D=1;", "Not an MU message"),
        ("MU;P0=-1440;P1=432;P2=-357;P3=635;P4=-559;D=012121212123412343412123434121234343412123412343434341234343412123434121212121212341231212343412341212121;CP=1;V=139;", "MU message failed regex validation"),
    ],
)
def test_mu_parser_corrupt_messages(mu_parser, mock_protocols, caplog, line, log_message):
    """Test corrupt or invalid MU messages."""
    frame = RawFrame(line=line)

    with caplog.at_level("DEBUG"):
        result = list(mu_parser.parse(frame))

    assert not result
    assert log_message in caplog.text