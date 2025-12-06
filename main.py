import argparse
import logging
import signal
import sys
import time
import os
import re
from typing import Optional
from dotenv import load_dotenv

from signalduino.constants import SDUINO_CMD_TIMEOUT
from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoConnectionError
from signalduino.transport import SerialTransport, TCPTransport
from signalduino.types import DecodedMessage

# Konfiguration des Loggings
def initialize_logging(log_level_str: str):
    """Initialisiert das Logging basierend auf dem übergebenen String."""
    level = getattr(logging, log_level_str.upper(), logging.INFO)
    
    # Konfiguration des Loggings
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    # Setze den Level auch auf den Root-Logger, falls basicConfig ihn nicht korrekt gesetzt hat (z.B. bei wiederholtem Aufruf)
    logging.getLogger().setLevel(level)

# Initialisiere das Logging mit dem LOG_LEVEL aus der Umgebungsvariable (falls vorhanden)
initialize_logging(os.environ.get("LOG_LEVEL", "INFO"))

logger = logging.getLogger("main")

def message_callback(message: DecodedMessage):
    """Callback-Funktion, die aufgerufen wird, wenn eine Nachricht dekodiert wurde."""
    model = message.metadata.get("model", "Unknown")
    logger.info(
        f"Decoded message received: protocol={message.protocol_id}, "
        f"model={model}, "
        f"payload={message.payload}"
    )
    logger.debug(f"Full Metadata: {message.metadata}")
    if message.raw:
        logger.debug(f"Raw Frame: {message.raw}")

