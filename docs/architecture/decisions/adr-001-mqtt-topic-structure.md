# ADR 001: MQTT Topic Struktur und Versionierung

## Kontext

Die vorhandene MQTT-Integration in PySignalduino verfügt über eine minimale Topic-Struktur für Telemetrie, aber keine konsistente, versionierte Befehlsschnittstelle. Für die Implementierung einer konsistenten API für alle Firmware-Parameter ist eine klare Struktur und Versionierung erforderlich, um Zukunftsfähigkeit und Wartbarkeit zu gewährleisten.

## Entscheidung

Wir führen eine hierarchische und versionierte Topic-Struktur für Befehle, Antworten und Statusmeldungen ein.

**Struktur:** `signalduino/<version>/<type>/<target>/<parameter>`

**Beispiele:**
*   **Befehle (Commands):** `signalduino/v1/commands/set/cc1101/frequency`
*   **Antworten (Responses):** `signalduino/v1/responses/get/system/version`
*   **Fehler (Errors):** `signalduino/v1/errors/set/cc1101/frequency`
*   **Status (State):** `signalduino/v1/state/device/uptime`

## Begründung

1.  **Versionierung (`v1`):** Durch die Topic-Versionierung können wir später Breaking Changes einführen (z.B. `v2`) und ältere Clients über einen längeren Zeitraum unterstützen, ohne die gesamte Infrastruktur sofort anpassen zu müssen.
2.  **Hierarchie (`commands`/`responses`/`errors`):** Die klare Trennung von Request- und Response-Topics vereinfacht die clientseitige Implementierung und ermöglicht eine präzise Konfiguration von MQTT-ACLs (Access Control Lists). Clients müssen nur Topics abonnieren, die für ihre Rolle relevant sind (z.B. nur `responses` und `errors`).
3.  **Konsistenz (`get`/`set`/`command`):** Das Paradigma spiegelt die gängige Praxis in modernen APIs (REST, IoT) wider und bietet eine intuitive Steuerung für alle Firmware-Parameter.

## Konsequenzen

*   **Code-Änderungen:** Der MQTT-Client in PySignalduino muss so erweitert werden, dass er Befehle auf diesen spezifischen Topics abonniert und eingehende Payloads entsprechend dem `type` (`get`/`set`/`command`) an einen Command Dispatcher weiterleitet.
*   **Kompatibilität:** Es besteht keine Abwärtskompatibilität zur bisherigen minimalen MQTT-Integration. Da diese jedoch ohnehin unstrukturiert und unvollständig war, wird dies als akzeptabler Breaking Change im Zuge der Implementierung der V1-API angesehen.
*   **Dokumentation:** Alle Clients und die Benutzerdokumentation müssen auf diese neue Topic-Struktur umgestellt werden.

---
[Fortsetzung in ADR-002]