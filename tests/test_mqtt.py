import json
import logging
import os
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock, Mock
from typing import Optional

import pytest
from aiomqtt import Client as AsyncMqttClient
from aiomqtt.message import Message # Korrekter Import

from signalduino.mqtt import MqttPublisher
from signalduino.types import DecodedMessage, RawFrame
from signalduino.transport import BaseTransport
from signalduino.controller import SignalduinoController

@pytest.fixture
def mock_controller():
    """Fixture for a simple mocked SignalduinoController."""
    mock_controller = MagicMock(spec=SignalduinoController)
    # Setze eine Dummy-get_version Methode, die vom Publisher aufgerufen wird
    mock_controller.get_version.return_value = "MockVersion"
    return mock_controller

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
    """Fixture für einen gemockten aiomqtt.Client."""
    # Der Mock muss ein MagicMock sein, aber seine Methoden müssen AsyncMock sein.
    # Da `aiomqtt.Client` ein asynchroner Kontextmanager ist, muss sein Rückgabewert AsyncMock sein.
    mock_client_class = MagicMock(spec=AsyncMqttClient)
    
    # Explizit die Instanz als AsyncMock setzen, da MagicMock.return_value nur MagicMock ist.
    mock_client_instance = AsyncMock(spec=AsyncMqttClient)
    
    # Stellen Sie sicher, dass alle awaitable Methoden als AsyncMocks gesetzt sind
    mock_client_instance.publish = AsyncMock()
    mock_client_instance.subscribe = AsyncMock()
    mock_client_instance.unsubscribe = AsyncMock()
    mock_client_instance.filtered_messages = AsyncMock()
    
    # Der MockClient muss eine Klasse sein, die eine Instanz zurückgibt
    mock_client_class.return_value.__aenter__.return_value = mock_client_instance
    mock_client_class.return_value.__aexit__.return_value = None
    
    return mock_client_class


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

# Der Test verwendet `patch` auf aiomqtt.Client, um die tatsächliche
# Netzwerkimplementierung zu vermeiden.
@patch("signalduino.mqtt.mqtt.Client")
@pytest.mark.asyncio
async def test_mqtt_publisher_init(MockClient, set_mqtt_env_vars, mock_controller):
    """Testet die Initialisierung des MqttPublisher (nur Attribut-Initialisierung)."""
    publisher = MqttPublisher(mock_controller)
    
    # Überprüfen der Konfiguration
    assert publisher.mqtt_host == "test-host"
    assert publisher.mqtt_port == 1883
    assert publisher.base_topic == "test/signalduino/v1"
    assert publisher.mqtt_username == "test-user"
    assert publisher.mqtt_password == "test-pass"

    # MockClient sollte hier NICHT aufgerufen werden, da die Instanzierung
    # des aiomqtt.Client in __aenter__ erfolgt.
    MockClient.assert_not_called()


@patch("signalduino.mqtt.mqtt.Client")
@pytest.mark.asyncio
async def test_mqtt_publisher_publish_success(MockClient, mock_decoded_message, caplog, mock_controller):
    """Testet publish(): Sollte verbinden und dann veröffentlichen."""
    caplog.set_level(logging.DEBUG)
    
    # Konfiguriere den MockClient-Kontextmanager-Rückgabewert, um das asynchrone await-Problem zu beheben
    # Der MockClient.return_value ist der MqttPublisher.client
    mock_client_instance = MockClient.return_value
    mock_client_instance.publish = AsyncMock()
    mock_client_instance.subscribe = AsyncMock()
    
    # Behebe den TypeError: 'MagicMock' object can't be awaited in signalduino/mqtt.py:54
    MockClient.return_value.__aenter__ = AsyncMock(return_value=None)
    MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

    publisher = MqttPublisher(mock_controller)
    
    async with publisher:
        await publisher.publish(mock_decoded_message)
    
    # Überprüfe den publish-Aufruf
    expected_topic = f"{publisher.base_topic}/state/messages"
    
    mock_client_instance.publish.assert_called_once()
    
    # Überprüfe Topic und Payload des Aufrufs
    # call_args ist ein Tupel: ((arg1, arg2), {kwarg1: val1})
    (call_topic, published_payload), call_kwargs = mock_client_instance.publish.call_args
    
    assert call_topic == expected_topic
    assert isinstance(published_payload, str)
    
    payload_dict = json.loads(published_payload)
    assert payload_dict["protocol_id"] == "1"
    assert "raw" not in payload_dict # raw sollte entfernt werden
    assert call_kwargs == {} # assert {} da keine kwargs im Code von MqttPublisher.publish übergeben werden

    assert "Published message for protocol 1 to test/signalduino/v1/state/messages" in caplog.text


