"""Specification loading and decoder lookup (ADR-006)."""

from __future__ import annotations

import json

import pytest

from signalduino.decoders import spec as spec_module
from signalduino.decoders.registry import DecoderRegistry, register_decoder, registered_custom
from signalduino.decoders.spec import SpecError

MINIMAL_SPEC = {
    "protocol_id": "999",
    "model": "TEST_999",
    "fields": {"id": {"source": "hex", "from": 0, "to": 1, "type": "str"}},
}


def write_spec(directory, name, document):
    path = directory / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class TestSpecValidation:

    def test_minimal_specification_is_accepted(self):
        result = spec_module.from_dict(MINIMAL_SPEC, "test")
        assert result.protocol_id == "999"
        assert result.model == "TEST_999"

    def test_missing_required_property_names_it(self):
        broken = {k: v for k, v in MINIMAL_SPEC.items() if k != "model"}
        with pytest.raises(SpecError, match="model"):
            spec_module.from_dict(broken, "broken")

    def test_unknown_property_is_rejected(self):
        broken = dict(MINIMAL_SPEC, colour="blue")
        with pytest.raises(SpecError):
            spec_module.from_dict(broken, "broken")

    def test_error_names_the_failing_path(self):
        broken = json.loads(json.dumps(MINIMAL_SPEC))
        broken["fields"]["id"]["source"] = "runes"
        with pytest.raises(SpecError, match="fields/id/source"):
            spec_module.from_dict(broken, "broken")

    def test_unknown_checksum_algorithm_is_rejected(self):
        broken = dict(
            MINIMAL_SPEC,
            crc={"algorithm": "md5", "data": {"from": 0, "to": 1}, "check": {"from": 2, "to": 3}},
        )
        with pytest.raises(SpecError):
            spec_module.from_dict(broken, "broken")

    def test_variants_without_a_selector_are_rejected(self):
        """Otherwise the variants would silently never be reached."""
        broken = dict(MINIMAL_SPEC, variants={
            "1": {"fields": {"temperature": {"source": "bits", "from": 0, "to": 7}}}
        })
        with pytest.raises(SpecError, match="variant_selector"):
            spec_module.from_dict(broken, "broken")

    def test_invalid_json_is_reported_with_the_file_name(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(SpecError, match="broken.json"):
            spec_module.load_file(path)


class TestVariantMerging:

    @pytest.fixture
    def spec(self):
        document = dict(
            MINIMAL_SPEC,
            variant_selector={"source": "hex", "from": 0, "to": 1},
            variants={
                "48": {
                    "model": "TEST_999_TH",
                    "fields": {"temperature": {"source": "bits", "from": 0, "to": 7}},
                    "limits": {"temperature": [-40, 60]},
                }
            },
            limits={"id": [0, 255]},
        )
        return spec_module.from_dict(document, "test")

    def test_common_fields_are_kept(self, spec):
        assert "id" in spec.fields_for("48")

    def test_variant_fields_are_added(self, spec):
        assert "temperature" in spec.fields_for("48")

    def test_without_a_variant_only_common_fields_remain(self, spec):
        assert set(spec.fields_for(None)) == {"id"}

    def test_limits_are_merged(self, spec):
        merged = spec.limits_for("48")
        assert merged["id"] == [0, 255]
        assert merged["temperature"] == [-40, 60]

    def test_unknown_variant_adds_nothing(self, spec):
        assert set(spec.fields_for("99")) == {"id"}


class TestRegistryLoading:

    def test_loads_specifications_from_a_directory(self, tmp_path):
        write_spec(tmp_path, "test_999.json", MINIMAL_SPEC)
        registry = DecoderRegistry(specs_dir=tmp_path)
        assert "999" in registry.specs
        assert registry.get("999") is not None

    def test_missing_directory_is_not_an_error(self, tmp_path):
        registry = DecoderRegistry(specs_dir=tmp_path / "absent")
        assert registry.specs == {}
        assert registry.errors == []

    def test_unknown_protocol_returns_none(self, tmp_path):
        registry = DecoderRegistry(specs_dir=tmp_path)
        assert registry.get("4711") is None

    def test_a_broken_specification_does_not_hide_the_others(self, tmp_path):
        write_spec(tmp_path, "good.json", MINIMAL_SPEC)
        (tmp_path / "bad.json").write_text("{", encoding="utf-8")
        registry = DecoderRegistry(specs_dir=tmp_path)
        assert "999" in registry.specs
        assert any("bad.json" in message for message in registry.errors)

    def test_duplicate_protocol_id_is_reported(self, tmp_path):
        write_spec(tmp_path, "a.json", MINIMAL_SPEC)
        write_spec(tmp_path, "b.json", dict(MINIMAL_SPEC, model="OTHER"))
        registry = DecoderRegistry(specs_dir=tmp_path)
        assert registry.specs["999"].model == "TEST_999"
        assert any("already defined" in message for message in registry.errors)

    def test_protocol_ids_are_sorted_numerically(self, tmp_path):
        write_spec(tmp_path, "a.json", dict(MINIMAL_SPEC, protocol_id="9"))
        write_spec(tmp_path, "b.json", dict(MINIMAL_SPEC, protocol_id="125"))
        registry = DecoderRegistry(specs_dir=tmp_path)
        assert registry.protocol_ids == ["9", "125"]

    def test_coverage_reports_the_ratio(self, tmp_path):
        write_spec(tmp_path, "a.json", MINIMAL_SPEC)
        registry = DecoderRegistry(specs_dir=tmp_path)
        assert registry.coverage(total=160) == "1 of 160 protocols"


class TestCustomDecoders:

    def test_a_custom_decoder_wins_over_a_specification(self, tmp_path):
        write_spec(tmp_path, "test_999.json", MINIMAL_SPEC)

        marker = object()

        @register_decoder("999")
        def _decode(message):
            return marker

        try:
            registry = DecoderRegistry(specs_dir=tmp_path)
            assert registry.get("999")(None) is marker
        finally:
            registered_custom().pop("999", None)
            from signalduino.decoders import registry as registry_module
            registry_module._CUSTOM.pop("999", None)

    def test_custom_registration_is_keyed_by_string(self):
        @register_decoder(998)
        def _decode(message):
            return None

        try:
            assert "998" in registered_custom()
        finally:
            from signalduino.decoders import registry as registry_module
            registry_module._CUSTOM.pop("998", None)


class TestShippedSpecifications:
    """Whatever ends up in specs/ has to stay loadable."""

    def test_the_shipped_directory_loads_without_errors(self):
        registry = DecoderRegistry()
        assert registry.errors == []
