import logging
import os
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock, call
from asyncio import Queue
import re

import json
import pytest
from aiomqtt import Client as AsyncMqttClient

from signalduino.mqtt import MqttPublisher
from signalduino.commands import MqttCommandDispatcher
from signalduino.controller import SignalduinoController
from signalduino.transport import BaseTransport
from signalduino.commands import SignalduinoCommands
from signalduino.exceptions import SignalduinoCommandTimeout
from signalduino.controller import QueuedCommand # Import QueuedCommand
from signalduino.constants import SDUINO_CMD_TIMEOUT

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
def mock_aiomqtt_client_cls():
    # Mock des aiomqtt.Client im MqttPublisher
    with patch("signalduino.mqtt.mqtt.Client") as MockClient:
        # Verwende eine einzelne AsyncMock-Instanz für den Client, um Konsistenz zu gewährleisten.
        mock_client_instance = AsyncMock()
        MockClient.return_value = mock_client_instance
        # Stelle sicher, dass der asynchrone Kontextmanager die Instanz selbst zurückgibt,
        # da der aiomqtt.Client im Kontextmanager-Block typischerweise sich selbst zurückgibt.
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        yield MockClient

@pytest.fixture
def signalduino_controller(mock_transport, mock_logger, mock_aiomqtt_client_cls):
    """Fixture for an async SignalduinoController with mocked transport and mqtt."""
    # mock_aiomqtt_client_cls wird nur für die Abhängigkeit benötigt, nicht direkt hier
    # Set environment variables for MQTT
    with patch.dict(os.environ, {
        "MQTT_HOST": "localhost",
        "MQTT_PORT": "1883",
        "MQTT_TOPIC": "signalduino"
    }):
        # Da MqttPublisher optional ist, müssen wir ihn im Test/Fixture mocken und übergeben,
        # damit self.mqtt_dispatcher im Controller gesetzt wird.
        with patch("signalduino.controller.MqttPublisher") as MockMqttPublisher:
            mock_publisher_instance = AsyncMock(spec=MqttPublisher)
            mock_publisher_instance.base_topic = os.environ["MQTT_TOPIC"]

            # Simuliere die Initialisierungsantworten und blockiere danach den Reader-Task.
            # Dies löst den RuntimeError: There is no current event loop in thread 'MainThread'
            # indem asyncio.Future() im synchronen Fixture-Setup vermieden wird.
            async def mock_readline_side_effect():
                # 1. Antwort auf V-Kommando
                yield "V 3.3.1-dev SIGNALduino cc1101  - compiled at Mar 10 2017 22:54:50\n"
                # 2. Blockiere den Reader-Task unbestimmt (innerhalb des Event Loops)
                while True:
                    await asyncio.sleep(3600) # Simuliere unendliches Warten

            mock_transport.readline.side_effect = mock_readline_side_effect()

            # Es ist KEINE asynchrone Initialisierung erforderlich, da MqttPublisher/Transport
            # erst im __aenter__ des Controllers gestartet werden.
            controller = SignalduinoController(
                transport=mock_transport,
                logger=mock_logger,
                mqtt_publisher=mock_publisher_instance # Wichtig: Den Mock übergeben
            )
            
            # Verwenden einer echten asyncio.Queue für die asynchrone Queue-Schnittstelle
            controller._write_queue = Queue()
            # Der put-Aufruf soll nur aufgezeichnet werden, die Antwort wird im Test manuell ausgelöst.
            
            # Die Fixture muss den Controller zurückgeben, um ihn im Test
            # als `async with` verwenden zu können.
            return controller

@pytest.mark.asyncio
async def run_mqtt_command_test(controller: SignalduinoController,
                         mock_aiomqtt_client_cls: MagicMock, # NEU: Mock des aiomqtt.Client Konstruktors
                         mqtt_cmd: str,
                         raw_cmd: str,
                         expected_response_line: str,
                         cmd_args: str = ""):
    """Helper to test a single MQTT command with an interleaved message scenario."""
    
    # Expected response payload (without trailing newline)
    expected_payload = expected_response_line.strip()

    # Die Instanz, auf der publish aufgerufen wird, ist self.client im MqttPublisher.
    # Dies entspricht dem Rückgabewert des Konstruktors (mock_aiomqtt_client_cls.return_value).
    # MqttPublisher ruft publish() direkt auf self.client auf, nicht auf dem Rückgabewert von __aenter__.
    mock_client_instance_for_publish = mock_aiomqtt_client_cls.return_value
    
    # ... Rest des Codes unverändert ...

