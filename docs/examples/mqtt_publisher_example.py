import asyncio
from signalduino.mqtt import MqttPublisher
from signalduino.types import DecodedMessage, RawFrame

async def example():
    async with MqttPublisher() as publisher:
        # Beispiel-Nachricht erstellen
        msg = DecodedMessage(
            protocol_id="1",
            payload="RSL: ID=01, SWITCH=01, CMD=OFF",
            raw=RawFrame(
                line="+MU;...",
                rssi=-80,
                freq_afc=433.92,
                message_type="MU"
            ),
            metadata={}
        )
        await publisher.publish(msg)
        print("Nachricht veröffentlicht")

asyncio.run(example())