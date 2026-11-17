"""Home Assistant output adapter; radio decoding stays in PySignalduino."""

import json
import logging
import time
from datetime import UTC, datetime
from importlib.metadata import version

from prometheus_client import CollectorRegistry, Counter, Gauge

from .. import actuators as radio
from ..output.homeassistant import discovery_config

LOG = logging.getLogger(__name__)
VERSION = version("signalduino-mqtt")


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.serial = Gauge(
            "signalduino_serial_connected",
            "Firmware heartbeat is healthy",
            registry=self.registry,
        )
        self.mqtt = Gauge(
            "signalduino_mqtt_connected",
            "MQTT session is connected",
            registry=self.registry,
        )
        self.heartbeat = Gauge(
            "signalduino_last_heartbeat_timestamp_seconds",
            "Last firmware heartbeat",
            registry=self.registry,
        )
        self.devices = Gauge(
            "signalduino_devices",
            "Known supported radio identities",
            registry=self.registry,
        )
        self.frames = Counter(
            "signalduino_received_frames",
            "Native decoded RF frames",
            registry=self.registry,
        )
        self.errors = Counter(
            "signalduino_errors",
            "Failed publish, serial or command operations",
            registry=self.registry,
        )
        self.sent = Counter(
            "signalduino_sent_commands",
            "Firmware-acknowledged transmissions, not physical acknowledgements",
            registry=self.registry,
        )


class Bridge:
    def __init__(
        self, client, send, metrics, root="signalduino", discovery="homeassistant"
    ):
        self.client = client
        self.send = send
        self.metrics = metrics
        self.root = root
        self.discovery = discovery
        self.devices = {}
        self.recent = {}

    async def publish(self, topic, payload, retain=False):
        try:
            await self.client.publish(topic, json.dumps(payload), qos=1, retain=retain)
        except Exception:
            self.metrics.errors.inc()
            raise

    async def discover(self, device):
        identity = radio.identity(device)
        domain, config = discovery_config(device, self.root, VERSION)
        # The native discovery node level permits a broker ACL scoped to this
        # driver without granting write access to every HA switch or cover.
        await self.publish(
            f"{self.discovery}/{domain}/signalduino/{identity}/config",
            config,
            retain=True,
        )

    async def receive(self, message):
        self.metrics.frames.inc()
        now = datetime.now(UTC).isoformat()
        await self.publish(
            f"{self.root}/events",
            {
                "protocol_id": message.protocol_id,
                "payload": message.payload,
                "received_at": now,
            },
        )
        event = radio.decode(message)
        if event is None:
            return
        try:
            device = radio.descriptor(event)
            identity = radio.identity(device)
        except (ValueError, TypeError, KeyError):
            LOG.warning("Ignoring invalid decoded device identity")
            return
        if identity not in self.devices:
            if len(self.devices) >= 256:
                LOG.warning("Learned-device limit reached")
                return
            await self.publish(
                f"{self.root}/devices/{identity}/config", device, retain=True
            )
            await self.discover(device)
            self.devices[identity] = device
            self.metrics.devices.set(len(self.devices))
            LOG.info("Learned %s", identity)
        state = event.values["state"]
        previous = self.recent.get(identity)
        clock = time.monotonic()
        if previous and previous[0] == state and clock - previous[1] < 0.4:
            return
        self.recent[identity] = (state, clock)
        ha_state = (
            state.upper()
            if device["protocol"] == "17"
            else {"up": "opening", "down": "closing", "stop": "stopped"}[state]
        )
        await self.publish(
            f"{self.root}/devices/{identity}/state",
            {
                "state": ha_state,
                "action": state,
                "source": "received",
                "received_at": now,
                "rssi": event.rssi,
            },
        )

    async def handle(self, topic, payload, retain):
        if topic == f"{self.discovery}/status" and payload == b"online":
            for device in tuple(self.devices.values()):
                await self.discover(device)
            return
        prefix = f"{self.root}/devices/"
        if not topic.startswith(prefix):
            return
        tail = topic[len(prefix) :].split("/")
        if len(tail) != 2:
            return
        identity, operation = tail
        try:
            if operation == "config":
                if len(payload) > 512:
                    raise ValueError("Device descriptor exceeds 512 bytes")
                device = radio.validate_descriptor(json.loads(payload))
                if identity != radio.identity(device):
                    raise ValueError("Registry identity mismatch")
                if identity not in self.devices:
                    if len(self.devices) >= 256:
                        raise ValueError("Learned-device limit reached")
                    await self.discover(device)
                    self.devices[identity] = device
                    self.metrics.devices.set(len(self.devices))
            elif operation == "set":
                if retain or identity not in self.devices:
                    raise ValueError("Retained or unknown device command")
                command = radio.encode(self.devices[identity], payload.decode("ascii"))
                await self.send(command)
                self.metrics.sent.inc()
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
            self.metrics.errors.inc()
            LOG.warning("Rejected invalid %s message for %s", operation, identity)