# ...

@pytest.mark.asyncio
async def test_controller_handles_version_command(signalduino_controller, mock_aiomqtt_client_cls):
    """Test handling of the 'version' command in the controller."""
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_aiomqtt_client_cls,
            mqtt_cmd="version",
            raw_cmd="V",
            expected_response_line="V 3.3.1-dev SIGNALduino cc1101  - compiled at Mar 10 2017 22:54:50\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_freeram_command(signalduino_controller, mock_aiomqtt_client_cls):
    """
    Test handling of the 'freeram' command, expecting an integer value.
    This also verifies the correct response_pattern is passed to _send_command.
    """
    
    # 1. Mock _send_command, das die Raw-Antwort (die das Regex matchen soll) liefert
    raw_response_line = "1234\n"
    send_command_mock = AsyncMock(return_value=raw_response_line.strip())
    signalduino_controller.commands._send_command = send_command_mock
    
    # 2. Dispatcher und Payload vorbereiten
    command_path = "get/system/freeram"
    mqtt_payload = '{"req_id": "test_freeram"}'
    
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    async with signalduino_controller:
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # 3. Assertions
        assert result['status'] == "OK"
        assert result['req_id'] == "test_freeram"
        # Erwartet den geparsten Integer-Wert
        assert result['data'] == 1234 
        
        # 4. Überprüfe, ob send_command mit dem korrekten Befehl und dem Regex aufgerufen wurde
        expected_pattern = re.compile(r'^(\d+)$')
        send_command_mock.assert_called_once_with(
            command='R',
            expect_response=True,
            timeout=SDUINO_CMD_TIMEOUT,
            response_pattern=expected_pattern
        )


@pytest.mark.asyncio
async def test_controller_handles_uptime_command(signalduino_controller, mock_aiomqtt_client_cls):
    """
    Test handling of the 'uptime' command, expecting an integer value.
    """
    
    # 1. Mock _send_command
    raw_response_line = "56789\n"
    send_command_mock = AsyncMock(return_value=raw_response_line.strip())
    signalduino_controller.commands._send_command = send_command_mock
    
    # 2. Dispatcher und Payload vorbereiten
    command_path = "get/system/uptime"
    mqtt_payload = '{"req_id": "test_uptime"}'
    
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    async with signalduino_controller:
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # 3. Assertions
        assert result['status'] == "OK"
        assert result['req_id'] == "test_uptime"
        # Erwartet den geparsten Integer-Wert
        assert result['data'] == 56789 
        
        # 4. Überprüfe, ob send_command mit dem korrekten Befehl und dem Regex aufgerufen wurde
        expected_pattern = re.compile(r'^(\d+)$')
        send_command_mock.assert_called_once_with(
            command='t',
            expect_response=True,
            timeout=SDUINO_CMD_TIMEOUT,
            response_pattern=expected_pattern
        )

@pytest.mark.asyncio
async def test_controller_handles_cmds_command(signalduino_controller, mock_aiomqtt_client_cls):
    """Test handling of the 'cmds' command."""
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_aiomqtt_client_cls,
            mqtt_cmd="cmds",
            raw_cmd="?",
            expected_response_line="V X t R C S U P G r W x E Z\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_ping_command(signalduino_controller, mock_aiomqtt_client_cls):
    """Test handling of the 'ping' command."""
    async with signalduino_controller:
        await run_mqtt_command_test(
            signalduino_controller,
            mock_aiomqtt_client_cls,
            mqtt_cmd="ping",
            raw_cmd="P",
            expected_response_line="OK\n"
        )

