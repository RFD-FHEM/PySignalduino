import json
import logging
import os
from dataclasses import asdict
from typing import Optional, Any, Callable, Awaitable # NEU: Awaitable für async callbacks

from .commands import MqttCommandDispatcher, CommandValidationError, SignalduinoCommandTimeout # NEU: Import Dispatcher
import aiomqtt as mqtt
import asyncio
import paho.mqtt.client as paho_mqtt # Für topic_matches_sub
from .types import DecodedMessage, RawFrame
from .persistence import get_or_create_client_id

# Import protocol loader helper to access preamble data
try:
    from sd_protocols.loader import _protocol_handler
except ImportError:
    _protocol_handler = None

class MqttPublisher:
    """Publishes DecodedMessage objects to an MQTT server and listens for commands."""

    def __init__(
        self, 
        controller: Any,
        logger: Optional[logging.Logger] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> None:
        self.controller = controller
        self.logger = logger or logging.getLogger(__name__)
        self.dispatcher = MqttCommandDispatcher(controller=controller) # NEU: Dispatcher initialisieren
        self.client_id = get_or_create_client_id()
        self.client: Optional[mqtt.Client] = None # Will be set in __aenter__
        self._listener_task: Optional[asyncio.Task[None]] = None # NEU: Task für den Command Listener
        self._protocol_handler = _protocol_handler

        # Konfiguration: CLI/Args > ENV > Default
        self.mqtt_host = host or os.environ.get("MQTT_HOST", "localhost")
        self.mqtt_port = port or int(os.environ.get("MQTT_PORT", 1883))
        
        # NEU: Verwende versioniertes Topic als Basis für alle Publishes/Subs
        topic_base = topic or os.environ.get('MQTT_TOPIC', 'signalduino')
        self.base_topic = f"{topic_base}/v1"
        self.mqtt_username = username or os.environ.get("MQTT_USERNAME")
        self.mqtt_password = password or os.environ.get("MQTT_PASSWORD")
        
        self.command_topic = f"{self.base_topic}/commands/#"
        self.response_topic = f"{self.base_topic}/responses" # Basis für Response Publishes
        self.error_topic = f"{self.base_topic}/errors" # Basis für Error Publishes



    async def __aenter__(self) -> "MqttPublisher":
        self.logger.debug("Initializing MQTT client...")
        
        if self.mqtt_username and self.mqtt_password:
            self.client = mqtt.Client(
                hostname=self.mqtt_host,
                port=self.mqtt_port,
                username=self.mqtt_username,
                password=self.mqtt_password,
            )
        else:
            self.client = mqtt.Client(
                hostname=self.mqtt_host,
                port=self.mqtt_port,
            )
        try:
            # Connect the client (asyncio-mqtt's connect is managed by __aenter__ of its own internal context manager)
            # We use the internal context manager to ensure connection/disconnection happens
            # The client property itself is the AsyncioMqttClient
            # Connect the client (asyncio-mqtt's connect is managed by __aenter__ of its own internal context manager)
            # We use the internal context manager to ensure connection/disconnection happens
            # The client property itself is the AsyncioMqttClient
            await self.client.__aenter__()
            self.logger.info("Connected to MQTT broker %s:%s", self.mqtt_host, self.mqtt_port)
            # Starte den Command Listener als Hintergrund-Task, um die Verbindung aktiv zu halten
            # und Kommandos zu empfangen. Dies ist entscheidend für aiomqtt.
            self._listener_task = asyncio.create_task(self._command_listener(), name="mqtt-listener")
            return self
        except Exception:
            self.client = None
            self.logger.error("Could not connect to MQTT broker %s:%s", self.mqtt_host, self.mqtt_port, exc_info=True)
            raise # Re-raise the exception to fail the async with block
            
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.client:
            self.logger.info("Disconnecting from MQTT broker...")
            # Beende den Command Listener Task, bevor der Client getrennt wird
            if self._listener_task:
                self._listener_task.cancel()
                # Warten auf Abschluss mit Ausnahmebehandlung
                await asyncio.gather(self._listener_task, return_exceptions=True)
                self._listener_task = None

            # Disconnect the client
            await self.client.__aexit__(exc_type, exc_val, exc_tb)
            self.client = None
            self.logger.info("Disconnected from MQTT broker.")

    async def is_connected(self) -> bool:
        """Returns True if the MQTT client is connected."""
        # asyncio_mqtt Client hat kein is_connected, aber der interne Client.
        # Wir können prüfen, ob self.client existiert.
        return self.client is not None
        
    async def _command_listener(self) -> None:
        """Listens for commands on the command topic and calls the callback."""
        if not self.client:
            self.logger.error("MQTT client is not connected. Cannot start command listener.")
            return

        self.logger.info("Subscribing to %s", self.command_topic)
        
        try:
            # Subscribe and then iterate over messages
            # Subscribe and then iterate over messages. aiomqtt hat keine filtered_messages.
            await self.client.subscribe(self.command_topic)

            messages = self.client.messages # messages ist jetzt eine Property und kein Context Manager
            self.logger.info("Command listener started for %s", self.command_topic)
            async for message in messages:
                # Manuelles Filtern des Topics, da aiomqtt kein filtered_messages hat
                topic_str = str(message.topic)
                if not paho_mqtt.topic_matches_sub(self.command_topic, topic_str):
                    continue
                try:
                    # message.payload ist bytes und .decode("utf-8") ist korrekt
                    payload = message.payload.decode("utf-8")
                    self.logger.debug("Received MQTT message on %s: %s", topic_str, payload)
                    
                    # Extract command from topic
                    # Topic structure: signalduino/v1/commands/<command>
                    parts = topic_str.split("/")
                    # Wir suchen nach 'commands' im Topic-Pfad
                    try:
                        cmd_index = parts.index("commands")
                    except ValueError:
                        # Sollte nicht passieren, da wir auf command_topic subscriben, aber zur Sicherheit
                        self.logger.warning("Received message on topic without 'commands' segment: %s", topic_str)
                        continue

                    if len(parts) > cmd_index + 1:
                        # Nimm den Rest des Pfades als Command-Name (für Unterbefehle wie get/system/version)
                        command_name = "/".join(parts[cmd_index + 1:])
                        # Handle command internally
                        await self._handle_command(command_name, payload)
                    else:
                        self.logger.warning("Received command on generic command topic without specific command: %s", topic_str)
                            
                except Exception:
                    self.logger.exception("Error processing incoming MQTT message")
                    
                await asyncio.sleep(0.01) # Wichtig: Yield, um die Event-Loop freizugeben, falls Nachrichten in schneller Folge ankommen
                        
        except mqtt.MqttError:
            self.logger.warning("Command listener stopped due to MQTT error (e.g. disconnect).")
        except asyncio.CancelledError:
            self.logger.info("Command listener task cancelled.")
        except Exception:
            self.logger.exception("Unexpected error in command listener.")

    async def _handle_command(self, command_name: str, payload: str) -> None:
        """Handles incoming MQTT commands based on the command_name."""
        
        self.logger.info("Handling command: %s with payload: %s", command_name, payload)
        
        req_id: Optional[str] = None
        
        # Versuche, req_id aus dem Payload zu extrahieren, falls es sich um gültiges JSON handelt.
        try:
            payload_dict = json.loads(payload)
            req_id = payload_dict.get("req_id")
        except json.JSONDecodeError:
            # Der Payload ist kein gültiges JSON. req_id bleibt None, und der Dispatcher
            # wird dies als CommandValidationError behandeln, wenn er json.loads erneut aufruft.
            pass
        
        try:
            # Der Dispatcher gibt ein Ergebnis-Dictionary mit 'status', 'req_id', 'data' zurück.
            result = await self.dispatcher.dispatch(command_name, payload)
            
            # Der Dispatcher kann req_id als None zurückgeben, wenn sie nicht im Payload war.
            # Wir überschreiben req_id mit dem Ergebnis, um Konsistenz zu gewährleisten.
            req_id = result.get("req_id") # Kann None sein

            response_payload = {
                "command": command_name,
                "success": True,
                "req_id": req_id, # Kann None sein, was in JSON zu null wird
                "payload": result.get("data"),
            }

            await self.publish_simple(
                subtopic="responses", 
                payload=json.dumps(response_payload), 
                retain=False
            )
            self.logger.info("Successfully handled and published response for command %s.", command_name)

        except (CommandValidationError, SignalduinoCommandTimeout) as e:
            self.logger.warning("Command failed (Validation/Timeout): %s: %s", command_name, e)

            await self.publish_simple(
                subtopic="errors",
                payload=json.dumps({
                    "command": command_name,
                    "success": False,
                    "req_id": req_id, # Verwendet die oben extrahierte (oder None)
                    "error": str(e),
                }),
                retain=False
            )
        except Exception:
            # Wenn ein interner Fehler auftritt (z.B. im Controller),
            # verwenden wir die zuvor extrahierte req_id.
            self.logger.exception("Internal error during command dispatching: %s", command_name)
            await self.publish_simple(
                subtopic="errors",
                payload=json.dumps({
                    "command": command_name,
                    "success": False,
                    "req_id": req_id, # Verwendet die oben extrahierte (oder None)
                    "error": "Internal server error during command execution.",
                }),
                retain=False
            )


    def _message_to_json(self, message: DecodedMessage) -> str:
        """Serializes a DecodedMessage to a JSON string."""

        # DecodedMessage uses dataclasses, but RawFrame inside it also uses a dataclass.
        # We need a custom serializer to handle nested dataclasses like RawFrame.
        def _raw_frame_to_dict(raw_frame: RawFrame) -> dict:
            return asdict(raw_frame)

        message_dict = asdict(message)
        
        # Convert RawFrame nested object to dict
        if "raw" in message_dict and isinstance(message_dict["raw"], RawFrame):
            message_dict["raw"] = _raw_frame_to_dict(message_dict["raw"])
        
        # Remove empty or non-useful fields for publication
        message_dict.pop("raw", None) # Do not publish raw frame data by default
        
        # Append preamble to payload for FHEM compatibility (PreambleProtocolID#HexData)
        preamble = ""
        if self._protocol_handler:
            try:
                # check_property returns the value or default
                preamble = self._protocol_handler.check_property(message.protocol_id, 'preamble', '')
            except Exception as e:
                self.logger.warning("Failed to get preamble: %s", e)

        # Add new 'preamble' field
        message_dict["preamble"] = preamble
        
        # Ensure payload is uppercase, but DO NOT prepend preamble anymore
        message_dict["payload"] = message.payload.upper()

        return json.dumps(message_dict, indent=4)

    async def publish_simple(self, subtopic: str, payload: str, retain: bool = False) -> None:
        """Publishes a simple string payload to a subtopic of the main topic."""
        if not self.client:
            self.logger.warning("Attempted to publish without an active MQTT client.")
            return
            
        try:
            topic = f"{self.base_topic}/{subtopic}"
            await self.client.publish(topic, payload, retain=retain)
            self.logger.debug("Published simple message to %s: %s", topic, payload)
        except Exception:
            self.logger.error("Failed to publish simple message to %s", subtopic, exc_info=True)

    async def publish(self, message: DecodedMessage) -> None:
        """Publishes a DecodedMessage."""
        if not self.client:
            self.logger.warning("Attempted to publish without an active MQTT client.")
            return

        try:
            topic = f"{self.base_topic}/state/messages"
            payload = self._message_to_json(message)
            await self.client.publish(topic, payload)
            self.logger.debug("Published message for protocol %s to %s", message.protocol_id, topic)
        except Exception:
            self.logger.error("Failed to publish message", exc_info=True)
