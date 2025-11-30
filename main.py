import argparse
import logging
import signal
import sys
import time
import os
import re
from typing import Optional

from signalduino.constants import SDUINO_CMD_TIMEOUT
from signalduino.controller import SignalduinoController
from signalduino.transport import SerialTransport, TCPTransport
from signalduino.types import DecodedMessage

# Konfiguration des Loggings
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

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
    parser = argparse.ArgumentParser(description="Signalduino Python Controller")
    
    # Verbindungseinstellungen
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--serial", help="Serieller Port (z.B. /dev/ttyUSB0)")
    group.add_argument("--tcp", help="TCP Host (z.B. 192.168.1.10)")
    
    parser.add_argument("--baud", type=int, default=57600, help="Baudrate für serielle Verbindung (Standard: 57600)")
    parser.add_argument("--port", type=int, default=23, help="Port für TCP Verbindung (Standard: 23)")
    parser.add_argument("--debug", action="store_true", help="Debug-Logging aktivieren")
    
    # MQTT Einstellungen (optional via CLI, sonst via ENV)
    parser.add_argument("--mqtt-host", help="MQTT Broker Host")
    parser.add_argument("--mqtt-port", type=int, help="MQTT Broker Port")
    parser.add_argument("--mqtt-username", help="MQTT Broker Benutzername")
    parser.add_argument("--mqtt-password", help="MQTT Broker Passwort")
    
    args = parser.parse_args()

    # Logging Level anpassen
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug-Modus aktiviert")

    # MQTT Umgebungsvariablen setzen, falls über CLI übergeben
    if args.mqtt_host:
        os.environ["MQTT_HOST"] = args.mqtt_host
    if args.mqtt_port:
        os.environ["MQTT_PORT"] = str(args.mqtt_port)
    if args.mqtt_username:
        os.environ["MQTT_USERNAME"] = args.mqtt_username
    if args.mqtt_password:
        os.environ["MQTT_PASSWORD"] = args.mqtt_password

    # Transport initialisieren
    transport = None
    if args.serial:
        logger.info(f"Initialisiere serielle Verbindung auf {args.serial} mit {args.baud} Baud...")
        transport = SerialTransport(port=args.serial, baudrate=args.baud)
    elif args.tcp:
        logger.info(f"Initialisiere TCP Verbindung zu {args.tcp}:{args.port}...")
        transport = TCPTransport(host=args.tcp, port=args.port)

    if not transport:
        logger.error("Kein gültiger Transport konfiguriert.")
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
            timeout=SDUINO_CMD_TIMEOUT,
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