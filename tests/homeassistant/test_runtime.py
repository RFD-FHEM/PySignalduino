import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoCommandTimeout
from signalduino.homeassistant import health
from signalduino.homeassistant import runtime as main
from signalduino.homeassistant.bridge import Metrics
from signalduino.transport import SerialTransport


class RuntimeTests(unittest.TestCase):
    def test_credentials_from_file_do_not_enter_repr(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "password"
            p.write_text("secret-test-value\n")
            with patch.dict(
                os.environ, {"MQTT_BROKER_PASSWORD_FILE": str(p)}, clear=True
            ):
                settings = main.Settings.from_env()
                self.assertEqual(settings.password, "secret-test-value")
                self.assertNotIn("secret-test-value", repr(settings))

    def test_topic_wildcards_and_conflicting_secret_inputs_are_rejected(self):
        for env in [
            {"MQTT_TOPIC": "signalduino/#"},
            {"MQTT_TOPIC": "homeassistant"},
            {"MQTT_BROKER_PASSWORD": "one", "MQTT_BROKER_PASSWORD_FILE": "/secret"},
        ]:
            with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                main.Settings.from_env()

    def test_health_rejects_stale_future_and_malformed_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "health"
            with patch.object(health, "HEALTH_FILE", p), patch.object(
                health.time, "monotonic", return_value=100
            ):
                for value, want in [
                    ("90", True),
                    ("0", False),
                    ("101", False),
                    ("nan", False),
                    ("garbage", False),
                ]:
                    p.write_text(value)
                    self.assertEqual(health.healthy(), want)


class FirmwareHeartbeat(unittest.IsolatedAsyncioTestCase):
    async def test_native_timeout_reconnects_instead_of_killing_driver(self):
        attempts = []

        async def failed_session(settings, metrics):
            attempts.append(1)
            if len(attempts) == 2:
                raise asyncio.CancelledError()
            raise SignalduinoCommandTimeout("no response")

        async def no_wait(delay):
            pass

        with patch.object(main, "session", failed_session), patch.object(
            main.asyncio, "sleep", no_wait
        ), self.assertRaises(asyncio.CancelledError):
            await main.reconnect(None, Metrics())
        self.assertEqual(len(attempts), 2)

    async def test_real_native_serial_heartbeat_updates_health_without_rf(self):
        master, slave = os.openpty()
        os.set_blocking(master, False)

        async def firmware():
            buffer = b""
            while True:
                try:
                    buffer += os.read(master, 4096)
                except BlockingIOError:
                    pass
                while b"\n" in buffer:
                    command, buffer = buffer.split(b"\n", 1)
                    if command == b"V":
                        os.write(master, b"V 4.0.0 SIGNALduino cc1101\r\n")
                    elif command == b"P":
                        os.write(master, b"OK\r\n")
                await asyncio.sleep(0.005)

        task = asyncio.create_task(firmware())
        metrics = Metrics()
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            health, "HEALTH_FILE", Path(tmp) / "health"
        ):
            try:
                async with SignalduinoController(
                    SerialTransport(os.ttyname(slave), 57600)
                ) as controller:
                    await main.check_serial(controller, metrics)
                    self.assertTrue(health.healthy())
                    self.assertEqual(metrics.serial._value.get(), 1)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                os.close(master)
                os.close(slave)


if __name__ == "__main__":
    unittest.main()
