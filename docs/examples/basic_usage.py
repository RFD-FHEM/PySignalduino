from sd_protocols import SDProtocols

# Protokolle laden
sd = SDProtocols()

# Verfügbare Protokolle auflisten
print(f"Geladene Protokolle: {len(sd.get_protocol_list())}")

# Beispiel: Prüfen ob ein Protokoll existiert
# ID 10 = Oregon Scientific v2|v3
if sd.protocol_exists("10"):
    print("Protokoll 10 (Oregon Scientific v2|v3) ist verfügbar.")