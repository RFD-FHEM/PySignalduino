from unittest.mock import MagicMock

import pytest

from signalduino.parser.mc import MCParser
from signalduino.types import RawFrame


@pytest.fixture
def mc_parser(mock_protocols, logger):
    return MCParser(protocols=mock_protocols, logger=logger)


@pytest.mark.parametrize(
    "line, expected_protocol, expected_payload, expected_rssi",
    [
        (
            "MC;LL=-653;LH=679;SL=-310;SH=351;D=D55B58;C=332;L=21;R=20;",
            "57",
            "D55B58", # Original test case
            -64.0,
        ),
        (
            "MC;LL=-762;LH=544;SL=-402;SH=345;D=DB6D5B54;C=342;L=48;R=32;", # Funkbus (PID 119) - 48 bits
            "119",
            "2C175F30008F", # Expected Funkbus hex output (48 bits -> 12 Hex chars)
            -58.0,
        ),
        (
            "MC;LL=100;LH=100;D=11112222;C=500;L=32;R=10;", # Grothe (PID 108) - 32 bits
            "108",
            "AAAAAAAA", # Expected Grothe hex output (32 bits -> 8 Hex chars)
            -69.0,
        ),
    ],
)
def test_mc_parser_valid_message(mc_parser, mock_protocols, line, expected_protocol, expected_payload, expected_rssi):
    """Test valid MC messages."""
    frame = RawFrame(line=line)
    demodulated = [{"protocol_id": expected_protocol, "payload": expected_payload}]
    mock_protocols.demodulate_mc.return_value = demodulated

    result = list(mc_parser.parse(frame))

    mock_protocols.demodulate_mc.assert_called_once()
    assert len(result) == 1
    assert result[0].protocol_id == expected_protocol
    assert result[0].payload == expected_payload
    assert frame.rssi == expected_rssi


@pytest.mark.parametrize(
    "line, log_message, expects_demodulate_call, raises_exception",
    [
        ("MC;LL=-762;LH=544;D=DB6;C=342;L=12;R=bar;", "Could not parse RSSI value: bar", False, True),
        (
            "MC;LL=-653;LH=679;SL=-310;SH=351;C=332;L=21;R=20;",
            "Ignoring MC message missing required fields (D, C, or L)",
            False, # No 'D=' part, so demodulate is not called
            False,
        ),
        ("FOO;LL=1;D=FF;", "Not an MC message", False, False),
        ("MC;LL=-2738;LH=3121;SL=-1268;SH=1667;D=GGD9FF0E;C=1465;L=32;R=246;", "Ignoring MC message with non-hexadecimal raw_hex:", False, True),
    ],
)
def test_mc_parser_corrupt_messages(mc_parser, mock_protocols, caplog, line, log_message, expects_demodulate_call, raises_exception):
    """Test corrupt MC messages with logging."""
    frame = RawFrame(line=line)

    if raises_exception:
        mock_protocols.demodulate.side_effect = Exception("Demodulation Error")

    with caplog.at_level("DEBUG"):
        result = list(mc_parser.parse(frame))

    assert not result
    assert log_message in caplog.text

    if expects_demodulate_call:
        mock_protocols.demodulate.assert_called_once()
    else:
        mock_protocols.demodulate.assert_not_called()

    if raises_exception:
        mock_protocols.demodulate.side_effect = None  # Reset side effect


@pytest.mark.parametrize(
    "line, expects_demodulate_call",
    [
        ("MC;LL=-2883;LH=2982;XX=-1401;SH=1509;D=AF7EFF2E;C=1466;L=31;R=14;", False),
        ("MC;LL=-2895;LH=2976;S=-1401;SH=1685;D=AFBEFFCE;C=1492;L=31;R=23;", False),
        ("MC;LL=-2901;LH=2958{SL=-1412;SH=1509;D=AFBEFFCE;C=1463;L=31;R=17;", False),
        ("MC;LH=-2889;LH=2963;SL=-1420;SH=1514;D=AF377F87;C=1464;L=32;R=11;", False),
        ("MC;LL=-2872:LH=2985;SL=-1401;SH=1527;D=AFFB7F2B;C=1464;L=32;R=10;", False),
        ("MC;LL=-2868;LL=-1416;SH=1525;D=AFBB7F4B;C=1468;L=32;R=16;", False),
        ("MC;LL=-762;LH=544;SL=-402;SH=345;D=DB6D5B54;C=342;L=30;R=32;", False),  # Too long (sd_protocols responsibility)
        ("MC;LL=-762;LH=544;SL=-402;SH=345;D=DB6;C=342;L=12;R=32;", False),  # Too short (sd_protocols responsibility)
    ],
)
def test_mc_parser_demodulate_failures(mc_parser, mock_protocols, line, expects_demodulate_call):
    """Test MC messages that are passed to demodulate but expected to fail there."""
    frame = RawFrame(line=line)
    mock_protocols.demodulate.reset_mock()

    result = list(mc_parser.parse(frame))

    assert result == []
    if expects_demodulate_call:
        mock_protocols.demodulate.assert_called_once()
    else:
        mock_protocols.demodulate.assert_not_called()