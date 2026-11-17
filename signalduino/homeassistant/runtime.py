"""Exclusive USB/MQTT lifecycle around PySignalduino's native controller."""

import asyncio
import logging
import os
import re
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiomqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode
from paho.mqtt.subscribeoptions import SubscribeOptions
from prometheus_client import start_http_server

from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoError
from signalduino.transport import SerialTransport

from . import health
from .bridge import Bridge, Metrics

LOG = logging.getLogger(__name__)


class MqttClient(aiomqtt.Client):
    """Propagate MQTT5 negative PUBACKs that aiomqtt 2.5.1 discards.

    Keep aiomqtt's native connection/event machinery. A denied publish poisons
    this session so concurrent publications cannot falsely refresh health.
    """

    def __init__(self, *args, **kwargs):
        self._publish_error = None
        super().__init__(*args, **kwargs)

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        if reason_code.is_failure:
            self._publish_error = aiomqtt.MqttCodeError(reason_code)
        super()._on_publish(client, userdata, mid, reason_code, properties)

    async def publish(self, *args, **kwargs):
        if self._publish_error:
            raise self._publish_error
        await super().publish(*args, **kwargs)
        if self._publish_error:
            raise self._publish_error

    async def __aexit__(self, exc_type, exc, tb):
        if self._publish_error and self._client.is_connected():
            # A poisoned session cannot publish cleanup's offline message. A
            # normal DISCONNECT would suppress its Will and leave HA online.
            # MQTT5 explicitly supports graceful disconnect WITH Will delivery.
            self._client.disconnect(
                reasoncode=ReasonCode(PacketTypes.DISCONNECT, identifier=4)
            )
            try:
                await self._wait_for(self._disconnected, timeout=2)
            except aiomqtt.MqttError:
                pass
        await super().__aexit__(exc_type, exc, tb)


def secret(name):
    value, filename = os.environ.get(name), os.environ.get(name + "_FILE")
    if value is not None and filename:
        raise ValueError(f"Choose {name} or {name}_FILE")
    return Path(filename).read_text().rstrip("\r\n") if filename else value


@dataclass(frozen=True)
class Settings:
    serial_port: str
    baud: int
    host: str
    port: int
    username: str | None = field(repr=False)
    password: str | None = field(repr=False)
    root: str
    discovery: str
    client_id: str

    @classmethod
    def from_env(cls):
        root = os.environ.get("MQTT_TOPIC", "signalduino")
        discovery = os.environ.get("MQTT_DISCOVERY_PREFIX", "homeassistant")
        for prefix in (root, discovery):
            if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", prefix):
                raise ValueError(
                    "MQTT prefixes must not contain wildcards or empty levels"
                )
        if (
            root == discovery
            or root.startswith(discovery + "/")
            or discovery.startswith(root + "/")
        ):
            raise ValueError(
                "Driver and Home Assistant topic prefixes must be separate"
            )
        baud = int(os.environ.get("SERIAL_BAUD", "57600"))
        if baud != 57600:
            raise ValueError("This qualified SIGNALduino configuration uses 57600 baud")
        port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid MQTT port")
        # Never let upstream instantiate its separate, incompatible MQTT publisher.
        if os.environ.get("MQTT_HOST"):
            raise ValueError("Use MQTT_BROKER_HOSTNAME, not upstream MQTT_HOST")
        return cls(
            os.environ.get("SERIAL_PORT", "/dev/signalduino"),
            baud,
            os.environ.get("MQTT_BROKER_HOSTNAME", "localhost"),
            port,
            secret("MQTT_BROKER_USERNAME"),
            secret("MQTT_BROKER_PASSWORD"),
            root,
            discovery,
            os.environ.get("MQTT_CLIENT_ID", "pysignalduino-mqtt"),
        )


async def check_serial(controller, metrics):
    if (
        not controller.get_cached_version()
        or "SIGNALduino" not in controller.get_cached_version()
    ):
        raise ConnectionError("Firmware initialization did not complete")
    if any(task.done() for task in controller._main_tasks[:3]):
        raise ConnectionError("Native serial reader/parser/writer stopped")
    response = await controller.send_command(
        "P", expect_response=True, response_pattern=re.compile(r"^OK\s*$"), timeout=5
    )
    if response.strip() != "OK":
        raise ConnectionError("Firmware heartbeat failed")
    metrics.serial.set(1)
    metrics.heartbeat.set_to_current_time()
    health.HEALTH_FILE.write_text(str(time.monotonic()))