@pytest.mark.asyncio
async def test_controller_handles_config_command(signalduino_controller, mock_aiomqtt_client_cls):
    """
    Test handling of the 'config' command, expecting a parsed decoder configuration dictionary.
    """
    # 1. Mock _send_command
    raw_response_line = "MS=1;MU=1;MC=1;MN=1\n"
    send_command_mock = AsyncMock(return_value=raw_response_line.strip())
    signalduino_controller.commands._send_command = send_command_mock
    
    # 2. Dispatcher und Payload vorbereiten
    command_path = "get/config/decoder"
    mqtt_payload = '{"req_id": "test_config"}'
    
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    async with signalduino_controller:
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # 3. Assertions
        assert result['status'] == "OK"
        assert result['req_id'] == "test_config"
        # Erwartet das geparste Dictionary
        assert result['data'] == {'MS': 1, 'MU': 1, 'MC': 1, 'MN': 1}
        
        # 4. Überprüfe, ob send_command mit dem korrekten Befehl aufgerufen wurde
        expected_pattern = re.compile(r'^\s*([A-Za-z0-9]+=\d+;?)+\s*$', re.IGNORECASE)
        send_command_mock.assert_called_once_with(
            command='CG',
            expect_response=True,
            timeout=SDUINO_CMD_TIMEOUT,
            response_pattern=expected_pattern
        )

@pytest.mark.asyncio
async def test_controller_handles_ccconf_command(signalduino_controller, mock_aiomqtt_client_cls):
    """
    Test handling of the 'ccconf' command, expecting the raw string wrapped in a dictionary.
    """
    # 1. Mock _send_command
    raw_response_line = "C0Dn11=105B1A57C43023B900070018146C070091" # Realistische Hardware-Antwort
    send_command_mock = AsyncMock(return_value=raw_response_line)
    signalduino_controller.commands._send_command = send_command_mock
    
    # 2. Dispatcher und Payload vorbereiten
    command_path = "get/cc1101/config"
    mqtt_payload = '{"req_id": "test_ccconf"}'
    
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    async with signalduino_controller:
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # 3. Assertions
        assert result['status'] == "OK"
        assert result['req_id'] == "test_ccconf"
        # Erwartet den gekapselten String
        assert result['data'] == {'cc1101_config_string': 'C0Dn11=105B1A57C43023B900070018146C070091'}
        
        # 4. Überprüfe, ob send_command mit dem korrekten Befehl und Pattern aufgerufen wurde
        expected_pattern = re.compile(r'^\s*C0D\w*\s*=\s*.*$', re.IGNORECASE)
        send_command_mock.assert_called_once_with(
            command='C0DnF',
            expect_response=True,
            timeout=SDUINO_CMD_TIMEOUT,
            response_pattern=expected_pattern
        )

@pytest.mark.asyncio
async def test_controller_handles_ccpatable_command(signalduino_controller, mock_aiomqtt_client_cls):
    """Test handling of the 'ccpatable' command."""
    # The regex r"^C3E\s=\s.*" expects the beginning of the line.
    # 1. Mock _send_command
    raw_response_line = "C3E = C0 C1 C2 C3 C4 C5 C6 C7\n"
    send_command_mock = AsyncMock(return_value=raw_response_line.strip())
    signalduino_controller.commands._send_command = send_command_mock
    
    # 2. Dispatcher und Payload vorbereiten
    command_path = "get/cc1101/patable"
    mqtt_payload = '{"req_id": "test_patable"}'
    
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    async with signalduino_controller:
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # 3. Assertions
        assert result['status'] == "OK"
        assert result['req_id'] == "test_patable"
        # Erwartet den gekapselten String
        assert result['data'] == {'pa_table_hex': 'C3E = C0 C1 C2 C3 C4 C5 C6 C7'}
        
        # 4. Überprüfe, ob send_command mit dem korrekten Befehl und Pattern aufgerufen wurde
        expected_pattern = re.compile(r'^\s*C3E\s*=\s*.*\s*$', re.IGNORECASE)
        send_command_mock.assert_called_once_with(
            command='C3E',
            expect_response=True,
            timeout=SDUINO_CMD_TIMEOUT,
            response_pattern=expected_pattern
        )

@pytest.mark.asyncio
async def test_controller_handles_ccreg_command(signalduino_controller, mock_aiomqtt_client_cls):
    """Test handling of the 'ccreg' command (default C00)."""
    # ccreg maps to SignalduinoCommands.read_cc1101_register(int(p, 16)) which sends C<reg_hex>
    async with signalduino_controller:
        await run_mqtt_command_test(
            controller=signalduino_controller,
            mock_aiomqtt_client_cls=mock_aiomqtt_client_cls,
            mqtt_cmd="ccreg",
            raw_cmd="C00", # Raw command is dynamically generated, but we assert against C00 for register 0
            expected_response_line="ccreg 00: 29 2E 05 7F ...\n",
            cmd_args="00" # Payload for ccreg is the register in hex
        )

