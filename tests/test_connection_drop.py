import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock
from typing import Optional

import pytest

from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError
from signalduino.transport import BaseTransport

class MockTransport(BaseTransport):
    def __init__(self, simulate_drop=False):
        self.is_open_flag = False
        self.output_queue = asyncio.Queue()
        self.simulate_drop = simulate_drop
        self.read_count = 0


    async def open(self):
        self.is_open_flag = True

    async def close(self):
        self.is_open_flag = False

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        
    @property
    def is_open(self) -> bool:
        return self.is_open_flag
    
    def closed(self) -> bool:
        return not self.is_open_flag

    async def write_line(self, data: str) -> None:
        if not self.is_open_flag:
            raise SignalduinoConnectionError("Closed")

    async def readline(self, timeout: Optional[float] = None) -> Optional[str]:
        if not self.is_open_flag:
            raise SignalduinoConnectionError("Closed")

        await asyncio.sleep(0)  # Yield control

        self.read_count += 1

        if not self.simulate_drop:
            # First read: Simulate version response for initialization
            if self.read_count == 1:
                return "V 3.4.0-rc3 SIGNALduino"
            # Subsequent reads: Simulate normal timeout (for test_timeout_normally)
            raise asyncio.TimeoutError("Simulated timeout")
        
        # Simulate connection drop (for test_connection_drop_during_command)
        if self.read_count > 1:
            # Simulate connection drop by closing transport first
            self.is_open_flag = False
            # Add small delay to ensure controller detects the closed state
            await asyncio.sleep(0.01)
            raise SignalduinoConnectionError("Connection dropped")

        # First read with simulate_drop=True: Still need to succeed initialization
        return "V 3.4.0-rc3 SIGNALduino"

@pytest.mark.asyncio
async def test_timeout_normally():
    """Test that a simple timeout raises SignalduinoCommandTimeout."""
    transport = MockTransport()
    mqtt_publisher = AsyncMock()
    controller = SignalduinoController(transport, mqtt_publisher=mqtt_publisher)
    
    # Expect SignalduinoCommandTimeout because transport sends nothing
    async with controller:
        with pytest.raises(SignalduinoCommandTimeout):
            await controller.send_command("V", expect_response=True, timeout=0.5)


@pytest.mark.asyncio
async def test_connection_drop_during_command():
    """Test that if connection dies during command wait, we get ConnectionError."""
    transport = MockTransport(simulate_drop=True)
    mqtt_publisher = AsyncMock()
    controller = SignalduinoController(transport, mqtt_publisher=mqtt_publisher)
    
    # The synchronous exception handler must be replaced by try/except within an async context
    
    async with controller:
        cmd_task = asyncio.create_task(
            controller.send_command("V", expect_response=True, timeout=1.0)
        )

        # Simulate connection loss
        await transport.close()

        with pytest.raises(SignalduinoConnectionError):
            # send_command should raise an exception because the connection is dead
            await cmd_task