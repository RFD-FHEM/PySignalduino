import pytest
import json
from sd_protocols.loader import resolve_method, run_method

# JSON laden
with open("protocols.json", "r", encoding="utf-8") as f:
    data = json.load(f)

protocols = data["protocols"]

# Nur die IDs oder Namen, die wir testen wollen
TEST_PROTOCOLS = {
    "grothe": ["mc_bit2grothe"],   # Methoden in grothe.py
    "somfy": ["mc_bit2somfy"],     # Methoden in somfy.py
    "rsl": ["decode_rsl", "encode_rsl"],  # Methoden in rsl.py
}

def test_selected_protocols_exist():
    """Stellt sicher, dass die gewünschten Protokolle in der JSON vorkommen."""
    found = []
    for pid, proto in protocols.items():
        if "method" in proto:
            method_str = proto["method"]
            for module, funcs in TEST_PROTOCOLS.items():
                if any(method_str.endswith(func) for func in funcs):
                    found.append(method_str)
    assert found, "Keine der gewünschten Methoden gefunden"

@pytest.mark.parametrize("module, funcs", TEST_PROTOCOLS.items())
def test_methods_resolvable(module, funcs):
    """Prüft, ob die gewünschten Methoden importierbar sind."""
    for func in funcs:
        method_str = f"{module}.{func}"
        resolved = resolve_method(method_str)
        assert callable(resolved), f"Methode {method_str} nicht auflösbar"

@pytest.mark.parametrize("module, funcs", TEST_PROTOCOLS.items())
def test_run_methods(module, funcs):
    """Führt jede gewünschte Methode einmal aus (Dummy-Argumente)."""
    for func in funcs:
        method_str = f"{module}.{func}"
        # Wir suchen das erste Protokoll, das diese Methode nutzt
        for pid, proto in protocols.items():
            if proto.get("method") == method_str:
                result = run_method(pid, "1010101010")
                assert result is not None
                break
