import json
import unittest
from pathlib import Path

from signalduino.homeassistant import bridge
from signalduino.parser import SignalParser


class Publisher:
    """External MQTT boundary; messages are checked as a HA consumer sees them."""

    def __init__(self):
        self.messages = []

    async def publish(self, topic, payload, qos=0, retain=False):
        self.messages.append(
            (
                topic,
                json.loads(payload) if payload.startswith("{") else payload,
                qos,
                retain,
            )
        )


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.publisher = Publisher()
        self.sent = []

        async def send(command):
            self.sent.append(command)

        self.driver = bridge.Bridge(self.publisher, send, bridge.Metrics())
        vectors = json.loads(
            (Path(__file__).parents[1] / "data" / "actuators.json").read_text()
        )["vectors"]
        self.messages = [
            m
            for v in vectors
            for m in SignalParser().parse_line("\x02" + v["rmsg"] + "\x03")
        ]

    async def test_received_devices_create_retained_switch_and_cover_discovery(self):
        for message in self.messages:
            await self.driver.receive(message)
        configs = {
            t: p
            for t, p, q, r in self.publisher.messages
            if t.startswith("homeassistant/")
        }
        cover = configs[
            "homeassistant/cover/signalduino/signalduino_56_479696_0100/config"
        ]
        switch = configs[
            "homeassistant/switch/signalduino/signalduino_17_05f931b_0_1/config"
        ]
        self.assertEqual(cover["device"]["identifiers"], ["signalduino_56_479696_0100"])
        self.assertTrue(cover["optimistic"])
        self.assertNotIn("position_topic", cover)
        self.assertEqual(
            switch["command_topic"],
            "signalduino/devices/signalduino_17_05f931b_0_1/set",
        )
        self.assertTrue(
            all(
                q == 1 and r
                for t, p, q, r in self.publisher.messages
                if t.startswith("homeassistant/")
            )
        )
        self.assertTrue(
            all(not r for t, p, q, r in self.publisher.messages if t.endswith("/state"))
        )

    async def test_restart_registry_and_ha_birth_keep_identity_without_fake_state(self):
        device = {"protocol": "56", "address": "479696", "channel": 256, "clock": 200}
        topic = "signalduino/devices/signalduino_56_479696_0100/config"
        await self.driver.handle(topic, json.dumps(device).encode(), True)
        await self.driver.handle("homeassistant/status", b"online", False)
        configs = [
            p
            for t, p, q, r in self.publisher.messages
            if t.startswith("homeassistant/")
        ]
        self.assertEqual(len(configs), 2)
        self.assertEqual(configs[0]["unique_id"], configs[1]["unique_id"])
        self.assertFalse(
            any(t.endswith("/state") for t, p, q, r in self.publisher.messages)
        )

    async def test_retained_unknown_and_invalid_commands_never_transmit(self):
        device = {"protocol": "56", "address": "479696", "channel": 256, "clock": 200}
        stem = "signalduino/devices/signalduino_56_479696_0100/"
        await self.driver.handle(stem + "config", json.dumps(device).encode(), True)
        await self.driver.handle(stem + "set", b"OPEN", True)
        await self.driver.handle(stem + "set", b"PROGRAM", False)
        await self.driver.handle("signalduino/devices/unknown/set", b"OPEN", False)
        self.assertEqual(self.sent, [])
        await self.driver.handle(stem + "set", b"STOP", False)
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0].startswith("SR;R=5;"))

    async def test_malformed_registry_cannot_stop_subsequent_device_learning(self):
        device = {"protocol": "56", "address": "479696", "channel": 256, "clock": 200}
        identity = "signalduino_56_479696_0100"
        topic = f"signalduino/devices/{identity}/config"
        poison = b'{"protocol":' + b"[" * 100000 + b"0" + b"]" * 100000 + b"}"
        await self.driver.handle(topic, poison, True)
        self.assertEqual(self.driver.devices, {})
        self.assertEqual(self.publisher.messages, [])
        await self.driver.handle(topic, json.dumps(device).encode(), True)
        self.assertEqual(self.driver.devices[identity], device)
        self.assertEqual(len(self.publisher.messages), 1)

    async def test_mismatched_registry_topic_cannot_create_or_control_device(self):
        device = {"protocol": "56", "address": "479696", "channel": 256, "clock": 200}
        await self.driver.handle(
            "signalduino/devices/not_the_address/config",
            json.dumps(device).encode(),
            True,
        )
        self.assertEqual(self.driver.devices, {})
        self.assertEqual(self.publisher.messages, [])

    async def test_repeated_rf_burst_does_not_duplicate_discovery(self):
        for _ in range(3):
            await self.driver.receive(self.messages[-1])
        configs = [
            t
            for t, p, q, r in self.publisher.messages
            if t.startswith("homeassistant/")
        ]
        self.assertEqual(
            configs,
            ["homeassistant/switch/signalduino/signalduino_17_05f931b_0_1/config"],
        )
        states = [p for t, p, q, r in self.publisher.messages if t.endswith("/state")]
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0]["state"], "OFF")
        self.assertEqual(states[0]["source"], "received")


if __name__ == "__main__":
    unittest.main()
