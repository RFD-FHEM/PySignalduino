import json
import logging
import os
from unittest.mock import MagicMock, patch
from typing import Optional # NEU: Import Optional für Type-Hints

import pytest
from paho.mqtt.client import Client, connack_string

from signalduino.mqtt import MqttPublisher
from signalduino.types import DecodedMessage, RawFrame
from signalduino.controller import SignalduinoController
from signalduino.transport import BaseTransport


# Definiere eine minimale DecodedMessage-Instanz für Tests
@pytest.fixture
def mock_decoded_message() -> DecodedMessage:
    return DecodedMessage(
        protocol_id="1",
        payload="RSL: ID=01, SWITCH=01, CMD=OFF",
        raw=RawFrame(
            line="+MU;...",
            rssi=-80,
            freq_afc=433.92,
            message_type="MU",
        ),
        metadata={
            "protocol_name": "Conrad RSL v1",
            "message_hex": "AABBCC",
            "message_bits": "101010101011101111001100",
            "is_repeat": False,
        },
    )

@pytest.fixture
def mock_mqtt_client():
    """Mock-Klasse für paho.mqtt.client.Client."""
    mock_client = MagicMock(spec=Client)
    # Setze einen Standardwert für is_connected()
    mock_client.is_connected.return_value = False
    yield mock_client

@pytest.fixture(autouse=True)
def set_mqtt_env_vars():
    """Setze Test-Umgebungsvariablen und räume danach auf."""
    os.environ["MQTT_HOST"] = "test-host"
    os.environ["MQTT_PORT"] = "1883"
    os.environ["MQTT_TOPIC"] = "test/signalduino"
    os.environ["MQTT_USERNAME"] = "test-user"
    os.environ["MQTT_PASSWORD"] = "test-pass"
    yield
    del os.environ["MQTT_HOST"]
    del os.environ["MQTT_PORT"]
    del os.environ["MQTT_TOPIC"]
    del os.environ["MQTT_USERNAME"]
    del os.environ["MQTT_PASSWORD"]

# Der Test verwendet `patch` auf paho.mqtt.client.Client, um die tatsächliche
# Netzwerkimplementierung zu vermeiden.
@patch("signalduino.mqtt.mqtt.Client")
def test_mqtt_publisher_init(MockClient, set_mqtt_env_vars, caplog):
    """Testet die Initialisierung des MqttPublisher."""
    caplog.set_level(logging.DEBUG)

    publisher = MqttPublisher()
    
    # Überprüfen der Client-Initialisierung
    MockClient.assert_called_once()
    assert publisher.client == MockClient.return_value
    
    # Überprüfen der Konfiguration
    assert publisher.mqtt_host == "test-host"
    assert publisher.mqtt_port == 1883
    assert publisher.mqtt_topic == "test/signalduino"
    assert publisher.mqtt_username == "test-user"
    
    # Überprüfen des Benutzernamens/Passworts
    publisher.client.username_pw_set.assert_called_once_with("test-user", "test-pass")
    
    # Überprüfen der Callbacks
    assert publisher.client.on_connect == publisher._on_connect
    assert publisher.client.on_disconnect == publisher._on_disconnect


@patch("signalduino.mqtt.mqtt.Client")
def test_mqtt_publisher_connect_success(MockClient, mock_mqtt_client, caplog):
    """Testet die erfolgreiche Verbindung und den Start der Loop."""
    caplog.set_level(logging.DEBUG)
    MockClient.return_value = mock_mqtt_client
    mock_mqtt_client.is_connected.return_value = False
    
    publisher = MqttPublisher()
    
    # Simuliere _on_connect-Aufruf, da paho-mqtt dies asynchron tut
    def simulate_connect(*args, **kwargs):
        # Rufe den on_connect-Handler manuell mit Erfolgscode (0) auf
        publisher._on_connect(mock_mqtt_client, None, None, 0)
        mock_mqtt_client.is_connected.return_value = True

    mock_mqtt_client.connect.side_effect = simulate_connect
    
    publisher._connect_if_needed()
    
    # Überprüfe, ob connect und loop_start aufgerufen wurden
    mock_mqtt_client.connect.assert_called_once_with("test-host", 1883)
    mock_mqtt_client.loop_start.assert_called_once()
    
    # Überprüfe das Log
    assert "Connected to MQTT broker test-host:1883" in caplog.text


