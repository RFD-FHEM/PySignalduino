# Asyncio-Migrationsleitfaden

## Übersicht

Mit dem Commit **b212b90** (10. Dezember 2025) wurde die gesamte Thread-basierte Implementierung durch **asyncio** ersetzt. Dieser Leitfaden hilft bestehenden Nutzern, ihre Integrationen und Skripte an die neue asynchrone API anzupassen.

## Warum asyncio?

*   **Höhere Performance** – Asynchrone I/O-Operationen blockieren nicht den gesamten Prozess.
*   **Einfachere Integration** – Moderne Python-Bibliotheken setzen zunehmend auf asyncio.
*   **Bessere Wartbarkeit** – Klare Trennung von Aufgaben durch `async/await`.
*   **MQTT-Integration** – Die neue MQTT-Bridge nutzt `aiomqtt`, das nahtlos in asyncio‑Event‑Loops integriert ist.

## Wichtige Änderungen

### 1. Controller-API

**Vorher (Thread-basiert):**
```python
from signalduino.controller import SignalduinoController
from signalduino.transport import SerialTransport

transport = SerialTransport(port="/dev/ttyUSB0")
controller = SignalduinoController(transport=transport)
controller.start()  # Startet Reader- und Parser-Threads
controller.join()   # Blockiert, bis Threads beendet sind
```

**Nachher (asynchron):**
```python
import asyncio
from signalduino.controller import SignalduinoController
from signalduino.transport import SerialTransport

async def main():
    transport = SerialTransport(port="/dev/ttyUSB0")
    controller = SignalduinoController(transport=transport)
    async with controller:          # Asynchroner Kontextmanager
        await controller.run()      # Asynchrone Hauptschleife

asyncio.run(main())
```

### 2. Transport-Klassen

Alle Transporte (`SerialTransport`, `TCPTransport`) sind jetzt asynchrone Kontextmanager und bieten asynchrone Methoden:

*   `await transport.aopen()` statt `transport.open()`
*   `await transport.aclose()` statt `transport.close()`
*   `await transport.readline()` statt `transport.readline()` (blockierend)
*   `await transport.write_line(data)` statt `transport.write_line(data)`

### 3. MQTT-Publisher

Der `MqttPublisher` ist jetzt vollständig asynchron und muss mit `async with` verwendet werden:

```python
from signalduino.mqtt import MqttPublisher
from signalduino.types import DecodedMessage

async def example():
    publisher = MqttPublisher()
    async with publisher:
        msg = DecodedMessage(...)
        await publisher.publish(msg)
```

### 4. Callbacks

Callback-Funktionen, die an den Controller übergeben werden (z.B. `message_callback`), müssen **asynchron** sein:

```python
async def my_callback(message: DecodedMessage):
    print(f"Received: {message.protocol_id}")
    # Asynchrone Operationen erlaubt, z.B.:
    # await database.store(message)

controller = SignalduinoController(
    transport=transport,
    message_callback=my_callback   # ← async Funktion
)
```

### 5. Befehlsausführung

Die Ausführung von Befehlen (z.B. `version`, `set`) erfolgt asynchron über den Controller:

```python
async with controller:
    version = await controller.execute_command("version")
    print(f"Firmware: {version}")
```

## Schritt-für-Schritt Migration

### Schritt 1: Abhängigkeiten aktualisieren

Stellen Sie sicher, dass Sie die neueste Version des Projekts installiert haben:

```bash
cd PySignalduino
git pull
pip install -e . --upgrade
```

Die neuen Abhängigkeiten (`aiomqtt`, `pyserial-asyncio`) werden automatisch installiert.

### Schritt 2: Hauptprogramm umschreiben

Wenn Sie ein eigenes Skript verwenden, das den Controller direkt instanziiert:

1.  **Event‑Loop** – Verwenden Sie `asyncio.run()` als Einstiegspunkt.
2.  **Kontextmanager** – Nutzen Sie `async with controller:` statt `controller.start()`/`controller.stop()`.
3.  **Async/Await** – Markieren Sie alle Funktionen, die auf den Controller zugreifen, mit `async` und verwenden Sie `await` für asynchrone Aufrufe.

**Beispiel – Migration eines einfachen Skripts:**

```python
# ALT
def main():
    transport = SerialTransport(...)
    controller = SignalduinoController(transport)
    controller.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop()

# NEU
async def main():
    transport = SerialTransport(...)
    controller = SignalduinoController(transport)
    async with controller:
        # Hauptschleife: Controller.run() läuft intern
        await controller.run(timeout=None)

if __name__ == "__main__":
    asyncio.run(main())
```

