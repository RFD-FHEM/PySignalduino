# Architekturproposal: FHEM-Integration über MQTT

## Zusammenfassung
Die empfohlene Architektur für die Anbindung von PySignalduino an FHEM basiert auf der Nutzung eines zentralen MQTT-Brokers. PySignalduino agiert als MQTT-Publisher und Subscriber, während FHEM über das `MQTT_DEVICE` Modul die Daten von PySignalduino konsumiert und Steuerbefehle zurücksendet.

## Datenfluss-Diagramm

```mermaid
flowchart TD
    A[SignalDuino Hardware] -->|Seriell/TCP| B(PySignalduino Anwendung);
    
    subgraph MQTT Broker (z.B. Mosquitto)
        M(MQTT Broker);
    end
    
    B -->|Publish (signalduino/messages/decoded/...)| M;
    B <--|Subscribe (signalduino/commands/#)| M;
    
    C(FHEM Server) -->|Verbindet sich mit| M;
    C <--|Abonniert Topics| M;
    C -->|Sendet Steuerbefehle| M;
    
    M -->|Topic: signalduino/messages/#| D[FHEM MQTT_DEVICE Modul];
    D -->|Internal FHEM Logic| C;
    C -->|Befehle publizieren| M;
    M -->|Topic: signalduino/commands/#| B;
    
    style B fill:#f9f,stroke:#333
    style C fill:#ccf,stroke:#333
    style M fill:#ffa,stroke:#333
    
    %% Datenfluss
    subgraph Datenfluss
        direction LR
        S1[PySignalduino publiziert] --> S2{MQTT Broker} --> S3[FHEM abonniert];
    end
    
    %% Befehlsfluss
    subgraph Befehlsfluss
        direction LR
        S4[FHEM Steuerbefehl] --> S5{MQTT Broker} --> S6[PySignalduino Subscriber];
    end

    B --> Datenfluss;
    B <-- Befehlsfluss;
    C --> Datenfluss;
    C <-- Befehlsfluss;
```

## Implementierungsplan (TODO-Liste)
Da die PySignalduino-Implementierung bereits vorhanden ist, konzentriert sich der Implementierungsplan auf die Erstellung von Dokumentation und Beispielen.

[x] Architektur-Entscheidung dokumentiert: Verwendung eines externen MQTT-Brokers für FHEM-Integration
[x] Devcontainer-Konfiguration geprüft und als ausreichend befunden.
[-] Mermaid-Diagramm zur Visualisierung des Datenflusses (PySignalduino <-> MQTT Broker <-> FHEM) erstellt.
[ ] FHEM-spezifische Konfigurationsbeispiele in `docs/01_user_guide/mqtt.adoc` ergänzen.
[ ] Plan dem Benutzer zur Genehmigung vorlegen und Moduswechsel zu 'code' vorschlagen.
