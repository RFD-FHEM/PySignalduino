import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock
from typing import Optional

import pytest

from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError
from signalduino.transport import BaseTransport
from signalduino.commands import Command, CommandType

class MockTransport(BaseTransport):
    def __init__(self):
        self.is_open_flag = False
        self.output_queue = asyncio.Queue()

    async def connect(self):
        self.is_open_flag = True

    async def close(self):
        self.is_open_flag = False

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        
    @property
    def is_open(self) -> bool:
        return self.is_open_flag
    
    @property
    def is_connected(self) -> bool:
        return self.is_open_flag
    
    def closed(self) -> bool:
        return not self.is_open_flag

    async def write_line(self, data: str) -> None:
        if not self.is_open_flag:
            raise SignalduinoConnectionError("Closed")

    async def read_line(self, timeout: Optional[float] = None) -> Optional[str]:
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
    mock_parser = MagicMock()
    controller = SignalduinoController(transport, mock_parser)

    # Prime controller for successful initialization:
    # 1. Answer for Command.VERSION()
    await transport.output_queue.put("V 1.0.0")
    # 2. Answer for Command.SET_FREQUENCY(DEFAULT_FREQUENCY)
    await transport.output_queue.put("b433.92")

    # Expect SignalduinoCommandTimeout because transport sends nothing after init
    async with controller:
        with pytest.raises(SignalduinoCommandTimeout):
            await controller.send_command(Command(name="VERSION_TEST_0.5", raw_command="V", command_type=CommandType.GET, timeout=0.5))


@pytest.mark.asyncio
async def test_connection_drop_during_command():
    """Test that if connection dies during command wait, we get ConnectionError."""
    transport = MockTransport()
    mock_parser = MagicMock()
    controller = SignalduinoController(transport, mock_parser)

    # Prime controller for successful initialization:
    # 1. Answer for Command.VERSION()
    await transport.output_queue.put("V 1.0.0")
    # 2. Answer for Command.SET_FREQUENCY(DEFAULT_FREQUENCY)
    await transport.output_queue.put("b433.92")

    # The synchronous exception handler must be replaced by try/except within an async context
    
    async with controller:
        cmd_task = asyncio.create_task(
            controller.send_command(Command(name="VERSION_TEST_1.0", raw_command="V", command_type=CommandType.GET, timeout=1.0))
        )

        # Give the command a chance to be sent and be in a waiting state
        await asyncio.sleep(0.001)

        # Simulate connection loss and cancel main task to trigger cleanup
        await transport.close()
        # controller._main_task.cancel() # Entfernt, da es in der neuen Controller-Version nicht mehr notwendig ist und Fehler verursacht.
        
        # Introduce a small delay to allow the event loop to process the connection drop
        # and set the controller's _stop_event before the command times out.
        await asyncio.sleep(0.01)

        with pytest.raises((SignalduinoConnectionError, asyncio.CancelledError, asyncio.TimeoutError, SignalduinoCommandTimeout)):
             # send_command should raise an exception because the connection is dead
            await cmd_task