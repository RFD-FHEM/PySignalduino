import json 
import logging
import re
import asyncio
import os
import traceback
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    Awaitable,
    Callable,
    List,
    Optional,
    Pattern,
    Dict,
    Tuple,
)

# threading, queue, time entfernt
from .commands import SignalduinoCommands, MqttCommandDispatcher
from .constants import (
    SDUINO_CMD_TIMEOUT,
    SDUINO_INIT_MAXRETRY,
    SDUINO_INIT_WAIT,
    SDUINO_INIT_WAIT_XQ,
    SDUINO_STATUS_HEARTBEAT_INTERVAL,
)
from .exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError, CommandValidationError
from .mqtt import MqttPublisher # Muss jetzt async sein
from .parser import SignalParser
from .transport import BaseTransport # Muss jetzt async sein
from .types import DecodedMessage, PendingResponse, QueuedCommand


class SignalduinoController:
    """Orchestrates the connection, command queue and message parsing using asyncio."""

    def __init__(
        self,
        transport: BaseTransport, # Erwartet asynchrone Implementierung
        parser: Optional[SignalParser] = None,
        # Callback ist jetzt ein Awaitable, da es im Async-Kontext aufgerufen wird
        message_callback: Optional[Callable[[DecodedMessage], Awaitable[None]]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.transport = transport
        self.parser = parser or SignalParser()
        self.message_callback = message_callback
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize queues and tasks
        self._write_queue: asyncio.Queue[QueuedCommand] = asyncio.Queue()
        self._raw_message_queue: asyncio.Queue[str] = asyncio.Queue()
        self._pending_responses: List[PendingResponse] = []
        self._pending_responses_lock = asyncio.Lock()
        self._init_complete_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._main_tasks: List[asyncio.Task[Any]] = []
        
        # send_command muss jetzt async sein
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
            read_task = asyncio.create_task(self.transport.readline())
            try:
                await self.transport.write_line(command)
                # Check connection immediately after writing
                if self.transport.closed():
                    raise SignalduinoConnectionError("Connection dropped during command")
                response = await asyncio.wait_for(
                    read_task,
                    timeout=timeout or SDUINO_CMD_TIMEOUT,
                )
                return response
            except asyncio.TimeoutError:
                read_task.cancel()
                # Check for connection drop first
                if self.transport.closed():
                    raise SignalduinoConnectionError("Connection dropped during command")
                if read_task.done() and not read_task.cancelled():
                    try:
                        exc = read_task.exception()
                        if isinstance(exc, SignalduinoConnectionError):
                            raise exc
                    except (asyncio.CancelledError, Exception):
                        pass
                raise SignalduinoCommandTimeout("Command timed out")
            except SignalduinoConnectionError as e:
                read_task.cancel()
                raise
            except Exception as e:
                read_task.cancel()
                if 'socket is closed' in str(e) or 'cannot reuse' in str(e):
                    raise SignalduinoConnectionError(str(e))
                raise
        else:
            await self.transport.write_line(command)
            return None
        self.parser = parser or SignalParser()
        self.message_callback = message_callback
        self.logger = logger or logging.getLogger(__name__)

        self.mqtt_publisher: Optional[MqttPublisher] = None
        self.mqtt_dispatcher: Optional[MqttCommandDispatcher] = None # NEU
        if os.environ.get("MQTT_HOST"):
            self.mqtt_publisher = MqttPublisher(logger=self.logger)
            self.mqtt_dispatcher = MqttCommandDispatcher(self) # NEU: Initialisiere Dispatcher
            # handle_mqtt_command muss jetzt async sein
            self.mqtt_publisher.register_command_callback(self._handle_mqtt_command)

        # Ersetze threading-Objekte durch asyncio-Äquivalente
        self._stop_event = asyncio.Event()
        self._raw_message_queue: asyncio.Queue[str] = asyncio.Queue()
        self._write_queue: asyncio.Queue[QueuedCommand] = asyncio.Queue()
        self._pending_responses: List[PendingResponse] = []
        self._pending_responses_lock = asyncio.Lock()
        self._init_complete_event = asyncio.Event() # NEU: Event für den Abschluss der Initialisierung

        # Timer-Handles (jetzt asyncio.Task anstelle von threading.Timer)
        self._heartbeat_task: Optional[asyncio.Task[Any]] = None
        self._init_task_xq: Optional[asyncio.Task[Any]] = None
        self._init_task_start: Optional[asyncio.Task[Any]] = None
        
        # Liste der Haupt-Tasks für die run-Methode
        self._main_tasks: List[asyncio.Task[Any]] = []

        self.init_retry_count = 0
        self.init_reset_flag = False
        self.init_version_response: Optional[str] = None # Hinzugefügt für _check_version_resp

    # Asynchroner Kontextmanager
    async def __aenter__(self) -> "SignalduinoController":
        """Opens transport and starts MQTT connection if configured."""
        await self.transport.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Closes transport and MQTT connection if configured."""
        # Cancel all running tasks
        for task in self._main_tasks:
            task.cancel()
        await self.transport.close()

    async def _reader_task(self) -> None:
        """Continuously reads lines from the transport."""
        while not self._stop_event.is_set():
            try:
                line = await self.transport.readline()
                if line is not None:
                    await self._raw_message_queue.put(line)
            except Exception as e:
                self.logger.error(f"Reader task error: {e}")
                break

    async def _parser_task(self) -> None:
        """Processes raw messages from the queue."""
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
        """Processes commands from the write queue."""
        while not self._stop_event.is_set():
            try:
                cmd = await self._write_queue.get()
                await self.transport.write_line(cmd.payload)
            except Exception as e:
                self.logger.error(f"Writer task error: {e}")
                break

    async def initialize(self) -> None:
        """Initialize the controller and start background tasks."""
        self._main_tasks = [
            asyncio.create_task(self._reader_task(), name="sd-reader"),
            asyncio.create_task(self._parser_task(), name="sd-parser"),
            asyncio.create_task(self._writer_task(), name="sd-writer")
        ]
        self._init_complete_event.set()