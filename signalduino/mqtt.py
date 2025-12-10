import json
import logging
import os
from dataclasses import asdict
from typing import Optional, Any, Callable, Awaitable # NEU: Awaitable für async callbacks

import aiomqtt as mqtt
import asyncio
import paho.mqtt.client as paho_mqtt # Für topic_matches_sub
from .types import DecodedMessage, RawFrame
from .persistence import get_or_create_client_id

class MqttPublisher:
    """Publishes DecodedMessage objects to an MQTT server and listens for commands."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.client_id = get_or_create_client_id()
        self.client: Optional[mqtt.Client] = None # Will be set in __aenter__

        self.mqtt_host = os.environ.get("MQTT_HOST", "localhost")
        self.mqtt_port = int(os.environ.get("MQTT_PORT", 1883))
        self.mqtt_topic = os.environ.get("MQTT_TOPIC", "signalduino")
        self.mqtt_username = os.environ.get("MQTT_USERNAME")
        self.mqtt_password = os.environ.get("MQTT_PASSWORD")
        
        # Callback ist jetzt ein awaitable
        self.command_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
        self.command_topic = f"{self.mqtt_topic}/commands/#"


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
            return self
        except Exception:
            self.client = None
            self.logger.error("Could not connect to MQTT broker %s:%s", self.mqtt_host, self.mqtt_port, exc_info=True)
            raise # Re-raise the exception to fail the async with block
            
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.client:
            self.logger.info("Disconnecting from MQTT broker...")
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

                    if self.command_callback:
                        # Extract command from topic
                        # Topic structure: signalduino/commands/<command>
                        parts = topic_str.split("/")
                        if "commands" in parts:
                            cmd_index = parts.index("commands")
                            if len(parts) > cmd_index + 1:
                                command_name = parts[cmd_index + 1]
                                # Callback ist jetzt async
                                await self.command_callback(command_name, payload)
                            else:
                                self.logger.warning("Received command on generic command topic without specific command: %s", topic_str)
                            
                except Exception:
                    self.logger.exception("Error processing incoming MQTT message")
                        
        except mqtt.MqttError:
            self.logger.warning("Command listener stopped due to MQTT error (e.g. disconnect).")
        except asyncio.CancelledError:
            self.logger.info("Command listener task cancelled.")
        except Exception:
            self.logger.exception("Unexpected error in command listener.")


    @staticmethod
    def _message_to_json(message: DecodedMessage) -> str:
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
        
        return json.dumps(message_dict, indent=4)

    async def publish_simple(self, subtopic: str, payload: str, retain: bool = False) -> None:
        """Publishes a simple string payload to a subtopic of the main topic."""
        if not self.client:
            self.logger.warning("Attempted to publish without an active MQTT client.")
            return
            
        try:
            topic = f"{self.mqtt_topic}/{subtopic}"
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
            topic = f"{self.mqtt_topic}/messages"
            payload = self._message_to_json(message)
            await self.client.publish(topic, payload)
            self.logger.debug("Published message for protocol %s to %s", message.protocol_id, topic)
        except Exception:
            self.logger.error("Failed to publish message", exc_info=True)

    def register_command_callback(self, callback: Callable[[str, str], Awaitable[None]]) -> None:
        """Registers a callback for incoming commands (now an awaitable)."""
        self.command_callback = callback

            