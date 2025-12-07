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
        response = controller.commands.get_version(timeout=1)
        mock_transport.write_line.assert_called_with("V")
        assert response is not None
        assert "SIGNALduino" in response
    finally:
        controller.disconnect()


def test_send_command_with_interleaved_message(mock_transport, mock_parser):
    """
    Test sending a command and receiving an irrelevant message before the
    expected command response. The irrelevant message must not be consumed
    as the response, and the correct response must still be received.
    """
    # Queue for all messages from the device
    response_q = queue.Queue()

    # The irrelevant message (e.g., an asynchronous received signal)
    interleaved_message = "MU;P0=353;P1=-184;D=0123456789;CP=1;SP=0;R=248;\n"
    # The expected command response
    command_response = "V 3.5.0-dev SIGNALduino\n"

    def write_line_side_effect(payload):
        # When the controller writes "V", simulate the device responding with
        # an interleaved message *then* the command response.
        if payload == "V":
            # 1. Interleaved message
            response_q.put(interleaved_message)
            # 2. Command response
            response_q.put(command_response)

    def readline_side_effect():
        # Simulate blocking read that gets a value from the queue.
        try:
            return response_q.get(timeout=0.5)
        except queue.Empty:
            return None

    mock_transport.write_line.side_effect = write_line_side_effect
    mock_transport.readline.side_effect = readline_side_effect

    # Mock the parser to track if the interleaved message is passed to it
    mock_parser.parse_line = Mock(wraps=mock_parser.parse_line)

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.connect()
    try:
        response = controller.commands.get_version(timeout=1)
        mock_transport.write_line.assert_called_with("V")
        
        # 1. Verify that the correct command response was received by send_command
        assert response is not None
        assert "SIGNALduino" in response
        assert response.strip() == command_response.strip()

        # 2. Verify that the interleaved message was passed to the parser
        # The parser loop (_parser_loop) should attempt to parse the interleaved_message
        # because _handle_as_command_response should return False for it.
        mock_parser.parse_line.assert_called_with(interleaved_message.strip())

        # Give the parser thread a moment to process the message
        time.sleep(0.1)
        
    finally:
        controller.disconnect()


def test_send_command_timeout(mock_transport, mock_parser):
    """Test that a command times out if no response is received."""
    mock_transport.readline.return_value = None
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.connect()
    try:
        with pytest.raises(SignalduinoCommandTimeout):
            controller.commands.get_version(timeout=0.2)
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


def test_initialize_retry_logic(mock_transport, mock_parser):
    """Test the retry logic during initialization."""
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.connect()

    # Mock send_command to fail initially and then succeed
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        payload = kwargs.get("payload") or args[0] if args else None

        if payload == "XQ":
            return None
        if payload == "V":
            if call_count <= 2:  # Fail first attempt (XQ is 1st call)
                raise SignalduinoCommandTimeout("Timeout")
            return "V 3.5.0-dev SIGNALduino"
        return None

    mocked_send_command = Mock(side_effect=side_effect)
    controller.commands._send = mocked_send_command

    # Use very short intervals for testing by patching the imported constants in the controller module
    import signalduino.controller
    
    original_wait = signalduino.controller.SDUINO_INIT_WAIT
    original_wait_xq = signalduino.controller.SDUINO_INIT_WAIT_XQ
    
    signalduino.controller.SDUINO_INIT_WAIT = 0.1
    signalduino.controller.SDUINO_INIT_WAIT_XQ = 0.05

    try:
        controller.initialize()
        time.sleep(3.0)  # Wait for timers and retries (increased from 1.5s due to potential race condition)

        # Verify calls:
        # 1. XQ
        # 2. V (fails)
        # 3. V (retry, succeeds)
        # 4. XE (enabled after success)
        
        # Note: Depending on timing and implementation details, call count might vary slighty
        # but we expect at least XQ, failed V, successful V, XE.
        
        calls = [c.kwargs.get('payload') or c.args[0] for c in mocked_send_command.call_args_list]

        assert "XQ" in calls
        assert calls.count("V") >= 2
        assert "XE" in calls

    finally:
        signalduino.controller.SDUINO_INIT_WAIT = original_wait
        signalduino.controller.SDUINO_INIT_WAIT_XQ = original_wait_xq
        controller.disconnect()