def main():
    # .env-Datei laden. Umgebungsvariablen werden gesetzt, aber CLI-Argumente überschreiben diese.
    load_dotenv()

    # ENV-Variablen für Standardwerte abrufen
    # Transport
    DEFAULT_SERIAL_PORT = os.environ.get("SIGNALDUINO_SERIAL_PORT")
    DEFAULT_TCP_HOST = os.environ.get("SIGNALDUINO_TCP_HOST")
    DEFAULT_BAUD = int(os.environ.get("SIGNALDUINO_BAUD", 57600))
    DEFAULT_TCP_PORT = int(os.environ.get("SIGNALDUINO_TCP_PORT", 23))
    
    # MQTT
    DEFAULT_MQTT_HOST = os.environ.get("MQTT_HOST")
    DEFAULT_MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883)) if os.environ.get("MQTT_PORT") else None
    DEFAULT_MQTT_USERNAME = os.environ.get("MQTT_USERNAME")
    DEFAULT_MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
    DEFAULT_MQTT_TOPIC = os.environ.get("MQTT_TOPIC")

    # Logging
    DEFAULT_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    parser = argparse.ArgumentParser(description="Signalduino Python Controller")
    
    # Verbindungseinstellungen
    # required=True entfernt, da Konfiguration aus ENV stammen kann
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--serial", default=DEFAULT_SERIAL_PORT, help=f"Serieller Port (z.B. /dev/ttyUSB0). Standard: {DEFAULT_SERIAL_PORT or 'Kein Default'}")
    group.add_argument("--tcp", default=DEFAULT_TCP_HOST, help=f"TCP Host (z.B. 192.168.1.10). Standard: {DEFAULT_TCP_HOST or 'Kein Default'}")
    
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Baudrate für serielle Verbindung (Standard: {DEFAULT_BAUD})")
    parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT, help=f"Port für TCP Verbindung (Standard: {DEFAULT_TCP_PORT})")
    
    # MQTT Einstellungen
    parser.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST, help=f"MQTT Broker Host. Standard: {DEFAULT_MQTT_HOST or 'Kein Default'}")
    parser.add_argument("--mqtt-port", type=int, default=DEFAULT_MQTT_PORT, help=f"MQTT Broker Port. Standard: {DEFAULT_MQTT_PORT or 'Kein Default'}")
    parser.add_argument("--mqtt-username", default=DEFAULT_MQTT_USERNAME, help=f"MQTT Broker Benutzername. Standard: {'*Vorhanden*' if DEFAULT_MQTT_USERNAME else 'Kein Default'}")
    parser.add_argument("--mqtt-password", default=DEFAULT_MQTT_PASSWORD, help=f"MQTT Broker Passwort. Standard: {'*Vorhanden*' if DEFAULT_MQTT_PASSWORD else 'Kein Default'}")
    parser.add_argument("--mqtt-topic", default=DEFAULT_MQTT_TOPIC, help=f"MQTT Basis Topic. Standard: {DEFAULT_MQTT_TOPIC or 'Kein Default'}")

    # Logging Einstellung
    parser.add_argument("--log-level", default=DEFAULT_LOG_LEVEL, choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help=f"Logging Level. Standard: {DEFAULT_LOG_LEVEL}")
    
    parser.add_argument("--timeout", type=int, default=None, help="Beendet das Programm nach N Sekunden (optional)")
    
    args = parser.parse_args()

    # Logging Level anpassen (aus CLI oder ENV Default)
    if args.log_level.upper() != DEFAULT_LOG_LEVEL:
        initialize_logging(args.log_level)
        logger.debug(f"Logging Level auf {args.log_level.upper()} angepasst.")
    
    # Manuelle Zuweisung von MQTT ENV Variablen ist nicht mehr nötig, da argparse sie für die gesamte Laufzeit setzt

    # Transport initialisieren
    transport = None
    if args.serial:
        logger.info(f"Initialisiere serielle Verbindung auf {args.serial} mit {args.baud} Baud...")
        transport = SerialTransport(port=args.serial, baudrate=args.baud)
    elif args.tcp:
        logger.info(f"Initialisiere TCP Verbindung zu {args.tcp}:{args.port}...")
        transport = TCPTransport(host=args.tcp, port=args.port)

    # Wenn weder --serial noch --tcp (oder deren ENV-Defaults) gesetzt sind
    if not transport:
        logger.error("Kein gültiger Transport konfiguriert. Bitte geben Sie --serial oder --tcp an oder setzen Sie SIGNALDUINO_SERIAL_PORT / SIGNALDUINO_TCP_HOST in der Umgebung.")
        sys.exit(1)

    # Controller initialisieren
    controller = SignalduinoController(
        transport=transport,
        message_callback=message_callback,
        logger=logger
    )

    # Graceful Shutdown Handler
    def signal_handler(sig, frame):
        logger.info("Programm wird beendet...")
        controller.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Starten
    try:
        logger.info("Verbinde zum Signalduino...")
        controller.connect()
        logger.info("Verbunden! Starte Initialisierung...")
        
        # Starte Initialisierung, welche die Versionsabfrage inkl. Retry-Logik durchführt
        controller.initialize()
        logger.info("Initialisierung abgeschlossen! Drücke Ctrl+C zum Beenden.")
        
        # Hauptschleife
        if args.timeout is not None:
            logger.info(f"Programm wird nach {args.timeout} Sekunden beendet.")
            start_time = time.time()
            # Der `while` Block mit `time.sleep(0.1)` wird verwendet, um auf das Timeout zu warten,
            # während das Controller-Thread im Hintergrund Nachrichten verarbeitet.
            while (time.time() - start_time) < args.timeout:
                time.sleep(0.1)
            # Timeout erreicht, Controller trennen (signal_handler wird nicht aufgerufen)
            logger.info("Timeout erreicht. Programm wird beendet.")
            controller.disconnect()
            sys.exit(0)
        else:
            # Endlosschleife, wenn kein Timeout gesetzt ist
            while True:
                time.sleep(1)

    except SignalduinoConnectionError as e:
        # Wird ausgelöst, wenn die Verbindung beim Start fehlschlägt (z.B. falscher Port, Gerät nicht angeschlossen)
        logger.error(f"Verbindungsfehler: {e}")
        logger.error("Das Programm wird beendet.")
        controller.disconnect()
        sys.exit(1)

    except Exception as e:
        logger.error(f"Ein unerwarteter Fehler ist aufgetreten: {e}", exc_info=True)
        controller.disconnect()
        sys.exit(1)

if __name__ == "__main__":
    main()