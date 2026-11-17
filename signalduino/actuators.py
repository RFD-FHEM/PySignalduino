"""Validated IT/A-OK routing identities and native transmit encoding."""

import re

from sd_protocols import SDProtocols

from .decoders import SensorDecoder

PROTOCOLS = SDProtocols()

DECODER = SensorDecoder()


def decode(message):
    """Use upstream routing/error isolation, returning only valid device events."""
    return DECODER.decode(message)


def descriptor(event):
    result = {key: event.values[key] for key in ("address", "channel", "clock")}
    result["protocol"] = event.protocol_id
    if event.protocol_id == "17":
        result["group"] = event.values["group"]
    return validate_descriptor(result)


def validate_descriptor(device):
    """Validate retained broker data as carefully as a new radio identity."""
    if not isinstance(device, dict) or device.get("protocol") not in ("17", "56"):
        raise ValueError("Unsupported device descriptor")
    it = device["protocol"] == "17"
    expected = {"protocol", "address", "channel", "clock"} | (
        {"group"} if it else set()
    )
    if set(device) != expected:
        raise ValueError("Unexpected descriptor fields")
    if not isinstance(device["address"], str) or not re.fullmatch(
        "[0-9a-f]{7}" if it else "[0-9a-f]{6}", device["address"]
    ):
        raise ValueError("Invalid radio address")
    if it and int(device["address"], 16) >= 1 << 26:
        raise ValueError("IT address outside 26-bit range")
    if type(device["channel"]) is not int or not (0 if it else 1) <= device[
        "channel"
    ] <= (15 if it else 65535):
        raise ValueError("Invalid channel")
    if type(device["clock"]) is not int or not 100 <= device["clock"] <= 1000:
        raise ValueError("Invalid pulse clock")
    if it and (type(device["group"]) is not int or device["group"] not in (0, 1)):
        raise ValueError("Invalid group bit")
    return dict(device)


def identity(device):
    device = validate_descriptor(device)
    prefix = f"signalduino_{device['protocol']}_{device['address']}_"
    if device["protocol"] == "17":
        return prefix + f"{device['group']}_{device['channel']:x}"
    return prefix + f"{device['channel']:04x}"


def encode(device, action):
    """Encode supported actions into the firmware's native bounded SR command."""
    device = validate_descriptor(device)
    pid = device["protocol"]
    if pid == "17":
        if action not in ("ON", "OFF"):
            raise ValueError("IT accepts ON or OFF")
        bits = (
            f"{int(device['address'],16):026b}{device['group']}"
            f"{int(action == 'ON')}{device['channel']:04b}"
        )
        start = PROTOCOLS.get_property(pid, "sync")
        end = PROTOCOLS.get_property(pid, "end")
    else:
        code = {"OPEN": 0x0B, "CLOSE": 0x43, "STOP": 0x23}.get(action)
        if code is None:
            raise ValueError("A-OK accepts OPEN, CLOSE or STOP")
        body = (
            bytes.fromhex(device["address"])
            + device["channel"].to_bytes(2, "big")
            + bytes([code])
        )
        raw = b"\xa3" + body + bytes([sum(body) & 255])
        bits = "".join(f"{value:08b}" for value in raw) + "1"
        start = PROTOCOLS.get_property(pid, "start")
        end = PROTOCOLS.get_property(pid, "pause")
    clock = device["clock"]
    pulses = [round(clock * p) for p in start]
    for bit in bits:
        pulses.extend(
            round(clock * p)
            for p in PROTOCOLS.get_property(pid, "one" if bit == "1" else "zero")
        )
    pulses.extend(round(clock * p) for p in end)
    patterns = list(dict.fromkeys(pulses))
    if len(patterns) > 8:
        raise ValueError("Firmware pattern limit exceeded")
    data = "".join(str(patterns.index(p)) for p in pulses)
    fields = ";".join(f"P{i}={p}" for i, p in enumerate(patterns))
    return f"SR;R=5;{fields};D={data};"
