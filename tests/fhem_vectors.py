"""Access to the vendored FHEM test vectors under tests/data/fhem/.

The vectors are imported by tools/fhem_testdata_import.py and are the shared
reference for both decoding stages: ``dmsg`` is what stage 1 has to produce,
``readings`` is what stage 2 has to produce (ADR-006).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).parent / "data" / "fhem"

STX = "\x02"
ETX = "\x03"


@dataclass(frozen=True)
class FhemVector:
    """One FHEM test vector."""

    rmsg: str
    dmsg: str
    module: str
    comment: str = ""
    readings: dict[str, Any] = field(default_factory=dict)
    expects_no_result: bool = False

    @property
    def protocol_id(self) -> Optional[str]:
        """Protocol id taken from the dmsg preamble, e.g. 'W125#...' -> '125'."""
        if "#" not in self.dmsg:
            return None
        head = self.dmsg.split("#", 1)[0]
        digits = "".join(char for char in head if char.isdigit())
        return digits or None

    @property
    def framed_rmsg(self) -> str:
        """The raw message with the STX/ETX framing the parser expects."""
        return f"{STX}{self.rmsg}{ETX}"

    def __str__(self) -> str:  # keeps pytest ids readable
        return f"{self.module}:{self.dmsg}"


def _walk(node: Any, module: str, found: list[FhemVector]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("rmsg"), str) and isinstance(node.get("dmsg"), str):
            readings: dict[str, Any] = {}
            expects_no_result = False
            for test in node.get("tests") or []:
                if not isinstance(test, dict):
                    continue
                if isinstance(test.get("readings"), dict):
                    readings = test["readings"]
                returns = test.get("returns")
                if isinstance(returns, dict) and returns.get("ParseFn") == "":
                    expects_no_result = True
            found.append(
                FhemVector(
                    rmsg=node["rmsg"],
                    dmsg=node["dmsg"],
                    module=module,
                    comment=node.get("comment", ""),
                    readings=readings,
                    expects_no_result=expects_no_result,
                )
            )
            return
        for value in node.values():
            _walk(value, module, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, module, found)


@lru_cache(maxsize=None)
def load_vectors(module: str = "sd_ws") -> tuple[FhemVector, ...]:
    """Loads all vectors of one vendored module file."""
    path = DATA_DIR / f"{module}.json"
    if not path.is_file():
        return ()
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    found: list[FhemVector] = []
    _walk(document.get("vectors", document), module, found)
    return tuple(found)


def vectors_for_protocol(protocol_id: str, module: str = "sd_ws") -> tuple[FhemVector, ...]:
    """All vectors of one protocol id."""
    return tuple(v for v in load_vectors(module) if v.protocol_id == protocol_id)
