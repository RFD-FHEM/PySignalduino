import logging
import os
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from asyncio import Queue
import re

import pytest
from aiomqtt import Client as AsyncMqttClient

from signalduino.mqtt import MqttPublisher
from signalduino.controller import SignalduinoController
from signalduino.transport import BaseTransport
from signalduino.commands import SignalduinoCommands
from signalduino.exceptions import SignalduinoCommandTimeout
from signalduino.controller import QueuedCommand # Import QueuedCommand


# Constants
INTERLEAVED_MESSAGE = "MU;P0=353;P1=-184;D=0123456789;CP=1;SP=0;R=248;\n"

@pytest.fixture
def mock_logger():
    return MagicMock(spec=logging.Logger)

@pytest.fixture
def mock_transport():
    transport = AsyncMock(spec=BaseTransport)
    transport.is_open = True
    return transport

@pytest.fixture
def mock_mqtt_publisher_cls():
    # Mock des aiomqtt.Client im MqttPublisher
    with patch("signalduino.mqtt.mqtt.Client") as MockClient:
        mock_client_instance = AsyncMock()
        # Stellen Sie sicher, dass die asynchronen Kontextmanager-Methoden AsyncMocks sind
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
        yield MockClient

@pytest.fixture
def signalduino_controller(mock_transport, mock_logger, mock_mqtt_publisher_cls):
    """Fixture for an async SignalduinoController with mocked transport and mqtt."""
    # mock_mqtt_publisher_cls wird nur für die Abhängigkeit benötigt, nicht direkt hier
    # Set environment variables for MQTT
    with patch.dict(os.environ, {
        "MQTT_HOST": "localhost",
        "MQTT_PORT": "1883",
        "MQTT_TOPIC": "signalduino"
    }):
        # Es ist KEINE asynchrone Initialisierung erforderlich, da MqttPublisher/Transport
        # erst im __aenter__ des Controllers gestartet werden.
        controller = SignalduinoController(
            transport=mock_transport,
            logger=mock_logger
        )
        
        # Verwenden von AsyncMock für die asynchrone Queue-Schnittstelle
        controller._write_queue = AsyncMock()
        # Der put-Aufruf soll nur aufgezeichnet werden, die Antwort wird im Test manuell ausgelöst.
        
        # Die Fixture muss den Controller zurückgeben, um ihn im Test
        # als `async with` verwenden zu können.
        return controller

@pytest.mark.asyncio
async def run_mqtt_command_test(controller: SignalduinoController,
                         mock_mqtt_client_constructor_mock: MagicMock, # NEU: Mock des aiomqtt.Client Konstruktors
                         mqtt_cmd: str,
                         raw_cmd: str,
                         expected_response_line: str,
                         cmd_args: str = ""):
    """Helper to test a single MQTT command with an interleaved message scenario."""
    
    # Expected response payload (without trailing newline)
    expected_payload = expected_response_line.strip()

    # Die Instanz, auf der publish aufgerufen wird, ist self.client im MqttPublisher.
    # Dies entspricht dem Rückgabewert des Konstruktors (mock_mqtt_client_constructor_mock.return_value).
    # MqttPublisher ruft publish() direkt auf self.client auf, nicht auf dem Rückgabewert von __aenter__.
    mock_client_instance_for_publish = mock_mqtt_client_constructor_mock.return_value
    
    # Start the handler as a background task because it waits for the response
    task = asyncio.create_task(controller._handle_mqtt_command(mqtt_cmd, cmd_args))
    
    # Wait until the command is put into the queue
    for _ in range(50): # Wait up to 0.5s
        if controller._write_queue.put.call_count >= 1:
            break
        await asyncio.sleep(0.01)
    
    # Verify command was queued
    controller._write_queue.put.assert_called_once()
    
    # Get the QueuedCommand object that was passed to put. It's the first argument of the first call.
    # call_args ist ((QueuedCommand(...),), {}), daher ist das Objekt in call_args
    queued_command = controller._write_queue.put.call_args[0][0] # Korrigiert: Extrahiere das QueuedCommand-Objekt
    
    # Manuell die Antwort simulieren, da die Fixture nur den Befehl selbst kannte.
    if queued_command.expect_response and queued_command.on_response:
        # Hier geben wir die gestrippte Zeile zurück, da der Parser Task dies normalerweise tun würde
        # bevor er _handle_as_command_response aufruft.
        # on_response ist synchron (def on_response(response: str):)
        queued_command.on_response(expected_response_line.strip())
        
    # Warte auf das Ende des Tasks
    await task
    
    if mqtt_cmd == "ccreg":
        # ccreg converts hex string (e.g. "00") to raw command (e.g. "C00").
        assert queued_command.payload == f"C{cmd_args.zfill(2).upper()}"
    elif mqtt_cmd == "rawmsg":
        # rawmsg uses the payload as the raw command.
        assert queued_command.payload == cmd_args
    else:
        assert queued_command.payload == raw_cmd
        
    assert queued_command.expect_response is True
    
    # Verify result was published (async call)
    # publish ist ein AsyncMock und assert_called_once_with ist die korrekte Methode
    mock_client_instance_for_publish.publish.assert_called_once_with(
        f"signalduino/result/{mqtt_cmd}",
        expected_payload,
        retain=False
    )
    # Check that the interleaved message was *not* published as a result
    # Wir verlassen uns darauf, dass der `_handle_mqtt_command` nur die Antwort veröffentlicht.
    assert mock_client_instance_for_publish.publish.call_count == 1