@patch("signalduino.mqtt.mqtt.Client")
def test_mqtt_publisher_connect_failure(MockClient, mock_mqtt_client, caplog):
    """Testet den Verbindungsfehler und die Fehlerprotokollierung."""
    caplog.set_level(logging.ERROR)
    MockClient.return_value = mock_mqtt_client
    mock_mqtt_client.is_connected.return_value = False
    
    publisher = MqttPublisher()
    
    # Simuliere einen Fehler in connect()
    mock_mqtt_client.connect.side_effect = ConnectionRefusedError("Test refusal")
    
    publisher._connect_if_needed()
    
    # Überprüfe, ob connect aufgerufen wurde, aber loop_start nicht
    mock_mqtt_client.connect.assert_called_once()
    mock_mqtt_client.loop_start.assert_not_called()
    
    # Überprüfe das Log
    assert "Could not connect to MQTT broker test-host:1883" in caplog.text
    
    # Simuliere on_connect-Fehler (wenn connect erfolgreich wäre, aber rc != 0)
    mock_mqtt_client.connect.side_effect = None
    mock_mqtt_client.reset_mock()
    caplog.clear()

    # on_connect wird asynchron aufgerufen. Simuliere das Aufrufen mit rc=5
    publisher._on_connect(mock_mqtt_client, None, None, 5)
    
    assert "Failed to connect to MQTT broker. Result code: 5" in caplog.text


@patch("signalduino.mqtt.mqtt.Client")
def test_mqtt_publisher_publish_connects_and_publishes(
    MockClient, mock_mqtt_client, mock_decoded_message, caplog
):
    """Testet publish(): Sollte verbinden und dann veröffentlichen."""
    caplog.set_level(logging.DEBUG)
    MockClient.return_value = mock_mqtt_client
    
    publisher = MqttPublisher()
    
    # Mocke die Verbindung, um sicherzustellen, dass sie einmal hergestellt wird
    mock_connect_if_needed = MagicMock()
    publisher._connect_if_needed = mock_connect_if_needed
    
    # Simuliere, dass die Verbindung nach dem ersten _connect_if_needed-Aufruf hergestellt wird
    mock_mqtt_client.is_connected.side_effect = [False, True, True] 
    
    publisher.publish(mock_decoded_message)
    
    # Überprüfe den Verbindungsversuch
    mock_connect_if_needed.assert_called_once()
    
    # Überprüfe den publish-Aufruf
    expected_topic = f"{publisher.mqtt_topic}/{mock_decoded_message.protocol_id}"
    
    # Überprüfe das Payload (muss gültiges JSON sein und das Protokoll enthalten)
    args, _ = mock_mqtt_client.publish.call_args
    # args ist ein Tupel (topic, payload), der payload ist das zweite Element
    published_payload = args[1]

    assert expected_topic == "test/signalduino/1"
    assert isinstance(published_payload, str)
    
    payload_dict = json.loads(published_payload)
    assert payload_dict["protocol_id"] == "1"
    assert "raw" not in payload_dict # raw sollte entfernt werden

    mock_mqtt_client.publish.assert_called_once()
    assert "Published message for protocol 1 to test/signalduino/1" in caplog.text
    
    # Teste erneutes Veröffentlichen (sollte nicht erneut verbinden)
    mock_mqtt_client.is_connected.side_effect = [True, True]
    publisher.publish(mock_decoded_message)
    mock_connect_if_needed.assert_called_once() # Sollte NICHT erneut aufgerufen werden
    assert mock_mqtt_client.publish.call_count == 2


