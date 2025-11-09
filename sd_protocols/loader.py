import importlib
import json
import os

# JSON laden (eine Ebene höher)
json_path = os.path.join(os.path.dirname(__file__), "..", "protocols.json")
with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

protocols = data["protocols"]

def resolve_method(path: str):
    """
    Wandelt einen String wie 'grothe.mc_bit2grothe' in eine echte Python-Funktion.
    """
    module_name, func_name = path.split(".", 1)
    module = importlib.import_module(f"sd_protocols.methods.{module_name}")
    return getattr(module, func_name)

def run_method(pid, *args, **kwargs):
    """
    Führt die Methode für ein bestimmtes Protokoll aus.
    """
    proto = protocols.get(str(pid))
    if not proto or "method" not in proto:
        raise ValueError(f"Kein method-handler für Protokoll {pid}")

    method_str = proto["method"]
    method = resolve_method(method_str)
    return method(*args, **kwargs)
