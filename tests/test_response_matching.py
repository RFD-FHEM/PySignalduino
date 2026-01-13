import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from signalduino.controller import SignalduinoController, SignalduinoCommandTimeout
from signalduino.types import DecodedMessage

# Mock transport setup (copied from test_controller.py since it's not exported)
@pytest.fixture
def mock_transport():
    from signalduino.transport import BaseTransport
    transport = AsyncMock(spec=BaseTransport)
    transport.closed.return_value = False
    
    async def a_readline_side_effect(*args, **kwargs):
        await asyncio.sleep(0.001)
        return None
    transport.readline.side_effect = a_readline_side_effect
    return transport

@pytest.fixture
def mock_parser():
    parser = MagicMock()
    parser.parse_line.return_value = []
    return parser

@pytest.fixture
def mock_controller_init(monkeypatch):
    async def mock_initialize(self, timeout=None):
        self._main_tasks = [
            asyncio.create_task(self._reader_task(), name="sd-reader"),
            asyncio.create_task(self._parser_task(), name="sd-parser"),
            asyncio.create_task(self._writer_task(), name="sd-writer")
        ]
        self._init_complete_event.set()
    monkeypatch.setattr(SignalduinoController, "initialize", mock_initialize)

@pytest.mark.asyncio
async def test_response_matching_separator(mock_transport, mock_parser, mock_controller_init):
    """
    Test that commands match responses separated by ';' or '=' and not just space.
    Reproduction of issue where 'SR' does not match 'SR;R=1'.
    """
    # Setup transport to return the response
    response_line = "SR;R=1\n"
    
    # We use an iterator to yield the response once, then sleep
    response_iter = iter([response_line])
    async def readline_side_effect():
        try:
            return next(response_iter)
        except StopIteration:
            await asyncio.sleep(1) # Keep connection open
            return None
            
    mock_transport.readline.side_effect = readline_side_effect

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        # We expect this to SUCCEED if the fix is implemented.
        # Currently it should TIMEOUT or fail if the logic is too strict.
        try:
            result = await controller.send_command("SR", expect_response=True, timeout=1.0)
            assert result.strip() == response_line.strip()
        except SignalduinoCommandTimeout:
            pytest.fail("Command 'SR' timed out waiting for 'SR;R=1' response. Logic is too strict.")

@pytest.mark.asyncio
async def test_response_matching_false_positive(mock_transport, mock_parser, mock_controller_init):
    """
    Test that 'M' does NOT match 'MN;D=...'.
    Ensures that relaxing the check doesn't introduce false positives.
    """
    # Transport sends MN message first, then the actual response
    mn_message = "MN;D=01010101;\n"
    actual_response = "M OK\n"
    
    response_iter = iter([mn_message, actual_response])
    async def readline_side_effect():
        try:
            await asyncio.sleep(0.01)
            return next(response_iter)
        except StopIteration:
            await asyncio.sleep(1)
            return None
            
    mock_transport.readline.side_effect = readline_side_effect

    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        # We send 'M' and expect 'M OK'. 'MN...' should be ignored.
        result = await controller.send_command("M", expect_response=True, timeout=1.0)
        assert result.strip() == actual_response.strip()
        
        # Verify that MN was NOT matched
        assert result.strip() != mn_message.strip()

@pytest.mark.asyncio
async def test_response_matching_exact(mock_transport, mock_parser, mock_controller_init):
    """Test exact match works."""
    response_line = "XYZ\n"
    mock_transport.readline.side_effect = [response_line, asyncio.sleep(1)]
    
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        result = await controller.send_command("XYZ", expect_response=True, timeout=1.0)
        assert result.strip() == response_line.strip()
