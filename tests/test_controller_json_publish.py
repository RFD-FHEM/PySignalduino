import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from dataclasses import asdict

from signalduino.controller import SignalduinoController
from signalduino.types import DecodedMessage

@pytest.fixture
def mock_transport():
    transport = AsyncMock()
    transport.readline = AsyncMock(return_value=None)
    transport.closed.return_value = False
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.__aenter__ = AsyncMock(return_value=transport)
    transport.__aexit__ = AsyncMock(return_value=None)
    return transport

@pytest.fixture
def mock_parser():
    parser = MagicMock()
    parser.parse_line.return_value = []
    return parser

@pytest.fixture
def mock_mqtt_publisher():
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher.publish_raw_line = AsyncMock()
    publisher.base_topic = "sduino"
    publisher.__aenter__ = AsyncMock(return_value=publisher)
    publisher.__aexit__ = AsyncMock(return_value=None)
    return publisher

@pytest.mark.asyncio
async def test_controller_publishes_object(mock_transport, mock_parser, mock_mqtt_publisher):
    """
    Test that the controller passes the DecodedMessage object directly
    to the MQTT publisher (which handles serialization).
    """
    # Create a dummy DecodedMessage
    decoded_msg = DecodedMessage(
        data="TestPayload", 
        raw="raw_data", 
        protocol={"id": "1", "name": "TestProtocol"},
        metadata={"rssi": -74.5}
    )
    
    # Configure parser to return this message
    mock_parser.parse_line.return_value = [decoded_msg]
    
    # Initialize controller with mocked components
    controller = SignalduinoController(
        transport=mock_transport, 
        parser=mock_parser, 
        mqtt_publisher=mock_mqtt_publisher
    )
    
    # Patch initialize to avoid full startup sequence, we just want to test _parser_task logic
    with patch.object(controller, 'initialize', new=AsyncMock()):
        # Manually put a line into the raw queue to trigger parsing
        await controller._raw_message_queue.put("TestLine")
        
        # Start the parser task
        parser_task = asyncio.create_task(controller._parser_task())
        
        # Allow some time for the task to process
        await asyncio.sleep(0.1)
        
        # Stop the task
        controller._stop_event.set()
        parser_task.cancel()
        try:
            await parser_task
        except asyncio.CancelledError:
            pass
            
        # Verify publish was called
        mock_mqtt_publisher.publish.assert_called_once()
        
        # Get the argument passed to publish
        args, _ = mock_mqtt_publisher.publish.call_args
        published_msg = args[0]
        
        # Assert it is the DecodedMessage object (Controller should pass it directly to Publisher)
        assert isinstance(published_msg, DecodedMessage), "Published message should be a DecodedMessage object"
        
        # Compare with expected object
        assert published_msg == decoded_msg
