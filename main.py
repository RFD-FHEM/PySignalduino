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

# Initialisiere das Logging mit dem LOG_LEVEL aus der Umgebungsvariable (falls vorhanden)
initialize_logging(os.environ.get("LOG_LEVEL", "INFO"))

logger = logging.getLogger("main")

def message_callback(message: DecodedMessage):
    """Callback-Funktion, die aufgerufen wird, wenn eine Nachricht dekodiert wurde."""
    print("\n" + "="*50)
    print(f"NEUE NACHRICHT EMPFANGEN (Protokoll-ID: {message.protocol_id})")
    model = message.metadata.get("model", "Unbekannt")
    print(f"Modell: {model}")
    print(f"Payload: {message.payload}")
    print("-" * 20)
    print("Alle Felder:")
    # Zeige Metadaten an
    for key, value in message.metadata.items():
        print(f"  {key}: {value}")
    
    # Zeige RawFrame-Infos an, falls vorhanden
    if message.raw:
        print("  Raw Frame Info:")
        print(f"    Line: {message.raw.line}")
        print(f"    Timestamp: {message.raw.timestamp}")
        if message.raw.rssi:
            print(f"    RSSI: {message.raw.rssi}")
    print("="*50 + "\n")

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
        logger.info("Verbunden! Drücke Ctrl+C zum Beenden.")
        
        # Sende Versionsabfrage zum Test
        logger.info("Sende Versionsabfrage (V)...")
        # Perl regex: 'V\s.*SIGNAL(?:duino|ESP|STM).*(?:\s\d\d:\d\d:\d\d)'
        version_pattern = re.compile(
            r"V\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE
        )
        version = controller.send_command(
            "V",
            expect_response=True,
            timeout=15.0,  # Erhöhe den Timeout für den initialen V-Befehl
            response_pattern=version_pattern,
        )
        if version:
            logger.info(f"Signalduino Version: {version.strip()}")
        else:
            logger.warning("Keine Antwort auf Versionsabfrage erhalten.")

        # Hauptschleife
        while True:
            time.sleep(1)

    except Exception as e:
        logger.error(f"Ein Fehler ist aufgetreten: {e}", exc_info=True)
        controller.disconnect()
        sys.exit(1)

if __name__ == "__main__":
    main()