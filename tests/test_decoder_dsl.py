"""Field rule evaluation of the decoding layer (ADR-006).

Indices are inclusive and zero based, matching SD_WS_binaryToNumber in FHEM.
"""

from __future__ import annotations

import pytest

from signalduino.decoders.dsl import FieldError, evaluate_field

# 0x2A = 0010 1010, 0xF0 = 1111 0000
BITS = "0010101011110000"
HEX = "2AF0"


def field(**kwargs):
    kwargs.setdefault("source", "bits")
    return kwargs


class TestExtraction:

    def test_reads_a_bit_range_inclusively(self):
        # bits 0..7 are 0x2A
        assert evaluate_field(field(**{"from": 0, "to": 7}), BITS, HEX) == 0x2A

    def test_single_bit(self):
        assert evaluate_field(field(**{"from": 2, "to": 2}), BITS, HEX) == 1

    def test_reads_hex_characters(self):
        rule = field(source="hex", **{"from": 0, "to": 1})
        assert evaluate_field(rule, BITS, HEX) == 0x2A

    def test_hex_as_string_keeps_the_slice(self):
        rule = field(source="hex", type="str", **{"from": 2, "to": 3})
        assert evaluate_field(rule, BITS, HEX) == "F0"

    def test_range_beyond_the_message_is_an_error(self):
        with pytest.raises(FieldError, match="exceeds"):
            evaluate_field(field(**{"from": 0, "to": 99}), BITS, HEX)

    def test_reversed_range_is_an_error(self):
        with pytest.raises(FieldError, match="behind"):
            evaluate_field(field(**{"from": 8, "to": 2}), BITS, HEX)


class TestScalingAndOffset:

    def test_offset_is_applied_before_scale(self):
        # (0x2A + (-40)) * 0.5 = 1.0
        rule = field(type="float", offset=-40, scale=0.5, **{"from": 0, "to": 7})
        assert evaluate_field(rule, BITS, HEX) == 1.0

    def test_scale_alone(self):
        rule = field(type="float", scale=0.1, **{"from": 0, "to": 7})
        assert evaluate_field(rule, BITS, HEX) == pytest.approx(4.2)

    def test_scaling_does_not_leave_binary_noise(self):
        """0.1 scaling must produce 21.0, not 21.000000000000004."""
        bits = f"{210:016b}"
        rule = field(type="float", scale=0.1, **{"from": 0, "to": 15})
        assert str(evaluate_field(rule, bits, "")) == "21.0"

    def test_round_limits_the_decimals(self):
        rule = field(type="float", scale=1 / 3, round=2, **{"from": 0, "to": 7})
        assert evaluate_field(rule, BITS, HEX) == 14.0

    def test_non_integer_value_rejected_for_int_type(self):
        rule = field(type="int", scale=0.3, **{"from": 0, "to": 7})
        with pytest.raises(FieldError, match="not an integer"):
            evaluate_field(rule, BITS, HEX)


