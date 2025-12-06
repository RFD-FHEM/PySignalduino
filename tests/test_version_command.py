import queue
import re
import time
from unittest.mock import MagicMock, Mock

import pytest

from signalduino.controller import SignalduinoController
from signalduino.constants import SDUINO_CMD_TIMEOUT
from signalduino.exceptions import SignalduinoCommandTimeout
from signalduino.transport import BaseTransport


@pytest.fixture
def mock_transport():
    """Fixture for a mocked transport layer."""
    transport = Mock(spec=BaseTransport)
    transport.is_open = False
    transport.readline.return_value = None

    def open_mock():
        transport.is_open = True

    def close_mock():
        transport.is_open = False

    transport.open.side_effect = open_mock
    transport.close.side_effect = close_mock
    return transport


@pytest.fixture
def mock_parser():
    """Fixture for a mocked parser."""
    parser = MagicMock()
    parser.parse_line.return_value = []
    return parser


def test_version_command_success(mock_transport, mock_parser):
    """Test that the version command works with the specific regex."""
    # Use a queue to synchronize the mock's write and read calls
    response_q = queue.Queue()

    def write_line_side_effect(payload):
        # When the controller writes "V", simulate the device responding correctly.
        if payload == "V":
            response_q.put("V 3.5.0-dev SIGNALduino cc1101 (optiboot) - compiled at 20250219\n")

    def readline_side_effect(timeout=None):
        try:
            return response_q.get(timeout=0.5)
        except queue.Empty:
            return None

    mock_transport.write_line.side_effect = write_line_side_effect
    mock_transport.readline.side_effect = readline_side_effect

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.connect()
    try:
        # Define the regex pattern as used in main.py
        version_pattern = re.compile(r"V\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE)
        
        response = controller.send_command(
            "V", 
            expect_response=True, 
            timeout=SDUINO_CMD_TIMEOUT,
            response_pattern=version_pattern
        )
        
        mock_transport.write_line.assert_called_with("V")
        assert response is not None
        assert "SIGNALduino" in response
        assert "V 3.5.0-dev" in response
    finally:
        controller.disconnect()


def test_version_command_with_noise_before(mock_transport, mock_parser):
    """Test that the version command works even if other data comes first."""
    response_q = queue.Queue()

    def write_line_side_effect(payload):
        if payload == "V":
            # Simulate some noise/other messages before the actual version response
            response_q.put("MS;P0=123;D=123;\n")
            response_q.put("MU;P0=-456;D=456;\n")
            response_q.put("V 3.5.0-dev SIGNALduino\n")

    def readline_side_effect(timeout=None):
        try:
            return response_q.get(timeout=0.5)
        except queue.Empty:
            return None

    mock_transport.write_line.side_effect = write_line_side_effect
    mock_transport.readline.side_effect = readline_side_effect

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.connect()
    try:
        version_pattern = re.compile(r"V\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE)
        
        response = controller.send_command(
            "V", 
            expect_response=True, 
            timeout=SDUINO_CMD_TIMEOUT,
            response_pattern=version_pattern
        )
        
        assert response is not None
        assert "SIGNALduino" in response
    finally:
        controller.disconnect()


def test_version_command_timeout(mock_transport, mock_parser):
    """Test that the version command times out correctly."""
    mock_transport.readline.return_value = None
    
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.connect()
    try:
        version_pattern = re.compile(r"V\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE)
        
        with pytest.raises(SignalduinoCommandTimeout):
            controller.send_command(
                "V", 
                expect_response=True, 
                timeout=0.2, # Short timeout for test
                response_pattern=version_pattern
            )
    finally:
        controller.disconnect()