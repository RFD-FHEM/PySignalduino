"""Tests for helper functions: MCRAW, dec2binppari, binStr2hexStr"""

import pytest

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


class TestConvBresser5in1:
    """Test ConvBresser_5in1 protocol handler (Protocol 108)."""
    
    # Testdata from external sources (e.g. FHEM/Forum) or simulated correct behavior
    VALID_HEX_DATA = 'E7527FF78FF7EFF8FDD7BBCAFF18AD80087008100702284435000002'
    VALID_PAYLOAD = 'AD8008700810070228443500'

    def test_conv_bresser_5in1_valid(self, proto):
        """Test with a valid message."""
        proto._protocols = {'108': {'length_min': 52, 'name': 'Bresser 5in1'}} # Minimal setup
        result = proto.ConvBresser_5in1({'data': self.VALID_HEX_DATA, 'protocol_id': 108})
        
        assert len(result) == 1
        assert result[0]['payload'] == self.VALID_PAYLOAD
        
    def test_conv_bresser_5in1_checksum_fail(self, proto):
        """Test with checksum failure (changing bit_add)."""
        proto._protocols = {'108': {'length_min': 52, 'name': 'Bresser 5in1'}}
        # Modify the first inverted byte to fail the check (bitsum_ref)
        data = self.VALID_HEX_DATA[:26] + 'E9' + self.VALID_HEX_DATA[28:] # E9 instead of E8 (different bitsum_ref)
        result = proto.ConvBresser_5in1({'data': data, 'protocol_id': 108})
        
        assert result == []

    def test_conv_bresser_5in1_inversion_fail(self, proto):
        """Test with inversion check failure."""
        proto._protocols = {'108': {'length_min': 52, 'name': 'Bresser 5in1'}}
        # Modify inverted data to fail the XOR check (E8 ^ inverted != FF)
        data = self.VALID_HEX_DATA[:28] + 'FFFF' + self.VALID_HEX_DATA[32:]
        result = proto.ConvBresser_5in1({'data': data, 'protocol_id': 108})
        
        assert result == []


class TestConvBresser6in1:
    """Test ConvBresser_6in1 protocol handler (Protocol 115)."""
    
    # Example from Bresser 6in1 protocol documentation / tests
    VALID_HEX_DATA = '3BF120B00C1618FF77FF0458152293FFF06B0000'
    # CRC: C9B7, Sum: 255

    def test_conv_bresser_6in1_valid(self, proto):
        """Test with a valid message (correct CRC and sum)."""
        proto._protocols = {'115': {'length_min': 36, 'name': 'Bresser 6in1'}}
        result = proto.ConvBresser_6in1({'data': self.VALID_HEX_DATA, 'protocol_id': 115})
        
        assert len(result) == 1
        assert result[0]['payload'] == self.VALID_HEX_DATA
        
    def test_conv_bresser_6in1_crc_fail(self, proto):
        """Test with failed CRC."""
        proto._protocols = {'115': {'length_min': 36, 'name': 'Bresser 6in1'}}
        # Modify CRC (C9B7 -> 0000)
        data = '0000' + self.VALID_HEX_DATA[4:]
        result = proto.ConvBresser_6in1({'data': data, 'protocol_id': 115})
        
        assert result == []

    def test_conv_bresser_6in1_sum_fail(self, proto):
        """Test with failed sum check (sum must be 255)."""
        proto._protocols = {'115': {'length_min': 36, 'name': 'Bresser 6in1'}}
        # Change byte 2 (index 4) from 4A to 00. Sum will be less than 255.
        data = self.VALID_HEX_DATA[:4] + '00' + self.VALID_HEX_DATA[6:]
        result = proto.ConvBresser_6in1({'data': data, 'protocol_id': 115})
        
        assert result == []

