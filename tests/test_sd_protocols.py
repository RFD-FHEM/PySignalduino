import pytest
from sd_protocols import SDProtocols

def test_protocol_exists():
    sd = SDProtocols()
    assert sd.protocol_exists("1")
    assert not sd.protocol_exists("999")

def test_get_property():
    sd = SDProtocols()
    assert sd.get_property("1", "name") == "Conrad RSL v1"

def test_check_property_with_default():
    sd = SDProtocols()
    assert sd.check_property("1", "nonexistent", default="fallback") == "fallback"

def test_get_keys_filter():
    sd = SDProtocols()
    keys = sd.get_keys("clientmodule")
    assert "1" in keys