"""Manchester (MC) parser."""

from __future__ import annotations

import logging
import re

from typing import Any, Dict, Iterable

from sd_protocols import SDProtocols

from ..exceptions import SignalduinoParserError
from ..types import DecodedMessage, RawFrame
from .base import calc_afc, calc_rssi, ensure_message_type


class MCParser:
    """
    Parses manchester (MC) messages from the Signalduino firmware.
    """

    def __init__(self, protocols: SDProtocols, logger: logging.Logger):
        self.protocols = protocols
        self.logger = logger

    def parse(self, frame: RawFrame) -> Iterable[DecodedMessage]:
        """
        Processes a raw MC frame, demodulates it using sd_protocols,
        and yields zero or more DecodedMessage objects.
        """
        try:
            ensure_message_type(frame.line, "MC")
        except SignalduinoParserError as e:
            self.logger.debug("Not an MC message: %s", e)
            return

        # Example: MC;LL=-10;LH=10;SL=-10;SH=10;D=AAAA9555555AA9555;C=450;L=128;(?:R=48;)?
        msg_data = self._parse_to_dict(frame.line)

        if "D" not in msg_data or "C" not in msg_data or "L" not in msg_data:
            self.logger.debug(
                "Ignoring MC message missing required fields (D, C, or L): %s", frame.line
            )
            return

        # Extract required fields based on Perl parsing logic (lines 2818-2823 in 00_SIGNALduino.pm)
        msg_data["raw_hex"] = msg_data["D"]
        msg_data["clock"] = msg_data["C"]
        msg_data["mcbitnum"] = msg_data["L"]
        msg_data["messagetype"] = msg_data.get("M", "MC")  # M or MC from header M[cC]

        raw_hex = msg_data["raw_hex"]
        if not re.fullmatch(r"[0-9a-fA-F]+", raw_hex):
            self.logger.warning("Ignoring MC message with non-hexadecimal raw_hex: %s", raw_hex)
            return
            
        self._extract_metadata(frame, msg_data)

        try:
            # Replace generic demodulate with MC-specific processing in the protocol layer
            # This call should now encapsulate the logic from SIGNALduino_Parse_MC (lines 2840-2919)
            demodulated_list = self.protocols.demodulate_mc(msg_data, frame)
        except Exception:
            self.logger.exception("Error during MC demodulation for line: %s", frame.line)
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