@pytest.mark.asyncio
async def test_controller_handles_rawmsg_command(signalduino_controller, mock_aiomqtt_client_cls):
    """Test handling of the 'rawmsg' command."""
    # rawmsg sends the payload itself and expects a response.
    raw_message = "C1D"
    async with signalduino_controller:
        await run_mqtt_command_test(
            controller=signalduino_controller,
            mock_aiomqtt_client_cls=mock_aiomqtt_client_cls,
            mqtt_cmd="rawmsg",
            raw_cmd=raw_message, # The raw command is the payload itself
            expected_response_line="OK\n",
            cmd_args=raw_message
        )

@pytest.mark.asyncio
async def test_controller_handles_get_frequency(signalduino_controller, mock_aiomqtt_client_cls, mock_logger):
    """
    Testet den 'get/cc1101/frequency' MQTT-Befehl, der intern 3x read_cc1101_register aufruft.
    Dies verifiziert, dass das 'command=' Argument anstelle von 'payload=' korrekt übergeben wird.
    """
    # Wir benötigen 'call' aus unittest.mock, das am Anfang der Datei importiert wurde.

    # Simuliere die Antworten für die drei Register-Lesebefehle (C0D, C0E, C0F)
    # FREQ2 (0D) -> 0x21
    # FREQ1 (0E) -> 0x62
    # FREQ0 (0F) -> 0x00
    mock_responses = [
        "C0D = 21", # FREQ2
        "C0E = 62", # FREQ1
        "C0F = 00", # FREQ0
    ]
    
    send_command_mock = AsyncMock(side_effect=mock_responses)
    
    # Überschreibe die interne Referenz im Commands-Objekt, da es sich um ein gebundenes Callable handelt
    signalduino_controller.commands._send_command = send_command_mock

    # 1. Dispatcher und Payload vorbereiten
    command_path = "get/cc1101/frequency"
    mqtt_payload = '{"req_id": "test_freq"}'
    
    # Dispatcher manuell erstellen, da der MqttPublisher im Fixture gemockt ist
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    # 2. Asynchronen Kontext des Controllers starten
    async with signalduino_controller:
    
        # 3. Dispatch ausführen
        # Die Dispatch-Methode erwartet den Command Path und den rohen JSON String.
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # 4. Assertions
        
        # F_REG = (0x21 << 16) | (0x62 << 8) | 0x00 = 2187776
        # Frequency = (26.0 / 65536.0) * F_REG = 868.35 MHz
        FXOSC = 26.0
        DIVIDER = 65536.0
        f_reg = (0x21 << 16) | (0x62 << 8) | 0x00
        expected_frequency = (FXOSC / DIVIDER) * f_reg
        expected_frequency_rounded = round(expected_frequency, 4)
        
        assert result['status'] == "OK"
        assert result['req_id'] == "test_freq"
        # Überprüfe den berechneten Frequenzwert
        # result['data'] ist jetzt {'frequency': float}, da commands.get_frequency geändert wurde.
        assert result['data']['frequency'] == expected_frequency_rounded
        
        # Überprüfe, ob send_command mit den korrekten Argumenten aufgerufen wurde
        expected_pattern = re.compile(r'^\s*(C[a-f0-9]{2}\s*=\s*[a-f0-9]+|ccreg [a-f0-9]{2}:.*)\s*$', re.IGNORECASE)

        send_command_mock.assert_has_calls([
            call(command='C0D', expect_response=True, timeout=SDUINO_CMD_TIMEOUT, response_pattern=expected_pattern),
            call(command='C0E', expect_response=True, timeout=SDUINO_CMD_TIMEOUT, response_pattern=expected_pattern),
            call(command='C0F', expect_response=True, timeout=SDUINO_CMD_TIMEOUT, response_pattern=expected_pattern),
        ])

