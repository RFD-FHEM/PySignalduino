# PySignalduino – Asynchrone MQTT-Bridge für SIGNALDuino

Dieses Projekt ist eine moderne Python-Implementierung der SIGNALDuino-Protokolle mit vollständiger **asyncio**-Unterstützung und integrierter **MQTT-Bridge**. Es ermöglicht die Kommunikation mit SIGNALDuino-Hardware (über serielle Schnittstelle oder TCP) und veröffentlicht empfangene Signale sowie empfängt Steuerbefehle über MQTT.

## Projektgeschichte

PySignalduino ist Teil des **RFD-FHEM**-Ökosystems, das ursprünglich als Perl-basierte Lösung für die Hausautomationssoftware FHEM begann. Die Entwicklung lässt sich in folgende Meilensteine unterteilen:

### Ursprung: RFD-FHEM und SIGNALDuino
- **2010er Jahre**: Die RFD-FHEM-Community entwickelte Hardware- und Softwarelösungen für die Funkkommunikation mit 433/868 MHz Geräten.
- **SIGNALDuino-Hardware**: Ein Arduino-basierter Transceiver mit CC1101 Funkmodul, der als kostengünstige Alternative zu kommerziellen Lösungen entstand.
- **Perl-Implementierung**: Die ursprüngliche Protokollimplementierung erfolgte in Perl als FHEM-Modul `00_SIGNALduino.pm`.

### Migration zu Python
- **2020er Jahre**: Mit der wachsenden Popularität von Python und MQTT entstand der Bedarf nach einer moderneren, asynchronen Lösung.
- **PySignalduino**: Diese Bibliothek portiert die Perl-Protokolle (`SD_Protocols.pm`, `SD_ProtocolData.pm`) in eine native Python-Implementierung.
- **Asynchrone Architektur**: Vollständige `asyncio`-Integration für bessere Performance und einfachere Integration in moderne IoT-Systeme.

