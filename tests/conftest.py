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
    transport.closed = Mock(return_value=False)
    transport.write_line = AsyncMock()
    
    async def aopen_mock():
        transport.is_open = True
    
    async def aclose_mock():
        transport.is_open = False

    transport.aopen.side_effect = aopen_mock
    transport.aclose.side_effect = aclose_mock
    transport.__aenter__.return_value = transport
    transport.__aexit__.return_value = None
    
    async def mock_readline_blocking():
        """A readline mock that blocks indefinitely, but is cancellable by the event loop."""
        try:
            # Blockiert auf ein Event, das niemals gesetzt wird, bis es abgebrochen wird
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # Wenn abgebrochen, verhält es sich wie ein geschlossener Transport (keine Zeile)
            return None
    
    transport.readline.side_effect = mock_readline_blocking
    
    return transport


@pytest_asyncio.fixture
async def controller(mock_transport, mocker):
    """Fixture for a SignalduinoController with a mocked transport and MQTT."""

    # Patche MqttPublisher, da die Initialisierung eines echten Publishers
    # ohne Broker zu einem Timeout führt.
    mock_mqtt_publisher_cls = mocker.patch("signalduino.controller.MqttPublisher", autospec=True)
    # Stelle sicher, dass der asynchrone Kontextmanager des MqttPublishers nicht blockiert.
    mock_mqtt_publisher_cls.return_value.__aenter__ = AsyncMock(return_value=mock_mqtt_publisher_cls.return_value)
    mock_mqtt_publisher_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_mqtt_publisher_cls.return_value.base_topic = "py-signalduino"

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

    # Workaround: AsyncMock.get() blocks indefinitely when empty and is not reliably cancelled.
    # We replace it with a mock that raises CancelledError immediately to prevent hanging.
    async def mock_get():
        raise asyncio.CancelledError
    
    ctrl._write_queue.get.side_effect = mock_get

    # Ensure background tasks are cancelled on fixture teardown
    async def cancel_background_tasks():
        if hasattr(ctrl, '_writer_task') and isinstance(ctrl._writer_task, asyncio.Task) and not ctrl._writer_task.done():
            ctrl._writer_task.cancel()
            try:
                await ctrl._writer_task
            except asyncio.CancelledError:
                pass

    # Da der Controller ein async-Kontextmanager ist, müssen wir ihn im Test
    # als solchen verwenden, was nicht in der Fixture selbst geschehen kann.
    # Wir geben das Objekt zurück und erwarten, dass der Test await/async with verwendet.
    async with ctrl:
        # Lösche die History der Mock-Aufrufe, die während der Initialisierung aufgetreten sind ('V', 'XQ')
        ctrl._write_queue.put.reset_mock()
        try:
            yield ctrl
        finally:
            await cancel_background_tasks()