@patch("signalduino.mqtt.mqtt.Client")
@pytest.mark.asyncio
async def test_mqtt_publisher_publish_simple(MockClient, caplog, mock_controller):
    """Testet publish_simple(): Sollte verbinden und dann einfache Nachricht veröffentlichen."""
    caplog.set_level(logging.DEBUG)
    
    # Konfiguriere den MockClient-Kontextmanager-Rückgabewert, um das asynchrone await-Problem zu beheben
    # Der MockClient.return_value ist der MqttPublisher.client
    mock_client_instance = MockClient.return_value
    mock_client_instance.publish = AsyncMock()
    mock_client_instance.subscribe = AsyncMock()
    # Behebe den TypeError: 'MagicMock' object can't be awaited in signalduino/mqtt.py:54
    MockClient.return_value.__aenter__ = AsyncMock(return_value=None)
    MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
    
    publisher = MqttPublisher(mock_controller)
    
    async with publisher:
        await publisher.publish_simple("status", "online", retain=True) # qos entfernt
    
    # Überprüfe den publish-Aufruf
    expected_topic = f"{publisher.base_topic}/status"
    
    mock_client_instance.publish.assert_called_once()
    (call_topic, call_payload), call_kwargs = mock_client_instance.publish.call_args
    
    assert call_topic == expected_topic
    assert call_payload == "online"
    assert call_kwargs['retain'] is True
    assert 'qos' not in call_kwargs # qos sollte nicht übergeben werden, um KeyError zu vermeiden
    
    assert "Published simple message to test/signalduino/v1/status: online" in caplog.text


@patch("signalduino.mqtt.mqtt.Client")
@pytest.mark.asyncio
async def test_mqtt_publisher_command_listener(MockClient, caplog, mock_controller):
    """Testet den asynchronen Befehls-Listener und die interne Verarbeitung."""
    caplog.set_level(logging.DEBUG)
    
    # Konfiguriere den MockClient-Kontextmanager-Rückgabewert, um das asynchrone await-Problem zu beheben
    # Der MockClient.return_value ist der MqttPublisher.client
    mock_client_instance = MockClient.return_value
    mock_client_instance.subscribe = AsyncMock()
    mock_client_instance.messages = MagicMock() # Property-Mock

    # Behebe den TypeError: 'MagicMock' object can't be awaited in signalduino/mqtt.py:54
    MockClient.return_value.__aenter__ = AsyncMock(return_value=None)
    MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

    # Mock des asynchronen Message-Generators, um "get/system/version" zu senden
    async def mock_messages_generator():
        # aiomqtt.message.Message muss gemockt werden
        mock_msg_get_version = Mock(spec=Message)
        mock_msg_get_version.topic = MagicMock()
        mock_msg_get_version.topic.__str__.return_value = "test/signalduino/v1/commands/get/system/version"
        mock_msg_get_version.payload = b"GET"

        yield mock_msg_get_version
        # Generator endet hier

    # Setze den asynchronen Generator als Rückgabewert von __aiter__ des messages-Mocks
    mock_client_instance.messages.__aiter__ = Mock(return_value=mock_messages_generator())

    publisher = MqttPublisher(mock_controller)

    # Mock publish_simple, das vom Publisher zum Senden der Response aufgerufen wird
    with patch.object(publisher, 'publish_simple', new=AsyncMock()) as mock_publish_simple:
    
        async with publisher:
            # Listener-Task wird jetzt automatisch in __aenter__ gestartet und verarbeitet die Nachrichten.

            # Warte, bis die Nachricht verarbeitet ist.
            await asyncio.sleep(0.1) 
            
            # Die Task wird beim Verlassen des async with Blocks von __aexit__ sauber beendet.
            
        mock_client_instance.subscribe.assert_called_once_with("test/signalduino/v1/commands/#")

        # Überprüfe die Aufrufe an den Controller
        mock_controller.get_version.assert_called_once()
        
        # Überprüfe den publish_simple Aufruf (als Response)
        expected_payload_response = json.dumps({
            "command": "get/system/version",
            "success": True,
            "payload": "MockVersion",
        }) # MqttPublisher serialisiert ohne indent

        mock_publish_simple.assert_called_once_with(
            subtopic="responses",
            payload=expected_payload_response,
            retain=False
        )
        assert "Received MQTT message on test/signalduino/v1/commands/get/system/version: GET" in caplog.text