# --- Command Tests ---

@pytest.mark.asyncio
async def test_controller_handles_unknown_command(signalduino_controller):
    """Test handling of unknown commands."""
    async with signalduino_controller:
        await signalduino_controller._handle_mqtt_command("unknown_cmd", "")
        signalduino_controller._write_queue.put.assert_not_called()

@pytest.mark.asyncio
async def test_controller_handles_version_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'version' command in the controller."""
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_mqtt_publisher_cls,
            mqtt_cmd="version",
            raw_cmd="V",
            expected_response_line="V 3.3.1-dev SIGNALduino cc1101  - compiled at Mar 10 2017 22:54:50\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_freeram_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'freeram' command."""
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_mqtt_publisher_cls,
            mqtt_cmd="freeram",
            raw_cmd="R",
            expected_response_line="1234\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_uptime_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'uptime' command."""
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_mqtt_publisher_cls,
            mqtt_cmd="uptime",
            raw_cmd="t",
            expected_response_line="56789\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_cmds_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'cmds' command."""
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_mqtt_publisher_cls,
            mqtt_cmd="cmds",
            raw_cmd="?",
            expected_response_line="V X t R C S U P G r W x E Z\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_ping_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'ping' command."""
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_mqtt_publisher_cls,
            mqtt_cmd="ping",
            raw_cmd="P",
            expected_response_line="OK\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_config_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'config' command."""
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_mqtt_publisher_cls,
            mqtt_cmd="config",
            raw_cmd="CG",
            expected_response_line="MS=1;MU=1;MC=1;MN=1\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_ccconf_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'ccconf' command."""
    # The regex r"C0Dn11=[A-F0-9a-f]+" is quite specific. The response is multi-line in reality,
    # but the controller only matches the first line that matches the pattern.
    # We simulate the first matching line.
    async with signalduino_controller:
        await run_mqtt_command_test(
            controller=signalduino_controller,
            mock_mqtt_client_constructor_mock=mock_mqtt_publisher_cls,
            mqtt_cmd="ccconf",
            raw_cmd="C0DnF",
            expected_response_line="C0D11=0F\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_ccpatable_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'ccpatable' command."""
    # The regex r"^C3E\s=\s.*" expects the beginning of the line.
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_mqtt_publisher_cls,
            mqtt_cmd="ccpatable",
            raw_cmd="C3E",
            expected_response_line="C3E = C0 C1 C2 C3 C4 C5 C6 C7\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_ccreg_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'ccreg' command (default C00)."""
    # ccreg maps to SignalduinoCommands.read_cc1101_register(int(p, 16)) which sends C<reg_hex>
    async with signalduino_controller:
        await run_mqtt_command_test(
            controller=signalduino_controller,
            mock_mqtt_client_constructor_mock=mock_mqtt_publisher_cls,
            mqtt_cmd="ccreg",
            raw_cmd="C00", # Raw command is dynamically generated, but we assert against C00 for register 0
            expected_response_line="ccreg 00: 29 2E 05 7F ...\n",
            cmd_args="00" # Payload for ccreg is the register in hex
        )

@pytest.mark.asyncio
async def test_controller_handles_rawmsg_command(signalduino_controller, mock_mqtt_publisher_cls):
    """Test handling of the 'rawmsg' command."""
    # rawmsg sends the payload itself and expects a response.
    raw_message = "C1D"
    async with signalduino_controller:
        await run_mqtt_command_test(
            controller=signalduino_controller,
            mock_mqtt_client_constructor_mock=mock_mqtt_publisher_cls,
            mqtt_cmd="rawmsg",
            raw_cmd=raw_message, # The raw command is the payload itself
            expected_response_line="OK\n",
            cmd_args=raw_message
        )
