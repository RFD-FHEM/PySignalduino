import asyncio
from asyncio import Queue
import re
from unittest.mock import MagicMock, Mock, AsyncMock

import pytest

from signalduino.controller import SignalduinoController, CommandError, InitError
from signalduino.commands import Command, CommandType, SDUINO_CMD_TIMEOUT
from signalduino.exceptions import SerialConnectionClosedError, SignalduinoCommandTimeout
from signalduino.types import SerialInterface
from signalduino.parser import SignalParser


@pytest.fixture
def mock_serial_interface():
    """Fixture for a mocked async serial interface layer."""
    serial_interface = AsyncMock(spec=SerialInterface)
    # Controller erwartet connect/close/read_line/write_line
    serial_interface.is_connected = False
    
    async def connect_mock():
        serial_interface.is_connected = True

    async def close_mock():
        serial_interface.is_connected = False

    serial_interface.connect.side_effect = connect_mock
    serial_interface.close.side_effect = close_mock

    async def read_line_mock():
        await asyncio.sleep(0.01)
        return None
    serial_interface.read_line.side_effect = read_line_mock
    serial_interface.write_line.return_value = None # Add this for completeness
    
    return serial_interface


@pytest.fixture
def mock_parser():
    """Fixture for a mocked parser."""
    parser = MagicMock(spec=SignalParser)
    parser.parse_line.return_value = []
    return parser


@pytest.mark.asyncio
async def test_version_command_success(mock_serial_interface, mock_parser):
    """Test that the version command works with the Command object."""
    
    controller = SignalduinoController(serial_interface=mock_serial_interface, parser=mock_parser)
    
    # Prime controller's response queue for initialization
    await controller._command_response_queue.put("V 1.0.0") 
    await controller._command_response_queue.put("b433.92")

    expected_response_line = "V 3.5.0-dev SIGNALduino cc1101 (optiboot) - compiled at 20250219"

    async with controller:
        
        # Sende den Befehl im Hintergrund, der auf eine Antwort in der Queue wartet
        response_task = asyncio.create_task(
            controller.send_command(Command.VERSION())
        )
        
        # Warte, bis der Controller den Befehl über die serielle Schnittstelle gesendet hat.
        while mock_serial_interface.write_line.call_count == 0:
            await asyncio.sleep(0.001)

        # Simuliere die Antwort in die interne Queue des Controllers.
        await controller._command_response_queue.put(expected_response_line)
        
        # Warte auf das Ergebnis von send_command
        response = await response_task
        
        # Verifizierungen
        assert mock_serial_interface.write_line.call_args_list[-1][0][0] == "V"
        assert mock_serial_interface.write_line.call_count == 3
        assert response == expected_response_line
        assert "SIGNALduino" in response
        assert "V 3.5.0-dev" in response

@pytest.mark.asyncio
async def test_set_frequency_success(mock_serial_interface, mock_parser):
    """Test that a SET command works and verifies the expected echo response."""
    
    controller = SignalduinoController(serial_interface=mock_serial_interface, parser=mock_parser)
    
    # Prime controller's response queue for initialization
    await controller._command_response_queue.put("V 1.0.0") 
    await controller._command_response_queue.put("b433.92")

    frequency = 433.92
    expected_raw_command = f"b{frequency}"
    expected_response_line = expected_raw_command

    async with controller:
        
        # Der Test setzt voraus, dass Command.SET_FREQUENCY existiert
        response_task = asyncio.create_task(
            controller.send_command(Command.SET_FREQUENCY(frequency))
        )
        
        # Warte, bis der Befehl gesendet wurde
        while mock_serial_interface.write_line.call_count == 0:
            await asyncio.sleep(0.001)

        # Simuliere die erwartete Echo-Antwort
        await controller._command_response_queue.put(expected_response_line)
        
        # Warte auf das Ergebnis von send_command
        response = await response_task
        
        # Verifizierungen
        assert mock_serial_interface.write_line.call_args_list[-1][0][0] == expected_raw_command
        assert mock_serial_interface.write_line.call_count == 3
        assert response == expected_response_line


@pytest.mark.asyncio
async def test_command_timeout(mock_serial_interface, mock_parser):
    """Test that a command times out correctly."""
    
    # Verwenden Sie ein Command-Objekt mit einem sehr kurzen Timeout
    test_command = Command(
        name="TEST_TIMEOUT",
        raw_command="T",
        command_type=CommandType.GET, # Verwenden Sie einen beliebigen Typ
        timeout=0.1
    )
    
    controller = SignalduinoController(serial_interface=mock_serial_interface, parser=mock_parser)
    
    # Prime controller's response queue for initialization
    await controller._command_response_queue.put("V 1.0.0") 
    await controller._command_response_queue.put("b433.92")

    async with controller:
        # Der Controller löst bei einem Timeout `TimeoutError` aus.
        with pytest.raises(SignalduinoCommandTimeout, match="Command 'TEST_TIMEOUT' timed out"):
            await controller.send_command(test_command)
            
        # Überprüfen, ob der Befehl gesendet wurde
        assert mock_serial_interface.write_line.call_args_list[-1][0][0] == "T"
        assert mock_serial_interface.write_line.call_count == 3
        

@pytest.mark.asyncio
async def test_command_failure_response(mock_serial_interface, mock_parser):
    """Test that a command fails if the response does not match the expected_response."""
    
    # Verwenden Sie ein Command-Objekt, das eine spezifische Antwort erwartet
    test_command = Command(
        name="TEST_FAILURE",
        raw_command="F",
        command_type=CommandType.SET,
        expected_response="F OK",
        timeout=1.0
    )
    
    controller = SignalduinoController(serial_interface=mock_serial_interface, parser=mock_parser)
    
    # Prime controller's response queue for initialization
    await controller._command_response_queue.put("V 1.0.0") 
    await controller._command_response_queue.put("b433.92")

    async with controller:
        
        response_task = asyncio.create_task(
            controller.send_command(test_command)
        )
        
        # Warte, bis der Befehl gesendet wurde
        while mock_serial_interface.write_line.call_count == 0:
            await asyncio.sleep(0.001)

        # Simuliere eine falsche Antwort
        failure_response = "F ERROR"
        await controller._command_response_queue.put(failure_response)
        
        # Es sollte ein CommandError geworfen werden
        with pytest.raises(CommandError, match=f"Command 'TEST_FAILURE' failed. Response: {failure_response}"):
            await response_task
        
        # Überprüfen, ob der Befehl gesendet wurde
        assert mock_serial_interface.write_line.call_args_list[-1][0][0] == "F"
        assert mock_serial_interface.write_line.call_count == 3
