"""Firmware message (MN) parser."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable

from sd_protocols import SDProtocols

from ..exceptions import SignalduinoParserError
from ..types import DecodedMessage, RawFrame
from .base import ensure_message_type


class MNParser:
    """
    Parses informational (MN) messages. If an rfmode is set, it attempts
    to demodulate the message; otherwise, it just logs it.
    """

    def __init__(self, protocols: SDProtocols, logger: logging.Logger, rfmode: str | None = None):
        self.protocols = protocols
        self.logger = logger
        self.rfmode = rfmode

    def parse(self, frame: RawFrame) -> Iterable[DecodedMessage]:
        """Processes a raw MN frame."""
        try:
            ensure_message_type(frame.line, "MN")
        except SignalduinoParserError as e:
            self.logger.debug("Not an MN message: %s", e)
            return

        msg_data = self._parse_to_dict(frame.line)

        # If no rfmode is set, just log the message
        if not self.rfmode:
            self.logger.info("Received firmware message: %s", frame.line)
            return

        if "D" not in msg_data:
            self.logger.debug("Ignoring MN message without data (D): %s", frame.line)
            return

        msg_data["data"] = msg_data["D"]
        msg_data["rfmode"] = self.rfmode

        try:
            demodulated_list = self.protocols.demodulate(msg_data, "MN")
        except Exception:
            self.logger.exception("Error during MN demodulation for line: %s", frame.line)
            return

        for decoded in demodulated_list:
            if not isinstance(decoded, dict) or "protocol_id" not in decoded:
                self.logger.warning("Invalid result from demodulator: %s", decoded)
                continue

            yield DecodedMessage(
                protocol_id=str(decoded["protocol_id"]),
                payload=str(decoded.get("payload", "")),
                raw=frame,
                metadata=decoded.get("meta", {}),
            )

    def _parse_to_dict(self, line: str) -> Dict[str, Any]:
        """Splits a semicolon-separated line into a dictionary."""
        msg_data: Dict[str, Any] = {}
        parts = line.split(";")
        for part in parts:
            if not part:
                continue
            if "=" in part:
                key, value = part.split("=", 1)
                msg_data[key] = value
            else:
                msg_data[part] = ""
        return msg_data
