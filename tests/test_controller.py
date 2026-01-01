import asyncio
from asyncio import Queue
from unittest.mock import MagicMock, Mock, AsyncMock

import pytest

from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoCommandTimeout
from signalduino.transport import BaseTransport
from signalduino.types import DecodedMessage, RawFrame


@pytest.fixture
def mock_transport():
    """Fixture for a mocked async transport layer."""
    transport = AsyncMock(spec=BaseTransport)
    transport.is_open = False
    
    # Define side effects that update state but let the Mock track the call
    async def aopen_side_effect(*args, **kwargs):
        transport.is_open = True
        transport.closed.return_value = False
        return transport
    
    async def aclose_side_effect(*args, **kwargs):
        transport.is_open = False
        transport.closed.return_value = True

    transport.open.side_effect = aopen_side_effect
    transport.close.side_effect = aclose_side_effect
    
    # Configure closed() to return True initially (closed)
    transport.closed.return_value = True
    
    # Configure context manager to call open/close methods of the mock
    # This ensures calls are tracked on .open() and .close()
    async def aenter_side_effect(*args, **kwargs):
        return await transport.open()

    async def aexit_side_effect(*args, **kwargs):
        await transport.close()

    transport.__aenter__.side_effect = aenter_side_effect
    transport.__aexit__.side_effect = aexit_side_effect
    
    # Ensure readline yields to prevent busy loops in reader task when returning None
    async def a_readline_side_effect(*args, **kwargs):
        await asyncio.sleep(0.001)
        return None

    transport.readline.side_effect = a_readline_side_effect
    return transport

async def start_controller_tasks(controller):
    """Helper to start the internal tasks of the controller without running full init."""
    reader_task = asyncio.create_task(controller._reader_task(), name="sd-reader")
    parser_task = asyncio.create_task(controller._parser_task(), name="sd-parser")
    writer_task = asyncio.create_task(controller._writer_task(), name="sd-writer")
    controller._main_tasks.extend([reader_task, parser_task, writer_task])
    return reader_task, parser_task, writer_task


@pytest.fixture
def mock_parser():
    """Fixture for a mocked parser."""
    parser = MagicMock()
    parser.parse_line.return_value = []
    return parser


@pytest.mark.asyncio
async def test_connect_disconnect(mock_transport, mock_parser):
    """Test that connect() and disconnect() open/close transport and tasks."""
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    assert controller._main_tasks is None or len(controller._main_tasks) == 0

    async with controller:
        mock_transport.open.assert_called_once()

    mock_transport.close.assert_called_once()


@pytest.mark.asyncio
async def test_send_command_fire_and_forget(mock_transport, mock_parser):
    """Test sending a command without expecting a response."""
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        # Start writer task to process the queue
        writer_task = asyncio.create_task(controller._writer_task())
        controller._main_tasks.append(writer_task)
        
        await controller.send_command("V", expect_response=False)
        # Verify command was queued
        assert controller._write_queue.qsize() == 1
        cmd = await controller._write_queue.get()
        assert cmd.payload == "V"
        assert not cmd.expect_response
        # Ensure the writer task is cancelled to avoid hanging
        writer_task.cancel()


@pytest.mark.asyncio
async def test_send_command_with_response(mock_transport, mock_parser):
    """Test sending a command and waiting for a response."""
    response = "V 3.5.0-dev SIGNALduino\n"

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        # Start writer task to process the queue
        writer_task = asyncio.create_task(controller._writer_task())
        controller._main_tasks.append(writer_task)
        
        # The reader task should process the response line once.
        response_iterator = iter([response])
        async def mock_readline_blocking():
            try:
                return next(response_iterator)
            except StopIteration:
                await asyncio.Future() # Block indefinitely after first message

        mock_transport.readline.side_effect = mock_readline_blocking

        # Start reader and parser tasks to process responses
        reader_task = asyncio.create_task(controller._reader_task())
        parser_task = asyncio.create_task(controller._parser_task())
        controller._main_tasks.extend([reader_task, parser_task])
        
        result = await controller.send_command("V", expect_response=True, timeout=10.0)
        assert result == response
        mock_transport.write_line.assert_called_once_with("V")
        # Ensure the writer task is cancelled to avoid hanging
        writer_task.cancel()


