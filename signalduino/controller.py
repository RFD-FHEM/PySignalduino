import json
import time
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, List, Optional, Dict, Tuple

from .commands import SignalduinoCommands, MqttCommandDispatcher
from .constants import (
    SDUINO_CMD_TIMEOUT,
    SDUINO_INIT_MAXRETRY,
    SDUINO_INIT_WAIT,
    SDUINO_INIT_WAIT_XQ,
    SDUINO_STATUS_HEARTBEAT_INTERVAL,
)
from .exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError, CommandValidationError
from .mqtt import MqttPublisher
from .parser import SignalParser
from .transport import BaseTransport
from .types import DecodedMessage, PendingResponse, QueuedCommand

class SignalduinoController:
    """Orchestrates the connection, command queue and message parsing using asyncio."""

    def __init__(
        self,
        transport: BaseTransport,
        parser: Optional[SignalParser] = None,
        message_callback: Optional[Callable[[DecodedMessage], Awaitable[None]]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.transport = transport
        self.parser = parser or SignalParser()
        self.message_callback = message_callback
        self.logger = logger or logging.getLogger(__name__)
        
        self._write_queue: asyncio.Queue[QueuedCommand] = asyncio.Queue()
        self._raw_message_queue: asyncio.Queue[str] = asyncio.Queue()
        self._pending_responses: List[PendingResponse] = []
        self._pending_responses_lock = asyncio.Lock()
        self._init_complete_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._main_tasks: List[asyncio.Task[Any]] = []
        
        self.commands = SignalduinoCommands(self.send_command)

    async def send_command(
        self,
        command: str,
        expect_response: bool = False,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """Send a command to the Signalduino and optionally wait for a response.

        Args:
            command: The command to send.
            expect_response: Whether to wait for a response.
            timeout: Timeout in seconds for waiting for a response.

        Returns:
            The response if expect_response is True, otherwise None.

        Raises:
            SignalduinoCommandTimeout: If no response is received within the timeout.
            SignalduinoConnectionError: If the connection is lost.
        """
        if self.transport.closed():
            raise SignalduinoConnectionError("Transport is closed")

        if expect_response:
            start_time = time.monotonic()
            read_task = asyncio.create_task(self.transport.readline())
            try:
                await self.transport.write_line(command)
                
                if self.transport.closed():
                    raise SignalduinoConnectionError("Connection dropped during command")
                
                # Get first response
                response = await asyncio.wait_for(
                    read_task,
                    timeout=timeout or SDUINO_CMD_TIMEOUT
                )
                
                # If it's an interleaved or STX message, get next response
                if response and (response.startswith("MU;") or response.startswith("MS;") or response.startswith("\x02")):
                    # Parse STX message if present
                    if response.startswith("\x02"):
                        self.parser.parse_line(response.strip())
                    # Create a new read task for the actual response
                    read_task2 = asyncio.create_task(self.transport.readline())
                    response = await asyncio.wait_for(
                        read_task2,
                        timeout=timeout or SDUINO_CMD_TIMEOUT
                    )
                
                return response
            except asyncio.TimeoutError:
                read_task.cancel()
                raise SignalduinoCommandTimeout("Command timed out")
            except Exception as e:
                read_task.cancel()
                if 'socket is closed' in str(e) or 'cannot reuse' in str(e):
                    raise SignalduinoConnectionError(str(e))
                raise
        else:
            await self._write_queue.put(QueuedCommand(
                payload=command,
                expect_response=False,
                timeout=timeout or SDUINO_CMD_TIMEOUT
            ))
            return None

    # Rest of the class implementation remains unchanged
    async def __aenter__(self) -> "SignalduinoController":
        await self.transport.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        for task in self._main_tasks:
            task.cancel()
        await self.transport.close()

    async def _reader_task(self) -> None:
        while not self._stop_event.is_set():
            try:
                line = await self.transport.readline()
                if line is not None:
                    await self._raw_message_queue.put(line)
                    await asyncio.sleep(0)  # yield to other tasks
            except Exception as e:
                self.logger.error(f"Reader task error: {e}")
                break

    async def _parser_task(self) -> None:
        while not self._stop_event.is_set():
            try:
                line = await self._raw_message_queue.get()
                if line:
                    decoded = self.parser.parse_line(line)
                    if decoded and self.message_callback:
                        await self.message_callback(decoded[0])
            except Exception as e:
                self.logger.error(f"Parser task error: {e}")
                break

    async def _writer_task(self) -> None:
        while not self._stop_event.is_set():
            try:
                cmd = await self._write_queue.get()
                await self.transport.write_line(cmd.payload)
                self._write_queue.task_done()
            except Exception as e:
                self.logger.error(f"Writer task error: {e}")
                break

    async def initialize(self) -> None:
        self._main_tasks = [
            asyncio.create_task(self._reader_task(), name="sd-reader"),
            asyncio.create_task(self._parser_task(), name="sd-parser"),
            asyncio.create_task(self._writer_task(), name="sd-writer")
        ]
        self._init_complete_event.set()