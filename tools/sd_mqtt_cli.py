import argparse
import json
import os
from pathlib import Path
from paho.mqtt.client import Client
from paho.mqtt.enums import CallbackAPIVersion
from dotenv import load_dotenv
import time

# Konfiguration
BASE_TOPIC = "signalduino/v1"
CMD_TOPIC = f"{BASE_TOPIC}/commands"
RESP_TOPIC = f"{BASE_TOPIC}/responses"
ERR_TOPIC = f"{BASE_TOPIC}/errors"

class MqttCli:
    """A simple CLI tool to send commands to the PySignalduino MQTT gateway."""

    def __init__(self, host: str, port: int, req_id: str, timeout: int = 5):
        self.host = host
        self.port = port
        self.req_id = req_id
        self.timeout = timeout
        self.response = None
        # Verwenden Sie paho.mqtt.client, um die Antwort zu abonnieren.
        self.client = Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=f"sd-mqtt-cli-{req_id}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(RESP_TOPIC)
            client.subscribe(ERR_TOPIC)
            print("Info: Subscribed to response topics.")
        else:
            print(f"Error: Connection failed with reason: {reason_code}")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            # Überprüfe auf die korrekte req_id
            if payload.get("req_id") == self.req_id:
                self.response = payload
                # Disconnect, um die Schleife zu beenden
                self.client.loop_stop()
        except json.JSONDecodeError:
            pass # Ignoriere ungültiges JSON

    def send_command(self, topic_suffix: str, payload_data: dict = {}) -> dict:
        try:
            self.client.connect(self.host, self.port, 60)
        except Exception as e:
            return {"success": False, "error": f"Failed to connect to MQTT broker: {e}"}

        self.client.loop_start()

        full_topic = f"{CMD_TOPIC}/{topic_suffix}"
        payload_data["req_id"] = self.req_id
        payload = json.dumps(payload_data)

        print(f"-> Sending command to {full_topic}: {payload}")
        self.client.publish(full_topic, payload)

        start_time = time.time()
        # Warte, bis die Antwort empfangen wird oder Timeout erreicht ist
        while self.response is None and (time.time() - start_time) < self.timeout:
            time.sleep(0.1)
        
        self.client.loop_stop()
        self.client.disconnect()

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
    parser.add_argument("--req-id", default=str(int(time.time())), help="Request ID for response correlation.")
    
    # Der Hauptparser muss zuerst die subparser hinzufügen
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Factory Reset Command
    reset_parser = subparsers.add_parser("reset", help="Execute a Factory Reset (EEPROM Defaults).")

    # 2. Get Hardware Status Commands (grouped)
    get_parser = subparsers.add_parser("get", help="Retrieve hardware settings.")
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

    args = parser.parse_args()
    
    cli = MqttCli(host=args.host, port=args.port, req_id=args.req_id)
    result = None

    if args.command == "reset":
        result = cli.send_command("set/factory_reset")

    elif args.command == "get":
        if args.setting == "all-settings":
            result = cli.send_command("get/cc1101/settings", {})
        elif args.setting == "hardware-status":
            topic_suffix = f"get/cc1101/{args.parameter}"
            result = cli.send_command(topic_suffix, {})
        
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
