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
    
    transport.readline.return_value = None
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
    mock_transport.readline.return_value = response

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        result = await controller.send_command("V", expect_response=True, timeout=1)
        assert result == response
        mock_transport.write_line.assert_called_once_with("V")


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
        # Do NOT start reader_task; let send_command read the messages directly
        result = await controller.send_command("V", expect_response=True, timeout=1)
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
    mock_transport.readline.return_value = "MS;P0=1;D=...;\n"

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
    """Test initialization retry logic."""
    # Mock send_command to fail first V attempt then succeed
    async def send_command_side_effect(cmd, **kwargs):
        if cmd == "V":
            if not hasattr(send_command_side_effect, "attempt"):
                setattr(send_command_side_effect, "attempt", 1)
                raise SignalduinoCommandTimeout("Timeout")
            return "V 3.5.0-dev SIGNALduino\n"
        return None

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller.send_command = AsyncMock(side_effect=send_command_side_effect)
    
    async with controller:
        await controller.initialize()
        assert controller.send_command.call_count >= 2  # At least one retry


@pytest.mark.asyncio
async def test_stx_message_bypasses_command_response(mock_transport, mock_parser):
    """Test STX messages bypass command response handling."""
    stx_msg = "\x02SomeSensorData\x03\n"
    response = "V X t R C S U P G r W x E Z\n"
    mock_transport.readline.side_effect = [stx_msg, response]

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        result = await controller.send_command("?", expect_response=True, timeout=1)
        assert result == response
        mock_parser.parse_line.assert_called_once_with(stx_msg.strip())