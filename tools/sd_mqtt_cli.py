import argparse
import json
import os
from pathlib import Path
from paho.mqtt.client import Client
from paho.mqtt.enums import CallbackAPIVersion
from dotenv import load_dotenv
import time
import uuid

# Konfiguration
BASE_TOPIC = "signalduino/v1"
CMD_TOPIC = f"{BASE_TOPIC}/commands"
RESP_TOPIC = f"{BASE_TOPIC}/responses"
ERR_TOPIC = f"{BASE_TOPIC}/errors"

# Liste der abzufragenden Topics für den Polling-Modus
POLL_TOPICS = [
    'get/system/version', 
    'get/system/freeram', 
    'get/system/uptime',
    'get/cc1101/frequency', 
    'get/cc1101/bandwidth', 
    'get/cc1101/datarate',
    'get/cc1101/rampl', 
    'get/cc1101/sensitivity',
    'get/cc1101/patable',
    'get/cc1101/config',
    'get/config/decoder', 
]

class MqttCli:
    """A simple CLI tool to send commands to the PySignalduino MQTT gateway."""

    def __init__(self, host: str, port: int, req_id: str, timeout: int = 5):
        self.host = host
        self.port = port
        self.req_id = req_id
        self.timeout = timeout
        self.response = None
        self.is_connected = False # NEU
        self.is_subscribed = False # NEU
        # Verwenden Sie paho.mqtt.client, um die Antwort zu abonnieren.
        self.client = Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=f"sd-mqtt-cli-{req_id}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.is_connected = True # Setze Flag
            # client.subscribe() ist blockierend, aber wir müssen auf den QOS-Rückruf warten,
            # was paho.mqtt.client im Hintergrund übernimmt. Wir verlassen uns darauf, dass
            # subscribe jetzt aufgerufen wird, aber müssen nicht explizit auf QOS warten, 
            # da die `on_connect` synchron läuft.
            # Ich ersetze client.subscribe(RESP_TOPIC) mit client.subscribe(RESP_TOPIC, qos=1)
            # und setze self.is_subscribed danach auf True.
            
            # Subskription durchführen
            # client.subscribe gibt ein Tuple zurück: (return_code, mid)
            result, mid = client.subscribe(RESP_TOPIC, qos=1)
            if result == 0:
                self.is_subscribed = True # Setze Flag, da der Aufruf erfolgreich war
                print("Info: Subscribed to response topics.")
            else:
                print(f"Error: Failed to subscribe with result code: {result}")
            
            # Separate Subscription für Errors
            client.subscribe(ERR_TOPIC, qos=0)
            
        else:
            print(f"Error: Connection failed with reason: {reason_code}")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            # Überprüfe auf die korrekte req_id
            if payload.get("req_id") == self.req_id:
                self.response = payload
                # Bei persistenten Verbindungen MUSS die Schleife weiterlaufen,
                # um weitere Nachrichten zu empfangen. Wir stoppen den Loop NICHT hier.
                pass
        except json.JSONDecodeError:
            pass # Ignoriere ungültiges JSON

    def connect_and_subscribe(self) -> dict:
        """Stellt die Verbindung her, startet den Loop und abonniert die Response-Topics.
        Gibt {"success": True} bei Erfolg oder ein Fehler-Dict bei Timeout/Fehler zurück.
        """
        try:
            self.client.connect(self.host, self.port, 60)
        except Exception as e:
            return {"success": False, "error": f"Failed to connect to MQTT broker: {e}"}

        # Startet den Loop im Hintergrund, damit on_connect und on_message funktionieren
        self.client.loop_start()

        start_time = time.time()
        # Warte auf Verbindung und Abonnement. Max. 5 Sekunden für Flags.
        while (not self.is_connected or not self.is_subscribed) and (time.time() - start_time) < 5.0:
            time.sleep(0.05)

        if not self.is_connected or not self.is_subscribed:
            return {"success": False, "error": "Timeout waiting for connection or subscription to be active."}
        
        return {"success": True}

    def disconnect_and_stop(self):
        """Stoppt den Loop und trennt die Verbindung."""
        self.client.loop_stop()
        self.client.disconnect()
        print("Info: Disconnected from MQTT broker.")

    def execute_command(self, topic_suffix: str, payload_data: dict = {}) -> dict:
        """Veröffentlicht einen Befehl und wartet auf die Antwort. 
        Verbindung/Trennung wird hier NICHT gehandhabt.
        """
        self.response = None # Antwort für diesen Befehl zurücksetzen
        
        full_topic = f"{CMD_TOPIC}/{topic_suffix}"
        payload_data["req_id"] = self.req_id
        payload = json.dumps(payload_data)

        print(f"-> Sending command to {full_topic} (req_id: {self.req_id})")
        self.client.publish(full_topic, payload)

        start_time = time.time()
        # Warte, bis die Antwort empfangen wird oder Timeout erreicht ist
        while self.response is None and (time.time() - start_time) < self.timeout:
            time.sleep(0.1)

        if self.response:
            return self.response
        else:
            return {"success": False, "req_id": self.req_id, "error": "Timeout waiting for response."}