# Ersetze die MockTransport-Klasse
class MockTransport(BaseTransport):
    """Minimaler asynchroner Transport-Mock für Controller-Tests."""
    def __init__(self):
        super().__init__()
        self._is_open = False
    
    @property
    def is_open(self) -> bool:
        return self._is_open

    def closed(self) -> bool:
        return not self._is_open

    async def open(self):
        self._is_open = True

    async def close(self):
        self._is_open = False

    async def readline(self, timeout: Optional[float] = None) -> Optional[str]:
        # Signatur von BaseTransport.readline anpassen
        return ""

    async def write_line(self, data: str) -> None:
        # Signatur von BaseTransport.write_line anpassen
        pass

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


@patch("signalduino.controller.MqttPublisher")
@patch.dict(os.environ, {"MQTT_HOST": "test-host"}, clear=True)
@pytest.mark.asyncio
async def test_controller_publisher_initialization_with_env(MockMqttPublisher):
    """Testet, ob der Publisher initialisiert wird, wenn MQTT_HOST gesetzt ist."""
    # Der Publisher wird jetzt in der __init__ erstellt, der Client im __aenter__.
    # Der Test prüft, ob die Publisher-Instanz erstellt wurde.
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
@pytest.mark.asyncio
async def test_controller_aexit_calls_publisher_aexit(MockMqttPublisher):
    """Testet, ob async with controller: den asynchronen Kontext des Publishers betritt/verlässt."""
    mock_publisher_instance = MockMqttPublisher.return_value
    
    # Stellen Sie sicher, dass der Controller den Publisher initialisiert (simuliere Umgebungsvariable)
    with patch.dict(os.environ, {"MQTT_HOST": "test-host"}, clear=True):
        controller = SignalduinoController(transport=MockTransport())
        
    controller._main_tasks = [] # Verhindert, dass aexit leere Tasks abbricht
    with patch.object(controller, 'initialize', new=AsyncMock()):
        async with controller:
            pass
    
    mock_publisher_instance.__aenter__.assert_called_once()
    mock_publisher_instance.__aexit__.assert_called_once()


@patch("signalduino.controller.MqttPublisher")
@patch("signalduino.controller.SignalParser")
@patch.dict(os.environ, {"MQTT_HOST": "test-host"}, clear=True)
@pytest.mark.asyncio
async def test_controller_parser_loop_publishes_message(
    MockParser, MockMqttPublisher, mock_decoded_message
):
    """Stellt sicher, dass die Nachricht im _parser_loop veröffentlicht wird."""
    mock_parser_instance = MockParser.return_value
    mock_publisher_instance = MockMqttPublisher.return_value
    mock_publisher_instance.publish = AsyncMock() # publish muss awaitbar sein
    
    # Der Parser gibt eine DecodedMessage zurück
    mock_parser_instance.parse_line.return_value = [mock_decoded_message]
    
    # Wir brauchen einen MockTransport, der eine Nachricht liefert
    mock_transport = MockTransport()
    
    # Wir greifen auf die interne raw_message_queue des Controllers zu, 
    # um die Nachricht direkt einzufügen (einfacher als den Transport zu mocken)
    controller = SignalduinoController(transport=mock_transport, parser=mock_parser_instance)
    
    with patch.object(controller, 'initialize', new=AsyncMock()):
        controller._main_tasks = [] 
        async with controller:
            # Starte den Parser-Task manuell, da run() im Test nicht aufgerufen wird
            parser_task = asyncio.create_task(controller._parser_task())
            
            # Fügen Sie die Nachricht manuell in die Queue ein
            # Die Queue ist eine asyncio.Queue und benötigt await
            await controller._raw_message_queue.put("MS;P0=1;D=...;\n")
            
            # Geben Sie dem Parser-Task Zeit, die Nachricht zu verarbeiten
            await asyncio.sleep(0.5)
            
            # Beende den Parser-Task sauber
            controller._stop_event.set()
            parser_task.cancel()
            await asyncio.gather(parser_task, return_exceptions=True)
            
            # Überprüfe, ob der Publisher für die DecodedMessage aufgerufen wurde
            # Der Publish-Aufruf ist jetzt auch async
            mock_publisher_instance.publish.assert_called_once_with(mock_decoded_message)