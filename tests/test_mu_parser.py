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
    frame = RawFrame(line=line)
    demodulated = [{"protocol_id": expected_protocol}]
    mock_protocols.demodulate.return_value = demodulated

    result = list(mu_parser.parse(frame))

    mock_protocols.demodulate.assert_called_once()
    assert len(result) == 1
    assert result[0].protocol_id == expected_protocol
    # Correct the expected RSSI value for R=217
    if expected_protocol == "84":
        assert frame.rssi == -93.5
    else:
        assert frame.rssi == expected_rssi


@pytest.mark.parametrize(
    "line, log_message",
    [
        ("MU;P0=-370;D=1;CP=4;R=foo;", "Could not parse RSSI value: foo"),
        ("MU;P0=-370;CP=4;R=42;", "Ignoring MU message without data (D)"),
        ("FOO;P0=1;D=1;", "Not an MU message"),
    ],
)
def test_mu_parser_corrupt_messages(mu_parser, mock_protocols, caplog, line, log_message):
    """Test corrupt or invalid MU messages."""
    frame = RawFrame(line=line)

    with caplog.at_level("DEBUG"):
        result = list(mu_parser.parse(frame))

    assert not result
    assert log_message in caplog.text