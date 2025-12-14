import asyncio
from signalduino.commands import SignalduinoCommands
from signalduino.transport import TcpTransport
from signalduino.controller import SignalduinoController

async def example():
    async with TcpTransport(host="192.168.1.100", port=23) as transport:
        async with SignalduinoController(transport=transport) as controller:
            # Zugriff auf das commands-Objekt des Controllers
            commands = controller.commands
            
            # Firmware-Version abfragen
            version = await commands.get_version()
            print(f"Firmware-Version: {version}")
            
            # Empfänger aktivieren
            await commands.enable_receiver()
            print("Empfänger aktiviert")
            
            # Konfiguration lesen
            config = await commands.get_config()
            print(f"Konfiguration: {config}")

asyncio.run(example())