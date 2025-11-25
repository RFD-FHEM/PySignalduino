import copy
import json
from pathlib import Path
from typing import Any, Dict
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
        self._protocols = self._load_protocols()
        self._log_callback = None
        self.set_defaults()

    def _load_protocols(self) -> Dict[str, Any]:
        """Loads protocols from protocols.json."""
        json_path = Path(__file__).resolve().parent / "protocols.json"
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("protocols", {})
        except Exception as e:
            # Fallback or error logging if needed, though for now we raise
            # or return empty dict if file missing (should not happen in prod)
            print(f"Error loading protocols.json: {e}")
            return {}

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


    def demodulate_mc(self, msg_data: Dict[str, Any], msg_type: str, version: str | None = None) -> list:
        """Attempts to demodulate an MC message using registered protocols."""
        
        protocol_id = msg_data.get("protocol_id")
        
        if not protocol_id or not self.protocol_exists(protocol_id):
            self._logging(f"MC Demodulation failed: Protocol ID {protocol_id} not found or missing.", 3)
            return []
            
        # Get data from msg_data
        raw_hex = msg_data.get('data', '')
        clock = msg_data.get('clock', 0)
        mcbitnum = msg_data.get('bit_length', 0)
        
        # We assume the caller (MCParser) ensures we have D, C, L
        
        rcode, dmsg, metadata = self._demodulate_mc_data(
            name=f"Protocol {protocol_id}", # Using protocol name as a simple name for logging
            protocol_id=protocol_id,
            clock=clock,
            raw_hex=raw_hex,
            mcbitnum=mcbitnum,
            messagetype=msg_type,
            version=version
        )
        
        if rcode == 1:
            # The payload will be inside dmsg, and protocol id in metadata
            # We assume dmsg contains the HEX payload (mcRaw/mcBit2* methods return this)
            return [{
                "protocol_id": str(protocol_id),
                "payload": dmsg,
                "meta": metadata
            }]
            
        return []

    def demodulate_mn(self, msg_data: Dict[str, Any], msg_type: str) -> list:
        """Attempts to demodulate an MN message using registered protocols."""
        if "protocol_id" not in msg_data:
            self._logging(f"MN Demodulation failed: Missing protocol_id in msg_data: {msg_data}", 3)
            return []

        protocol_id = msg_data["protocol_id"]
        
        if not self.protocol_exists(protocol_id):
            self._logging(f"MN Demodulation: Protocol ID {protocol_id} not found.", 3)
            return []

        method_name_full = self.get_property(protocol_id, 'method')
        
        if not method_name_full:
            self._logging(f"MN Demodulation: No method defined for protocol {protocol_id}. Data: {msg_data.get('data', '')}", 3)
            return []
            
        # MN messages usually pass the raw data directly (no bit conversion)
        # We assume the method handles raw hex/data string or needs it as hex.
        # The method name is expected to be 'method_name' or 'module.method_name'
        method_name = method_name_full.split('.')[-1]

        if hasattr(self, method_name) and callable(getattr(self, method_name)):
            method_func = getattr(self, method_name)
            
            # MN methods might be called differently than MC methods, let's check existing ones
            # For now, we will assume they take msg_data and return a list of decoded messages/dicts
            try:
                # Generic call signature for new methods, using msg_data and msg_type for context
                demodulated_list = method_func(msg_data, msg_type)
            except TypeError:
                self._logging(f"MN Demodulation: Method {method_name} failed due to wrong signature/arguments.", 3)
                return []
        else:
            self._logging(f"MN Demodulation: Unknown method {method_name} referenced by '{method_name_full}'.", 3)
            return []
            
        if not isinstance(demodulated_list, list):
            self._logging(f"MN Demodulation: Method {method_name} returned non-list: {type(demodulated_list)}.", 3)
            return []
            
        return demodulated_list

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
