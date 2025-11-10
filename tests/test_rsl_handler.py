"""
Tests for RSL and specialized protocol handlers.
"""

import pytest
from sd_protocols.sd_protocols import SDProtocols


@pytest.fixture
def proto():
    """Fixture to provide a real SDProtocols instance for testing."""
    return SDProtocols()


class TestRSLHandlers:
    """Test RSL (Revolt Smart Lighting) protocol handlers."""
    
    def test_decode_rsl(self, proto):
        """Test RSL decode function."""
        bit_data = "1010101010101010"
        result = proto.decode_rsl(bit_data)
        assert result is not None
        assert isinstance(result, dict)
        assert "decoded" in result
        assert result["status"] == 1
    
    def test_encode_rsl(self, proto):
        """Test RSL encode function."""
        data = {"test": "data"}
        result = proto.encode_rsl(data)
        assert result is not None
        assert isinstance(result, dict)
        assert "encoded" in result
        assert result["status"] == 1
