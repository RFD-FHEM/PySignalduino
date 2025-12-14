import logging
import asyncio
from unittest.mock import MagicMock, Mock, AsyncMock

import pytest
import pytest_asyncio

from sd_protocols import SDProtocols
from signalduino.types import DecodedMessage
from signalduino.controller import SignalduinoController


@pytest.fixture
def logger():
    """Fixture for a logger."""
    return logging.getLogger(__name__)


@pytest.fixture
def proto():
    """Fixture for a real SDProtocols instance."""
    return SDProtocols()

@pytest.fixture
def mock_protocols(mocker):
    """Fixture for a mocked SDProtocols instance."""
    mock = mocker.patch("signalduino.parser.mc.SDProtocols", autospec=True)
    return mock.return_value


@pytest.fixture
def mock_transport():
    """Fixture for a mocked async transport layer."""
    transport = AsyncMock()
    transport.is_open = True
    transport.write_line = AsyncMock()
    
    async def aopen_mock():
        transport.is_open = True
    
    async def aclose_mock():
        transport.is_open = False

    transport.aopen.side_effect = aopen_mock
    transport.aclose.side_effect = aclose_mock
    transport.__aenter__.return_value = transport
    transport.__aexit__.return_value = None
    transport.readline.return_value = None
    return transport


@pytest_asyncio.fixture
async def controller(mock_transport):
    """Fixture for a SignalduinoController with a mocked transport."""
    ctrl = SignalduinoController(transport=mock_transport)

    # Verwende eine interne Queue, um das Verhalten zu simulieren
    # Da die Tests die Queue direkt mocken, lasse ich die Mock-Logik so, wie sie ist.
    
    async def mock_put(queued_command):
        # Simulate an immediate async response for commands that expect one.
        if queued_command.expect_response and queued_command.on_response:
            # For Set-Commands, the response is often an echo of the command itself or 'OK'.
            queued_command.on_response(queued_command.payload)

    # We mock the queue to directly call the response callback (now async)
    ctrl._write_queue = AsyncMock()
    ctrl._write_queue.put.side_effect = mock_put

    # Da der Controller ein async-Kontextmanager ist, müssen wir ihn im Test
    # als solchen verwenden, was nicht in der Fixture selbst geschehen kann.
    # Wir geben das Objekt zurück und erwarten, dass der Test await/async with verwendet.
    async with ctrl:
        yield ctrl