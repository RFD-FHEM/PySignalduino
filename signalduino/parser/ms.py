"""Synced (MS) parser."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable

from sd_protocols import SDProtocols

from ..exceptions import SignalduinoParserError
from ..types import DecodedMessage, RawFrame
from .base import calc_afc, calc_rssi, ensure_message_type


class MSParser:
    """
    Parses synchronous (MS) messages from the Signalduino firmware.
    These messages contain demodulated data with clock timings.
    """

    def __init__(self, protocols: SDProtocols, logger: logging.Logger):
        self.protocols = protocols
        self.logger = logger

    def parse(self, frame: RawFrame) -> Iterable[DecodedMessage]:
        """
        Processes a raw MS frame, demodulates it using sd_protocols,
        and yields zero or more DecodedMessage objects.
        """
        try:
            ensure_message_type(frame.line, "MS")
        except SignalduinoParserError as e:
            self.logger.debug("Not an MS message: %s", e)
            return

        # Example: MS;P0=-32001;P1=488;D=0101;CP=1;R=48;
        msg_data = self._parse_to_dict(frame.line)

        # Let sd_protocols handle the heavy lifting
        if "D" not in msg_data:
            self.logger.debug("Ignoring MS message without data (D): %s", frame.line)
            return

        # Prepare data for sd_protocols by renaming 'D' to 'data'
        msg_data["data"] = msg_data["D"]

        # Extract common metadata and attach to the raw frame
        self._extract_metadata(frame, msg_data)

        try:
            demodulated_list = self.protocols.demodulate(msg_data, "MS")
        except Exception:
            self.logger.exception("Error during MS demodulation for line: %s", frame.line)
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
                # Handles the "MS" part
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