@patch("signalduino.mqtt.mqtt.Client")
def test_mqtt_publisher_publish_not_connected(
    MockClient, mock_mqtt_client, mock_decoded_message, caplog
):
    """Testet publish(): Sollte nicht veröffentlichen, wenn die Verbindung fehlschlägt."""
    caplog.set_level(logging.DEBUG)
    MockClient.return_value = mock_mqtt_client
    
    publisher = MqttPublisher()
    
    # Mocke die Verbindung, um sicherzustellen, dass sie fehlschlägt
    mock_connect_if_needed = MagicMock()
    publisher._connect_if_needed = mock_connect_if_needed
    
    # Simuliere, dass die Verbindung immer fehlschlägt
    mock_mqtt_client.is_connected.return_value = False
    
    publisher.publish(mock_decoded_message)
    
    # Überprüfe den Verbindungsversuch
    mock_connect_if_needed.assert_called_once()
    
    # Überprüfe, dass publish NICHT aufgerufen wurde
    mock_mqtt_client.publish.assert_not_called()


@patch("signalduino.mqtt.mqtt.Client")
def test_mqtt_publisher_stop(MockClient, mock_mqtt_client, caplog):
    """Testet die stop-Methode."""
    caplog.set_level(logging.DEBUG)
    MockClient.return_value = mock_mqtt_client
    
    publisher = MqttPublisher()
    
    # Simuliere, dass der Client verbunden ist
    mock_mqtt_client.is_connected.return_value = True
    
    publisher.stop()
    
    mock_mqtt_client.loop_stop.assert_called_once()
    mock_mqtt_client.disconnect.assert_called_once()
    
    assert "Disconnecting from MQTT broker..." in caplog.text
    
    # Teste den Aufruf, wenn der Client nicht verbunden ist
    mock_mqtt_client.is_connected.return_value = False
    mock_mqtt_client.reset_mock()
    caplog.clear()
    
    publisher.stop()
    
    mock_mqtt_client.loop_stop.assert_not_called()
    mock_mqtt_client.disconnect.assert_not_called()


class MockTransport(BaseTransport):
    """Minimaler Transport-Mock für Controller-Tests."""
    def __init__(self):
        # BaseTransport.__init__ erwartet keine Argumente
        super().__init__()
        self._is_open = False
    
    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self):
        self._is_open = True

    def close(self):
        self._is_open = False

    def readline(self, timeout: Optional[float] = None) -> Optional[str]:
        # Signatur von BaseTransport.readline anpassen
        return ""

    def write_line(self, data: str) -> None:
        # Signatur von BaseTransport.write_line anpassen
        pass


@patch("signalduino.controller.MqttPublisher")
@patch.dict(os.environ, {"MQTT_HOST": "test-host"}, clear=True)
def test_controller_publisher_initialization_with_env(MockMqttPublisher):
    """Testet, ob der Publisher initialisiert wird, wenn MQTT_HOST gesetzt ist."""
    controller = SignalduinoController(transport=MockTransport())
    
    MockMqttPublisher.assert_called_once()
    assert controller.mqtt_publisher is MockMqttPublisher.return_value
    

@patch("signalduino.controller.MqttPublisher")
@patch.dict(os.environ, {}, clear=True)
def test_controller_publisher_initialization_without_env(MockMqttPublisher):
    """Testet, ob der Publisher NICHT initialisiert wird, wenn MQTT_HOST fehlt."""
    controller = SignalduinoController(transport=MockTransport())
    
    MockMqttPublisher.assert_not_called()
    assert controller.mqtt_publisher is None
    

