import copy
from .sd_protocol_data import protocols
from .helpers import ProtocolHelpersMixin
from .manchester import ManchesterMixin
from .postdemodulation import PostdemodulationMixin
from .rsl_handler import RSLMixin


class SDProtocols(ProtocolHelpersMixin, ManchesterMixin, PostdemodulationMixin, RSLMixin):
    """Main protocol handling class with helper methods from multiple mixins.
    
    Inherits from:
    - ProtocolHelpersMixin: Basic protocol helpers (manchester/binary conversion)
    - ManchesterMixin: Manchester signal protocol handlers (mcBit2* methods)
    - PostdemodulationMixin: Post-demodulation processors (postDemo_* methods)
    - RSLMixin: RSL protocol handlers (decode_rsl, encode_rsl methods)
    """

    def __init__(self):
        self._protocols = copy.deepcopy(protocols)
        self._log_callback = None
        self.set_defaults()

    def protocol_exists(self, pid: str) -> bool:
        return pid in self._protocols

    def get_protocol_list(self) -> dict:
        return self._protocols

    def get_keys(self, filter_key: str = None) -> list:
        if filter_key:
            return [pid for pid, props in self._protocols.items() if filter_key in props]
        return list(self._protocols.keys())

    def check_property(self, pid: str, value_name: str, default=None):
        return self._protocols.get(pid, {}).get(value_name, default)

    def get_property(self, pid: str, value_name: str):
        return self._protocols.get(pid, {}).get(value_name)

    def set_defaults(self):
        for pid, proto in self._protocols.items():
            proto.setdefault("active", True)
            proto.setdefault("name", f"Protocol_{pid}")

    def register_log_callback(self, callback):
        """Register a callback function for logging."""
        if callable(callback):
            self._log_callback = callback

    def _logging(self, message: str, level: int = 3):
        """Log a message if a callback is registered."""
        if self._log_callback:
            self._log_callback(message, level)

