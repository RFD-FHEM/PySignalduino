# Architekturproposal: Erweiterung der MQTT-Schnittstelle um Firmware-Befehle

**Datum:** 2025-12-21
**Basis:** ADR-001 (Topic-Struktur), ADR-002 (Command Dispatcher)

## 1. Einleitung und Zielsetzung

Dieses Architekturproposal definiert die Integration von direkten Firmware-Steuerungsbefehlen (`set raw`, `set cc1101_reg`) in die `PySignalduino` MQTT-API (V1). Ziel ist es, die volle Funktionalität der seriellen Schnittstelle über MQTT verfügbar zu machen.

## 2. Definition der MQTT-Kommandos

Die neuen Befehle folgen der in ADR-001 definierten Struktur: `signalduino/v1/commands/set/<target>/<parameter>`. Das Payload-Format ist strikt JSON und wird durch den Command Dispatcher validiert.

### 2.1. `set raw` (Senden von rohen Firmware-Befehlen)

| Schlüssel | Wert |
| :--- | :--- |
| **Topic** | `signalduino/v1/commands/set/firmware/raw` |
| **Payload-Format** | JSON |
| **Payload-Schema (Teilauszug)** | Objekt mit `value` (String, z.B. C11) |
| **Beispiel Payload** | `{"value": "C11"}` |
| **Beschreibung** | Leitet den String im Feld `value` direkt als seriellen Befehl an die Firmware weiter. |

### 2.2. `set cc1101_reg` (Setzen eines CC1101-Registers)

| Schlüssel | Wert |
| :--- | :--- |
| **Topic** | `signalduino/v1/commands/set/cc1101/register` |
| **Payload-Format** | JSON |
| **Payload-Schema (Teilauszug)** | Objekt mit `address` (Hex-String, 2 Zeichen) und `value` (Hex-String, 2 Zeichen) |
| **Beispiel Payload** | `{"address": "0D", "value": "2E"}` |
| **Beschreibung** | Setzt das CC1101-Register an der Adresse `address` auf den Wert `value`. Alle Werte müssen als Hex-Strings (z.B. "0D") übergeben werden. |

## 3. Architekturentscheidung (ADR-Auszug)

> **Titel:** Integration der Firmware-Steuerbefehle (`raw`, `cc1101_reg`) in die V1 MQTT-API
> 
> **Kontext:** Um PySignalduino zu einem vollständigen Backend für Steuerungs-Frontends (wie FHEM) zu machen, ist es erforderlich, die direkten Steuerungsmöglichkeiten der seriellen Schnittstelle (z.B. Frequenz- und Registermanipulation) über die standardisierte MQTT-API anzubieten.
> 
> **Entscheidung:**
> Die Befehle `set raw` und `set cc1101_reg` werden unter den in Abschnitt 2.1 und 2.2 definierten Topics und Payloads in die MQTT-Schnittstelle integriert. Die strikte **JSON-Schema-Validierung** wird für beide Befehle implementiert.
> 
> **Begründung:**
> 1. **Vollständigkeit:** Diese Befehle schließen eine kritische Lücke im Funktionsumfang der MQTT-API im Vergleich zur seriellen Schnittstelle.
> 2. **Sicherheit:** Die direkte Manipulation der CC1101-Hardware erfordert höchste Sorgfalt. Die in ADR-002 beschlossene JSON-Schema-Validierung ist für diese Befehle zwingend erforderlich, um sicherzustellen, dass nur gültige Adressen und Werte an die Firmware gesendet werden.
> 3. **Konsistenz:** Durch die Verwendung der `signalduino/v1/commands/set` Topic-Hierarchie wird die Konsistenz mit dem Rest der API gewahrt.

## 4. Compliance-Checks (Mermaid)

Der erweiterte Workflow visualisiert die Verarbeitung eines CC1101-Registersatzbefehls.

```mermaid
flowchart TD
    A[MQTT Client sendet set cc1101_reg] --> B{Topic: signalduino/v1/commands/set/cc1101/register}
    B --> C[MQTT Interface empfängt Payload]
    C --> D[Command Dispatcher]
    D --> E{Input Validator (JSON Schema)}
    E -- Validierung fehlgeschlagen --> F[Error Response Topic publish]
    E -- Validierung erfolgreich --> G[SignalduinoController.execute_command]
    G --> H[Controller generiert serielle Raw-Befehle]
    H --> I[Transport Layer sendet an Hardware]
    I --> J{Hardware (SIGNALduino)}
    J --> K[Hardware setzt CC1101 Register]
```