@patch("signalduino.controller.MqttPublisher")
def test_controller_stop_calls_publisher_stop(MockMqttPublisher):
    """Testet, ob controller.disconnect() publisher.stop() aufruft."""
    mock_publisher_instance = MockMqttPublisher.return_value
    
    # Stelle sicher, dass der Controller den Publisher initialisiert (simuliere Umgebungsvariable)
    with patch.dict(os.environ, {"MQTT_HOST": "test-host"}, clear=True):
        controller = SignalduinoController(transport=MockTransport())
        
    controller.connect() # Muss verbunden sein, damit disconnect() die Logik ausführt
    controller.disconnect()
    
    mock_publisher_instance.stop.assert_called_once()


@patch("signalduino.controller.MqttPublisher")
@patch("signalduino.controller.SignalParser")
@patch("signalduino.controller.threading.Thread")
@patch("signalduino.controller.threading.Event")
@patch("signalduino.controller.queue.Queue")
@patch.dict(os.environ, {"MQTT_HOST": "test-host"}, clear=True)
def test_controller_parser_loop_publishes_message(
    MockQueue, MockEvent, MockThread, MockParser, MockMqttPublisher, mock_decoded_message
):
    """Stellt sicher, dass die Nachricht im _parser_loop veröffentlicht wird."""
    mock_parser_instance = MockParser.return_value
    mock_publisher_instance = MockMqttPublisher.return_value
    
    # Die Queue liefert: +OK, +MU;..., Empty, Empty, Empty
    # Der Parser-Loop ruft `_handle_as_command_response` auf. Da wir es nicht mocken, wird es False zurückgeben.
    # Daher ruft der Loop `parse_line` für alle 5 Queue-Items auf.
    # - +OK (keine DecodedMessage)
    # - +MU;... (eine DecodedMessage)
    # - Empty (parse_line wird nicht aufgerufen, da die raw_line leer ist)
    # - Empty
    # - Empty
    # Für die zwei Nicht-Empty-Items muss der Parser gemockt werden. Für die leeren Zeilen (vom Empty-Queue-Item), wird parse_line NICHT aufgerufen.
    mock_parser_instance.parse_line.side_effect = [[], [mock_decoded_message]]
    
    # Mock die Warteschlange, um Nachrichten zurückzugeben und dann queue.Empty zu werfen.
    # Wir brauchen den Import der Empty-Exception für das side_effect
    from queue import Empty
    mock_raw_queue = MockQueue.return_value
    
    # Simuliere 3 Nachrichtenlesungen, dann Empty, dann Empty (für den nächsten Loop-check), dann True im is_set()
    # Der Parser-Loop ruft `get(timeout=0.1)` auf. Wenn die Queue leer ist, fängt er Empty ab und macht weiter.
    # Wir brauchen genug Empty-Werte, um die Schleife zu stoppen, wenn is_set() True wird.
    mock_raw_queue.get.side_effect = ["+OK", "+MU;...", Empty, Empty, Empty]

    # Simuliere die Stop-Logik
    mock_event_instance = MockEvent.return_value
    # Die Schleife soll 3x (für "+OK", "+MU;...", Empty) laufen und beim 4. Aufruf stoppen.
    # Nach 2 echten Nachrichten wird 1 Empty abgefangen und weitergemacht. Die Schleife läuft
    # weiter, bis is_set() True liefert. Der StopIteration-Fehler kam von is_set.side_effect,
    # der zu kurz war. Wir verlängern.
    mock_event_instance.is_set.side_effect = [False, False, False, False, True]

    controller = SignalduinoController(transport=MockTransport(), parser=mock_parser_instance)
    
    # Ersetze die Threads durch einen direkten Aufruf der Loop-Funktion
    controller._stop_event = mock_event_instance
    controller._raw_message_queue = mock_raw_queue

    # Führe die Parser-Loop aus
    controller._parser_loop()
    
    # Überprüfe, ob der Publisher für die DecodedMessage aufgerufen wurde
    mock_publisher_instance.publish.assert_called_with(mock_decoded_message)
    assert mock_publisher_instance.publish.call_count == 1