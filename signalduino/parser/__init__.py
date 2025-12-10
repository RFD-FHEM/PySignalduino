"""Entry point for Signalduino parsing logic."""

from __future__ import annotations

import logging
from typing import Iterable, List

from sd_protocols import SDProtocols

from ..types import DecodedMessage, RawFrame
from . import base
from .mc import MCParser
from .mn import MNParser
from .ms import MSParser
from .mu import MUParser


class SignalParser:
    """Routes firmware lines to the dedicated parser for each message type."""

    def __init__(
        self,
        protocols: SDProtocols | None = None,
        logger: logging.Logger | None = None,
        rfmode: str | None = None,
    ):
        self.protocols = protocols or SDProtocols()
        self.logger = logger or logging.getLogger(__name__)
        self.protocols.register_log_callback(self._log_adapter)
        self.rfmode = rfmode
        self.ms_parser = MSParser(self.protocols, self.logger)
        self.mu_parser = MUParser(self.protocols, self.logger)
        self.mc_parser = MCParser(self.protocols, self.logger)
        self.mn_parser = MNParser(self.protocols, self.logger, self.rfmode)

    def parse_line(self, line: str) -> List[DecodedMessage]:
        payload = base.extract_payload(line)
        if payload is None:
            self.logger.debug("SignalParser: ignoring line without STX/ETX framing: %s", line.strip())
            return []

        frame = RawFrame(line=payload, message_type=payload[:2].upper())
        parser = self._select_parser(frame.message_type)

        if parser is None:
            self.logger.debug("SignalParser: no parser registered for %s", frame.message_type)
            return []

        return list(parser.parse(frame))

    def _log_adapter(self, message: str, level: int):
        """Adapts SDProtocols custom log levels to python logging."""
        # FHEM levels: 1=Error, 2=Warn, 3=Info, 4=More Info, 5=Debug
        if level <= 1:
            self.logger.error(message)
        elif level == 2:
            self.logger.warning(message)
        elif level == 3:
            self.logger.info(message)
        elif level == 4:
            self.logger.debug(message) # or info? keeping debug for now
        else:
            self.logger.debug(message)

    def _select_parser(self, message_type: str | None):
        if not message_type:
            return None
        if message_type == "MS":
            return self.ms_parser
        if message_type == "MU":
            return self.mu_parser
        if message_type == "MC":
            return self.mc_parser
        if message_type == "MN":
            return self.mn_parser
        return None


__all__ = ["SignalParser"]