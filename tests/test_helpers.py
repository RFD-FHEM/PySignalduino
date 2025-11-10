"""Tests for helper functions: MCRAW, dec2binppari, binStr2hexStr"""


class TestBinStr2HexStr:
    """Test binary to hex string conversion."""

    def test_bin_str_2_hex_str_as_method(self, proto):
        """Test binStr2hexStr called as method with various inputs."""
        # Test basic conversions
        assert proto.bin_str_2_hex_str('1111') == 'F'
        assert proto.bin_str_2_hex_str('1010') == 'A'
        assert proto.bin_str_2_hex_str('101011111010') == 'AFA'
        assert proto.bin_str_2_hex_str('11') == '3'
        assert proto.bin_str_2_hex_str('0000') == '0'
        
        # Test 8-bit values
        assert proto.bin_str_2_hex_str('11111111') == 'FF'
        assert proto.bin_str_2_hex_str('00000000') == '00'
        
        # Test invalid input
        assert proto.bin_str_2_hex_str('0x00000000') is None
        assert proto.bin_str_2_hex_str('00000002') is None

    def test_bin_str_2_hex_str_long_binary(self, proto):
        """Test binStr2hexStr with a long binary string."""
        long_binary = '1111' * 32  # 128 bits
        expected = 'F' * 32
        assert proto.bin_str_2_hex_str(long_binary) == expected

    def test_bin_str_2_hex_str_invalid_input(self, proto):
        """Test binStr2hexStr with invalid inputs."""
        assert proto.bin_str_2_hex_str(None) is None
        assert proto.bin_str_2_hex_str('') == ''
        assert proto.bin_str_2_hex_str('abc') is None


class TestDec2BinPpari:
    """Test decimal to binary with parity conversion."""

    def test_dec_2_bin_ppari_as_method(self, proto):
        """Test dec2binppari called as method."""
        # Test cases from Perl tests
        assert proto.dec_2_bin_ppari(32) == '001000001'
        assert proto.dec_2_bin_ppari(204) == '110011000'
        
    def test_dec_2_bin_ppari_edge_cases(self, proto):
        """Test dec2binppari with edge cases."""
        # 0 -> '00000000' with parity 0
        assert proto.dec_2_bin_ppari(0) == '000000000'
        # 255 -> '11111111' with parity 0 (even number of 1s)
        assert proto.dec_2_bin_ppari(255) == '111111110'
        # 1 -> '00000001' with parity 1
        assert proto.dec_2_bin_ppari(1) == '000000011'

    def test_dec_2_bin_ppari_parity_calculation(self, proto):
        """Test that parity is correctly calculated."""
        # 32 = 0b00100000 -> one '1', so parity bit = 1
        result = proto.dec_2_bin_ppari(32)
        assert result == '001000001'
        assert result[-1] == '1'  # last bit is parity
        
        # 204 = 0b11001100 -> four '1's (even), so parity bit = 0
        result = proto.dec_2_bin_ppari(204)
        assert result == '110011000'
        assert result[-1] == '0'  # last bit is parity


class TestMCRAW:
    """Test MCRAW protocol handler."""

    def test_mcraw_good_message(self, proto):
        """Test MCRAW with a valid message."""
        # Protocol 9989 has length_max in test_protocolData
        # From Perl test: bitData="001010101010010010100111"
        bit_data = '001010101010010010100111'
        rc, hex_result = proto.mcraw(
            name='some_name',
            bit_data=bit_data,
            protocol_id=9989,
            mcbitnum=len(bit_data)
        )
        assert rc == 1
        assert hex_result == '2AA4A7'

    def test_mcraw_message_too_long(self, proto):
        """Test MCRAW with a message that exceeds length_max."""
        # Set up a protocol with length_max constraint
        # Using protocol 9989 with modified length_max
        bit_data = '0010101010100100101001110011'
        
        # First, manually set length_max for protocol 9989
        proto._protocols[9989] = {
            'length_max': 24,  # Restrict to 24 bits
            'name': 'Test Protocol'
        }
        
        rc, msg = proto.mcraw(
            name='some_name',
            bit_data=bit_data,
            protocol_id=9989,
            mcbitnum=len(bit_data)
        )
        assert rc == -1
        assert msg == 'message is to long'

    def test_mcraw_no_bit_data(self, proto):
        """Test MCRAW with missing bit data."""
        rc, msg = proto.mcraw(
            name='some_name',
            bit_data=None,
            protocol_id=9989,
            mcbitnum=24
        )
        assert rc == -1
        assert msg == 'no bitData provided'

    def test_mcraw_no_protocol_id(self, proto):
        """Test MCRAW with missing protocol ID."""
        rc, msg = proto.mcraw(
            name='some_name',
            bit_data='001010101010010010100111',
            protocol_id=None,
            mcbitnum=24
        )
        assert rc == -1
        assert msg == 'no protocolId provided'


class TestLengthInRange:
    """Test message length range validation."""

    def test_length_in_range_inside_range(self, proto):
        """Test length_in_range with valid message lengths."""
        # Protocol 9990 has length_min=2, length_max=8 (from conftest.py)
        for length in range(2, 9):
            rc, msg = proto.length_in_range(protocol_id='9990', message_length=length)
            assert rc == 1, f"Failed for length {length}"
            assert msg == '', f"Expected empty message for length {length}"

    def test_length_in_range_too_short(self, proto):
        """Test length_in_range with message that is too short."""
        # Protocol 9990 has length_min=2
        for length in (-1, 0, 1):
            rc, msg = proto.length_in_range(protocol_id='9990', message_length=length)
            assert rc == 0, f"Failed for length {length}"
            assert msg == 'message is to short', f"Expected error message for length {length}"

    def test_length_in_range_too_long(self, proto):
        """Test length_in_range with message that is too long."""
        # Protocol 9990 has length_max=8
        rc, msg = proto.length_in_range(protocol_id='9990', message_length=9)
        assert rc == 0
        assert msg == 'message is to long'

    def test_length_in_range_protocol_not_exists(self, proto):
        """Test length_in_range with non-existent protocol."""
        rc, msg = proto.length_in_range(protocol_id='556565', message_length=5)
        assert rc == 0
        assert msg == 'protocol does not exists'

    def test_length_in_range_boundary_min(self, proto):
        """Test length_in_range at minimum boundary."""
        # Protocol 9990 has length_min=2
        rc, msg = proto.length_in_range(protocol_id='9990', message_length=2)
        assert rc == 1
        assert msg == ''

    def test_length_in_range_boundary_max(self, proto):
        """Test length_in_range at maximum boundary."""
        # Protocol 9990 has length_max=8
        rc, msg = proto.length_in_range(protocol_id='9990', message_length=8)
        assert rc == 1
        assert msg == ''
