import logging
import os
from unittest.mock import MagicMock, patch
import threading
import queue
import re

import pytest
import paho.mqtt.client as mqtt

from signalduino.mqtt import MqttPublisher
from signalduino.controller import SignalduinoController, QueuedCommand
from signalduino.transport import BaseTransport

@pytest.fixture
def mock_logger():
    return MagicMock(spec=logging.Logger)

@pytest.fixture
def mock_mqtt_client_cls():
    with patch("signalduino.mqtt.mqtt.Client") as MockClient:
        yield MockClient

@pytest.fixture
def mock_transport():
    transport = MagicMock(spec=BaseTransport)
    transport.is_open = True
    return transport

@pytest.fixture
def signalduino_controller(mock_transport, mock_logger):
    # Set environment variables for MQTT
    with patch.dict(os.environ, {
        "MQTT_HOST": "localhost",
        "MQTT_PORT": "1883",
        "MQTT_TOPIC": "signalduino"
    }):
        # Mock Client within controller init
        with patch("signalduino.mqtt.mqtt.Client") as MockClient:
            controller = SignalduinoController(
                transport=mock_transport,
                logger=mock_logger
            )
            return controller

def test_mqtt_subscribe_on_connect(mock_mqtt_client_cls, mock_logger):
    """Test that the client subscribes to command topic on connect."""
    # Setup
    mock_client_instance = MagicMock()
    mock_mqtt_client_cls.return_value = mock_client_instance
    
    with patch.dict(os.environ, {
        "MQTT_HOST": "localhost", 
        "MQTT_TOPIC": "test/sduino"
    }):
        publisher = MqttPublisher(logger=mock_logger)
        
        # Simulate on_connect
        publisher._on_connect(mock_client_instance, None, None, 0)
        
        # Verify subscription
        mock_client_instance.subscribe.assert_called_with("test/sduino/commands/#")

def test_mqtt_incoming_command_callback(mock_mqtt_client_cls, mock_logger):
    """Test that incoming messages trigger the registered callback."""
    mock_client_instance = MagicMock()
    mock_mqtt_client_cls.return_value = mock_client_instance
    
    with patch.dict(os.environ, {"MQTT_TOPIC": "test/sduino"}):
        publisher = MqttPublisher(logger=mock_logger)
        
        # Register callback
        callback_mock = MagicMock()
        publisher.register_command_callback(callback_mock)
        
        # Simulate incoming message
        msg = MagicMock()
        msg.topic = "test/sduino/commands/version"
        msg.payload = b""
        
        publisher._on_message(mock_client_instance, None, msg)
        
        callback_mock.assert_called_with("version", "")

def test_controller_handles_version_command(signalduino_controller):
    """Test handling of the 'version' command in the controller."""
    # Setup mock for _write_queue
    signalduino_controller._write_queue = MagicMock()
    
    # Mock MQTT publisher client to check publish calls
    signalduino_controller.mqtt_publisher.client = MagicMock()
    signalduino_controller.mqtt_publisher.client.is_connected.return_value = True
    
    # We need to mock queue behavior for the internal response queue within _handle_mqtt_command
    # Since _handle_mqtt_command creates a local Queue, we can't easily mock it directly.
    # However, we can patch Queue inside the method or rely on the _write_queue.put side effect
    # to feed the response if we were running threads. 
    # But here we are unit testing _handle_mqtt_command in isolation.
    
    # The current implementation of _handle_mqtt_command creates a local queue and waits on it.
    # To test this without blocking forever, we need to inject the response into that queue
    # when _write_queue.put is called.
    
    def side_effect_put(cmd_obj):
        # Provide response immediately via the callback in cmd_obj
        if cmd_obj.on_response:
            cmd_obj.on_response("V 3.3.1-dev SIGNALduino cc1101  - compiled at Mar 10 2017 22:54:50")
            
    signalduino_controller._write_queue.put.side_effect = side_effect_put
    
    # Call the handler
    signalduino_controller._handle_mqtt_command("version", "")
    
    # Verify command was queued
    signalduino_controller._write_queue.put.assert_called_once()
    args, _ = signalduino_controller._write_queue.put.call_args
    queued_cmd = args[0]
    assert queued_cmd.payload == "V"
    assert queued_cmd.expect_response is True
    
    # Verify result was published
    signalduino_controller.mqtt_publisher.client.publish.assert_called_with(
        "signalduino/result/version",
        "V 3.3.1-dev SIGNALduino cc1101  - compiled at Mar 10 2017 22:54:50",
        retain=False
    )

def test_controller_handles_unknown_command(signalduino_controller):
    """Test handling of unknown commands."""
    signalduino_controller._write_queue = MagicMock()
    
    signalduino_controller._handle_mqtt_command("unknown_cmd", "")
    
    signalduino_controller._write_queue.put.assert_not_called()

def test_mqtt_integration_full_flow(mock_mqtt_client_cls, mock_transport, mock_logger):
    """Test the full flow from MQTT message to Controller action."""
    mock_client_instance = MagicMock()
    mock_mqtt_client_cls.return_value = mock_client_instance
    
    with patch.dict(os.environ, {
        "MQTT_HOST": "localhost",
        "MQTT_TOPIC": "signalduino"
    }):
        controller = SignalduinoController(transport=mock_transport, logger=mock_logger)
        
        # Setup write queue mock to auto-respond
        controller._write_queue = MagicMock()
        def side_effect_put(cmd_obj):
            if cmd_obj.payload == "V" and cmd_obj.on_response:
                cmd_obj.on_response("V 3.3.1-dev SIGNALduino")
        controller._write_queue.put.side_effect = side_effect_put
        
        # Ensure publisher is connected for response publishing
        controller.mqtt_publisher.client.is_connected.return_value = True
        
        # Simulate incoming MQTT message
        msg = MagicMock()
        msg.topic = "signalduino/commands/version"
        msg.payload = b""
        
        # Trigger message handler on publisher
        # This calls controller._handle_mqtt_command via callback
        controller.mqtt_publisher._on_message(mock_client_instance, None, msg)
        
        # Verify controller action
        controller._write_queue.put.assert_called_once()
        
        # Verify response published
        mock_client_instance.publish.assert_called_with(
            "signalduino/result/version",
            "V 3.3.1-dev SIGNALduino",
            retain=False
        )
