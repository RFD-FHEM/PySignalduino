"""Pure Home Assistant discovery configuration for supported actuators."""

from .. import actuators as radio


def discovery_config(device, root="signalduino", version="0.1.0"):
    """Return (domain, config), without publishing or changing device state."""
    device = radio.validate_descriptor(device)
    identity = radio.identity(device)
    domain = "switch" if device["protocol"] == "17" else "cover"
    stem = f"{root}/devices/{identity}"
    model = "Intertechno v3" if domain == "switch" else "AC114-01B"
    config = {
        "name": None,
        "unique_id": identity,
        "command_topic": f"{stem}/set",
        "state_topic": f"{stem}/state",
        "value_template": "{{ value_json.state }}",
        "availability_topic": f"{root}/availability",
        "optimistic": True,
        "device": {
            "identifiers": [identity],
            "name": f"{model} {device['address']} / {device['channel']:x}",
            "model": model,
        },
        "origin": {
            "name": "pysignalduino-mqtt",
            "sw_version": version,
            "support_url": "https://github.com/RFD-FHEM/PySignalduino",
        },
    }
    if domain == "switch":
        config.update(payload_on="ON", payload_off="OFF")
    else:
        config.update(
            payload_open="OPEN",
            payload_close="CLOSE",
            payload_stop="STOP",
            state_opening="opening",
            state_closing="closing",
            state_stopped="stopped",
        )
    return domain, config
