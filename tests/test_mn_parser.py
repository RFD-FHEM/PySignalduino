import logging
from unittest.mock import MagicMock

import pytest

from signalduino.parser.mn import MNParser
from signalduino.types import RawFrame


@pytest.fixture
def mn_parser(mock_protocols, logger):
    return MNParser(protocols=mock_protocols, logger=logger)


def test_mn_parser_with_rfmode(mock_protocols, logger):
    """Test that an MN message with an rfmode is demodulated."""
    mn_parser = MNParser(protocols=mock_protocols, logger=logger, rfmode="Bresser_6in1")
    line = "MN;D=3BF120B00C1618FF77FF0458152293FFF06B0000;R=242;"
    frame = RawFrame(line=line)
    demodulated = [{"protocol_id": "100"}]
    mock_protocols.demodulate.return_value = demodulated

    result = list(mn_parser.parse(frame))

    mock_protocols.demodulate.assert_called_once()
    assert len(result) == 1
    assert result[0].protocol_id == "100"


def test_mn_parser_without_rfmode(mn_parser, mock_protocols, caplog):
    """Test that an MN message without an rfmode is just logged."""
    line = "MN;D=9AA6362CC8AAAA000012F8F4;R=4;"
    frame = RawFrame(line=line)

    with caplog.at_level(logging.INFO):
        result = list(mn_parser.parse(frame))

    assert not result
    mock_protocols.demodulate.assert_not_called()
    assert "Received firmware message" in caplog.text
