"""Real isolated Mosquitto and native serial pipeline; never production RF."""

import asyncio
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import aiomqtt

from signalduino.homeassistant import health
from signalduino.homeassistant import runtime as main
from signalduino.homeassistant.bridge import Metrics


@unittest.skipUnless(
    os.environ.get("MQTT_TEST_HOST"), "isolated MQTT test broker not configured"
)
class MqttIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_failed_publication_still_replaces_retained_online_with_offline(self):
        host = os.environ["MQTT_TEST_HOST"]
        topic = "permitted/availability"
        async with aiomqtt.Client(host) as observer:
            await observer.publish(topic, None, qos=1, retain=True)
            await observer.subscribe(topic, qos=1)
            async with main.MqttClient(
                host,
                username="restricted",
                password="test-password",
                protocol=aiomqtt.ProtocolVersion.V5,
                will=aiomqtt.Will(topic, "offline", qos=1, retain=True),
            ) as client:
                await client.publish(topic, "online", qos=1, retain=True)
                async with asyncio.timeout(3):
                    async for message in observer.messages:
                        if message.payload == b"online":
                            break
                with self.assertRaises(aiomqtt.MqttError):
                    await client.publish(
                        "forbidden/discovery", "{}", qos=1, retain=True
                    )
                # Match the runtime's best-effort cleanup after a poisoned session.
                with self.assertRaises(aiomqtt.MqttError):
                    await client.publish(topic, "offline", qos=1, retain=True)
            async with asyncio.timeout(3):
                async for message in observer.messages:
                    if message.payload == b"offline":
                        break
            async with aiomqtt.Client(host) as fresh:
                await fresh.subscribe(topic, qos=1)
                async with asyncio.timeout(3):
                    async for message in fresh.messages:
                        self.assertEqual(message.payload, b"offline")
                        self.assertTrue(message.retain)
                        break

    async def test_broker_puback_denial_is_an_error(self):
        async with main.MqttClient(
            os.environ["MQTT_TEST_HOST"],
            username="restricted",
            password="test-password",
            protocol=aiomqtt.ProtocolVersion.V5,
        ) as client:
            with self.assertRaises(aiomqtt.MqttError):
                await client.publish("forbidden/discovery", "{}", qos=1, retain=True)

    async def test_real_runtime_discovers_and_retained_commands_never_reach_serial(
        self,
    ):
        host = os.environ["MQTT_TEST_HOST"]
        root = "sdtest_" + uuid.uuid4().hex[:8]
        discovery = root + "_ha"
        master, slave = os.openpty()
        os.set_blocking(master, False)
        commands = []

        async def firmware():
            buffer = b""
            while True:
                try:
                    buffer += os.read(master, 8192)
                except BlockingIOError:
                    pass
                while b"\n" in buffer:
                    command, buffer = buffer.split(b"\n", 1)
                    commands.append(command)
                    if command == b"V":
                        os.write(master, b"V 4.0.0 SIGNALduino cc1101\r\n")
                    elif command == b"P":
                        os.write(master, b"OK\r\n")
                    elif command.startswith(b"SR;"):
                        os.write(master, command + b"\r\n")
                await asyncio.sleep(0.005)

        async def until(client, predicate):
            async with asyncio.timeout(12):
                async for message in client.messages:
                    if predicate(message):
                        return message

        emulator = asyncio.create_task(firmware())
        session = None
        settings = main.Settings(
            os.ttyname(slave), 57600, host, 1883, None, None, root, discovery, root
        )
        metrics = Metrics()
        vectors = json.loads(
            (Path(__file__).parents[1] / "data" / "actuators.json").read_text()
        )["vectors"]
        identity = "signalduino_56_479696_0100"
        cfg = f"{discovery}/cover/signalduino/{identity}/config"
        state = f"{root}/devices/{identity}/state"
        command_topic = f"{root}/devices/{identity}/set"
        registry = f"{root}/devices/{identity}/config"
        try:
            async with aiomqtt.Client(host) as observer:
                await observer.subscribe(f"{root}/#", qos=1)
                await observer.subscribe(f"{discovery}/#", qos=1)
                # Cached commands must not be delivered to a new driver session.
                await observer.publish(command_topic, "OPEN", qos=1, retain=True)
                with tempfile.TemporaryDirectory() as tmp, patch.object(
                    health, "HEALTH_FILE", Path(tmp) / "health"
                ):
                    session = asyncio.create_task(main.session(settings, metrics))
                    await until(
                        observer,
                        lambda m: str(m.topic) == f"{root}/availability"
                        and m.payload == b"online",
                    )
                    os.write(
                        master,
                        ("\x02" + vectors[1]["rmsg"] + "\x03\n").encode("latin-1"),
                    )
                    message = await until(observer, lambda m: str(m.topic) == cfg)
                    self.assertEqual(json.loads(message.payload)["unique_id"], identity)
                    await until(observer, lambda m: str(m.topic) == state)
                    self.assertTrue(health.healthy())
                    # MQTT5 must preserve RETAIN on live delivery as well.
                    await observer.publish(command_topic, "CLOSE", qos=1, retain=True)
                    await asyncio.sleep(0.1)
                    self.assertFalse(any(c.startswith(b"SR;") for c in commands))
                    await observer.publish(command_topic, "STOP", qos=1, retain=False)
                    async with asyncio.timeout(5):
                        while metrics.sent._value.get() != 1:
                            await asyncio.sleep(0.01)
                    self.assertEqual(sum(c.startswith(b"SR;") for c in commands), 1)
                    async with aiomqtt.Client(host) as retained:
                        await retained.subscribe(cfg, qos=1)
                        remembered = await until(
                            retained, lambda m: str(m.topic) == cfg
                        )
                        self.assertTrue(remembered.retain)
                        await retained.subscribe(registry, qos=1)
                        remembered = await until(
                            retained, lambda m: str(m.topic) == registry
                        )
                        self.assertEqual(
                            json.loads(remembered.payload)["address"], "479696"
                        )
                        # State must not survive for a fresh subscriber.
                        await retained.subscribe(state, qos=1)
                        with self.assertRaises(TimeoutError):
                            await asyncio.wait_for(
                                anext(retained.messages.__aiter__()), 0.15
                            )
                    session.cancel()
                    await asyncio.gather(session, return_exceptions=True)
                    await until(
                        observer,
                        lambda m: str(m.topic) == f"{root}/availability"
                        and m.payload == b"offline",
                    )
                    self.assertFalse(health.healthy())
                    commands.clear()
                    session = asyncio.create_task(main.session(settings, metrics))
                    restored = set()
                    async with asyncio.timeout(12):
                        async for message in observer.messages:
                            if str(message.topic) == cfg:
                                restored.add("config")
                            if (
                                str(message.topic) == f"{root}/availability"
                                and message.payload == b"online"
                            ):
                                restored.add("online")
                            if restored == {"config", "online"}:
                                break
                    await observer.publish(f"{discovery}/status", "online", qos=1)
                    message = await until(observer, lambda m: str(m.topic) == cfg)
                    self.assertEqual(json.loads(message.payload)["unique_id"], identity)
                    self.assertFalse(any(c.startswith(b"SR;") for c in commands))
                    self.assertFalse(any(c[:1] in (b"W", b"e", b"x") for c in commands))
        finally:
            if session:
                session.cancel()
                await asyncio.gather(session, return_exceptions=True)
            emulator.cancel()
            await asyncio.gather(emulator, return_exceptions=True)
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
