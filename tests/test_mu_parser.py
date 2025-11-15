from unittest.mock import MagicMock

import pytest

from signalduino.parser.mu import MUParser
from signalduino.types import RawFrame


@pytest.fixture
def mu_parser(mock_protocols, logger):
    return MUParser(protocols=mock_protocols, logger=logger)


def test_mu_parser_valid_message(mu_parser, mock_protocols):
    """Test a valid MU message."""
    line = "MU;P0=32001;P1=-1939;P2=1967;D=0121;CP=2;R=39;"
    frame = RawFrame(line=line)
    demodulated = [{"protocol_id": "44"}]
    mock_protocols.demodulate.return_value = demodulated

    result = list(mu_parser.parse(frame))

    mock_protocols.demodulate.assert_called_once()
    assert len(result) == 1
    assert result[0].protocol_id == "44"
    assert frame.rssi == -54.5


def test_mu_parser_corrupt_message(mu_parser, mock_protocols, caplog):
    """Test a corrupt MU message."""
    line = "MU;P0=-370;D=1;CP=4;R=foo;"
    frame = RawFrame(line=line)

    result = list(mu_parser.parse(frame))

    assert not result
    mock_protocols.demodulate.assert_called_once()
    assert "Could not parse RSSI value: foo" in caplog.text
