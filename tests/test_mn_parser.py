import logging
from unittest.mock import MagicMock

import pytest

from signalduino.parser.mn import MNParser
from signalduino.types import RawFrame


@pytest.fixture
def mn_parser_factory(mock_protocols, logger):
    def _mn_parser(rfmode: str | None = None):
        return MNParser(protocols=mock_protocols, logger=logger, rfmode=rfmode)
    return _mn_parser


@pytest.mark.parametrize(
    "line, rfmode, expected_protocol_id, expected_log_message, expects_demodulate_call, raises_exception",
    [
        # Valid messages with rfmode
        (
            "MN;D=3BF120B00C1618FF77FF0458152293FFF06B0000;R=242;",
            "Bresser_6in1",
            "100",
            None,
            True,
            False,
        ),
        (
            "MN;D=2547F536721602000231D27C7A000008000F80130001090086B41E00175914011B0806020400000000001945000E;R=14;A=0;",
            "WMBus_T",
            "200",
            None,
            True,
            False,
        ),
        # Valid messages without rfmode (should just log)
        (
            "MN;D=9AA6362CC8AAAA000012F8F4;R=4;",
            None,
            None,
            "Received firmware message",
            False,
            False,
        ),
        (
            "MN;D=07FA5E1721CC0F02FE000000000000;",
            None,
            None,
            "Received firmware message",
            False,
            False,
        ),
        # Corrupt messages with rfmode (demodulation should fail)
        (
            "MN;D=9AA63&2CC8AAAA000012F8F4;R=4;",  # Corrupt D=
            "Bresser_6in1",
            None,
            "Error during MN demodulation for line:",
            True,
            True,
        ),
        (
            "MN;D=01050;",  # Message too short
            "Lacrosse_mode2",
            None,
            "Error during MN demodulation for line:",
            True,
            True,
        ),
        # Corrupt messages without rfmode (should just log)
        (
            "MN;D=9AA63&2CC8AAAA000012F8F4;R=4;",
            None,
            None,
            "Received firmware message",
            False,
            False,
        ),
        # Invalid message type
        ("FOO;D=1;", None, None, "Not an MN message", False, False),
    ],
)
def test_mn_parser_messages(
    mn_parser_factory, mock_protocols, caplog, line, rfmode, expected_protocol_id, expected_log_message, expects_demodulate_call, raises_exception
):
    """Test various MN messages with and without rfmode, including corrupt ones."""
    mn_parser = mn_parser_factory(rfmode=rfmode)
    frame = RawFrame(line=line)

    if raises_exception:
        mock_protocols.demodulate.side_effect = Exception("Demodulation Error")

    with caplog.at_level(logging.DEBUG if expects_demodulate_call else logging.INFO):
        result = list(mn_parser.parse(frame))

    if expected_log_message:
        assert expected_log_message in caplog.text

    if expects_demodulate_call:
        mock_protocols.demodulate.assert_called_once()
        if not raises_exception:
            assert len(result) == 1
            assert result[0].protocol_id == expected_protocol_id
        else:
            assert not result
        mock_protocols.demodulate.side_effect = None  # Reset side effect
    else:
        mock_protocols.demodulate.assert_not_called()
        assert not result