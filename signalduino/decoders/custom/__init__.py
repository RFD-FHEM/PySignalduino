"""Python decoders for protocols a specification cannot express (ADR-006).

A protocol belongs here when its fields depend on each other, when the
checksum runs over a reordered payload, or when the model name itself is
derived from the data. Everything else belongs in specs/*.json.

A module in this package registers itself:

    from ..registry import register_decoder

    @register_decoder("115")
    def decode_bresser_5in1(message):
        ...
        return SensorEvent(...)

and is imported here so the registry picks it up. A custom decoder takes
precedence over a specification with the same protocol id.
"""
