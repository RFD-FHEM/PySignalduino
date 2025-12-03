import json
import logging
import os
from dataclasses import asdict
from typing import Optional, Any, Callable

import paho.mqtt.client as mqtt

from .types import DecodedMessage, RawFrame
from .persistence import get_or_create_client_id

class MqttPublisher:
    """Publishes DecodedMessage objects to an MQTT server and listens for commands."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        client_id = get_or_create_client_id()
        self.client = mqtt.Client(client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        self.mqtt_host = os.environ.get("MQTT_HOST", "localhost")
        self.mqtt_port = int(os.environ.get("MQTT_PORT", 1883))
        self.mqtt_topic = os.environ.get("MQTT_TOPIC", "signalduino")
        self.mqtt_username = os.environ.get("MQTT_USERNAME")
        self.mqtt_password = os.environ.get("MQTT_PASSWORD")

        if self.mqtt_username and self.mqtt_password:
            self.client.username_pw_set(self.mqtt_username, self.mqtt_password)
        
        self.command_callback: Optional[Callable[[str, str], None]] = None
        self.client.on_message = self._on_message

        # Will connect on first publish attempt if not connected

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            self.logger.info("Connected to MQTT broker %s:%s", self.mqtt_host, self.mqtt_port)
            # Subscribe to command topic
            command_topic = f"{self.mqtt_topic}/commands/#"
            self.client.subscribe(command_topic)
            self.logger.info("Subscribed to %s", command_topic)
        else:
            self.logger.error("Failed to connect to MQTT broker. Result code: %s", rc)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Handles incoming MQTT messages."""
        try:
            payload = msg.payload.decode("utf-8")
            self.logger.debug("Received MQTT message on %s: %s", msg.topic, payload)
            
            if self.command_callback:
                # Extract command from topic or payload
                # Topic structure: signalduino/commands/<command>
                # Example: signalduino/commands/version -> get version
                
                parts = msg.topic.split("/")
                if "commands" in parts:
                    cmd_index = parts.index("commands")
                    if len(parts) > cmd_index + 1:
                        command_name = parts[cmd_index + 1]
                        self.command_callback(command_name, payload)
                    else:
                        self.logger.warning("Received command on generic command topic without specific command: %s", msg.topic)
                
        except Exception:
            self.logger.exception("Error processing incoming MQTT message")

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        if rc != 0:
            self.logger.warning("Disconnected from MQTT broker with result code: %s. Attempting auto-reconnect.", rc)
        else:
            self.logger.info("Disconnected from MQTT broker.")

    def _connect_if_needed(self) -> None:
        if not self.client.is_connected():
            try:
                self.logger.debug("Attempting to connect to MQTT broker...")
                self.client.connect(self.mqtt_host, self.mqtt_port)
                self.client.loop_start()  # Start a non-blocking loop
            except Exception:
                self.logger.error("Could not connect to MQTT broker %s:%s", self.mqtt_host, self.mqtt_port, exc_info=True)

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

    def is_connected(self) -> bool:
        """Checks if the client is connected."""
        return self.client.is_connected()

    def publish_simple(self, subtopic: str, payload: str, retain: bool = False) -> None:
        """Publishes a simple string payload to a subtopic of the main topic."""
        if not self.is_connected():
            self._connect_if_needed()
        
        if self.is_connected():
            try:
                topic = f"{self.mqtt_topic}/{subtopic}"
                self.client.publish(topic, payload, retain=retain)
                self.logger.debug("Published simple message to %s: %s", topic, payload)
            except Exception:
                self.logger.error("Failed to publish simple message to %s", subtopic, exc_info=True)

    def publish(self, message: DecodedMessage) -> None:
        """Publishes a DecodedMessage."""
        if not self.is_connected():
            self._connect_if_needed()

        if self.is_connected():
            try:
                topic = f"{self.mqtt_topic}/messages"
                payload = self._message_to_json(message)
                self.client.publish(topic, payload)
                self.logger.debug("Published message for protocol %s to %s", message.protocol_id, topic)
            except Exception:
                self.logger.error("Failed to publish message", exc_info=True)

    def register_command_callback(self, callback: Callable[[str, str], None]) -> None:
        """Registers a callback for incoming commands."""
        self.command_callback = callback

    def stop(self) -> None:
        """Stops the MQTT client and disconnects."""
        if self.client.is_connected():
            self.logger.info("Disconnecting from MQTT broker...")
            self.client.loop_stop()
            self.client.disconnect()
        
            