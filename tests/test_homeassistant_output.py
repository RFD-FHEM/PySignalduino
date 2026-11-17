"""The native output adapter formats discovery without a broker or side effects."""

from signalduino.output.homeassistant import discovery_config


def test_cover_discovery_is_pure_and_includes_the_complete_channel_bitmap():
    device = {"protocol": "56", "address": "479696", "channel": 256, "clock": 200}
    original = dict(device)
    domain, config = discovery_config(device, "signalduino", "0.1.0")
    assert device == original
    assert domain == "cover"
    assert config["unique_id"] == "signalduino_56_479696_0100"
    assert (
        config["command_topic"] == "signalduino/devices/signalduino_56_479696_0100/set"
    )
    assert config["optimistic"] is True
    assert "position_topic" not in config
