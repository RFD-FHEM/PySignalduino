import queue
import threading
import time
from unittest.mock import MagicMock, Mock

import pytest

from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoCommandTimeout
from signalduino.transport import BaseTransport
from signalduino.types import DecodedMessage, RawFrame


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


def test_connect_disconnect(mock_transport, mock_parser):
    """Test that connect() and disconnect() open/close transport and threads."""
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    assert controller._reader_thread is None

    controller.connect()

    mock_transport.open.assert_called_once()
    assert controller._reader_thread.is_alive()
    assert controller._parser_thread.is_alive()
    assert controller._writer_thread.is_alive()

    time.sleep(0.1)

    controller.disconnect()

    mock_transport.close.assert_called_once()
    assert not controller._reader_thread.is_alive()
    assert not controller._parser_thread.is_alive()
    assert not controller._writer_thread.is_alive()


def test_send_command_fire_and_forget(mock_transport, mock_parser):
    """Test sending a command without expecting a response."""
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.connect()
    try:
        controller.send_command("V")
        cmd = controller._write_queue.get(timeout=1)
        assert cmd.payload == "V"
        assert not cmd.expect_response
    finally:
        controller.disconnect()


def test_send_command_with_response(mock_transport, mock_parser):
    """Test sending a command and waiting for a response."""
    # Use a queue to synchronize the mock's write and read calls
    response_q = queue.Queue()

    def write_line_side_effect(payload):
        # When the controller writes "V", simulate the device responding.
        if payload == "V":
            response_q.put("V 3.5.0-dev SIGNALduino\n")

    def readline_side_effect():
        # Simulate blocking read that gets a value after write_line is called.
        try:
            return response_q.get(timeout=0.5)
        except queue.Empty:
            return None

    mock_transport.write_line.side_effect = write_line_side_effect
    mock_transport.readline.side_effect = readline_side_effect

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.connect()
    try:
        response = controller.send_command("V", expect_response=True, timeout=1)
        mock_transport.write_line.assert_called_with("V")
        assert response is not None
        assert "SIGNALduino" in response
    finally:
        controller.disconnect()


def test_send_command_timeout(mock_transport, mock_parser):
    """Test that a command times out if no response is received."""
    mock_transport.readline.return_value = None
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.connect()
    try:
        with pytest.raises(SignalduinoCommandTimeout):
            controller.send_command("V", expect_response=True, timeout=0.2)
    finally:
        controller.disconnect()


def test_message_callback(mock_transport, mock_parser):
    """Test that the message callback is invoked for decoded messages."""
    callback_mock = Mock()
    decoded_msg = DecodedMessage(protocol_id="1", payload="test", raw=RawFrame(line=""))
    mock_parser.parse_line.return_value = [decoded_msg]

    def readline_side_effect():
        yield "MS;P0=1;D=...;\n"
        while True:
            yield None

    readline_gen = readline_side_effect()
    mock_transport.readline.side_effect = lambda: next(readline_gen)

    controller = SignalduinoController(
        transport=mock_transport,
        parser=mock_parser,
        message_callback=callback_mock,
    )

    controller.connect()
    time.sleep(0.2)

    try:
        callback_mock.assert_called_once_with(decoded_msg)
    finally:
        controller.disconnect()