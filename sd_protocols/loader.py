import json
from pathlib import Path
from .sd_protocols import SDProtocols

# JSON laden (im selben Paketverzeichnis)
json_path = Path(__file__).resolve().parent / "protocols.json"
with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

protocols = data["protocols"]

# Erstelle eine globale SDProtocols Instanz für Methoden-Aufrufe
_protocol_handler = SDProtocols()

def resolve_method(path: str):
    """
    Wandelt einen String wie 'manchester.mcBit2Grothe' in eine echte Python-Methode.
    
    Das Format ist jetzt konsistent: "module.method_name" wobei:
    - manchester.* → Methoden aus ManchesterMixin
    - postdemodulation.* → Methoden aus PostdemodulationMixin
    - rsl_handler.* → Methoden aus RSLMixin
    - helpers.* → Methoden aus ProtocolHelpersMixin
    
    Args:
        path: Pfad im Format 'module.function' (z.B. 'manchester.mcBit2Grothe')
        
    Returns:
        Callable method from SDProtocols instance
        
    Raises:
        AttributeError: wenn die Methode nicht in SDProtocols existiert
    """
    # Nur den method-Namen extrahieren (alles nach dem Punkt)
    if '.' not in path:
        raise ValueError(f"Invalid method path: {path}. Expected format: 'module.method'")
    
    module_name, method_name = path.split(".", 1)
    
    # Get method from SDProtocols instance
    # SDProtocols erbt von allen Mixins, daher sind alle Methoden direkt verfügbar
    method = getattr(_protocol_handler, method_name, None)
    if method is None:
        raise AttributeError(
            f"Method '{method_name}' not found in SDProtocols "
            f"(path: {path})"
        )
    
    return method

def run_method(pid, *args, **kwargs):
    """
    Führt die Methode für ein bestimmtes Protokoll aus.
    
    Args:
        pid: Protocol ID (int or str)
        *args: Positional arguments for the method
        **kwargs: Keyword arguments for the method
        
    Returns:
        Return value from the protocol method
        
    Raises:
        ValueError: if protocol not found or has no method handler
    """
    proto = protocols.get(str(pid))
    if not proto or "method" not in proto:
        raise ValueError(f"Kein method-handler für Protokoll {pid}")

    method_str = proto["method"]
    method = resolve_method(method_str)
    return method(*args, **kwargs)


