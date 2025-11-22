# Manchester (mc*) & PostDemodulation (postDemo*) Migration Plan

## Übersicht

Alle Funktionen in `lib/SD_Protocols.pm` mit "mc" oder "postDemo" Präfix müssen von Perl zu Python konvertiert werden.

### Manchester-Funktionen (Format: manchester, Signalverarbeitung)

| Funktion | Zeile | Beschreibung | Status | Python-Modul |
|----------|-------|-------------|--------|--------|
| `mc2dmc` | 427 | Manchester zu Differential Manchester | ✅ DONE (helpers.py) | helpers.py |
| `mcBit2Funkbus` | 458 | Funkbus Protocol Handler | ✅ DONE (test_funkbus.py) | manchester.py |
| `mcBit2Sainlogic` | 558 | Sainlogic Weather Sensor | ⏳ TODO | manchester.py |
| `mcBit2AS` | 668 | AS Protocol Handler | ⏳ TODO | manchester.py |
| `mcBit2Grothe` | 709 | Grothe Protocol Handler | ✅ DONE (methods/grothe.py) | grothe.py |
| `mcBit2Hideki` | 752 | Hideki Sensor Handler | ⏳ TODO | manchester.py |
| `mcBit2Maverick` | 828 | Maverick Sensor Handler | ⏳ TODO | manchester.py |
| `mcBit2OSV1` | 859 | Oregon Scientific V1 | ⏳ TODO | manchester.py |
| `mcBit2OSV2o3` | 932 | Oregon Scientific V2/V3 | ⏳ TODO | manchester.py |
| `mcBit2OSPIR` | 1088 | Oregon Scientific PIR | ⏳ TODO | manchester.py |
| `mcBit2SomfyRTS` | 1119 | Somfy RTS Blinds | ✅ DONE (methods/somfy.py) | somfy.py |
| `mcBit2TFA` | 1149 | TFA Protocol | ⏳ TODO | manchester.py |

**Total: 12 Manchester-Funktionen** (3 bereits konvertiert, 9 ausstehend)

### PostDemodulation-Funktionen (Format: ASK/OOK, Nachverarbeitung)

| Funktion | Zeile | Beschreibung | Status | 
|----------|-------|-------------|--------|
| `postDemo_EM` | 1222 | EM Protocol Post-Processing | ⏳ TODO |
| `postDemo_Revolt` | 1264 | Revolt Protocol Post-Processing | ⏳ TODO |
| `postDemo_FS20` | 1300 | FS20 Protocol Post-Processing | ⏳ TODO |
| `postDemo_FHT80` | 1386 | FHT80 Protocol Post-Processing | ⏳ TODO |
| `postDemo_FHT80TF` | 1464 | FHT80TF Protocol Post-Processing | ⏳ TODO |
| `postDemo_WS2000` | 1529 | WS2000 Weather Station Post-Processing | ⏳ TODO |
| `postDemo_WS7035` | 1655 | WS7035 Protocol Post-Processing | ⏳ TODO |
| `postDemo_WS7053` | 1702 | WS7053 Protocol Post-Processing | ⏳ TODO |
| `postDemo_lengtnPrefix` | 1754 | Length-Prefix Post-Processing | ⏳ TODO |

**Total: 9 PostDemodulation-Funktionen** (0 konvertiert, 9 ausstehend)

## Architektur-Plan

### Manchester-Funktionen (`sd_protocols/manchester.py`)

```python
class ManchesterMixin:
    """Manchester signal encoding/decoding handlers"""
    
    # Basic conversions (from ProtocolHelpersMixin)
    mc2dmc(self, bit_data)           # Manchester → Differential Manchester
    bin_str_2_hex_str(self, num)     # Binary string → Hex conversion
    
    # Protocol-specific handlers
    mcBit2Funkbus(self, name, bit_data, protocol_id, mcbitnum)
    mcBit2Sainlogic(self, name, bit_data, protocol_id)
    mcBit2AS(self, name, bit_data, protocol_id)
    mcBit2Hideki(self, name, bit_data, protocol_id)
    mcBit2Maverick(self, name, bit_data, protocol_id)
    mcBit2OSV1(self, name, bit_data, protocol_id)
    mcBit2OSV2o3(self, name, bit_data, protocol_id)
    mcBit2OSPIR(self, name, bit_data, protocol_id)
    mcBit2SomfyRTS(self, name, bit_data, protocol_id)
    mcBit2TFA(self, name, bit_data, protocol_id)
```

**Struktur:**
- `helpers.py`: Enthält grundlegende Helper (`mc2dmc`, `bin_str_2_hex_str`, etc.)
- `manchester.py`: `ManchesterMixin` mit allen `mcBit2*` Funktionen
- `sd_protocols.py`: Erbt von `ProtocolHelpersMixin` UND `ManchesterMixin`

