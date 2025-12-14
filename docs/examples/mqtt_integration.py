import asyncio
from signalduino.controller import SignalduinoController
from signalduino.transport import TcpTransport

async def main():
    async with TcpTransport(host="192.168.1.100", port=23) as transport:
        async with SignalduinoController(transport=transport) as controller:
            # MQTT-Publisher ist automatisch aktiv, wenn MQTT_HOST gesetzt ist
            # Dekodierte Nachrichten werden automatisch unter `signalduino/messages` veröffentlicht
            await controller.run()  # Blockiert und verarbeitet eingehende Daten

asyncio.run(main())