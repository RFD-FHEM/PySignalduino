import json
import os
import uuid
import logging
from typing import Optional

# Todo: Pfad anpassen
CLIENT_ID_FILE = os.path.join(os.path.expanduser("~"), ".signalduino_id")
logger = logging.getLogger(__name__)

def get_or_create_client_id() -> str:
    """
    Liest die persistente Client-ID aus der Datei oder generiert eine neue und speichert sie.
    """
    client_id = None
    
    # 1. Versuche, die ID aus der Konfigurationsdatei zu lesen
    try:
        if os.path.exists(CLIENT_ID_FILE):
            with open(CLIENT_ID_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                client_id = config.get("client_id")
    except Exception as e:
        logger.warning("Fehler beim Lesen der Client-ID aus %s: %s", CLIENT_ID_FILE, e)
        
    # 2. Wenn keine ID gefunden wurde, generiere eine neue
    if not client_id:
        client_id = f"signalduino-{uuid.uuid4().hex}"
        logger.info("Neue Client-ID generiert: %s", client_id)
        
        # 3. Speichere die ID persistent
        try:
            with open(CLIENT_ID_FILE, "w", encoding="utf-8") as f:
                json.dump({"client_id": client_id}, f, indent=4)
            logger.info("Client-ID dauerhaft gespeichert in %s", CLIENT_ID_FILE)
        except Exception as e:
            logger.error("Fehler beim Speichern der Client-ID in %s: %s", CLIENT_ID_FILE, e)
            
    return client_id

if __name__ == "__main__":
    # Beispiel für die Verwendung
    logging.basicConfig(level=logging.INFO)
    print(f"Client ID: {get_or_create_client_id()}")