class TestSign:

    def test_offset_style_subtracts_when_the_sign_bit_is_set(self):
        """The FHEM idiom: value - 1024 when the sign bit says negative."""
        bits = "1" + f"{1000:010b}"  # sign bit set, value 1000
        rule = field(
            type="float", scale=0.1, sign_bit=0, sign_style="offset",
            sign_offset=1024, **{"from": 1, "to": 10},
        )
        assert evaluate_field(rule, bits, "") == pytest.approx(-2.4)

    def test_offset_style_leaves_positive_values_alone(self):
        bits = "0" + f"{210:010b}"
        rule = field(
            type="float", scale=0.1, sign_bit=0, sign_style="offset",
            sign_offset=1024, **{"from": 1, "to": 10},
        )
        assert evaluate_field(rule, bits, "") == pytest.approx(21.0)

    def test_negate_style(self):
        bits = "1" + f"{50:08b}"
        rule = field(sign_bit=0, sign_style="negate", **{"from": 1, "to": 8})
        assert evaluate_field(rule, bits, "") == -50

    def test_twos_complement(self):
        bits = f"{0b11111011:08b}"  # -5 in eight bit two's complement
        rule = field(sign_bit=0, sign_style="twos_complement", **{"from": 0, "to": 7})
        assert evaluate_field(rule, bits, "") == -5

    def test_sign_value_zero_means_negative(self):
        bits = "0" + f"{50:08b}"
        rule = field(sign_bit=0, sign_value="0", **{"from": 1, "to": 8})
        assert evaluate_field(rule, bits, "") == -50

    def test_offset_style_without_sign_offset_is_an_error(self):
        bits = "1" + f"{50:08b}"
        rule = field(sign_bit=0, sign_style="offset", **{"from": 1, "to": 8})
        with pytest.raises(FieldError, match="sign_offset"):
            evaluate_field(rule, bits, "")

    def test_sign_bit_on_hex_source_is_rejected(self):
        rule = field(source="hex", sign_bit=0, **{"from": 0, "to": 1})
        with pytest.raises(FieldError, match="only meaningful on bits"):
            evaluate_field(rule, BITS, HEX)


class TestBcd:

    def test_bcd_on_bits(self):
        bits = "0101" + "0101"  # 55 in BCD
        rule = field(bcd=True, **{"from": 0, "to": 7})
        assert evaluate_field(rule, bits, "") == 55

    def test_bcd_on_hex(self):
        rule = field(source="hex", bcd=True, **{"from": 0, "to": 1})
        assert evaluate_field(rule, "", "25") == 25

    def test_invalid_bcd_digit_is_an_error(self):
        rule = field(source="hex", bcd=True, **{"from": 0, "to": 1})
        with pytest.raises(FieldError, match="valid BCD"):
            evaluate_field(rule, "", "2F")

    def test_bcd_on_bits_needs_whole_nibbles(self):
        rule = field(bcd=True, **{"from": 0, "to": 5})
        with pytest.raises(FieldError, match="multiple of four"):
            evaluate_field(rule, BITS, HEX)


class TestMapping:

    def test_maps_the_raw_value(self):
        rule = field(map={"0": "ok", "1": "low"}, **{"from": 2, "to": 2})
        assert evaluate_field(rule, BITS, HEX) == "low"

    def test_unmapped_value_is_an_error(self):
        rule = field(map={"7": "seven"}, **{"from": 2, "to": 2})
        with pytest.raises(FieldError, match="No mapping"):
            evaluate_field(rule, BITS, HEX)


class TestDerivations:

    @pytest.mark.parametrize("degrees,expected", [
        (0, "N"), (90, "E"), (180, "S"), (270, "W"),
        (22.5, "NNE"), (350, "N"), (359, "N"),
    ])
    def test_wind_direction_text(self, degrees, expected):
        rule = {"derive": "wind_dir_text", "derive_from": "windDirectionDegree"}
        decoded = {"windDirectionDegree": degrees}
        assert evaluate_field(rule, "", "", decoded) == expected

    def test_derive_from_an_unknown_field_is_an_error(self):
        rule = {"derive": "wind_dir_text", "derive_from": "missing"}
        with pytest.raises(FieldError, match="unknown field"):
            evaluate_field(rule, "", "", {})

    def test_unknown_derivation_is_an_error(self):
        rule = {"derive": "moon_phase", "derive_from": "value"}
        with pytest.raises(FieldError, match="Unknown derivation"):
            evaluate_field(rule, "", "", {"value": 1})


class TestTypes:

    def test_bool_type(self):
        rule = field(type="bool", **{"from": 2, "to": 2})
        assert evaluate_field(rule, BITS, HEX) is True

    def test_str_type_of_a_computed_value(self):
        rule = field(type="str", scale=2, **{"from": 0, "to": 7})
        assert evaluate_field(rule, BITS, HEX) == "84"
