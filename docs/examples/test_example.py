import pytest
from unittest.mock import AsyncMock, patch
from signalduino.controller import SignalduinoController

@pytest.mark.asyncio
async def test_send_command():
    transport = AsyncMock()
    controller = SignalduinoController(transport)
    async with controller:
        result = await controller.send_command("V")
        assert result is not None