"""Shared helpers for parsing firmware messages."""

from __future__ import annotations

import re
from typing import Optional

from ..exceptions import SignalduinoParserError

_STX_ETX = re.compile(r"^\x02(M.;.*;)\x03$")


def extract_payload(line: str) -> Optional[str]:
    """Return the payload between STX/ETX markers if present."""

    if not line:
        return None
    match = _STX_ETX.match(line.strip())
    if not match:
        return None
    return match.group(1)


def ensure_message_type(payload: str, expected: str) -> None:
    if not payload.upper().startswith(expected.upper()):
        raise SignalduinoParserError(f"expected {expected} message, got {payload[:2]}")


def calc_rssi(raw_rssi: int) -> float:
    """Match Perl's RSSI conversion formula."""

    if raw_rssi >= 128:
        return ((raw_rssi - 256) / 2) - 74
    return (raw_rssi / 2) - 74


def calc_afc(raw_afc: int) -> float:
    """Match Perl's AFC conversion formula."""

    if raw_afc >= 128:
        return (raw_afc - 256) / 2
    return raw_afc / 2