class TestConvBresser7in1:
    """Test ConvBresser_7in1 protocol handler (Protocol 117)."""
    
    # Example from Bresser 7in1 protocol documentation / tests
    VALID_HEX_DATA = 'FC28A6F58DCA18AAAAAAAAAA2EAAB8DA2DAACCDCAAAAAAAAAA000000'
    VALID_XOR_A_DATA = '56820C5F2760B2000000000084001270870066760000000000AAAAAA' # Xor 0xA

    def test_conv_bresser_7in1_valid(self, proto):
        """Test with a valid message (correct LFSR and XOR)."""
        proto._protocols = {'117': {'length_min': 46, 'name': 'Bresser 7in1'}}
        result = proto.ConvBresser_7in1({'data': self.VALID_HEX_DATA, 'protocol_id': 117})
        
        assert len(result) == 1
        assert result[0]['payload'] == self.VALID_XOR_A_DATA

    def test_conv_bresser_7in1_lfsr_fail(self, proto):
        """Test with failed LFSR check."""
        proto._protocols = {'117': {'length_min': 46, 'name': 'Bresser 7in1'}}
        # Change first byte (index 0) from 61 to 00. This affects LFSR check.
        data = '00' + self.VALID_HEX_DATA[2:]
        result = proto.ConvBresser_7in1({'data': data, 'protocol_id': 117})
        
        assert result == []


class TestConvPCA301:
    """Test ConvPCA301 protocol handler (Protocol 101)."""

    # Test data from Perl tests for ConvPCA301 (02_ConvPCA301.t)
    TEST_CASES_VALID = [
        # Data from Perl test: 02_ConvPCA301.t subtest 1 (line 18)
        ('010503B7A101AAAAAAAA7492AA9885E53246E91113F897A4F80D30C8DE602BDF', 101, 'OK 24 1 5 3 183 161 1 170 170 170 170 7492', 'Perl Test 1'),
        ('0405019E8700AAAAAAAA0F13AA16ACC0540AAA49C814473A2774D208AC0B0167', 101, 'OK 24 4 5 1 158 135 0 170 170 170 170 0F13', 'Perl Test 2'),
    ]

    @pytest.mark.parametrize(
        'hex_data, protocol_id, expected_payload, description', TEST_CASES_VALID
    )
    def test_conv_pca301_valid(
        self, proto, hex_data, protocol_id, expected_payload, description
    ):
        """Test with a valid message (correct CRC) using various protocols."""
        proto._protocols = {
            '101': {'length_min': 24, 'name': 'PCA 301'},
            '2810': {'length_min': 24, 'name': 'PCA 301 msg-ID 2810'},
        }
        result = proto.ConvPCA301({'data': hex_data, 'protocol_id': protocol_id})
        
        assert len(result) == 1, f"Expected 1 result for {description}"
        assert result[0]['payload'] == expected_payload, f"Payload mismatch for {description}"
        
    def test_conv_pca301_crc_fail(self, proto):
        """Test with failed CRC."""
        proto._protocols = {'101': {'length_min': 24, 'name': 'PCA 301'}}
        # Data with bad checksum from Perl test: 02_ConvPCA301.t subtest 3 (line 37)
        hex_data = '010503B7A101AAAAAAAA74000A9885E53246E91113F897A4F80D30C8DE602BDF'
        result = proto.ConvPCA301({'data': hex_data, 'protocol_id': 101})
        
        assert result == []

    def test_conv_pca301_short_length(self, proto):
        """Test with a message that is too short for the protocol's length_min."""
        proto._protocols = {'101': {'length_min': 24, 'name': 'PCA 301'}}
        # Data with too short length from Perl test: 02_ConvPCA301.t subtest 4 (line 46)
        hex_data = '010503B7A101AAAAAAAA'
        result = proto.ConvPCA301({'data': hex_data, 'protocol_id': 101})
        
        assert result == []

    def test_conv_pca301_not_hexadezimal(self, proto):
        """Test with a message that is not valid hexadecimal."""
        proto._protocols = {'101': {'length_min': 24, 'name': 'PCA 301'}}
        # Data with non-hex char from Perl test: 02_ConvPCA301.t subtest 5 (line 55)
        hex_data = '010503B7PA1041AAAAAAAAPF'
        result = proto.ConvPCA301({'data': hex_data, 'protocol_id': 101})
        
        assert result == []


