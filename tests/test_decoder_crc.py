"""Checksum algorithms of the decoding layer (ADR-006)."""

from __future__ import annotations

import pytest

from signalduino.decoders import crc


class TestCrc8:
    """CRC-8, the most common check across the SD_WS protocols."""

    def test_nrsc5_check_value(self):
        """CRC-8/NRSC-5: poly 0x31, init 0xFF - catalogue check value 0xF7."""
        assert crc.crc8(b"123456789", poly=0x31, init=0xFF) == 0xF7

    def test_maxim_check_value(self):
        """CRC-8/MAXIM: poly 0x31 reflected in and out - catalogue check value 0xA1."""
        assert crc.crc8(
            b"123456789", poly=0x31, init=0x00, reflect_in=True, reflect_out=True
        ) == 0xA1

    def test_default_parameters_match_the_sensor_variant(self):
        """The default (poly 0x31, init 0, unreflected) is what the sensors use."""
        assert crc.crc8(b"123456789") == 0xA2

    def test_matches_the_existing_helper_implementation(self):
        """Same result as the hand rolled loop in helpers.py ConvLaCrosse."""
        data = bytes.fromhex("9E1A1837")
        expected = 0x00
        for byte in data:
            expected ^= byte
            for _ in range(8):
                expected = ((expected << 1) ^ 0x31) & 0xFF if expected & 0x80 else (expected << 1) & 0xFF
        assert crc.crc8(data) == expected

    def test_empty_data_returns_init(self):
        assert crc.crc8(b"", init=0x2A) == 0x2A

    def test_xor_out_is_applied(self):
        plain = crc.crc8(b"\x01\x02")
        assert crc.crc8(b"\x01\x02", xor_out=0xFF) == plain ^ 0xFF

    def test_reflection_changes_the_result(self):
        data = bytes.fromhex("0123")
        assert crc.crc8(data, reflect_in=True) != crc.crc8(data)


class TestSumAndXor:

    def test_sum8_truncates_to_one_byte(self):
        assert crc.sum8(bytes([0xFF, 0x02])) == 0x01

    def test_sum8_honours_init(self):
        assert crc.sum8(b"\x10", init=0x05) == 0x15

    def test_xor8_of_a_value_with_itself_is_zero(self):
        assert crc.xor8(bytes([0xA5, 0xA5])) == 0x00

    def test_xor8_single_byte(self):
        assert crc.xor8(b"\x5A") == 0x5A


class TestLfsrDigest:

    def test_digest_is_deterministic(self):
        data = bytes.fromhex("AABBCC")
        assert crc.lfsr_digest8(data) == crc.lfsr_digest8(data)

    def test_zero_data_gives_zero(self):
        assert crc.lfsr_digest8(b"\x00\x00") == 0

    def test_reflect_variant_differs_from_plain(self):
        data = bytes.fromhex("A1B2C3")
        assert crc.lfsr_digest8(data) != crc.lfsr_digest8_reflect(data)

    def test_key_changes_the_digest(self):
        data = bytes.fromhex("A1B2")
        assert crc.lfsr_digest8(data, key=0xF4) != crc.lfsr_digest8(data, key=0x31)


class TestCrc16:

    def test_ccitt_false_check_value(self):
        """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF - check value 0x29B1."""
        assert crc.crc16(b"123456789", poly=0x1021, init=0xFFFF) == 0x29B1

    def test_arc_check_value(self):
        """CRC-16/ARC: poly 0x8005, init 0, reflected - check value 0xBB3D."""
        assert crc.crc16(
            b"123456789", poly=0x8005, init=0x0000, reflect_in=True, reflect_out=True
        ) == 0xBB3D

    def test_lsb_variant_is_deterministic(self):
        data = bytes.fromhex("DEADBEEF")
        assert crc.crc16lsb(data) == crc.crc16lsb(data)

    def test_result_stays_within_16_bits(self):
        assert 0 <= crc.crc16lsb(bytes(range(16))) <= 0xFFFF


class TestCompute:

    def test_dispatches_by_name(self):
        assert crc.compute("crc8", b"123456789", poly=0x31) == crc.crc8(b"123456789")

    def test_passes_parameters_through(self):
        assert crc.compute("sum8", b"\x10", init=0x05) == 0x15

    def test_unknown_algorithm_names_the_known_ones(self):
        with pytest.raises(KeyError) as excinfo:
            crc.compute("md5", b"")
        assert "crc8" in str(excinfo.value)

    def test_every_algorithm_is_callable(self):
        for name in crc.ALGORITHMS:
            assert isinstance(crc.compute(name, b"\x01\x02"), int)
