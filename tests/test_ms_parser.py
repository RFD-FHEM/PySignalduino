from unittest.mock import MagicMock

import pytest

from signalduino.parser.ms import MSParser
from signalduino.types import RawFrame


@pytest.fixture
def ms_parser(mock_protocols, logger):
    return MSParser(protocols=mock_protocols, logger=logger)


def test_ms_parser_valid_message(ms_parser, mock_protocols):
    """Test a valid MS message."""
    line = "MS;P1=502;P2=-9212;P3=-1939;P4=-3669;D=12131413141414131313131313141313131313131314141414141413131313141413131413;CP=1;SP=2;R=42;"
    frame = RawFrame(line=line)
    demodulated = [{"protocol_id": "2", "payload": "sA018185020"}]
    mock_protocols.demodulate.return_value = demodulated

    result = list(ms_parser.parse(frame))

    mock_protocols.demodulate.assert_called_once()
    assert len(result) == 1
    assert result[0].protocol_id == "2"
    assert frame.rssi == -53.0


def test_ms_parser_corrupt_message(ms_parser, mock_protocols, caplog):
    """Test a corrupt MS message."""
    line = "MS;P1=-8043;D=212123;CP=2;SP=1;R=1q;"
    frame = RawFrame(line=line)

    result = list(ms_parser.parse(frame))

    assert not result
    mock_protocols.demodulate.assert_called_once()
    assert "Could not parse RSSI value: 1q" in caplog.text
