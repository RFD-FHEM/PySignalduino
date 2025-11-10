"""
Tests for Manchester protocol handlers (mcBit2* methods).

These tests validate the Manchester signal decoders integrated into
the ManchesterMixin class via SDProtocols.
"""

import pytest
from sd_protocols.sd_protocols import SDProtocols


@pytest.fixture
def proto():
    """Fixture to provide a real SDProtocols instance for testing."""
    return SDProtocols()


class TestMcBit2Funkbus:
    """Test Funkbus (119) protocol Manchester handler."""
    
    @pytest.mark.parametrize("bitdata, expected", [
        (
            # good message -> expected hex '2C175F30008F' from Perl test
            '1001110101001111001111110111010101010101101000000000',
            (1, '2C175F30008F'),
        ),
    ])
    def test_mcbit2funkbus_good(self, proto, bitdata, expected):
        """Test valid Funkbus message decoding."""
        rc, hexres = proto.mcBit2Funkbus(name='some_name', bit_data=bitdata, protocol_id='119', mcbitnum=len(bitdata))
        assert rc == expected[0]
        assert hexres == expected[1]

    def test_mcbit2funkbus_wrong_parity(self, proto):
        """Test Funkbus message with parity error detection."""
        # altered bitstring to trigger parity error (from original Perl test)
        bitdata = '100111010100111100111111011101010101010110110000000'
        rc, msg = proto.mcBit2Funkbus(name='some_name', bit_data=bitdata, protocol_id='119', mcbitnum=len(bitdata))
        assert rc == -1
        assert msg == 'parity error'

    def test_mcbit2funkbus_wrong_checksum(self, proto):
        """Test Funkbus message with checksum error detection."""
        # altered bitstring to trigger checksum error (from original Perl test)
        bitdata = '1001110101001111101111110111010101010101101000000000'
        rc, msg = proto.mcBit2Funkbus(name='some_name', bit_data=bitdata, protocol_id='119', mcbitnum=len(bitdata))
        assert rc == -1
        assert msg == 'checksum error'


class TestMcBit2Grothe:
    """Test Grothe weather sensor Manchester handler."""
    
    def test_mcbit2grothe_valid(self, proto):
        """Test valid Grothe 32-bit message."""
        # Example 32-bit Grothe message
        bitdata = '10101010101010101010101010101010'
        rc, hexdata = proto.mcBit2Grothe(name='test', bit_data=bitdata, protocol_id='108', mcbitnum=32)
        assert rc == 1
        assert isinstance(hexdata, str)
        assert len(hexdata) > 0
    
    def test_mcbit2grothe_invalid_length(self, proto):
        """Test Grothe message with invalid length."""
        # Grothe requires exactly 32 bits
        bitdata = '1010101010101010101010101010'  # 28 bits
        rc, msg = proto.mcBit2Grothe(name='test', bit_data=bitdata, protocol_id='108', mcbitnum=len(bitdata))
        assert rc == -1


class TestMcBit2SomfyRTS:
    """Test Somfy RTS roller shutter Manchester handler."""
    
    def test_mcbit2somfy_56bit(self, proto):
        """Test valid Somfy 56-bit message."""
        # Example 56-bit Somfy message
        bitdata = '10101010' * 7  # 56 bits
        rc, hexdata = proto.mcBit2SomfyRTS(name='test', bit_data=bitdata, protocol_id='122', mcbitnum=56)
        assert rc == 1
        assert isinstance(hexdata, str)
    
    def test_mcbit2somfy_57bit(self, proto):
        """Test Somfy 57-bit message (first bit discarded)."""
        # 57-bit message - first bit should be discarded
        bitdata = '0' + ('10101010' * 7 + '101010')  # 57 bits
        rc, hexdata = proto.mcBit2SomfyRTS(name='test', bit_data=bitdata, protocol_id='122', mcbitnum=57)
        assert rc == 1
        assert isinstance(hexdata, str)
    
    def test_mcbit2somfy_invalid_length(self, proto):
        """Test Somfy message with invalid length."""
        # Neither 56 nor 57 bits after trimming
        bitdata = '10101010' * 6  # 48 bits
        rc, msg = proto.mcBit2SomfyRTS(name='test', bit_data=bitdata, protocol_id='122', mcbitnum=48)
        assert rc == -1
