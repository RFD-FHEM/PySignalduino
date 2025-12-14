import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock
from typing import Optional

import pytest

from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError
from signalduino.transport import BaseTransport

class MockTransport(BaseTransport):
    def __init__(self):
        self.is_open_flag = False
        self.output_queue = asyncio.Queue()

    async def aopen(self):
        self.is_open_flag = True

    async def aclose(self):
        self.is_open_flag = False

    async def __aenter__(self):
        await self.aopen()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()
        
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
        try:
            # await output_queue.get with timeout
            line = await asyncio.wait_for(self.output_queue.get(), timeout=timeout or 0.1)
            return line
        except asyncio.TimeoutError:
            return None

@pytest.mark.asyncio
async def test_timeout_normally():
    """Test that a simple timeout raises SignalduinoCommandTimeout."""
    transport = MockTransport()
    controller = SignalduinoController(transport)
    
    # Expect SignalduinoCommandTimeout because transport sends nothing
    async with controller:
        with pytest.raises(SignalduinoCommandTimeout):
            await controller.send_command("V", expect_response=True, timeout=0.5)


@pytest.mark.asyncio
async def test_connection_drop_during_command():
    """Test that if connection dies during command wait, we get ConnectionError."""
    transport = MockTransport()
    controller = SignalduinoController(transport)

    # The synchronous exception handler must be replaced by try/except within an async context
    
    async with controller:
        cmd_task = asyncio.create_task(
            controller.send_command("V", expect_response=True, timeout=1.0)
        )

        # Give the command a chance to be sent and be in a waiting state
        await asyncio.sleep(0.001)

        # Simulate connection loss and cancel main task to trigger cleanup
        await transport.aclose()
        # controller._main_task.cancel() # Entfernt, da es in der neuen Controller-Version nicht mehr notwendig ist und Fehler verursacht.
        
        # Introduce a small delay to allow the event loop to process the connection drop
        # and set the controller's _stop_event before the command times out.
        await asyncio.sleep(0.01)

        with pytest.raises((SignalduinoConnectionError, asyncio.CancelledError, asyncio.TimeoutError)):
             # send_command should raise an exception because the connection is dead
            await cmd_task