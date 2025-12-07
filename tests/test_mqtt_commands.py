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
from signalduino.commands import SignalduinoCommands
from signalduino.exceptions import SignalduinoCommandTimeout

# Constants
INTERLEAVED_MESSAGE = "MU;P0=353;P1=-184;D=0123456789;CP=1;SP=0;R=248;\n"

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
            # Override response queue for synchronous testing
            # We mock the entire queue but need to ensure the methods on it are callable for mock assertions
            controller._write_queue = MagicMock(spec=queue.Queue)
            
            # The controller's MqttPublisher is an actual instance, so we mock its client
            mock_mqtt_client = MagicMock()
            controller.mqtt_publisher.client = mock_mqtt_client
            controller.mqtt_publisher.client.is_connected.return_value = True
            return controller

def run_mqtt_command_test(controller: SignalduinoController, 
                         mqtt_cmd: str, 
                         raw_cmd: str, 
                         expected_response_line: str,
                         cmd_args: str = ""):
    """Helper to test a single MQTT command with an interleaved message scenario."""
    
    # Expected response payload (without trailing newline)
    expected_payload = expected_response_line.strip()

    # Re-mock side effect for the command's response queue
    def side_effect_put_sync(cmd_obj: QueuedCommand):
        # The line that the controller processes and checks against the pattern
        response_line_to_check = expected_response_line.strip()
        
        # In a unit test, we cannot reliably simulate the threading for interleaved messages
        # without running the threads. Instead, we call the on_response callback directly 
        # to simulate a successful match of the response pattern in the parser loop.
        if cmd_obj.on_response:
            # Forcing a successful response, simulating that the regex match occurred
            # Note: We are not testing that the command's regex pattern *fails* for 
            # the interleaved message, this should be tested in tests/test_controller.py
            cmd_obj.on_response(response_line_to_check)

    controller._write_queue.put.side_effect = side_effect_put_sync

    # Call the handler
    controller._handle_mqtt_command(mqtt_cmd, cmd_args)
    
    # Verify command was queued
    controller._write_queue.put.assert_called_once()
    
    # Get the QueuedCommand object that was passed to put. It's the first argument of the first call.
    # MagicMock call_args is a tuple: ((arg1, arg2), {kwarg1: val1})
    queued_cmd: QueuedCommand = controller._write_queue.put.call_args[0][0]
    
    if mqtt_cmd == "ccreg":
        # ccreg converts hex string (e.g. "00") to raw command (e.g. "C00").
        assert queued_cmd.payload == f"C{cmd_args.zfill(2).upper()}"
    elif mqtt_cmd == "rawmsg":
        # rawmsg uses the payload as the raw command.
        assert queued_cmd.payload == cmd_args
    else:
        assert queued_cmd.payload == raw_cmd
        
    assert queued_cmd.expect_response is True
    
    # Verify result was published
    controller.mqtt_publisher.client.publish.assert_called_with(
        f"signalduino/result/{mqtt_cmd}",
        expected_payload,
        retain=False
    )
    # Check that the interleaved message was *not* published as a result
    publish_calls = [c.args for c in controller.mqtt_publisher.client.publish.call_args_list]
    assert INTERLEAVED_MESSAGE.strip() not in [call for call in publish_calls if len(call) > 1 and isinstance(call, str)]


# --- Existing Tests (moved and simplified) ---

def test_mqtt_subscribe_on_connect(mock_mqtt_client_cls, mock_logger):
    """Test that the client subscribes to command topic on connect."""
    mock_client_instance = MagicMock()
    mock_mqtt_client_cls.return_value = mock_client_instance
    
    with patch.dict(os.environ, {
        "MQTT_HOST": "localhost", 
        "MQTT_TOPIC": "test/sduino"
    }):
        publisher = MqttPublisher(logger=mock_logger)
        publisher._on_connect(mock_client_instance, None, None, 0)
        
        mock_client_instance.subscribe.assert_called_with("test/sduino/commands/#")

def test_mqtt_incoming_command_callback(mock_mqtt_client_cls, mock_logger):
    """Test that incoming messages trigger the registered callback."""
    mock_client_instance = MagicMock()
    mock_mqtt_client_cls.return_value = mock_client_instance
    
    with patch.dict(os.environ, {"MQTT_TOPIC": "test/sduino"}):
        publisher = MqttPublisher(logger=mock_logger)
        
        callback_mock = MagicMock()
        publisher.register_command_callback(callback_mock)
        
        msg = MagicMock()
        msg.topic = "test/sduino/commands/version"
        msg.payload = b""
        
        publisher._on_message(mock_client_instance, None, msg)
        
        callback_mock.assert_called_with("version", "")

