# Verwenden von Umgebungsvariablen in Dev Containern (`.devcontainer.env`)

Dieses Dokument beschreibt die Verwendung einer dedizierten Datei zur Bereitstellung von Umgebungsvariablen für Ihren Dev Container, um Geheimnisse und benutzerspezifische Einstellungen von der Versionskontrolle fernzuhalten.

## 1. Zweck

Die Datei dient dazu, **Umgebungsvariablen** (z. B. API-Tokens, geheime Schlüssel, benutzerspezifische Pfade oder Einstellungen) in den laufenden Development Container einzuspeisen. Dies ist ein wichtiger Mechanismus, um zu verhindern, dass sensible oder benutzerspezifische Daten in der Konfigurationsdatei [`devcontainer.json`](.devcontainer/devcontainer.json) hartcodiert oder versehentlich in das Git-Repository committet werden.

## 2. Erstellung und Speicherort

1.  **Speicherort:** Erstellen Sie die Datei manuell. Es wird empfohlen, sie im Ordner [`./.devcontainer`](.devcontainer/) zu speichern, z.B. als [`./.devcontainer/.devcontainer.env`](.devcontainer/.devcontainer.env).
2.  **Versionskontrolle:** **Wichtig:** Fügen Sie den Dateinamen (z.B. `.devcontainer/.devcontainer.env`) sofort der Datei [`./.gitignore`](.gitignore) hinzu, um zu verhindern, dass die Umgebungsvariablen versehentlich in das Git-Repository committet werden.

## 3. Format

Die Datei ist eine einfache Textdatei und folgt den Standard-`.env`-Dateikonventionen:

*   Jede Zeile enthält ein Schlüssel-Wert-Paar.
*   Das Format ist `SCHLÜSSEL=WERT`.
*   Kommentare beginnen mit `#`.

```
# Beispiel für .devcontainer.env
API_KEY=mein_geheimer_schluessel_12345
USER_EMAIL=ich@beispiel.de
LOG_LEVEL=DEBUG
```

## 4. Verwendung mit Dockerfile/Image-basierten Dev Containern

Wenn Sie eine Konfiguration verwenden, die direkt auf einem Dockerfile oder einem Docker-Image basiert (erkennbar an der Verwendung von `"dockerfile"` oder `"image"` in [`devcontainer.json`](.devcontainer/devcontainer.json)), verwenden Sie das Docker CLI-Argument `--env-file` in der Eigenschaft `"runArgs"`:

```json
// .devcontainer/devcontainer.json
{
    // ...
    "runArgs": [
        "--env-file", 
        "./.devcontainer.env" // Pfad relativ zum .devcontainer-Ordner
    ]
    // ...
}
```

## 5. Verwendung mit Docker Compose-basierten Dev Containern

Wenn Sie eine Konfiguration verwenden, die auf Docker Compose basiert (erkennbar an der Verwendung von `"dockerComposeFile"` in [`devcontainer.json`](.devcontainer/devcontainer.json)), fügen Sie den Schlüssel `env_file` zum entsprechenden Service in Ihrer [`docker-compose.yml`](docker-compose.yml) hinzu:

```yaml
# docker-compose.yml
version: '3.8'
services:
  app:
    build: .
    # ... andere Konfigurationen ...
    env_file:
      - ./.devcontainer/.devcontainer.env # Pfad relativ zur docker-compose.yml
```

## 6. Best Practice: Beispiel-Datei

Um anderen Entwicklern mitzuteilen, welche Umgebungsvariablen benötigt werden, existiert eine **Beispiel-Datei**:

*   **Name:** [`./.devcontainer/.devcontainer.env.sample`](.devcontainer/.devcontainer.env.sample) (oder ähnlich).
*   **Inhalt:** Führen Sie die benötigten Variablen mit leeren oder Platzhalter-Werten auf.

```
# .devcontainer/.devcontainer.env.sample
# Kopieren Sie diese Datei nach .devcontainer/.devcontainer.env und füllen Sie die Werte aus.

# MQTT Broker Konfiguration
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_TOPIC=signalduino/messages

# Signalduino Verbindungseinstellungen
SIGNALDUINO_SERIAL_PORT=/dev/ttyUSB0
SIGNALDUINO_BAUD=57600
# SIGNALDUINO_TCP_HOST=192.168.1.10
# SIGNALDUINO_TCP_PORT=23

# Logging
LOG_LEVEL=INFO