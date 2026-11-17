"""Regressions for native USB transport, initialization and parser delivery."""

import asyncio
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

from signalduino.controller import SignalduinoController
from signalduino.parser import SignalParser
from signalduino.transport import SerialTransport
from signalduino.types import DecodedMessage, RawFrame


class NativeParsing(unittest.TestCase):
    def test_fhem_aok_and_intertechno_vectors_reach_native_decoder(self):
        parser = SignalParser()
        vectors = json.loads(
            (Path(__file__).parents[1] / "data" / "actuators.json").read_text()
        )["vectors"]
        for vector in vectors:
            with self.subTest(vector=vector["comment"]):
                messages = parser.parse_line("\x02" + vector["rmsg"] + "\x03")
                expected = vector.get("protocol_id", "56")
                matches = [m for m in messages if m.protocol_id == expected]
                self.assertTrue(matches, "Native parser lost the target protocol")
                if "dmsg" in vector:
                    self.assertEqual(matches[0].payload.upper(), vector["dmsg"].upper())
                self.assertTrue(matches[0].metadata["bits"])


class NativeAsync(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_initialization_closes_serial_and_background_tasks(self):
        master, slave = os.openpty()
        transport = SerialTransport(os.ttyname(slave), baudrate=57600)
        controller = SignalduinoController(transport)
        try:
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(controller.__aenter__(), 0.05)
            self.assertTrue(transport.closed())
            self.assertTrue(all(t.done() for t in controller._main_tasks))
        finally:
            await controller.__aexit__(None, None, None)
            os.close(master)
            os.close(slave)

    async def test_serial_roundtrip_and_close(self):
        master, slave = os.openpty()
        transport = SerialTransport(os.ttyname(slave), baudrate=57600)
        try:
            await transport.open()
            self.assertFalse(transport.closed())
            await transport.write_line("V")
            command = await asyncio.wait_for(asyncio.to_thread(os.read, master, 128), 2)
            self.assertEqual(command, b"V\n")
            os.write(master, b"V 4.0.0 SIGNALduino\r\n")
            self.assertEqual(
                await asyncio.wait_for(transport.readline(), 2), "V 4.0.0 SIGNALduino"
            )
            await transport.close()
            self.assertTrue(transport.closed())
        finally:
            await transport.close()
            os.close(master)
            os.close(slave)

    async def test_controller_delivers_every_demodulated_result(self):
        messages = [
            DecodedMessage(str(pid), "test", RawFrame("test")) for pid in (17, 56)
        ]
        observed = []
        complete = asyncio.Event()

        async def receive(message):
            observed.append(message.protocol_id)
            if len(observed) == 2:
                complete.set()

        controller = SignalduinoController(
            transport=None,
            parser=SimpleNamespace(parse_line=lambda line: messages),
            message_callback=receive,
        )
        task = asyncio.create_task(controller._parser_task())
        try:
            await controller._raw_message_queue.put("test")
            await asyncio.wait_for(complete.wait(), 0.5)
            self.assertEqual(observed, ["17", "56"])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