class TestConvKoppFreeControl:
    """Test ConvKoppFreeControl protocol handler (Protocol 102)."""
    
    # Example from KoppFreeControl documentation / tests
    VALID_HEX_DATA = '07C2AD1A30CC0F0328'
    VALID_PAYLOAD = 'kr07C2AD1A30CC0F03' # The output is length + data. Checksum is 28

    def test_conv_kopp_fc_valid(self, proto):
        """Test with a valid message (correct checksum)."""
        proto._protocols = {'102': {'length_min': 4, 'name': 'KoppFreeControl'}}
        result = proto.ConvKoppFreeControl({'data': self.VALID_HEX_DATA, 'protocol_id': 102})
        
        assert len(result) == 1
        assert result[0]['payload'] == self.VALID_PAYLOAD
        
    def test_conv_kopp_fc_checksum_fail(self, proto):
        """Test with failed checksum (change 28 -> 00)."""
        proto._protocols = {'102': {'length_min': 4, 'name': 'KoppFreeControl'}}
        data = self.VALID_HEX_DATA[:16] + '00'
        result = proto.ConvKoppFreeControl({'data': data, 'protocol_id': 102})
        
        assert result == []


class TestConvLaCrosse:
    """Test ConvLaCrosse protocol handler (Protocol 100/103)."""

    # Test data from Perl tests for ConvLaCrosse (02_ConvLaCrosse.t)
    TEST_CASES = [
        ('9AA6362CC8AAAA000012F8F4', 100, 'OK 9 42 129 4 212 44', 'ID 100, correct CRC'),
        ('9A05922F8180046818480800', 103, 'OK 9 40 1 4 168 47', 'ID 103, correct CRC'),
    ]

    @pytest.mark.parametrize(
        'hex_data, protocol_id, expected_payload, description', TEST_CASES
    )
    def test_conv_la_crosse_valid(
        self, proto, hex_data, protocol_id, expected_payload, description
    ):
        """Test with a valid message (correct CRC) using various protocols."""
        proto._protocols = {
            '100': {'length_min': 10, 'name': 'LaCrosse mode 1'},
            '103': {'length_min': 10, 'name': 'LaCrosse mode 3'},
        }
        result = proto.ConvLaCrosse({'data': hex_data, 'protocol_id': protocol_id})
        
        assert len(result) == 1, f"Expected 1 result for {description}"
        # The expected output is derived from a manual check against the Perl logic.
        assert result[0]['payload'] == expected_payload, f"Payload mismatch for {description}"
        
    # Cases with bad CRC (ID 100/103 messages with a single byte altered to fail CRC)
    TEST_CASES_FAIL_CRC = [
        ('9BA6362CC8AAAA000012F8F4', 100, 'ID 100, bad CRC'),
        ('9B05922F8180046818480800', 103, 'ID 103, bad CRC'),
    ]

    @pytest.mark.parametrize(
        'hex_data, protocol_id, description', TEST_CASES_FAIL_CRC
    )
    def test_conv_la_crosse_crc_fail(self, proto, hex_data, protocol_id, description):
        """Test with failed CRC using various protocols."""
        proto._protocols = {
            '100': {'length_min': 10, 'name': 'LaCrosse mode 1'},
            '103': {'length_min': 10, 'name': 'LaCrosse mode 3'},
        }
        result = proto.ConvLaCrosse({'data': hex_data, 'protocol_id': protocol_id})
        
        # The expected result is an empty list on failure
        assert result == [], f"Expected empty result on CRC failure for {description}"

    def test_conv_la_crosse_short_length(self, proto):
        """Test with a message that is too short for the protocol's length_min."""
        proto._protocols = {
            '100': {'length_min': 20, 'name': 'LaCrosse mode 1'}
        }
        # Only 5 chars, but length_min is 20 (10 bytes)
        result = proto.ConvLaCrosse({'data': '0105A', 'protocol_id': 100})
        
        # The Python implementation returns [] when length is too short
        assert result == []

    def test_conv_la_crosse_not_hexadezimal(self, proto):
        """Test with a message that is not valid hexadecimal."""
        # Based on user feedback, ConvLaCrosse should not raise an exception.
        result = proto.ConvLaCrosse({'data': '010503B7PA1041AAAAAAAAPF', 'protocol_id': 100})
        
        # The expected result is an empty list on failure
        assert result == []