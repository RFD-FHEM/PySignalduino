"""Unsynced (MU) parser."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable

from sd_protocols import SDProtocols

from ..exceptions import SignalduinoParserError
from ..types import DecodedMessage, RawFrame
from .base import calc_afc, calc_rssi, ensure_message_type


class MUParser:
    """
    Parses unsynchronous (MU) messages from the Signalduino firmware.
    These messages contain raw pulse/space timings.
    """

    def __init__(self, protocols: SDProtocols, logger: logging.Logger):
        self.protocols = protocols
        self.logger = logger

    def parse(self, frame: RawFrame) -> Iterable[DecodedMessage]:
        """
        Processes a raw MU frame, demodulates it using sd_protocols,
        and yields zero or more DecodedMessage objects.
        """
        try:
            ensure_message_type(frame.line, "MU")
        except SignalduinoParserError as e:
            self.logger.debug("Not an MU message: %s", e)
            return

        # Regex check for validity (ported from Perl)
        # ^(?=.*D=\d+)(?:MU;(?:P[0-7]=-?[0-9]{1,5};){2,8}((?:D=\d{2,};)|(?:CP=\d;)|(?:R=\d+;)?|(?:O;)?|(?:e;)?|(?:p;)?|(?:w=\d;)?)*)$
        # Note: The Perl regex allows 'R=' with optional value? No, 'R=\d+;'.
        # The Perl regex groups are:
        # ((?:D=\d{2,};)|(?:CP=\d;)|(?:R=\d+;)?|(?:O;)?|(?:e;)?|(?:p;)?|(?:w=\d;)?)*
        # Wait, (?:R=\d+;)? means R=123; is optional match, but if present must match R=\d+;
        # But if it matches empty string? The outer loop * repeats.
        # So essentially it allows empty strings between semicolons?
        # Let's use the exact logic:
        # It ensures that AFTER the P patterns, ONLY the specified keys appear.
        
        regex = r"^(?=.*D=\d+)(?:MU;(?:P[0-7]=-?[0-9]{1,5};){2,8}((?:D=\d{2,};)|(?:CP=\d;)|(?:R=\d+;)|(?:O;)|(?:e;)|(?:p;)|(?:w=\d;))*)$"
        
        if not re.match(regex, frame.line):
             self.logger.debug("MU message failed regex validation: %s", frame.line)
             return

        # Example: MU;P0=-1508;P1=476;D=0121;CP=1;R=43;
        msg_data = self._parse_to_dict(frame.line)

        if "D" not in msg_data:
            self.logger.debug("Ignoring MU message without data (D): %s", frame.line)
            return

        msg_data["data"] = msg_data["D"]
        self._extract_metadata(frame, msg_data)

        try:
            demodulated_list = self.protocols.demodulate(msg_data, "MU")
        except Exception:
            self.logger.exception("Error during MU demodulation for line: %s", frame.line)
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

    def _extract_metadata(self, frame: RawFrame, msg_data: Dict[str, Any]) -> None:
        """Extracts RSSI and AFC values and attaches them to the frame."""
        if "R" in msg_data:
            try:
                frame.rssi = calc_rssi(int(msg_data["R"]))
            except (ValueError, TypeError):
                self.logger.warning("Could not parse RSSI value: %s", msg_data["R"])

        if "F" in msg_data:
            try:
                frame.freq_afc = calc_afc(int(msg_data["F"]))
            except (ValueError, TypeError):
                self.logger.warning("Could not parse AFC value: %s", msg_data["F"])