### Schritt 3: Callbacks anpassen

Suchen Sie nach Callback‑Definitionen (z.B. `message_callback`, `command_callback`) und machen Sie sie asynchron:

```python
# ALT
def on_message(msg):
    print(msg)

# NEU
async def on_message(msg):
    print(msg)
    # Falls Sie asynchrone Bibliotheken verwenden:
    # await mqtt_client.publish(...)
```

### Schritt 4: Tests aktualisieren

Falls Sie eigene Tests haben, die `unittest` oder `pytest` mit Thread‑Mocks verwenden, müssen Sie auf `pytest‑asyncio` und `AsyncMock` umstellen:

```python
# ALT
with patch("signalduino.controller.SerialTransport") as MockTransport:
    transport = MockTransport.return_value
    transport.readline.return_value = "MS;..."

# NEU
@pytest.mark.asyncio
async def test_controller():
    with patch("signalduino.controller.SerialTransport") as MockTransport:
        transport = AsyncMock()
        transport.readline.return_value = "MS;..."
```

## Häufige Fallstricke

### 1. Blockierende Aufrufe in asynchronem Kontext

Vermeiden Sie blockierende Funktionen wie `time.sleep()` oder `serial.Serial.read()`. Verwenden Sie stattdessen:

*   `await asyncio.sleep(1)` statt `time.sleep(1)`
*   `await transport.readline()` statt `transport.readline()` (blockierend)

### 2. Vergessen von `await`

Vergessene `await`‑Schlüsselwörter führen zu `RuntimeWarning` oder hängen das Programm auf. Achten Sie besonders auf:

*   `await controller.run()`
*   `await publisher.publish()`
*   `await transport.write_line()`

### 3. Gleichzeitige Verwendung von Threads und asyncio

Wenn Sie Threads und asyncio mischen müssen (z.B. für Legacy‑Code), verwenden Sie `asyncio.run_coroutine_threadsafe()` oder `loop.call_soon_threadsafe()`.

## Vollständiges Migrationsbeispiel

Hier ein komplettes Beispiel, das einen einfachen MQTT‑Bridge‑Service migriert:

```python
# ALT: Thread-basierter Bridge-Service
import time
from signalduino.controller import SignalduinoController
from signalduino.transport import SerialTransport
from signalduino.mqtt import MqttPublisher

def message_callback(msg):
    publisher = MqttPublisher()
    publisher.connect()
    publisher.publish(msg)
    publisher.disconnect()

def main():
    transport = SerialTransport(port="/dev/ttyUSB0")
    controller = SignalduinoController(
        transport=transport,
        message_callback=message_callback
    )
    controller.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop()

# NEU: Asynchrone Version
import asyncio
from signalduino.controller import SignalduinoController
from signalduino.transport import SerialTransport
from signalduino.mqtt import MqttPublisher

async def message_callback(msg):
    # Publisher ist jetzt asynchron und muss mit async with verwendet werden
    publisher = MqttPublisher()
    async with publisher:
        await publisher.publish(msg)

async def main():
    transport = SerialTransport(port="/dev/ttyUSB0")
    controller = SignalduinoController(
        transport=transport,
        message_callback=message_callback
    )
    async with controller:
        await controller.run()

if __name__ == "__main__":
    asyncio.run(main())
```

## Hilfe und Fehlerbehebung

*   **Logging aktivieren** – Setzen Sie `LOG_LEVEL=DEBUG`, um detaillierte Informationen über asynchrone Operationen zu erhalten.
*   **Tests als Referenz** – Die Testdateien `tests/test_controller.py` und `tests/test_mqtt.py` zeigen korrekte asynchrone Nutzung.
*   **Issue melden** – Falls Sie auf Probleme stoßen, öffnen Sie ein Issue im Repository.

## Rückwärtskompatibilität

Es gibt **keine** Rückwärtskompatibilität für die Thread‑API. Ältere Skripte, die `controller.start()` oder `controller.stop()` aufrufen, müssen angepasst werden.

## Nächste Schritte

Nach der Migration können Sie die neuen Features nutzen:

*   **MQTT‑Integration** – Nutzen Sie den integrierten Publisher/Subscriber.
*   **Kompression** – Aktivieren Sie die Payload‑Kompression für effizientere MQTT‑Nachrichten.
*   **Heartbeat** – Überwachen Sie die Verbindung mit dem MQTT‑Heartbeat.

Weitere Informationen finden Sie in der [Benutzerdokumentation](01_user_guide/usage.adoc) und der [MQTT‑Dokumentation](01_user_guide/mqtt.adoc).