async def heartbeat(controller, metrics):
    while True:
        await check_serial(controller, metrics)
        await asyncio.sleep(15)


async def mqtt_messages(client, driver):
    async for message in client.messages:
        await driver.handle(str(message.topic), message.payload, message.retain)
    raise ConnectionError("MQTT incoming stream ended")


async def session(settings, metrics):
    availability = f"{settings.root}/availability"
    client = MqttClient(
        hostname=settings.host,
        port=settings.port,
        username=settings.username,
        password=settings.password,
        identifier=settings.client_id,
        protocol=aiomqtt.ProtocolVersion.V5,
        clean_start=True,
        keepalive=30,
        timeout=10,
        max_queued_incoming_messages=512,
        will=aiomqtt.Will(availability, "offline", qos=1, retain=True),
    )
    metrics.devices.set(0)
    try:
        async with client:
            metrics.mqtt.set(1)
            lock = asyncio.Lock()
            controller = SignalduinoController(
                SerialTransport(settings.serial_port, settings.baud)
            )

            async def send(command):
                async with lock:
                    await controller.send_command(
                        command,
                        expect_response=True,
                        response_pattern=re.compile(r"^SR;"),
                        timeout=10,
                    )

            driver = Bridge(client, send, metrics, settings.root, settings.discovery)
            controller.message_callback = driver.receive
            # Registry and commands are separate subscriptions. MQTT5 preserves the
            # retain flag even for live delivery; old retained commands are never sent.
            await client.subscribe(f"{settings.root}/devices/+/config", qos=1)
            await client.subscribe(
                f"{settings.root}/devices/+/set",
                options=SubscribeOptions(
                    qos=1, retainAsPublished=True, retainHandling=2
                ),
            )
            await client.subscribe(f"{settings.discovery}/status", qos=1)
            try:
                async with controller:
                    await check_serial(controller, metrics)
                    await client.publish(availability, "online", qos=1, retain=True)
                    LOG.info("Gateway online: %s", controller.get_cached_version())
                    tasks = [
                        asyncio.create_task(heartbeat(controller, metrics)),
                        asyncio.create_task(mqtt_messages(client, driver)),
                    ]
                    try:
                        done, _ = await asyncio.wait(
                            tasks, return_when=asyncio.FIRST_COMPLETED
                        )
                        for task in done:
                            task.result()
                        raise ConnectionError("Gateway worker ended unexpectedly")
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                try:
                    await asyncio.wait_for(
                        client.publish(availability, "offline", qos=1, retain=True), 2
                    )
                except (aiomqtt.MqttError, TimeoutError):
                    pass
    finally:
        metrics.serial.set(0)
        metrics.mqtt.set(0)
        health.HEALTH_FILE.unlink(missing_ok=True)


async def reconnect(settings, metrics):
    delay = 1
    while True:
        started = time.monotonic()
        try:
            await session(settings, metrics)
        except (
            OSError,
            TimeoutError,
            ConnectionError,
            aiomqtt.MqttError,
            SignalduinoError,
        ) as error:
            metrics.errors.inc()
            # Exception payloads from brokers can include configuration; log type only.
            LOG.warning(
                "Gateway session lost (%s); reconnect in %ss",
                type(error).__name__,
                delay,
            )
        if time.monotonic() - started > 60:
            delay = 1
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30)


async def run():
    settings = Settings.from_env()
    metrics = Metrics()
    health.HEALTH_FILE.unlink(missing_ok=True)
    start_http_server(8000, registry=metrics.registry)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    worker = asyncio.create_task(reconnect(settings, metrics))
    stopping = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait(
            [worker, stopping], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            task.result()
    finally:
        worker.cancel()
        stopping.cancel()
        await asyncio.gather(worker, stopping, return_exceptions=True)


def main():
    """Run the explicitly selected Home Assistant USB gateway."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    asyncio.run(run())
