# ADR 002: Command Dispatcher Pattern und JSON-Schema-Validierung

## Kontext

Die Verarbeitung eingehender MQTT-Befehle erfordert Robustheit, Skalierbarkeit und strenge Eingabeverifizierung, insbesondere da die Befehle direkt in serielle Kommandos für die Firmware übersetzt werden, was kritische Hardware-Einstellungen beeinflussen kann (z.B. CC1101-Register). Ein direktes Mapping von Topic zu Funktion ist unflexibel und anfällig für ungültige Eingaben.

## Entscheidung

Wir implementieren einen dedizierten **Command Dispatcher** als zentrale Komponente zwischen der MQTT-Schnittstelle und dem `SignalduinoController`. Jeder eingehende Befehl wird vor der Ausführung einer strikten **JSON-Schema-Validierung** unterzogen.

**Workflow des Dispatchers:**
1.  MQTT-Interface empfängt Payload.
2.  Dispatcher extrahiert `command_name`, `target`, `type` und `req_id`.
3.  Dispatcher übergibt Payload an den **Input Validator**.
4.  Der Validator verwendet ein dem `command_name` zugeordnetes JSON-Schema, um die `value` und `parameters` zu prüfen.
5.  Nur bei erfolgreicher Validierung wird der Befehl an den **Command Executor** weitergeleitet.

## Begründung

1.  **Sicherheit und Stabilität:** Die JSON-Schema-Validierung garantiert, dass nur erwartete Datenformate und Wertebereiche an den Core-Controller und letztlich an die serielle Schnittstelle gelangen. Dies verhindert Pufferüberläufe oder die Einstellung illegaler Hardware-Werte.
2.  **Entkopplung:** Der Command Dispatcher entkoppelt die MQTT-Topics von den internen Python-Methoden. Topic-Änderungen erfordern keine Anpassung der Business-Logik.
3.  **Flexibilität:** Das Muster ermöglicht eine einfache Erweiterung um neue Befehle und Befehls-Typen (z.B. zukünftige `batch`-Befehle) ohne Modifikation der Kernlogik.
4.  **Strukturierte Fehlerbehandlung:** Validierungsfehler können sofort mit einem HTTP 400-ähnlichen Status (Bad Request) beantwortet werden, bevor Ressourcen für die serielle Kommunikation verschwendet werden.

## Konsequenzen

*   **Neue Komponenten:** Es müssen die Komponenten `Command Dispatcher` und `Input Validator` (mit Integration einer JSON-Schema-Bibliothek wie `jsonschema`) implementiert werden.
*   **Wartungsaufwand:** Für jeden neuen Befehl muss ein entsprechendes JSON-Schema definiert und gewartet werden. Dies ist ein akzeptabler Aufwand im Austausch für erhöhte Robustheit und Sicherheit.
*   **Abhängigkeiten:** Die externe Abhängigkeit zu einer JSON-Schema-Validierungsbibliothek wird hinzugefügt.

---
[Ende der ADRs für diese Architekturphase]