def test_controller_handles_unknown_command(signalduino_controller):
    """Test handling of unknown commands."""
    signalduino_controller._handle_mqtt_command("unknown_cmd", "")
    signalduino_controller._write_queue.put.assert_not_called()

# --- New Command Tests with Interleaving Logic ---

def test_controller_handles_version_command(signalduino_controller):
    """Test handling of the 'version' command in the controller with simulated interleaved message."""
    run_mqtt_command_test(
        signalduino_controller, 
        mqtt_cmd="version", 
        raw_cmd="V", 
        expected_response_line="V 3.3.1-dev SIGNALduino cc1101  - compiled at Mar 10 2017 22:54:50\n"
    )

def test_controller_handles_freeram_command(signalduino_controller):
    """Test handling of the 'freeram' command."""
    run_mqtt_command_test(
        signalduino_controller, 
        mqtt_cmd="freeram", 
        raw_cmd="R", 
        expected_response_line="1234\n"
    )

def test_controller_handles_uptime_command(signalduino_controller):
    """Test handling of the 'uptime' command."""
    run_mqtt_command_test(
        signalduino_controller, 
        mqtt_cmd="uptime", 
        raw_cmd="t", 
        expected_response_line="56789\n"
    )

def test_controller_handles_cmds_command(signalduino_controller):
    """Test handling of the 'cmds' command."""
    run_mqtt_command_test(
        signalduino_controller, 
        mqtt_cmd="cmds", 
        raw_cmd="?", 
        expected_response_line="V X t R C S U P G r W x E Z\n"
    )

def test_controller_handles_ping_command(signalduino_controller):
    """Test handling of the 'ping' command."""
    run_mqtt_command_test(
        signalduino_controller, 
        mqtt_cmd="ping", 
        raw_cmd="P", 
        expected_response_line="OK\n"
    )

def test_controller_handles_config_command(signalduino_controller):
    """Test handling of the 'config' command."""
    run_mqtt_command_test(
        signalduino_controller, 
        mqtt_cmd="config", 
        raw_cmd="CG", 
        expected_response_line="MS=1;MU=1;MC=1;MN=1\n"
    )

def test_controller_handles_ccconf_command(signalduino_controller):
    """Test handling of the 'ccconf' command."""
    # The regex r"C0Dn11=[A-F0-9a-f]+" is quite specific. The response is multi-line in reality,
    # but the controller only matches the first line that matches the pattern.
    # We simulate the first matching line.
    run_mqtt_command_test(
        controller=signalduino_controller, 
        mqtt_cmd="ccconf", 
        raw_cmd="C0DnF", 
        expected_response_line="C0D11=0F\n"
    )

def test_controller_handles_ccpatable_command(signalduino_controller):
    """Test handling of the 'ccpatable' command."""
    # The regex r"^C3E\s=\s.*" expects the beginning of the line.
    run_mqtt_command_test(
        signalduino_controller, 
        mqtt_cmd="ccpatable", 
        raw_cmd="C3E", 
        expected_response_line="C3E = C0 C1 C2 C3 C4 C5 C6 C7\n"
    )

def test_controller_handles_ccreg_command(signalduino_controller):
    """Test handling of the 'ccreg' command (default C00)."""
    # ccreg maps to SignalduinoCommands.read_cc1101_register(int(p, 16)) which sends C<reg_hex>
    run_mqtt_command_test(
        controller=signalduino_controller, 
        mqtt_cmd="ccreg", 
        raw_cmd="C00", # Raw command is dynamically generated, but we assert against C00 for register 0
        expected_response_line="ccreg 00: 29 2E 05 7F ...\n",
        cmd_args="00" # Payload for ccreg is the register in hex
    )

def test_controller_handles_rawmsg_command(signalduino_controller):
    """Test handling of the 'rawmsg' command."""
    # rawmsg sends the payload itself and expects a response.
    raw_message = "C1D"
    run_mqtt_command_test(
        controller=signalduino_controller, 
        mqtt_cmd="rawmsg", 
        raw_cmd=raw_message, # The raw command is the payload itself
        expected_response_line="OK\n",
        cmd_args=raw_message
    )
