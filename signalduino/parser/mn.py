"""Firmware message (MN) parser."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable

from sd_protocols import SDProtocols

from ..exceptions import SignalduinoParserError
from ..types import DecodedMessage, RawFrame
from .base import ensure_message_type, calc_rssi

# Regex to match MN messages: MN;D=...;R=...;A=...
# Supports optional Y prefix in data, and optional R/A fields
MN_PATTERN = re.compile(r"^MN;D=(Y?)([0-9A-F]+);(?:R=([0-9]+);)?(?:A=(-?[0-9]{1,3});)?$")


class MNParser:
    """
    Parses informational (MN) messages.
    Iterates over available MN protocols to find a match based on rfmode, length, and regex.
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

        match = MN_PATTERN.match(frame.line)
        if not match:
            self.logger.debug("MN message format mismatch: %s", frame.line)
            return

        # Extract groups
        # Group 1: 'Y' or ''
        # Group 2: Hex Data
        # Group 3: RSSI (optional)
        # Group 4: AFC (optional)
        
        # raw_data should not contain the 'Y' prefix if present
        raw_data = match.group(2)
        
        rssi = None
        if match.group(3):
            try:
                rssi = calc_rssi(int(match.group(3)))
            except ValueError:
                pass

        freq_afc = None
        if match.group(4):
            try:
                # AFC calculation formula from Perl:
                # round((26000000 / 16384 * freqafc / 1000), 0)
                raw_afc = int(match.group(4))
                freq_afc = round((26000000 / 16384 * raw_afc / 1000), 0)
            except ValueError:
                pass

        # Prepare common message data for methods
        msg_data = {
            "raw_data": raw_data,
            "data": raw_data, # Alias
            "rssi": rssi,
            "freq_afc": freq_afc,
            "rfmode": self.rfmode
        }

        # Iterate over all MN protocols (those having 'modulation' property)
        mn_ids = self.protocols.get_keys('modulation')
        
        for pid in mn_ids:
            # 1. Check rfmode
            proto_rfmode = self.protocols.check_property(pid, 'rfmode', None)
            if not proto_rfmode:
                self.logger.debug("MN Parse: Protocol %s has no rfmode defined", pid)
                continue
            
            # Perl implementation checks if rfmode is active in some way, but here we just check if it matches.
            # If rfmode is set on parser, only try this specific protocol
            if self.rfmode and proto_rfmode != self.rfmode:
                self.logger.debug("MN Parse: Skipping protocol %s. Expected rfmode: %s, Protocol rfmode: %s", pid, self.rfmode, proto_rfmode)
                continue
            
            # 2. Check Length
            # Note: raw_data is hex string here. LengthInRange in Perl checks char length of this string.
            # length_in_range in SDProtocols expects length.
            rcode, rtxt = self.protocols.length_in_range(pid, len(raw_data))
            if not rcode:
                self.logger.debug("MN Parse: Protocol %s length check failed: %s", pid, rtxt)
                continue

            # 3. Regex Match
            match_regex = self.protocols.check_property(pid, 'regexMatch', None)
            modulation = self.protocols.check_property(pid, 'modulation', None)
            proto_name = self.protocols.get_property(pid, 'name')

            if match_regex:
                if re.search(match_regex, raw_data):
                    self.logger.debug("MN Parse: Found %s Protocol id %s -> %s with match", modulation, pid, proto_name)
                else:
                    self.logger.debug("MN Parse: %s Protocol id %s -> %s msg %s not match %s", modulation, pid, proto_name, raw_data, match_regex)
                    continue
            else:
                self.logger.debug("MN Parse: Found %s Protocol id %s -> %s (no regex)", modulation, pid, proto_name)

            # 4. Method Execution
            method_name_full = self.protocols.get_property(pid, 'method')
            
            # Default result is just raw_data if no method
            decoded_payload = raw_data
            
            if method_name_full:
                method_name = method_name_full.split('.')[-1]
                method = getattr(self.protocols, method_name, None)
                
                if method and callable(method):
                    try:
                        # We assume the method takes (self.protocols, raw_data) or similar.
                        # Based on Perl: $method->($hash->{protocolObject},$rawData)
                        # Based on existing Python structure it might be method(msg_data, 'MN')
                        # But since we are in the parser and have direct access, let's try to be robust.
                        # If the method was ported from Perl 1:1, it might expect (protocols, raw_data).
                        # If it was adapted for Python SDProtocols style, it might expect (msg_data, 'MN').
                        
                        # Let's inspect existing methods? No can do easily.
                        # We assume adaptation to: method(msg_data, 'MN') -> list of dicts OR (decoded, error)
                        # OR method(protocols_obj, raw_data) -> (decoded_data, error_msg)
                        
                        # Given `demodulate_mn` implementation in `sd_protocols.py`:
                        # It calls method_func(msg_data, msg_type)
                        
                        # So we pass:
                        msg_data_with_id = msg_data.copy()
                        msg_data_with_id['protocol_id'] = pid
                        
                        # We try to support both signatures or assume one.
                        # Let's assume the `demodulate_mn` signature is the standard for Python port.
                        result = method(msg_data_with_id, "MN")
                        
                        # Result handling depends on what the method returns.
                        # Perl returns array: (decoded_data, error_msg)
                        # Python `demodulate_mn` expects list of dicts.
                        
                        if isinstance(result, list) and result and isinstance(result[0], dict):
                             # Looks like demodulate_mn style result
                             decoded_payload = result[0].get('payload', raw_data)
                        elif isinstance(result, tuple):
                             # Maybe (decoded, error)
                             if len(result) > 1 and result[1] and "missing module" in str(result[1]):
                                 self.logger.warning("MN Parse: Error method %s", result[1])
                                 continue
                             decoded_payload = result[0]
                        else:
                             # Fallback
                             decoded_payload = str(result)

                    except Exception as e:
                        self.logger.exception("Error executing method %s for protocol %s: %s", method_name, pid, e)
                        continue
                else:
                     self.logger.warning("MN Parse: Method %s not found for protocol %s", method_name, pid)
                     continue

            # 5. Construct Final Message
            preamble = self.protocols.check_property(pid, 'preamble', '')
            final_payload = f"{preamble}{decoded_payload}"
            
            self.logger.info("MN Parse: Decoded matched MN Protocol id %s dmsg=%s", pid, final_payload)
            
            yield DecodedMessage(
                protocol_id=str(pid),
                payload=final_payload,
                raw=frame,
                metadata={
                    "rssi": rssi,
                    "freq_afc": freq_afc,
                    "modulation": modulation,
                    "rfmode": proto_rfmode
                },
            )
