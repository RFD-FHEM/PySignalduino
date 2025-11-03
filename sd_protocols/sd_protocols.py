import copy
from .sd_protocol_data import protocols

class SDProtocols:
    def __init__(self):
        self._protocols = copy.deepcopy(protocols)
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
