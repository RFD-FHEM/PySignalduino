import json
import unittest
from pathlib import Path

from signalduino import actuators as radio
from signalduino.parser import SignalParser
from signalduino.types import DecodedMessage, RawFrame


class RadioTests(unittest.TestCase):
    def setUp(self):
        self.parser = SignalParser()
        self.vectors = json.loads(
            (Path(__file__).parents[1] / "data" / "actuators.json").read_text()
        )["vectors"]

    def test_native_fhem_vectors_create_correct_devices(self):
        for vector in self.vectors:
            with self.subTest(vector=vector["comment"]):
                events = [
                    radio.decode(m)
                    for m in self.parser.parse_line("\x02" + vector["rmsg"] + "\x03")
                ]
                events = [e for e in events if e]
                self.assertTrue(events)
                event = events[0]
                expected = vector.get("readings", {}).get("state", vector.get("state"))
                self.assertEqual(event.values["state"], expected)
                device = radio.descriptor(event)
                if event.protocol_id == "56":
                    self.assertEqual(
                        device["address"], vector["readings"]["deviceCode"].lower()
                    )
                    self.assertEqual(device["channel"], 256)
                else:
                    self.assertEqual(device["address"], "05f931b")
                    self.assertEqual(device["channel"], 1)
                    self.assertEqual(device["group"], 0)

    def test_aok_rejects_bad_checksum_marker_header_and_secondary_command(self):
        for payload in [
            "A347969601000B7E8",
            "A347969601000B7F0",
            "A247969601000B7F8",
            "A3479696010024988",
            "A34796",
            "ZZ",
        ]:
            with self.subTest(payload=payload):
                msg = DecodedMessage("56", "P56#" + payload, RawFrame(""))
                self.assertIsNone(radio.decode(msg))

    def test_full_aok_channel_bitmap_is_identity(self):
        # Checksum = 0x47+0x96+0x96+0x02+0x00+0x0b = 0x80.
        first = radio.decode(
            DecodedMessage("56", "P56#A347969601000B7F8", RawFrame(""))
        )
        second = radio.decode(
            DecodedMessage("56", "P56#A347969602000B808", RawFrame(""))
        )
        self.assertNotEqual(first.device_id, second.device_id)

    def test_unknown_protocol_or_malformed_it_has_no_device(self):
        for protocol, payload in [
            ("999", "123"),
            ("17", "i1234"),
            ("17", "iFFFFFFFF000"),
            ("17", "iBAD"),
        ]:
            self.assertIsNone(
                radio.decode(DecodedMessage(protocol, payload, RawFrame("")))
            )

    def test_send_aok_matches_independent_65_bit_reference(self):
        d = {"protocol": "56", "address": "479696", "channel": 256, "clock": 200}
        command = radio.encode(d, "OPEN")
        pulses = self.pulses(command)
        self.assertEqual(pulses[:2], [5000, -600])
        pairs = [tuple(pulses[i : i + 2]) for i in range(2, len(pulses) - 1, 2)]
        bits = "".join({(600, -200): "1", (200, -600): "0"}[pair] for pair in pairs)
        self.assertEqual(
            bits, "10100011010001111001011010010110000000010000000000001011011111111"
        )
        self.assertEqual(pulses[-1], -5000)

    def test_send_intertechno_uses_full_address_group_and_unit(self):
        d = {
            "protocol": "17",
            "address": "05f931b",
            "channel": 1,
            "group": 0,
            "clock": 275,
        }
        pulses = self.pulses(radio.encode(d, "ON"))
        self.assertEqual(pulses[:2], [275, -2750])
        bits = "".join(
            {(275, -275, 275, -1375): "0", (275, -1375, 275, -275): "1"}[
                tuple(pulses[i : i + 4])
            ]
            for i in range(2, len(pulses) - 2, 4)
        )
        self.assertEqual(bits, "00010111111001001100011011010001")
        self.assertEqual(pulses[-2:], [275, -11000])

    def test_registry_and_commands_reject_injection_and_out_of_range_data(self):
        valid = {
            "protocol": "17",
            "address": "05f931b",
            "channel": 1,
            "group": 0,
            "clock": 275,
        }
        for patch in [
            {"address": "../bad"},
            {"protocol": "17/other"},
            {"channel": 16},
            {"clock": -1},
            {"group": 2},
        ]:
            with self.assertRaises(ValueError):
                radio.validate_descriptor(valid | patch)
        for command in ["PROGRAM", "ON\nW0000", "", "toggle"]:
            with self.assertRaises(ValueError):
                radio.encode(valid, command)

    @staticmethod
    def pulses(command):
        parts = command.split(";")
        if parts[0] != "SR" or "R=5" not in parts:
            raise AssertionError("Not a bounded native SR command")
        mapping = {
            part[1]: int(part.split("=")[1]) for part in parts if part.startswith("P")
        }
        data = next(part[2:] for part in parts if part.startswith("D="))
        return [mapping[i] for i in data]


if __name__ == "__main__":
    unittest.main()