def run_cli():
    # Lade Umgebungsvariablen aus .devcontainer/devcontainer.env
    dotenv_path = Path(__file__).parent.parent / ".devcontainer" / "devcontainer.env"
    if dotenv_path.is_file():
        load_dotenv(dotenv_path=dotenv_path, override=True)

    default_host = os.environ.get("MQTT_HOST", "127.0.0.1")
    default_port = int(os.environ.get("MQTT_PORT", 1883))
    
    parser = argparse.ArgumentParser(description="CLI for PySignalduino MQTT commands.")
    parser.add_argument("--host", default=default_host, help=f"MQTT broker host. Defaults to $MQTT_HOST or {default_host}.")
    parser.add_argument("--port", type=int, default=default_port, help=f"MQTT broker port. Defaults to $MQTT_PORT or {default_port}.")
    
    # Der Hauptparser muss zuerst die subparser hinzufügen
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Factory Reset Command
    reset_parser = subparsers.add_parser("reset", help="Execute a Factory Reset (EEPROM Defaults).")

    # 2. Poll All Settings Command (NEU)
    poll_parser = subparsers.add_parser("poll", help="Query all system and CC1101 settings sequentially.")

    # 3. Get Hardware Status Commands (grouped)
    get_parser = subparsers.add_parser("get", help="Retrieve hardware settings.")
    # Füge req-id zum get-Subparser hinzu, da es nur hier benötigt wird
    get_parser.add_argument("--req-id", default=str(int(time.time())), help="Request ID for response correlation.")
    get_subparsers = get_parser.add_subparsers(dest="setting", required=True)

    # NEU: Subcommand für alle CC1101-Einstellungen
    get_subparsers.add_parser("all-settings", help="Get all key CC1101 configuration settings (freq, bw, rampl, sens, dr).")

    # Hardware Status Subcommand
    hw_parser = get_subparsers.add_parser("hardware-status", help="Get specific CC1101 hardware status.")
    hw_parser.add_argument(
        "--parameter", 
        choices=["frequency", "bandwidth", "rampl", "sensitivity", "datarate"],
        required=True,
        help="The hardware parameter to query."
    )
    
    # System Status Subcommand
    sys_parser = get_subparsers.add_parser("system-status", help="Get system status (version, freeram, uptime).")
    sys_parser.add_argument(
        "--parameter", 
        choices=["version", "freeram", "uptime"],
        required=True,
        help="The system parameter to query."
    )

    args = parser.parse_args()
    
    result = None

    if args.command == "reset":
        # Erstelle CLI Instanz mit einer eindeutigen req_id
        req_id = str(uuid.uuid4())
        cli = MqttCli(host=args.host, port=args.port, req_id=req_id)
        
        connect_result = cli.connect_and_subscribe()
        if connect_result.get("success") is True:
            result = cli.execute_command("set/factory_reset")
            cli.disconnect_and_stop()
        else:
            result = connect_result

    elif args.command == "poll":
        print("\n--- Starting Sequential Poll ---")
        all_results = {}
        # Erstelle EINE CLI-Instanz für alle Befehle
        req_id_base = str(uuid.uuid4()) # Nur zur Erstellung der Client-ID
        cli = MqttCli(host=args.host, port=args.port, req_id=req_id_base, timeout=5)

        # 1. Verbindung herstellen und abonnieren
        connect_result = cli.connect_and_subscribe()
        if connect_result.get("success") is not True:
            # Verbindung fehlgeschlagen (es wird ein Fehler-Dict zurückgegeben)
            all_results["connection_error"] = connect_result
            result = {"poll_summary": all_results}
            # Der Loop wurde in connect_and_subscribe gestartet, muss aber gestoppt werden.
            cli.disconnect_and_stop() 
            print("--- Poll Aborted ---")
            
        else:
            # 2. Gehe die Liste der Topics durch und frage jeden Parameter ab
            for topic_suffix in POLL_TOPICS:
                # Für jeden Befehl EINE NEUE req_id generieren
                req_id = str(uuid.uuid4()) 
                cli.req_id = req_id # WICHTIG: Die req_id muss für jeden Befehl neu gesetzt werden
                
                # Verwende einen Topic-Key, der für das Zusammenfassungs-Dictionary lesbar ist
                topic_key = topic_suffix.replace('get/', '').replace('/', '_')
                
                # Führe Befehl auf persistenter Verbindung aus
                response = cli.execute_command(topic_suffix)
                all_results[topic_key] = response

                if response.get("success", False):
                    print(f"-> OK: {topic_suffix} -> {json.dumps(response.get('payload'))}")
                else:
                    print(f"-> ERROR: {topic_suffix} -> {response.get('error', 'Timeout or connection failed.')}")
                    
                # Warte kurz, um System nicht zu überlasten
                time.sleep(1.5) 
                
            # 3. Verbindung trennen
            cli.disconnect_and_stop()

            print("\n--- Poll Complete ---")
            print("Summary of all results:")
            result = {"poll_summary": all_results}

    elif args.command == "get":
        # Die req_id ist jetzt direkt an get_parser gebunden
        cli = MqttCli(host=args.host, port=args.port, req_id=args.req_id)
        
        connect_result = cli.connect_and_subscribe()
        if connect_result.get("success") is True:
            if args.setting == "all-settings":
                result = cli.execute_command("get/cc1101/settings", {})
            elif args.setting == "hardware-status":
                topic_suffix = f"get/cc1101/{args.parameter}"
                result = cli.execute_command(topic_suffix, {})
            elif args.setting == "system-status":
                topic_suffix = f"get/system/{args.parameter}"
                result = cli.execute_command(topic_suffix, {})
            
            cli.disconnect_and_stop()
        else:
            result = connect_result
        
    if result:
        print(json.dumps(result, indent=2))
        
    # Prüfe auf paho.mqtt.client Abhängigkeit
    try:
        import paho.mqtt.client
    except ImportError:
        print("\n--- WARNING ---")
        print("To run this CLI, you must install the paho-mqtt dependency:")
        print("pip install paho-mqtt")
        
if __name__ == "__main__":
    run_cli()