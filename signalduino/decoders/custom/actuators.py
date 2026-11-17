"""IT v3 and A-OK AC114-01B stage-two decoders (ADR-006)."""

import re

from ...types import SensorEvent
from ..pipeline import DecodeError
from ..registry import register_decoder

AOK_ACTIONS = {0x0B: "up", 0x23: "stop", 0x43: "down"}


@register_decoder("17")
def _intertechno(message):
    bits = message.metadata.get("bits")
    if not bits:
        if not re.fullmatch(r"i[0-9a-fA-F]{8}00", message.payload):
            raise DecodeError("Invalid IT v3 payload")
        bits = f"{int(message.payload[1:9], 16):032b}"
    if not re.fullmatch("[01]{32}", bits):
        raise DecodeError("Invalid IT v3 bit length")
    address = f"{int(bits[:26], 2):07x}"
    group = int(bits[26], 2)
    state = "on" if bits[27] == "1" else "off"
    channel = int(bits[28:], 2)
    values = {
        "address": address,
        "group": group,
        "channel": channel,
        "state": state,
        "clock": round(float(message.metadata.get("clock", 275))),
    }
    return _event(
        message,
        "Intertechno v3",
        address,
        f"signalduino_17_{address}_{group}_{channel:x}",
        values,
    )


@register_decoder("56")
def _aok(message):
    if not re.fullmatch(r"P56#[0-9a-fA-F]{17}", message.payload):
        raise DecodeError("Invalid A-OK payload")
    raw = bytes.fromhex(message.payload[4:20])
    if raw[0] != 0xA3 or message.payload[-1].lower() != "8":
        raise DecodeError("Invalid A-OK header or trailing marker")
    if sum(raw[1:7]) & 255 != raw[7]:
        raise DecodeError("Invalid A-OK checksum")
    if raw[6] not in AOK_ACTIONS:
        raise DecodeError("Not an A-OK movement/stop telegram")
    channel = int.from_bytes(raw[4:6], "big")
    if channel == 0:
        raise DecodeError("A-OK telegram selects no channel")
    address = raw[1:4].hex()
    values = {
        "address": address,
        "channel": channel,
        "state": AOK_ACTIONS[raw[6]],
        "clock": round(float(message.metadata.get("clock", 200))),
    }
    return _event(
        message, "AC114-01B", address, f"signalduino_56_{address}_{channel:04x}", values
    )


def _event(message, model, address, identity, values):
    return SensorEvent(
        protocol_id=message.protocol_id,
        model=model,
        sensor_type="switch" if message.protocol_id == "17" else "cover",
        device_id=identity,
        sensor_id=address,
        channel=values["channel"],
        values=values,
        dmsg=message.payload,
        rssi=message.raw.rssi,
    )
