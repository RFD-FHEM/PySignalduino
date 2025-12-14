import asyncio
from signalduino.controller import SignalduinoController
from signalduino.transport import TcpTransport

async def main():
    async with TcpTransport(host="192.168.1.100", port=23) as transport:
        async with SignalduinoController(transport=transport) as controller:
            # Beide Context-Manager sind aktiv
            await controller.run()

asyncio.run(main())