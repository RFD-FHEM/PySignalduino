import asyncio
from signalduino.controller import SignalduinoController
from signalduino.transport import SerialTransport

async def main():
    # Serielle Verbindung (z. B. USB)
    async with SerialTransport(port="/dev/ttyUSB0", baudrate=115200) as transport:
        async with SignalduinoController(transport=transport) as controller:
            # Controller ist bereit, Befehle können gesendet werden
            await controller.commands.ping()
            print("Ping erfolgreich")
            
            # Hauptverarbeitung starten
            await controller.run()

asyncio.run(main())