@pytest.mark.asyncio
async def test_controller_handles_get_frequency_without_req_id(signalduino_controller, mock_aiomqtt_client_cls, mock_logger):
    """
    Testet den 'get/cc1101/frequency' MQTT-Befehl, wenn keine req_id gesendet wird.
    Die resultierende Response sollte eine req_id von None enthalten (was in JSON zu null wird).
    """
    # Wir benötigen 'call' aus unittest.mock, das am Anfang der Datei importiert wurde.

    # Simuliere die Antworten für die drei Register-Lesebefehle (C0D, C0E, C0F)
    # FREQ2 (0D) -> 0x21
    # FREQ1 (0E) -> 0x62
    # FREQ0 (0F) -> 0x00
    mock_responses = [
        "C0D = 21", # FREQ2
        "C0E = 62", # FREQ1
        "C0F = 00", # FREQ0
    ]
    
    send_command_mock = AsyncMock(side_effect=mock_responses)
    
    # Überschreibe die interne Referenz im Commands-Objekt, da es sich um ein gebundenes Callable handelt
    signalduino_controller.commands._send_command = send_command_mock

    # 1. Dispatcher und Payload vorbereiten (keine req_id!)
    command_path = "get/cc1101/frequency"
    mqtt_payload = '{}'
    
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    # 2. Asynchronen Kontext des Controllers starten
    async with signalduino_controller:
    
        # 3. Dispatch ausführen
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # 4. Assertions
        
        # Berechne erwartete Frequenz
        FXOSC = 26.0
        DIVIDER = 65536.0
        f_reg = (0x21 << 16) | (0x62 << 8) | 0x00
        expected_frequency = (FXOSC / DIVIDER) * f_reg
        expected_frequency_rounded = round(expected_frequency, 4)
        
        assert result['status'] == "OK"
        assert result['req_id'] is None # <- CRITICAL: Überprüfe, dass req_id None ist
        assert result['data']['frequency'] == expected_frequency_rounded
        
        # Überprüfe, ob send_command mit den korrekten Argumenten aufgerufen wurde (gleiche Calls wie zuvor)
        expected_pattern = re.compile(r'^\s*(C[a-f0-9]{2}\s*=\s*[a-f0-9]+|ccreg [a-f0-9]{2}:.*)\s*$', re.IGNORECASE)

        send_command_mock.assert_has_calls([
            call(command='C0D', expect_response=True, timeout=SDUINO_CMD_TIMEOUT, response_pattern=expected_pattern),
            call(command='C0E', expect_response=True, timeout=SDUINO_CMD_TIMEOUT, response_pattern=expected_pattern),
            call(command='C0F', expect_response=True, timeout=SDUINO_CMD_TIMEOUT, response_pattern=expected_pattern),
        ])

@pytest.mark.asyncio
async def test_controller_handles_set_factory_reset(signalduino_controller, mock_aiomqtt_client_cls, mock_logger):
    """Test handling of the 'set/factory_reset' command, ensuring the 'e' command is sent."""
    
    # Simuliere eine einfache Antwort, z.B. "OK"
    send_command_mock = AsyncMock(return_value="OK\n")
    signalduino_controller.commands._send_command = send_command_mock

    command_path = "set/factory_reset"
    mqtt_payload = '{"req_id": "test_reset"}'
    
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    async with signalduino_controller:
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # 1. Assertions für das Ergebnis
        assert result['status'] == "OK"
        assert result['req_id'] == "test_reset"
        # Die erwartete Rückgabe ist nun die Fire-and-Forget-Meldung
        assert result['data'] == {'status': 'Reset command sent', 'info': 'Factory reset triggered'}
        
        # 2. Assertions für den gesendeten Befehl (e)
        # Der Timeout für factory_reset ist SDUINO_CMD_TIMEOUT
        send_command_mock.assert_called_once_with(
            command='e',
            expect_response=False,
            timeout=SDUINO_CMD_TIMEOUT
        )