@pytest.mark.asyncio
async def test_send_command_with_interleaved_message(mock_parser):
    """Test handling of interleaved messages during command response."""
    from .test_transport import TestTransport
    
    transport = TestTransport()
    interleaved_msg = "MU;P0=353;P1=-184;D=0123456789;CP=1;SP=0;R=248;\n"
    response = "V 3.5.0-dev SIGNALduino\n"
    
    # Add messages to transport
    transport.add_message(interleaved_msg)
    transport.add_message(response)
    
    controller = SignalduinoController(transport=transport, parser=mock_parser)
    async with controller:
        reader_task, parser_task, writer_task = await start_controller_tasks(controller)
        result = await controller.send_command("V", expect_response=True, timeout=10.0)
        assert result == response
        # The interleaved message is ignored by send_command (treated as interleaved)
        # No parsing occurs because parser tasks are not running


@pytest.mark.asyncio
async def test_send_command_timeout(mock_transport, mock_parser):
    """Test command timeout when no response is received."""
    mock_transport.readline.side_effect = asyncio.TimeoutError()

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        with pytest.raises(SignalduinoCommandTimeout):
            await controller.send_command("V", expect_response=True, timeout=0.1)


@pytest.mark.asyncio
async def test_message_callback(mock_transport, mock_parser):
    """Test message callback invocation."""
    callback_mock = Mock()
    decoded_msg = DecodedMessage(protocol_id="1", payload="test", raw=RawFrame(line=""))
    mock_parser.parse_line.return_value = [decoded_msg]
    
    # Use side_effect to return the line once, then fall back to the fixture's yielding None
    mock_transport.readline.side_effect = ["MS;P0=1;D=...;\n", None]

    controller = SignalduinoController(
        transport=mock_transport,
        parser=mock_parser,
        message_callback=callback_mock
    )
    async with controller:
        await start_controller_tasks(controller)
        await asyncio.sleep(0.1)  # Allow time for message processing
        callback_mock.assert_called_once_with(decoded_msg)


@pytest.mark.asyncio
async def test_initialize_retry_logic(mock_transport, mock_parser):
    """Test initialization retry logic with proper task cleanup."""
    # Track command attempts
    attempts = []
    
    async def send_command_side_effect(cmd, **kwargs):
        attempts.append(cmd)
        if cmd == "V" and len(attempts) == 1:
            raise SignalduinoCommandTimeout("Timeout")
        return "V 3.5.0-dev SIGNALduino\n"
    
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.send_command = AsyncMock(side_effect=send_command_side_effect)
    
    try:
        async with controller:
            # Start initialization
            init_task = asyncio.create_task(controller.initialize())
            
            # Wait for completion with timeout
            try:
                await asyncio.wait_for(init_task, timeout=12.0)
            except asyncio.TimeoutError:
                init_task.cancel()
                pytest.fail("Initialization timed out")
            
            # Verify retry behavior: V (timeout) -> V (success) -> XQ (final command)
            assert attempts[0] == "V"
            assert attempts[1] == "V"
            assert attempts[2] == "XQ"
            assert len(attempts) >= 3 # At least two V attempts and the final XQ
            assert all(cmd in ("V", "XQ") for cmd in attempts) # Only V and XQ commands
    finally:
        # Ensure all tasks are cancelled
        if hasattr(controller, '_main_tasks'):
            for task in controller._main_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*controller._main_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_stx_message_bypasses_command_response(mock_transport, mock_parser):
    """Test STX messages bypass command response handling."""
    stx_msg = "\x02SomeSensorData\x03\n"
    response = "? V X t R C S U P G r W x E Z\n"
    mock_transport.readline.side_effect = [stx_msg, response]

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        reader_task, parser_task, writer_task = await start_controller_tasks(controller)

        result = await controller.send_command("?", expect_response=True, timeout=5.0)
        assert result == response
        # Both lines are passed to the parser (this confirms the parser is not bypassed)
        assert mock_parser.parse_line.call_count == 2
        # The STX message is stripped and passed to the parser
        mock_parser.parse_line.assert_any_call(stx_msg)
        # The command response is also passed to the parser
        mock_parser.parse_line.assert_any_call(response)