### PostDemodulation-Funktionen (`sd_protocols/postdemodulation.py`)

```python
class PostdemodulationMixin:
    """Post-demodulation processing for ASK/OOK signals"""
    
    postDemo_EM(self, name, bit_msg)
    postDemo_Revolt(self, name, bit_msg)
    postDemo_FS20(self, name, bit_msg)
    postDemo_FHT80(self, name, bit_msg)
    postDemo_FHT80TF(self, name, bit_msg)
    postDemo_WS2000(self, name, bit_msg)
    postDemo_WS7035(self, name, bit_msg)
    postDemo_WS7053(self, name, bit_msg)
    postDemo_lengtnPrefix(self, name, bit_msg)
```

**Struktur:**
- `postdemodulation.py`: Neue Datei mit `PostdemodulationMixin`
- `sd_protocols.py`: Erbt auch von `PostdemodulationMixin`

## Konvertierungs-Reihenfolge

### Phase 1: Manchester (Priority: Bereits geplant)
1. ✅ `mc2dmc` - DONE (helpers.py)
2. ✅ `mcBit2Funkbus` - DONE (helpers.py + test_funkbus.py)
3. ✅ `mcBit2Grothe` - DONE (methods/grothe.py)
4. ✅ `mcBit2SomfyRTS` - DONE (methods/somfy.py)
5. `mcBit2Sainlogic` - Weather sensor
6. `mcBit2AS` - AS Protocol
7. `mcBit2Hideki` - Hideki sensor
8. `mcBit2Maverick` - Maverick sensor
9. `mcBit2OSV1` - Oregon Scientific V1
10. `mcBit2OSV2o3` - Oregon Scientific V2/V3
11. `mcBit2OSPIR` - Oregon Scientific PIR
12. `mcBit2TFA` - TFA Protocol

### Phase 2: PostDemodulation (Neue Funktionalität)
1. `postDemo_EM` - EM Protocol
2. `postDemo_Revolt` - Revolt Protocol
3. `postDemo_FS20` - FS20 Protocol
4. `postDemo_FHT80` - FHT80 Protocol
5. `postDemo_FHT80TF` - FHT80TF Protocol
6. `postDemo_WS2000` - WS2000 Weather Station
7. `postDemo_WS7035` - WS7035 Protocol
8. `postDemo_WS7053` - WS7053 Protocol
9. `postDemo_lengtnPrefix` - Length-Prefix handling

## Datei-Struktur nach Migration

```
sd_protocols/
├── __init__.py
├── loader.py
├── protocols.json
├── sd_protocol_data.py
├── sd_protocols.py              # Haupt-Klasse (erbt von 3 Mixins)
├── helpers.py                   # ProtocolHelpersMixin (mc2dmc, etc.)
├── manchester.py                # NEW: ManchesterMixin (mcBit2*, mc*)
├── postdemodulation.py          # NEW: PostdemodulationMixin (postDemo_*)
├── methods/
│   ├── grothe.py               # Protocol-spezifische Implementierung
│   ├── rsl.py
│   └── somfy.py                # Protocol-spezifische Implementierung

tests/
├── test_funkbus.py             # ✅ Manchester tests
├── test_helpers.py             # ✅ Helper function tests
├── test_manchester.py          # NEW: mcBit2* functions
├── test_postdemodulation.py    # NEW: postDemo_* functions
├── conftest.py                 # pytest fixtures
└── ...
```

## Test-Strategie

### Für Manchester-Funktionen
- Konvertiere Test-Cases aus RFFHEM Perl Tests
- Location: `https://github.com/RFD-FHEM/RFFHEM/tree/master/t/SD_Protocols/`
- Erstelle parametrisierte Tests für jede Protocol-Variante

### Für PostDemodulation-Funktionen
- Konvertiere Test-Cases aus RFFHEM Perl Tests
- Focus auf Edge-Cases: CRC-Fehler, Längenprüfung, Präambeln
- Integration mit conftest.py Test-Protokollen

## Merging-Strategie

1. **Pro Funktion ein PR**
   - `manchester.py` mit mcBit2Sainlogic, mcBit2AS, etc.
   - `postdemodulation.py` mit postDemo_EM, postDemo_Revolt, etc.
   
2. **Inheritance Chain aktualisieren**
   - `sd_protocols.py` schrittweise erweitern
   - CI/Tests nach jeder Phase

3. **Dokumentation**
   - MIGRATION.md aktualisieren
   - Docstrings für jede neue Funktion

## Referenzen

- **Perl Original**: `/workspaces/PySignalduino/lib/SD_Protocols.pm`
- **Tests**: https://github.com/RFD-FHEM/RFFHEM/tree/master/t/SD_Protocols/
- **Test-Daten**: https://raw.githubusercontent.com/RFD-FHEM/RFFHEM/refs/heads/master/t/SD_Protocols/test_protocolData.json
