from unittest.mock import MagicMock

import pytest

from signalduino.parser.mc import MCParser
from signalduino.types import RawFrame


@pytest.fixture
def mc_parser(mock_protocols, logger):
    return MCParser(protocols=mock_protocols, logger=logger)


def test_mc_parser_valid_message(mc_parser, mock_protocols):
    """Test a valid MC message."""
    line = "MC;LL=-653;LH=679;SL=-310;SH=351;D=D55B58;C=332;L=21;R=20;"
    frame = RawFrame(line=line)
    demodulated = [{"protocol_id": "57"}]
    mock_protocols.demodulate.return_value = demodulated

    result = list(mc_parser.parse(frame))

    mock_protocols.demodulate.assert_called_once()
    assert len(result) == 1
    assert result[0].protocol_id == "57"
    assert frame.rssi == -64.0


def test_mc_parser_corrupt_message(mc_parser, mock_protocols, caplog):
    """Test a corrupt MC message."""
    line = "MC;LL=-762;LH=544;D=DB6;C=342;L=12;R=bar;"
    frame = RawFrame(line=line)

    result = list(mc_parser.parse(frame))

    assert not result
    mock_protocols.demodulate.assert_called_once()
    assert "Could not parse RSSI value: bar" in caplog.text