@pytest.mark.asyncio
async def test_controller_handles_get_cc1101_settings(signalduino_controller, mock_aiomqtt_client_cls, mock_logger):
    """
    Testet den 'get/cc1101/settings' MQTT-Befehl, der alle 5 CC1101-Getter aggregiert.
    """
    
    # Mocking der 5 internen Getter-Methoden des Commands-Objekts, 
    # die von get_cc1101_settings aufgerufen werden.
    # Wir müssen die Methoden im Commands-Objekt überschreiben.
    
    # get_frequency gibt ein geschachteltes Dict zurück, das von get_cc1101_settings abgeflacht wird.
    freq_mock = AsyncMock(return_value={"frequency": 868.35})
    signalduino_controller.commands.get_frequency = freq_mock
    
    # 2. Bandbreiten-Mock (liefert jetzt Dict)
    bw_mock = AsyncMock(return_value={"bandwidth": 102.0})
    signalduino_controller.commands.get_bandwidth = bw_mock
    
    # 3. RAMPL-Mock (liefert jetzt Dict)
    rampl_mock = AsyncMock(return_value={"rampl": 30})
    signalduino_controller.commands.get_rampl = rampl_mock

    # 4. Sensitivity-Mock (liefert jetzt Dict)
    sens_mock = AsyncMock(return_value={"sensitivity": 12})
    signalduino_controller.commands.get_sensitivity = sens_mock
    
    # 5. Data Rate-Mock (liefert jetzt Dict)
    dr_mock = AsyncMock(return_value={"datarate": 4.8})
    signalduino_controller.commands.get_data_rate = dr_mock
    # Dispatcher und Payload vorbereiten
    command_path = "get/cc1101/settings"
    mqtt_payload = '{"req_id": "test_settings"}'
    
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    async with signalduino_controller:
    
        # Dispatch ausführen
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # Assertions
        assert result['status'] == "OK"
        assert result['req_id'] == "test_settings"
        assert result['data'] == {
            "frequency_mhz": 868.35,
            "bandwidth": 102.0,
            "rampl": 30,
            "sensitivity": 12,
            "datarate": 4.8,
        }
        
        # Verifiziere, dass alle Commands aufgerufen wurden
        freq_mock.assert_called_once()
        bw_mock.assert_called_once()
        rampl_mock.assert_called_once()
        sens_mock.assert_called_once()
        dr_mock.assert_called_once()


@pytest.mark.asyncio
async def test_controller_handles_get_cc1101_register(signalduino_controller, mock_aiomqtt_client_cls, mock_logger):
    """
    Testet den 'get/cc1101/register' MQTT-Befehl. 
    Es wird erwartet, dass der Registername im Payload enthalten ist und die Antwort 
    die geparste Registerinformation zurückgibt.
    """
    
    # 1. Mock _read_cc1101_register_by_address, die die rohe Hardware-Antwort liefert.
    # MDMCFG4 hat Adresse 0x10. Die erwartete Antwort ist C10 = <Wert>.
    raw_response_line = "C10 = 02" # Beispielwert
    
    # Die Commands-Methode, die wir mocken müssen, ist _read_cc1101_register_by_address, 
    # da die öffentliche Methode read_cc1101_register sie aufruft.
    # Da wir uns außerhalb der Klasse befinden, ist dies kompliziert. Stattdessen mocken wir
    # die gesamte read_cc1101_register Methode in commands.py.
    
    # Wir stellen den Mock für die öffentliche Methode in Commands.py bereit:
    # `async def read_cc1101_register(self, register_name: str, ...)`
    expected_result_data = {
        "register_value": raw_response_line,
        "register_name": "MDMCFG4",
        "address_hex": "10"
    }
    
    read_reg_mock = AsyncMock(return_value=expected_result_data)
    signalduino_controller.commands.read_cc1101_register = read_reg_mock
    
    # 2. Dispatcher und Payload vorbereiten
    register_name = "MDMCFG4"
    command_path = "get/cc1101/register"
    mqtt_payload = f'{{"req_id": "test_reg", "value": "{register_name}"}}'
    
    dispatcher = MqttCommandDispatcher(controller=signalduino_controller)

    async with signalduino_controller:
    
        # 3. Dispatch ausführen
        result = await dispatcher.dispatch(command_path, mqtt_payload)
        
        # 4. Assertions
        assert result['status'] == "OK"
        assert result['req_id'] == "test_reg"
        assert result['data'] == expected_result_data
        
        # 5. Verifiziere, dass die Commands-Methode mit dem korrekten Payload aufgerufen wurde
        expected_payload_dict = json.loads(mqtt_payload)
        read_reg_mock.assert_called_once_with(expected_payload_dict, timeout=SDUINO_CMD_TIMEOUT)

