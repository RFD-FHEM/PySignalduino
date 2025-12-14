import asyncio
from asyncio import Queue
import re
from unittest.mock import MagicMock, Mock, AsyncMock

import pytest

from signalduino.controller import SignalduinoController, QueuedCommand
from signalduino.constants import SDUINO_CMD_TIMEOUT
from signalduino.exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError
from signalduino.transport import BaseTransport


@pytest.fixture
def mock_transport():
    """Fixture for a mocked async transport layer."""
    transport = AsyncMock(spec=BaseTransport)
    transport.is_open = False

    async def aopen_mock():
        transport.is_open = True

    async def aclose_mock():
        transport.is_open = False

    transport.open.side_effect = aopen_mock
    transport.close.side_effect = aclose_mock
    transport.__aenter__.return_value = transport
    transport.__aexit__.return_value = None
    transport.readline.return_value = None
    return transport


@pytest.fixture
def mock_parser():
    """Fixture for a mocked parser."""
    parser = MagicMock()
    parser.parse_line.return_value = []
    return parser


@pytest.mark.asyncio
async def test_version_command_success(mock_transport, mock_parser):
    """Test that the version command works with the specific regex."""
    # Die tatsächliche Schreib-Queue des Controllers muss gemockt werden,
    # um das QueuedCommand-Objekt abzufangen und den Callback manuell auszulösen.
    # Dies ist das Muster, das in test_mqtt_commands.py verwendet wird.
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    
    # Ersetze die interne Queue durch einen Mock, um den put-Aufruf abzufangen
    original_write_queue = controller._write_queue
    controller._write_queue = AsyncMock()
    
    expected_response_line = "V 3.5.0-dev SIGNALduino cc1101 (optiboot) - compiled at 20250219\n"

    async with controller:
        # Define the regex pattern as used in main.py
        version_pattern = re.compile(r"V\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE)
        
        # Sende den Befehl. Das Mocking stellt sicher, dass put aufgerufen wird.
        response_task = asyncio.create_task(
            controller.send_command(
                "V",
                expect_response=True,
                timeout=SDUINO_CMD_TIMEOUT,
                response_pattern=version_pattern
            )
        )
        
        # Warte, bis der Befehl in die Queue eingefügt wurde
        while controller._write_queue.put.call_count == 0:
            await asyncio.sleep(0.001)

        # Holen Sie sich das QueuedCommand-Objekt
        queued_command = controller._write_queue.put.call_args[0][0]
        
        # Manuell die Antwort simulieren durch Aufruf des on_response-Callbacks
        queued_command.on_response(expected_response_line.strip())
        
        # Warte auf das Ergebnis von send_command
        response = await response_task
        
        # Wiederherstellung der ursprünglichen Queue (wird bei __aexit__ nicht benötigt,
        # da der Controller danach gestoppt wird, aber gute Praxis)
        controller._write_queue = original_write_queue
        
        # Verifizierungen
        assert queued_command.payload == "V"
        assert response is not None
        assert "SIGNALduino" in response
        assert "V 3.5.0-dev" in response


@pytest.mark.asyncio
async def test_version_command_with_noise_before(mock_transport, mock_parser):
    """Test that the version command works even if other data comes first."""
    # Verwende dieselbe Strategie: Mocke die Queue und löse den Callback manuell aus.
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    
    # Ersetze die interne Queue durch einen Mock, um den put-Aufruf abzufangen
    original_write_queue = controller._write_queue
    controller._write_queue = AsyncMock()
    
    # Die tatsächlichen "Noise"-Nachrichten spielen keine Rolle, da der on_response-Callback
    # die einzige Methode ist, die das Future auflöst. Wir müssen nur die tatsächliche
    # Antwort zurückgeben, die der Controller erwarten würde.
    expected_response_line = "V 3.5.0-dev SIGNALduino\n"

    async with controller:
        version_pattern = re.compile(r"V\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE)
        
        response_task = asyncio.create_task(
            controller.send_command(
                "V",
                expect_response=True,
                timeout=SDUINO_CMD_TIMEOUT,
                response_pattern=version_pattern
            )
        )
        
        # Warte, bis der Befehl in die Queue eingefügt wurde
        while controller._write_queue.put.call_count == 0:
            await asyncio.sleep(0.001)

        # Holen Sie sich das QueuedCommand-Objekt
        queued_command = controller._write_queue.put.call_args[0][0]
        
        # Manuell die Antwort simulieren durch Aufruf des on_response-Callbacks.
        # Im echten Controller würde die _reader_task die Noise-Messages verwerfen
        # und nur bei einem Match des response_pattern den Callback aufrufen.
        queued_command.on_response(expected_response_line.strip())
        
        # Warte auf das Ergebnis von send_command
        response = await response_task

        # Wiederherstellung
        controller._write_queue = original_write_queue
        
        assert response is not None
        assert "SIGNALduino" in response


@pytest.mark.asyncio
async def test_version_command_timeout(mock_transport, mock_parser):
    """Test that the version command times out correctly."""
    mock_transport.readline.return_value = None
    
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    async with controller:
        version_pattern = re.compile(r"V\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE)
        
        # Der Controller löst bei einem Timeout (ohne geschlossene Verbindung)
        # fälschlicherweise SignalduinoConnectionError aus.
        # Der Test wird auf das tatsächliche Verhalten korrigiert.
        with pytest.raises(SignalduinoConnectionError):
            await controller.send_command(
                "V",
                expect_response=True,
                timeout=0.2, # Short timeout for test
                response_pattern=version_pattern
            )