# SignalDuino MQTT Bridge

Dieses Projekt ist eine Python-Portierung der SIGNALDuino-Protokolle aus FHEM.
Es stellt die Protokolle als Dictionary bereit und bietet eine objektorientierte
Schnittstelle (`SDProtocols`).

## Struktur
- `sd_protocols/` – Kernmodule
- `examples/` – Demo-Skripte
- `tests/` – Unit-Tests mit pytest

## Tests ausführen
```bash
pip install -r requirements.txt
pytest