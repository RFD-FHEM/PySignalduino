import pytest
from sd_protocols.postdemodulation import PostdemodulationMixin


class TestPostdemodulation(PostdemodulationMixin):
    """Test cases for post-demodulation methods."""

    def _logging(self, msg, level):
        """Mock logging method for testing."""
        pass

    def bin_str_2_hex_str(self, bin_str):
        """Mock bin_str_2_hex_str method for testing."""
        # Convert binary string to hex
        hex_str = ""
        for i in range(0, len(bin_str), 4):
            nibble = bin_str[i:i+4]
            if len(nibble) < 4:
                nibble = nibble.ljust(4, '0')
            hex_str += hex(int(nibble, 2))[2:].upper()
        return hex_str


class TestPostDemoEM:
    """Test cases for postDemo_EM method."""

    def test_crc_ok(self):
        """Test CRC OK case."""
        pd = TestPostdemodulation()
        # Test data from GitHub: MU;P1=-417;P2=385;P3=-815;P4=-12058;D=42121212121212121212121212121212121232321212121212121232321212121212121232323212323212321232121212321212123232121212321212121232323212121212121232121212121212121232323212121212123232321232121212121232123232323212321;CP=2;R=87;
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 0, 1, 0]

        result = pd.postDemo_EM("test", bits)
        assert result[0] == 1
        expected_bits = [0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 1, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 1, 0, 1]
        assert result[1] == expected_bits

    def test_crc_error(self):
        """Test CRC ERROR case."""
        pd = TestPostdemodulation()
        # Modified test data to cause CRC error
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 0]

        result = pd.postDemo_EM("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_length_not_correct(self):
        """Test length not correct case."""
        pd = TestPostdemodulation()
        # Test data with wrong length
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0]

        result = pd.postDemo_EM("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_start_not_found(self):
        """Test start not found case."""
        pd = TestPostdemodulation()
        # Test data without preamble
        bits = [0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 0, 1, 0]

        result = pd.postDemo_EM("test", bits)
        assert result[0] == 0
        assert result[1] is None


class TestPostDemoRevolt:
    """Test cases for postDemo_Revolt method."""

    def test_crc_ok(self):
        """Test CRC OK case."""
        pd = TestPostdemodulation()
        # Test data from GitHub
        bits = [0, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1]

        result = pd.postDemo_Revolt("test", bits)
        assert result[0] == 1
        expected_bits = [0, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 1]
        assert result[1] == expected_bits

    def test_crc_error(self):
        """Test CRC ERROR case."""
        pd = TestPostdemodulation()
        # Modified test data to cause CRC error
        bits = [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1]

        result = pd.postDemo_Revolt("test", bits)
        assert result[0] == 0
        assert result[1] is None


class TestPostDemoFS20:
    """Test cases for postDemo_FS20 method."""

    def test_good_message(self):
        """Test good message case."""
        pd = TestPostdemodulation()
        # Test data from GitHub
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 0, 1]

        result = pd.postDemo_FS20("test", bits)
        assert result[0] == 1
        expected_bits = [0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0]
        assert result[1] == expected_bits

    def test_bad_message_all_zeros(self):
        """Test bad message, all bits are zeros."""
        pd = TestPostdemodulation()
        bits = [0] * 58

        result = pd.postDemo_FS20("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_detection_aborted(self):
        """Test bad message, detection aborted."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 1]

        result = pd.postDemo_FS20("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_wrong_length(self):
        """Test bad message, wrong length."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

        result = pd.postDemo_FS20("test", bits)
        assert result[0] == 0
        assert result[1] is None


class TestPostDemoFHT80:
    """Test cases for postDemo_FHT80 method."""

    def test_good_message(self):
        """Test good message case."""
        pd = TestPostdemodulation()
        # Test data from GitHub
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 0, 1, 0, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 1, 1, 1, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1]

        result = pd.postDemo_FHT80("test", bits)
        assert result[0] == 1
        expected_bits = [0, 0, 0, 1, 0, 1, 1, 0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0]
        assert result[1] == expected_bits

    def test_bad_message_all_zeros(self):
        """Test bad message, all bits are zeros."""
        pd = TestPostdemodulation()
        bits = [0] * 66

        result = pd.postDemo_FHT80("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_wrong_length(self):
        """Test bad message, wrong length."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 0, 1, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]

        result = pd.postDemo_FHT80("test", bits)
        assert result[0] == 0
        assert result[1] is None


class TestPostDemoFHT80TF:
    """Test cases for postDemo_FHT80TF method."""

    def test_good_message(self):
        """Test good message case."""
        pd = TestPostdemodulation()
        # Test data from GitHub
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 0]
        rcode, result = pd.postDemo_FHT80TF("test", bits)
        assert rcode == 1
        expected_bits = [1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1]
        assert result == expected_bits

    def test_bad_message_wrong_length(self):
        """Test bad message, wrong length."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 0]

        rcode, result = pd.postDemo_FHT80TF("test", bits)
        assert rcode == 0
        assert result is None

    def test_bad_message_all_zeros(self):
        """Test bad message, all bits are zeros."""
        pd = TestPostdemodulation()
        bits = [0] * 57

        rcode, result = pd.postDemo_FHT80TF("test", bits)
        assert rcode == 0
        assert result is None


class TestPostDemoWS2000:
    """Test cases for postDemo_WS2000 method."""

    def test_good_message(self):
        """Test good message case."""
        pd = TestPostdemodulation()
        # Test data from GitHub
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 1, 1]
        rcode, result = pd.postDemo_WS2000("test", bits)
        assert rcode == 1

        expected_bits = [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        assert result == expected_bits

    def test_bad_message_all_zeros(self):
        """Test bad message, all bits are zeros."""
        pd = TestPostdemodulation()
        bits = [0] * 59

        result = pd.postDemo_WS2000("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_every_5th_bit(self):
        """Test bad message, every 5th bit fails."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0]

        result = pd.postDemo_WS2000("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_preamble_long(self):
        """Test bad message, preamble too long."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 1, 1]

        result = pd.postDemo_WS2000("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_type_big(self):
        """Test bad message, type is too big."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0]

        result = pd.postDemo_WS2000("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_length_mismatch(self):
        """Test bad message, length mismatch."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1]

        result = pd.postDemo_WS2000("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_xor_mismatch(self):
        """Test bad message, xor mismatch."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0]

        result = pd.postDemo_WS2000("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_sum_mismatch(self):
        """Test bad message, sum mismatch."""
        pd = TestPostdemodulation()
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1]

        result = pd.postDemo_WS2000("test", bits)
        assert result[0] == 0
        assert result[1] is None


class TestPostDemoWS7035:
    """Test cases for postDemo_WS7035 method."""

    def test_good_message(self):
        """Test good message case."""
        pd = TestPostdemodulation()
        # Test data from GitHub, modified for even parity and correct checksum
        bits = [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0]
                
        result = pd.postDemo_WS7035("test", bits)
        assert result[0] == 1
        expected_bits = [int(b) for b in '1010000010000100011100110010011100111100']
        assert result[1] == expected_bits

    def test_bad_message_ident_not_10100000(self):
        """Test bad message, ident not 1010 0000."""
        pd = TestPostdemodulation()
        bits = [1, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0]
        result = pd.postDemo_WS7035("test", bits)
        assert result[0] == 0
        assert result[1] == None

    def test_bad_message_parity_not_even(self):
        """Test bad message, parity not even."""
        pd = TestPostdemodulation()
        bits = [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0]
                
        result = pd.postDemo_WS7035("test", bits)
        assert result[0] == 0
        assert result[1] == None

    def test_bad_message_wrong_checksum(self):
        """Test bad message, wrong checksum."""
        pd = TestPostdemodulation()
        bits = [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 0]

        result = pd.postDemo_WS7035("test", bits)
        assert result[0] == 0
        assert result[1] == None


class TestPostDemoWS7053: 
    """Test cases for postDemo_WS7053 method."""

    def test_good_message(self):
        """Test good message case."""
        pd = TestPostdemodulation()
        # Test data from GitHub
        bits = [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0]

        result = pd.postDemo_WS7053("test", bits)
        assert result[0] == 1
        expected_bits = [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0, 1, 1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0]
                         
        assert result[1] == expected_bits

    def test_bad_message_ident_not_found(self):
        """Test bad message, ident not found."""
        pd = TestPostdemodulation()
        bits = [1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
                
        result = pd.postDemo_WS7053("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_length_too_short(self):
        """Test bad message, length too short."""
        pd = TestPostdemodulation()
        bits = [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
                
        result = pd.postDemo_WS7053("test", bits)
        assert result[0] == 0
        assert result[1] is None

    def test_bad_message_parity_not_even(self):
        """Test bad message, parity not even."""
        pd = TestPostdemodulation()
        bits = [1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]

        result = pd.postDemo_WS7053("test", bits)
        assert result[0] == 0
        assert result[1] is None


class TestPostDemoLengtnPrefix:
    """Test cases for postDemo_lengtnPrefix method."""

    def test_x10_transmission(self):
        """Test X10 transmission case."""
        pd = TestPostdemodulation()
        # Test data from GitHub
        bits = [0, 1, 0, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 0, 1, 1, 1, 0]

        result = pd.postDemo_lengtnPrefix("test", bits)
        assert result[0] == 1
        expected_bits = [0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 0, 1, 1, 1, 0]

        assert result[1] == expected_bits
