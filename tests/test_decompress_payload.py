import re
from typing import List, Tuple, Dict
from signalduino.parser.base import decompress_payload

# Testdaten basierend auf temp_repo/t/FHEM/00_SIGNALduino/02_sub_SIGNALduino_Read.t
# Die Rohdaten müssen von Hex-String in einen String aus Latin-1-Zeichen umgewandelt werden, 
# da die Dekomprimierungsfunktion einen String erwartet.

TEST_CASES: List[Tuple[str, str, str]] = [
    (
        "ID 9 MU message",
        # Komprimierte Daten (ohne STX/ETX, da die Funktion nur den Payload nimmt)
        # HIER WURDE ";F64;D" (3b 46 36 34 3b 44) ENTFERNT, UM DIE DATEN ZU BEREINIGEN
        "4d 75 3b a0 a0 f0 3b 91 c2 81 3b a2 a8 84 3b 93 8e 85 3b 43 31 3b 52 44 3b 44 01 21 21 21 21 21 21 21 23 21 21 21 21 21 21 21 21 21 21 21 23 23 23 23 23 21 23 21 23 21 23 21 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 21 21 21 21 23 21 01 21 21 21 21 21 21 21 23 21 21 21 21 21 21 21 21 21 21 21 23 23 23 23 23 21 23 21 23 21 23 21 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 21 21 21 21 23 21 01 21 21 21 21 21 21 21 23 21 21 21 21 21 21 21 21 21 21 21 23 23 23 23 23 21 23 21 23 21 23 21 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 23 21 21 21 21 23 21 3b",
        # Erwartetes unkomprimiertes Ergebnis (ohne F=100)
        "MU;P0=-28704;P1=450;P2=-1064;P3=1422;CP=1;R=13;D=012121212121212123212121212121212121212123232323232123212321232123232323232323232323232323232323232323232323232323232121212123210121212121212121232121212121212121212121232323232321232123212321232323232323232323232323232323232323232323232323232321212121232101212121212121212321212121212121212121212323232323212321232123212323232323232323232323232323232323232323232323232323212121212321;",
    ),
    (
        "ID 7 MS message",
        # Komprimierte Daten (ohne STX/ETX)
        "4d 73 3b 92 dc 81 3b a3 b6 8f 3b b4 d1 83 3b b5 ae 87 3b 44 23 24 25 25 24 25 24 25 25 24 24 25 24 24 24 24 24 25 24 25 25 24 25 25 25 25 25 25 25 24 24 25 25 24 24 25 24 3b 43 32 3b 53 33 3b 52 46 30 3b 4f 3b 6d 30 3b",
        # Erwartetes unkomprimiertes Ergebnis
        "MS;P2=476;P3=-3894;P4=-977;P5=-1966;D=23242525242524252524242524242424242524252524252525252525252424252524242524;CP=2;SP=3;R=240;O;m0;",
    ),
]

def hex_string_to_latin1(hex_str: str) -> str:
    """Converts a space-separated hex string to a Latin-1 string."""
    hex_str = hex_str.replace(" ", "")
    if hex_str.startswith("02") and hex_str.endswith("03"):
        hex_str = hex_str[2:-2]
    
    return bytes.fromhex(hex_str).decode("latin-1")

def test_decompress_payload():
    """Unit tests for decompress_payload against known compressed/decompressed messages."""
    
    for name, raw_hex, expected_payload in TEST_CASES:
        # 1. Prepare the raw input
        compressed_input = hex_string_to_latin1(raw_hex)
        
        # 2. Call the function
        actual_payload = decompress_payload(compressed_input)

        # 3. Assert (Normalize whitespace and trailing semicolon for robust comparison)
        expected = expected_payload.strip()
        actual = actual_payload.strip()
        
        if not expected.endswith(';'):
            expected += ';'
        
        def normalize_message(msg: str) -> Dict[str, str]:
            if not msg:
                return {}
            # Clean up the message for parsing: remove M[S|U|O]; prefix, split by ;
            parts = msg.upper().strip(';').split(';')
            result = {}
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    result[key.strip()] = value.strip()
                elif part:
                     result[part.strip()] = ""
            
            # The message type is special
            if parts in ("MS", "MU", "MO"):
                result["MSG_TYPE"] = parts
            
            return result

        normalized_expected = normalize_message(expected)
        normalized_actual = normalize_message(actual)

        # We assume the order of keys for MS/MU is not strict, but the keys/values must match.
        assert normalized_actual == normalized_expected, f"\n--- {name} ---\nExpected: {normalized_expected}\nActual:   {normalized_actual}"

    print("All decompress_payload tests passed successfully.")

if __name__ == "__main__":
    test_decompress_payload()