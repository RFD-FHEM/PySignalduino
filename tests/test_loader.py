import pytest
from sd_protocols.loader import resolve_method, protocols

# Test-Protokolle die wir validieren wollen
# Die Method-Strings sind jetzt direkt die Python-Klassenmethoden
TEST_PROTOCOLS = {
    "manchester": ["mcBit2Grothe", "mcBit2SomfyRTS"],  # ManchesterMixin
    "rsl_handler": ["decode_rsl", "encode_rsl"],      # RSLMixin
}

def test_selected_protocols_exist():
    """Stellt sicher, dass die gewünschten Protokolle in der JSON vorkommen."""
    found = []
    for pid, proto in protocols.items():
        if "method" in proto:
            method_str = proto["method"]
            for module, funcs in TEST_PROTOCOLS.items():
                for func in funcs:
                    if method_str == f"{module}.{func}":
                        found.append(method_str)
    assert found, "Keine der gewünschten Methoden gefunden"

@pytest.mark.parametrize("module, funcs", TEST_PROTOCOLS.items())
def test_methods_resolvable(module, funcs):
    """Prüft, ob die gewünschten Methoden aufgelöst werden können."""
    for func in funcs:
        method_str = f"{module}.{func}"
        resolved = resolve_method(method_str)
        assert callable(resolved), f"Methode {method_str} nicht auflösbar"

@pytest.mark.parametrize("module, funcs", TEST_PROTOCOLS.items())
def test_run_methods(module, funcs):
    """Führt jede gewünschte Methode einmal aus mit korrekten Argumenten."""
    for func in funcs:
        method_str = f"{module}.{func}"
        # Wir suchen das erste Protokoll, das diese Methode nutzt
        for pid, proto_data in protocols.items():
            if proto_data.get("method") == method_str:
                # Call resolved method with proper arguments
                method = resolve_method(method_str)
                
                # Different calling conventions for different methods
                if func in ['decode_rsl', 'encode_rsl']:
                    # RSL methods take different arguments
                    result = method("1010101010")
                else:
                    # Manchester methods: name, bit_data, protocol_id, mcbitnum
                    result = method(name="test", bit_data="1010101010", protocol_id=pid, mcbitnum=10)
                
                assert result is not None
                break


