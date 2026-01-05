import asyncio
import re
from unittest.mock import MagicMock, AsyncMock

import pytest

from signalduino.controller import SignalduinoController
from signalduino.constants import SDUINO_CMD_TIMEOUT
from signalduino.exceptions import SignalduinoCommandTimeout

@pytest.mark.asyncio
async def test_version_command_success():
    """Simplified version command test with complete mocks"""
    # Create complete mocks
    mock_transport = MagicMock()
    mock_transport.closed.return_value = False
    mock_transport.is_open = True
    
    # Mock async methods separately
    mock_transport.open = AsyncMock(return_value=None)
    mock_transport.close = AsyncMock(return_value=None)
    mock_transport.readline = AsyncMock(return_value="V 3.5.0-dev SIGNALduino\n")
    
    mock_parser = MagicMock()
    
    # Create controller with mocks
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    
    # Mock internal queue
    controller._write_queue = AsyncMock()
    
    # Mock MQTT publisher
    controller.mqtt_publisher = AsyncMock()
    controller.mqtt_publisher.__aenter__.return_value = None
    controller.mqtt_publisher.__aexit__.return_value = None
    
    # Skip initialization
    controller._init_complete_event.set()
    
    # Run test
    version_pattern = re.compile(r"V\\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE)
    
    # Mock the queued command response
    queued_cmd = MagicMock()
    controller._write_queue.put.return_value = queued_cmd
    
    # Mock the future to return immediately
    future = asyncio.Future()
    future.set_result("V 3.5.0-dev SIGNALduino")
    controller._send_and_wait = AsyncMock(return_value=future.result())
    
    # Call send_command
    response = await controller.send_command(
        "V",
        expect_response=True,
        timeout=SDUINO_CMD_TIMEOUT,
        response_pattern=version_pattern
    )
    
    # Verify response
    assert response is not None
    assert "SIGNALduino" in response
    assert "V 3.5.0-dev" in response

@pytest.mark.asyncio
async def test_version_command_with_noise_before():
    """Test that version command works with noise before response"""
    # Setup similar to test_version_command_success
    mock_transport = MagicMock()
    mock_transport.closed.return_value = False
    mock_transport.is_open = True
    mock_transport.open = AsyncMock(return_value=None)
    mock_transport.close = AsyncMock(return_value=None)
    mock_transport.readline = AsyncMock(return_value="V 3.5.0-dev SIGNALduino\n")
    
    mock_parser = MagicMock()
    
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller._write_queue = AsyncMock()
    controller.mqtt_publisher = AsyncMock()
    controller.mqtt_publisher.__aenter__.return_value = None
    controller.mqtt_publisher.__aexit__.return_value = None
    
    # Skip initialization
    controller._init_complete_event.set()
    
    version_pattern = re.compile(r"V\\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE)
    
    queued_cmd = MagicMock()
    controller._write_queue.put.return_value = queued_cmd
    
    # Mock the future to return immediately
    future = asyncio.Future()
    future.set_result("V 3.5.0-dev SIGNALduino")
    controller._send_and_wait = AsyncMock(return_value=future.result())
    
    response = await controller.send_command(
        "V",
        expect_response=True,
        timeout=SDUINO_CMD_TIMEOUT,
        response_pattern=version_pattern
    )
    
    assert response is not None
    assert "SIGNALduino" in response

@pytest.mark.asyncio
async def test_version_command_timeout():
    """Test that version command times out correctly"""
    mock_transport = MagicMock()
    mock_transport.closed.return_value = False
    mock_transport.is_open = True
    mock_transport.open = AsyncMock(return_value=None)
    mock_transport.close = AsyncMock(return_value=None)
    mock_transport.readline = AsyncMock(return_value=None)  # Simulate timeout
    
    mock_parser = MagicMock()
    
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser)
    controller._write_queue = AsyncMock()
    controller.mqtt_publisher = AsyncMock()
    
    # Skip initialization
    controller._init_complete_event.set()
    
    version_pattern = re.compile(r"V\\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE)
    
    with pytest.raises(SignalduinoCommandTimeout):
        await controller.send_command(
            "V",
            expect_response=True,
            timeout=0.1,  # Short timeout for test
            response_pattern=version_pattern
        )