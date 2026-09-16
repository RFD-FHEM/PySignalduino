"""Finds the decoder for a protocol (ADR-006).

Two kinds of decoder end up here: specifications from specs/*.json, and Python
decoders registered from custom/ for the protocols whose logic does not fit a
declarative description. Custom decoders win over a specification with the same
id, so a protocol can be moved from one to the other without deleting anything.

Routing is by protocol id, which the message already carries. The preamble and
modulematch from protocols.json are used for stripping and as the default
prematch, but never to find the decoder.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Callable, Optional

from ..types import DecodedMessage, SensorEvent
from .pipeline import decode_with_spec
from .spec import DecoderSpec, SpecError, load_file

SPECS_DIR = Path(__file__).parent / "specs"

Decoder = Callable[[DecodedMessage], SensorEvent]

_CUSTOM: dict[str, Decoder] = {}


def register_decoder(protocol_id: str) -> Callable[[Decoder], Decoder]:
    """Registers a Python decoder for a protocol id.

    Used by modules under custom/ for protocols that a specification cannot
    express, for example when fields depend on each other or the checksum is
    computed over a reordered payload.
    """
    def wrapper(func: Decoder) -> Decoder:
        _CUSTOM[str(protocol_id)] = func
        return func
    return wrapper


def registered_custom() -> dict[str, Decoder]:
    """The custom decorators registered so far."""
    return dict(_CUSTOM)


class DecoderRegistry:
    """Holds the decoders available at runtime."""

    def __init__(self, specs_dir: Optional[Path] = None,
                 protocols=None,
                 logger: Optional[logging.Logger] = None,
                 load: bool = True):
        self.specs_dir = specs_dir if specs_dir is not None else SPECS_DIR
        self.protocols = protocols
        self.logger = logger or logging.getLogger(__name__)
        self.specs: dict[str, DecoderSpec] = {}
        self.custom: dict[str, Decoder] = {}
        self.errors: list[str] = []
        if load:
            self.load()

    def load(self) -> None:
        """Loads all specifications and picks up the custom decoders."""
        self.specs.clear()
        self.errors.clear()

        # Importing the package runs the @register_decoder decorators in it.
        try:
            importlib.import_module(f"{__package__}.custom")
        except ImportError as error:
            self.errors.append(f"custom decoders not loaded: {error}")
            self.logger.error("Could not import custom decoders: %s", error)

        if self.specs_dir.is_dir():
            for path in sorted(self.specs_dir.glob("*.json")):
                try:
                    spec = load_file(path)
                except SpecError as error:
                    # A broken specification must not take the others down.
                    self.errors.append(str(error))
                    self.logger.error("Ignoring decoder specification: %s", error)
                    continue
                if spec.protocol_id in self.specs:
                    self.errors.append(
                        f"{path.name}: protocol {spec.protocol_id} already defined by "
                        f"{self.specs[spec.protocol_id].source}"
                    )
                    self.logger.warning("%s", self.errors[-1])
                    continue
                self.specs[spec.protocol_id] = spec

        self.custom = registered_custom()
        for protocol_id in sorted(set(self.custom) & set(self.specs)):
            self.logger.info(
                "Protocol %s has both a specification and a custom decoder, using the custom one",
                protocol_id,
            )

    def _preamble(self, protocol_id: str) -> str:
        if self.protocols is None:
            return ""
        try:
            return self.protocols.check_property(protocol_id, "preamble", "") or ""
        except Exception:  # noqa: BLE001 - protocol data must not break decoding
            self.logger.debug("No preamble for protocol %s", protocol_id)
            return ""

    def _default_prematch(self, protocol_id: str) -> Optional[str]:
        if self.protocols is None:
            return None
        try:
            return self.protocols.check_property(protocol_id, "modulematch", None)
        except Exception:  # noqa: BLE001
            return None

    def get(self, protocol_id: str) -> Optional[Decoder]:
        """The decoder for a protocol, or None if there is none."""
        protocol_id = str(protocol_id)

        custom = self.custom.get(protocol_id)
        if custom is not None:
            return custom

        spec = self.specs.get(protocol_id)
        if spec is None:
            return None

        preamble = self._preamble(protocol_id)

        def decode(message: DecodedMessage) -> SensorEvent:
            return decode_with_spec(spec, message, preamble)

        return decode

    @property
    def protocol_ids(self) -> list[str]:
        """All protocol ids that can be decoded, specifications and custom."""
        return sorted(set(self.specs) | set(self.custom), key=int)

    def coverage(self, total: Optional[int] = None) -> str:
        """A short 'x of y protocols' line for logs and reports."""
        covered = len(self.protocol_ids)
        if total is None and self.protocols is not None:
            try:
                total = len(self.protocols.protocols)
            except Exception:  # noqa: BLE001
                total = None
        return f"{covered} of {total} protocols" if total else f"{covered} protocols"
