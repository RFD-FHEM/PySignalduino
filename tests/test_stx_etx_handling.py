import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from signalduino.controller import SignalduinoController, SignalduinoCommandTimeout
from signalduino.transport import BaseTransport
from signalduino.constants import ASCII_STX, ASCII_ETX

@pytest.fixture
def mock_transport():
    transport = AsyncMock(spec=BaseTransport)
    transport.closed.return_value = False
    transport.readline.side_effect = lambda: asyncio.sleep(0.001) or None
    return transport

@pytest.fixture
def mock_parser():
    parser = MagicMock()
    parser.parse_line.return_value = []
    return parser

@pytest.mark.asyncio
async def test_valid_framing_and_responses(mock_transport, mock_parser):
    """
    Test that:
    1. Valid STX/ETX framed messages (e.g. MC) are passed to parser.
    2. Valid unframed command responses (e.g. V) are handled by controller.
    """
    
    # Valid framed message and valid command response
    framed_msg = f"{ASCII_STX}MC;LL=-1006;LH=937;{ASCII_ETX}\n"
    cmd_response = "V 3.3.1\n"
    
    # Iterator to return messages
    response_iter = iter([framed_msg, cmd_response])
    
    async def readline_side_effect():
        try:
            val = next(response_iter)
            # Give tasks a chance to run
            await asyncio.sleep(0.01)
            return val.strip() # Simulate transport stripping
        except StopIteration:
            await asyncio.sleep(0.1)
            return None
            
    mock_transport.readline.side_effect = readline_side_effect

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    # Mock initialize
    controller.initialize = AsyncMock()
    controller.initialize.side_effect = lambda *args, **kwargs: controller._init_complete_event.set()

    async with controller:
        # Start both tasks
        reader_task = asyncio.create_task(controller._reader_task(), name="reader")
        parser_task = asyncio.create_task(controller._parser_task(), name="parser")
        controller._main_tasks.extend([reader_task, parser_task])
        
        # 1. Send command "V" and wait for "V 3.3.1"
        # The framed_msg should be processed by parser task in background
        try:
            result = await controller.send_command("V", expect_response=True, timeout=2.0)
            assert result is not None
            assert result.strip() == "V 3.3.1"
            
            # 2. Verify framed message was parsed
            # We need to wait a bit to ensure parser task processed the first message
            await asyncio.sleep(0.1)
            
            # Check if parse_line was called with the framed message
            # The parser receives the line from transport, which includes newline (unless stripped by transport)
            # Transport.readline does .strip().
            # So expected line is framed_msg.strip()
            expected_line = framed_msg.strip()
            
            found = False
            for call in mock_parser.parse_line.call_args_list:
                args, _ = call
                if args[0] == expected_line:
                    found = True
                    break
            assert found, f"Parser should have received: {expected_line}"
            
        finally:
            reader_task.cancel()
            parser_task.cancel()