### Community-Entwicklung
- **Open Source**: Das Projekt wird von einer aktiven Community auf GitHub gepflegt und weiterentwickelt.
- **Firmware-Entwicklung**: Die SIGNALDuino-Firmware wird parallel im Repository [RFD-FHEM/SIGNALDuino](https://github.com/RFD-FHEM/SIGNALDuino) entwickelt.
- **Version 3.5.0**: Die aktuelle Firmware-Version bietet erweiterte Funktionen wie WiFi-Unterstützung für ESP32-basierte Boards.

### Entwicklungsstatus

> **⚠️ Entwicklungsstatus**
>
> PySignalduino befindet sich noch in aktiver Entwicklung und hat noch kein offizielles Release veröffentlicht. Die API kann sich zwischen Versionen ändern. Entwickler sollten bei der Verwendung Vorsicht walten lassen und auf mögliche Breaking Changes vorbereitet sein.

### PySignalduino vs. Original
PySignalduino ist keine direkte Portierung, sondern eine Neuimplementierung mit folgenden Unterschieden:
- **Asynchrone Verarbeitung**: Statt Threads wird `asyncio` verwendet.
- **MQTT-Integration**: Eingebaute MQTT-Bridge für nahtlose Integration in IoT-Ökosysteme.
- **Moderne Python-Praktiken**: Typisierung, strukturierte Logging, Konfiguration über Umgebungsvariablen.

## Controller-Code und Firmware

Die SIGNALDuino-Firmware (Microcontroller-Code) wird in einem separaten Repository entwickelt:

- **GitHub Repository**: https://github.com/RFD-FHEM/SIGNALDuino
- **Aktuelle Version**: v3.5.0
- **Unterstützte Hardware**:
  - Arduino Nano mit CC1101
  - ESP32-basierte Boards (z.B. ESP32-DevKitC)
  - Maple Mini (STM32)
- **Build-Anleitungen**: Das Repository enthält PlatformIO-Konfigurationen und Arduino-IDE-Projektdateien für einfache Kompilierung.

## Hauptmerkmale

*   **Vollständig asynchron** – Basierend auf `asyncio` für hohe Performance und einfache Integration in asynchrone Anwendungen.
*   **MQTT-Integration** – Automatisches Publizieren dekodierter Nachrichten in konfigurierbare Topics und Empfang von Steuerbefehlen (z.B. `version`, `set`, `mqtt`).
*   **Unterstützte Transporte** – Serielle Verbindung (über `pyserial-asyncio`) und TCP-Verbindung.
*   **Umfangreiche Protokollbibliothek** – Portierung der originalen FHEM‑SIGNALDuino‑Protokolle mit `SDProtocols` und `SDProtocolData`.
*   **Konfiguration über Umgebungsvariablen** – Einfache Einrichtung ohne Codeänderungen.
*   **Ausführbares Hauptprogramm** – `main.py` bietet eine sofort einsatzbereite Lösung mit Logging, Signalbehandlung und Timeout‑Steuerung.
*   **Komprimierte Datenübertragung** – Effiziente Payload‑Kompression für MQTT‑Nachrichten.

## Installation

### Voraussetzungen

*   Python 3.8 oder höher
*   pip (Python-Paketmanager)

### Paketinstallation

1.  Repository klonen:
    ```bash
    git clone https://github.com/.../PySignalduino.git
    cd PySignalduino
    ```

2.  Abhängigkeiten installieren (empfohlen in einer virtuellen Umgebung):
    ```bash
    pip install -e .
    ```

    Dies installiert das Paket im Entwicklermodus inklusive aller Runtime‑Abhängigkeiten:
    *   `pyserial`
    *   `pyserial-asyncio`
    *   `aiomqtt` (asynchrone MQTT‑Client‑Bibliothek)
    *   `python-dotenv`
    *   `requests`

3.  Für Entwicklung und Tests zusätzlich:
    ```bash
    pip install -r requirements-dev.txt
    ```

## Schnellstart

1.  **Umgebungsvariablen setzen** (optional). Erstelle eine `.env`‑Datei im Projektverzeichnis:
    ```bash
    SIGNALDUINO_SERIAL_PORT=/dev/ttyUSB0
    MQTT_HOST=localhost
    LOG_LEVEL=INFO
    ```

2.  **Programm starten**:
    ```bash
    python3 main.py --serial /dev/ttyUSB0 --mqtt-host localhost
    ```

    Oder nutze die Umgebungsvariablen:
    ```bash
    python3 main.py
    ```

3.  **Ausgabe beobachten**. Das Programm verbindet sich mit dem SIGNALDuino, initialisiert die Protokolle und beginnt mit dem Empfang. Dekodierte Nachrichten werden im Log ausgegeben und – sofern MQTT konfiguriert ist – an den Broker gesendet.

## Konfiguration

### Umgebungsvariablen

| Variable | Beschreibung | Beispiel |
|----------|--------------|----------|
| `SIGNALDUINO_SERIAL_PORT` | Serieller Port (z.B. `/dev/ttyUSB0`) | `/dev/ttyACM0` |
| `SIGNALDUINO_BAUD` | Baudrate (Standard: `57600`) | `115200` |
| `SIGNALDUINO_TCP_HOST` | TCP‑Host (alternativ zu Serial) | `192.168.1.10` |
| `SIGNALDUINO_TCP_PORT` | TCP‑Port (Standard: `23`) | `23` |
| `MQTT_HOST` | MQTT‑Broker‑Host | `mqtt.eclipseprojects.io` |
| `MQTT_PORT` | MQTT‑Broker‑Port (Standard: `1883`) | `1883` |
| `MQTT_USERNAME` | Benutzername für MQTT‑Authentifizierung | `user` |
| `MQTT_PASSWORD` | Passwort für MQTT‑Authentifizierung | `pass` |
| `MQTT_TOPIC` | Basis‑Topic für Publikation/Subscription | `signalduino/` |
| `LOG_LEVEL` | Logging‑Level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `DEBUG` |

### Kommandozeilenargumente

Alle Umgebungsvariablen können auch als Argumente übergeben werden (sie haben Vorrang). Eine vollständige Liste erhält man mit:

```bash
python3 main.py --help
```

Wichtige Optionen:
*   `--serial PORT` – Serieller Port
*   `--tcp HOST` – TCP‑Host
*   `--mqtt-host HOST` – MQTT‑Broker
*   `--mqtt-topic TOPIC` – Basis‑Topic
*   `--timeout SECONDS` – Automatisches Beenden nach N Sekunden
*   `--log-level LEVEL` – Logging‑Level

## MQTT‑Integration

### Publizierte Topics

*   `{basis_topic}/decoded` – JSON‑Nachricht jedes dekodierten Signals.
*   `{basis_topic}/raw` – Rohdaten (falls aktiviert).
*   `{basis_topic}/status` – Statusmeldungen (Verbunden/Getrennt/Fehler).

### Abonnierte Topics (Befehle)

*   `{basis_topic}/cmd/version` – Liefert die Firmware‑Version des SIGNALDuino.
*   `{basis_topic}/cmd/set` – Sendet einen `set`‑Befehl an den SIGNALDuino.
*   `{basis_topic}/cmd/mqtt` – Steuert die MQTT‑Integration (z.B. Kompression an/aus).

Die genauen Payload‑Formate und weitere Befehle sind in der [Befehlsreferenz](docs/03_protocol_reference/commands.adoc) dokumentiert.

## Projektstruktur

```
PySignalduino/
├── signalduino/              # Hauptpaket
│   ├── controller.py         # Asynchroner Controller
│   ├── mqtt.py               # MQTT‑Publisher/Subscriber
│   ├── transport.py          # Serielle/TCP‑Transporte (asyncio)
│   ├── commands.py           # Befehlsimplementierung
│   └── ...
├── sd_protocols/             # Protokollbibliothek (SDProtocols)
├── tests/                    # Umfangreiche Testsuite
├── docs/                     # Dokumentation (AsciiDoc)
├── main.py                   # Ausführbares Hauptprogramm
├── pyproject.toml            # Paketkonfiguration
└── requirements*.txt         # Abhängigkeiten
```

## Entwicklung

### Tests ausführen

```bash
pytest
```

Für Tests mit Coverage‑Bericht:

```bash
pytest --cov=signalduino --cov=sd_protocols
```

### Beitragen

Beiträge sind willkommen! Bitte erstelle einen Pull‑Request oder öffne ein Issue im Repository.

## Dokumentation

*   [Installationsanleitung](docs/01_user_guide/installation.adoc)
*   [Benutzerhandbuch](docs/01_user_guide/usage.adoc)
*   [Asyncio‑Migrationsleitfaden](docs/ASYNCIO_MIGRATION.md)
*   [Protokollreferenz](docs/03_protocol_reference/protocol_details.adoc)
*   [Befehlsreferenz](docs/01_user_guide/usage.adoc#_command_interface)

## SEO & Sitemap

Die Dokumentation wird automatisch mit einer dynamischen Sitemap (`sitemap.xml`) und branch‑spezifischen `robots.txt`‑Dateien versehen, um die Auffindbarkeit in Suchmaschinen zu verbessern.

*   **Sitemap‑Generierung:** Das Skript `tools/generate_sitemap.py` scannt den Build‑Output, weist Prioritäten und Update‑Frequenzen zu und generiert eine valide XML‑Sitemap gemäß sitemaps.org.
*   **Branch‑spezifische URLs:** Für die Branches `main`, `preview` und `develop` werden unterschiedliche Base‑URLs verwendet.
*   **Integration in CI/CD:** Der GitHub Actions Workflow `.github/workflows/docs.yml` generiert die Sitemap automatisch nach jedem Build und passt die `robots.txt` entsprechend an.

Weitere Details zur Architektur finden Sie im [Architektur‑Dokument](docs/02_developer_guide/architecture.adoc#dokumentations-infrastruktur-sitemap--seo).

## Lizenz

Dieses Projekt steht unter der MIT‑Lizenz – siehe [LICENSE](LICENSE) für Details.

## Danksagung

Basierend auf der originalen FHEM‑SIGNALDuino‑Implementierung von [@Sidey79](https://github.com/Sidey79) und der Community.