import json
import re
import os
import time
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, List, Optional, Dict, Tuple, Pattern

from .commands import SignalduinoCommands
from .constants import (
    SDUINO_CMD_TIMEOUT,
    SDUINO_INIT_MAXRETRY,
    SDUINO_INIT_WAIT,
    SDUINO_INIT_WAIT_XQ,
    SDUINO_STATUS_HEARTBEAT_INTERVAL,
)
from .exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError, CommandValidationError
from .mqtt import MqttPublisher
from aiomqtt.exceptions import MqttError
from .parser import SignalParser
from .transport import BaseTransport
from .types import DecodedMessage, PendingResponse, QueuedCommand


class SignalduinoController:
    """Orchestrates the connection, command queue and message parsing using asyncio."""

    async def run(self, timeout: Optional[float] = None) -> None:
        """Run the main loop until the timeout is reached or the stop event is set."""
        try:
            if timeout is not None:
                await asyncio.wait_for(self._stop_event.wait(), timeout=timeout)
            else:
                await self._stop_event.wait()
        except asyncio.TimeoutError:
            self.logger.info("Main loop timeout reached.")
        except Exception as e:
            self.logger.error(f"Error in main loop: {e}")
            raise
    """Orchestrates the connection, command queue and message parsing using asyncio."""

    def __init__(
        self,
        transport: BaseTransport,
        parser: Optional[SignalParser] = None,
        message_callback: Optional[Callable[[DecodedMessage], Awaitable[None]]] = None,
        logger: Optional[logging.Logger] = None,
        mqtt_publisher: Optional[MqttPublisher] = None,
    ) -> None:
        self.transport = transport
        self.parser = parser or SignalParser()
        self.message_callback = message_callback
        self.logger = logger or logging.getLogger(__name__)
        
        # NEU: Automatische Initialisierung des MqttPublisher, wenn keine Instanz übergeben wird und
        # die Umgebungsvariable MQTT_HOST gesetzt ist.
        if mqtt_publisher is None and os.environ.get("MQTT_HOST"):
            self.mqtt_publisher = MqttPublisher(controller=self, logger=self.logger)
        else:
            self.mqtt_publisher = mqtt_publisher
        
        self._write_queue: asyncio.Queue[QueuedCommand] = asyncio.Queue()
        self._raw_message_queue: asyncio.Queue[str] = asyncio.Queue()
        self._pending_responses: List[PendingResponse] = []
        self._pending_responses_lock = asyncio.Lock()
        self._init_complete_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._main_tasks: List[asyncio.Task[Any]] = []
        
        # MQTT and initialization state
        self.init_retry_count = 0
        self.init_reset_flag = False
        self.init_version_response = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._init_task_xq: Optional[asyncio.Task[None]] = None
        self._init_task_start: Optional[asyncio.Task[None]] = None
        
        mqtt_topic_root = self.mqtt_publisher.base_topic if self.mqtt_publisher else None
        self.commands = SignalduinoCommands(self.send_command, mqtt_topic_root)

    def get_cached_version(self) -> Optional[str]:
        """Returns the cached firmware version string."""
        return self.init_version_response

    async def get_version(self, payload: Dict[str, Any]) -> str:
        """Requests the firmware version from the device and returns the raw response string."""
        # Der Payload wird vom MqttCommandDispatcher übergeben, wird aber im commands.get_version ignoriert.
        # commands.get_version ist eine asynchrone Methode in SignalduinoCommands, die 'V' sendet.
        return await self.commands.get_version()

    async def get_frequency(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Delegates to SignalduinoCommands to get the current CC1101 frequency."""
        # Der Payload wird vom MqttCommandDispatcher übergeben, aber von commands.get_frequency ignoriert.
        return await self.commands.get_frequency(payload)

    async def factory_reset(self, payload: Dict[str, Any]) -> str:
        """Delegates to SignalduinoCommands to execute a factory reset (e)."""
        # Payload wird zur Validierung akzeptiert, aber ignoriert.
        return await self.commands.factory_reset()

    async def get_bandwidth(self, payload: Dict[str, Any]) -> float:
        """Delegates to SignalduinoCommands to get the current CC1101 bandwidth in kHz."""
        return await self.commands.get_bandwidth(payload)

    async def get_rampl(self, payload: Dict[str, Any]) -> int:
        """Delegates to SignalduinoCommands to get the current CC1101 receiver amplification in dB."""
        return await self.commands.get_rampl(payload)

    async def get_sensitivity(self, payload: Dict[str, Any]) -> int:
        """Delegates to SignalduinoCommands to get the current CC1101 sensitivity in dB."""
        return await self.commands.get_sensitivity(payload)

    async def get_data_rate(self, payload: Dict[str, Any]) -> float:
        """Delegates to SignalduinoCommands to get the current CC1101 data rate in kBaud."""
        return await self.commands.get_data_rate(payload)
    
    # --- CC1101 Hardware Status SET-Methoden ---

    async def set_cc1101_frequency(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """Sets the CC1101 RF frequency from an MQTT command."""
        await self.commands.set_frequency(payload["value"])
        return {"status": "Frequency set successfully", "value": payload["value"]}

    async def set_cc1101_bandwidth(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """Sets the CC1101 IF bandwidth from an MQTT command."""
        await self.commands.set_bwidth(payload["value"])
        return {"status": "Bandwidth set successfully", "value": payload["value"]}

    async def set_cc1101_datarate(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """Sets the CC1101 data rate from an MQTT command."""
        await self.commands.set_datarate(payload["value"])
        return {"status": "Data rate set successfully", "value": payload["value"]}
        
    async def set_cc1101_sensitivity(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """Sets the CC1101 sensitivity from an MQTT command."""
        await self.commands.set_sens(payload["value"])
        return {"status": "Sensitivity set successfully", "value": payload["value"]}

    async def set_cc1101_rampl(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """Sets the CC1101 receiver amplification (Rampl) from an MQTT command."""
        await self.commands.set_rampl(payload["value"])
        return {"status": "Rampl set successfully", "value": payload["value"]}
    
    async def get_cc1101_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Delegates to SignalduinoCommands to get all key CC1101 settings."""
        return await self.commands.get_cc1101_settings(payload)

    async def send_command(
        self,
        command: str,
        expect_response: bool = False,
        timeout: Optional[float] = None,
        response_pattern: Optional[Pattern[str]] = None,
    ) -> Optional[str]:
        """Send a command to the Signalduino and optionally wait for a response.

        Args:
            command: The command to send.
            expect_response: Whether to wait for a response.
            timeout: Timeout in seconds for waiting for a response.
            response_pattern: Optional regex pattern to match against responses.

        Returns:
            The response if expect_response is True, otherwise None.

        Raises:
            SignalduinoCommandTimeout: If no response is received within the timeout.
            SignalduinoConnectionError: If the connection is lost.
        """
        if self.transport.closed():
            raise SignalduinoConnectionError("Transport is closed")

        if expect_response:
            return await self._send_and_wait(command, timeout or SDUINO_CMD_TIMEOUT, response_pattern)
        else:
            await self._write_queue.put(QueuedCommand(
                payload=command,
                expect_response=False,
                timeout=timeout or SDUINO_CMD_TIMEOUT
            ))
            return None

    async def __aenter__(self) -> "SignalduinoController":
        await self.transport.open()
        if self.mqtt_publisher:
            try:
                await self.mqtt_publisher.__aenter__()
            except MqttError as exc:
                self.logger.warning("Konnte keine Verbindung zum MQTT-Broker herstellen: %s", exc)
        try:
            await self.initialize() # Wichtig: Initialisierung nach dem Öffnen des Transports und Publishers
        except SignalduinoConnectionError as exc:
            self.logger.error("Verbindungsfehler während der Initialisierung, setze fort: %s", exc)
            
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._stop_event.set()
        for task in self._main_tasks:
            task.cancel()
        await asyncio.gather(*self._main_tasks, return_exceptions=True)
        if self.mqtt_publisher:
            await self.mqtt_publisher.__aexit__(exc_type, exc_val, exc_tb)
        await self.transport.close()

    async def _reader_task(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.logger.debug("Reader task waiting for line...")
                line = await self.transport.readline()
                if line is not None:
                    self.logger.debug(f"Reader task received line: {line}")
                    await self._raw_message_queue.put(line)
                
                await asyncio.sleep(0.01)  # Ensure minimal yield time to prevent 100% CPU usage
            except Exception as e:
                self.logger.error(f"Reader task error: {e}")
                break

    async def _parser_task(self) -> None:
        while not self._stop_event.is_set():
            try:
                line = await self._raw_message_queue.get()
                if line:
                    # Führe die rechenintensive Parsing-Logik in einem separaten Thread aus.
                    # Dadurch wird die asyncio-Event-Schleife nicht blockiert.
                    decoded = await asyncio.to_thread(self.parser.parse_line, line)
                    if decoded and self.message_callback:
                        await self.message_callback(decoded[0])
                    if self.mqtt_publisher and decoded:
                        # Verwende die neue MqttPublisher.publish(message: DecodedMessage) Signatur
                        await self.mqtt_publisher.publish(decoded[0])
                    await self._handle_as_command_response(line)
                
                # Ensure a minimal yield time for other tasks when the queue is rapidly processed.
                await asyncio.sleep(0.01)
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

    async def initialize(self, timeout: Optional[float] = None) -> None:
        """Initialize the connection by starting tasks and retrieving firmware version.
        
        Args:
            timeout: Optional timeout in seconds. Defaults to SDUINO_INIT_MAXRETRY * SDUINO_INIT_WAIT
        """
        self._main_tasks = [
            asyncio.create_task(self._reader_task(), name="sd-reader"),
            asyncio.create_task(self._parser_task(), name="sd-parser"),
            asyncio.create_task(self._writer_task(), name="sd-writer")
        ]
        
        # Start initialization task
        self._init_task_start = asyncio.create_task(self._init_task_start_loop())
        self._main_tasks.append(self._init_task_start)
        self._main_tasks.append(self._init_task_start)
        
        # Calculate timeout
        init_timeout = timeout if timeout is not None else SDUINO_INIT_MAXRETRY * SDUINO_INIT_WAIT
        
        try:
            await asyncio.wait_for(self._init_complete_event.wait(), timeout=init_timeout)
        except asyncio.TimeoutError:
            self.logger.error("Initialization timed out after %s seconds", init_timeout)
            self._stop_event.set()  # Signal all tasks to stop
            self._init_complete_event.set()  # Unblock waiters
            
            # Cancel all tasks
            tasks = [t for t in [*self._main_tasks, self._init_task_start] if t is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            
            raise SignalduinoConnectionError(f"Initialization timed out after {init_timeout} seconds")
            
        self.logger.info("Signalduino Controller initialized successfully.")

    async def _send_and_wait(self, command: str, timeout: float, response_pattern: Optional[Pattern[str]] = None) -> str:
        """Send a command and wait for a response matching the pattern."""
        future = asyncio.Future()
        self.logger.debug(f"Creating QueuedCommand for '{command}' with timeout {timeout}")
        queued_cmd = QueuedCommand(
            payload=command,
            expect_response=True,
            timeout=timeout,
            response_pattern=response_pattern,
            on_response=lambda line: (
                self.logger.debug(f"Received response for '{command}': {line}"),
                future.set_result(line)
            )[-1]
        )
        
        # Create and store PendingResponse
        pending = PendingResponse(
            command=queued_cmd,
            deadline=datetime.now(timezone.utc) + timedelta(seconds=timeout),
            event=asyncio.Event(),
            future=future,
            response=None
        )
        async with self._pending_responses_lock:
            self._pending_responses.append(pending)
        
        await self._write_queue.put(queued_cmd)
        self.logger.debug(f"Queued command '{command}', waiting for response...")

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            self.logger.debug(f"Successfully received response for '{command}': {result}")
            return result
        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout waiting for response to '{command}'")
            async with self._pending_responses_lock:
                if pending in self._pending_responses:
                    self._pending_responses.remove(pending)
            raise SignalduinoCommandTimeout("Command timed out")
        except Exception as e:
            async with self._pending_responses_lock:
                if future in self._pending_responses:
                    self._pending_responses.remove(future)
            if 'socket is closed' in str(e) or 'cannot reuse' in str(e):
                raise SignalduinoConnectionError(str(e))
            raise

    async def _handle_as_command_response(self, line: str) -> None:
        """Check if the received line matches any pending command response."""
        self.logger.debug(f"Checking line for command response: {line}")
        async with self._pending_responses_lock:
            self.logger.debug(f"Current pending responses: {len(self._pending_responses)}")
            for pending in self._pending_responses:
                try:
                    self.logger.debug(f"Checking pending response: {pending.payload}")
                    if pending.response_pattern:
                        self.logger.debug(f"Testing pattern: {pending.response_pattern}")
                        if pending.response_pattern.match(line):
                            self.logger.debug(f"Matched response pattern for command: {pending.payload}")
                            pending.future.set_result(line)
                            self._pending_responses.remove(pending)
                            return
                    self.logger.debug(f"Testing direct match for: {pending.payload}")
                    if line.startswith(pending.payload):
                        self.logger.debug(f"Matched direct response for command: {pending.payload}")
                        pending.future.set_result(line)
                        self._pending_responses.remove(pending)
                        return
                except Exception as e:
                    self.logger.error(f"Error processing pending response: {e}")
                    continue
            self.logger.debug("No matching pending response found")

    async def _init_task_start_loop(self) -> None:
        """Main initialization task that handles version check and XQ command."""
        try:
            # 1. Deaktivieren des Empfängers (XQ) und Warten auf Abschluss der Warteschlange
            self.logger.info("Disabling Signalduino receiver (XQ) before version check...")
            await self.send_command("XQ", expect_response=False)
            await asyncio.sleep(SDUINO_INIT_WAIT) # Warte, bis der Befehl verarbeitet wurde

            # 2. Retry logic for 'V' command (Version)
            version_response = None
            for attempt in range(SDUINO_INIT_MAXRETRY):
                try:
                    self.logger.info("Requesting firmware version (attempt %s of %s)...",
                                    attempt + 1, SDUINO_INIT_MAXRETRY)
                    version_response = await self.send_command("V", expect_response=True)
                    if version_response:
                        self.init_version_response = version_response.strip()
                        self.logger.info("Firmware version received: %s", self.init_version_response)
                        break  # Success
                except SignalduinoCommandTimeout:
                    self.logger.warning("Version request timed out. Retrying in %s seconds...",
                                      SDUINO_INIT_WAIT)
                    await asyncio.sleep(SDUINO_INIT_WAIT)
                except SignalduinoConnectionError as e:
                    self.logger.error("Connection error during initialization: %s", e)
                    raise
            else:
                self.logger.error("Failed to initialize Signalduino after %s attempts.",
                                SDUINO_INIT_MAXRETRY)
                self._init_complete_event.set()  # Ensure event is set to unblock
                raise SignalduinoConnectionError("Maximum initialization retries reached.")

            # 2. Activate receiver (XE) after successful version check (V).
            if version_response:
                self.logger.info("Enabling Signalduino receiver (XE)...")
                await self.send_command("XE", expect_response=False)

            self._init_complete_event.set()
            return
            
        except Exception as e:
            self.logger.error(f"Initialization task error: {e}")
            self._init_complete_event.set()  # Ensure event is set to unblock
            raise

    async def _schedule_xq_command(self) -> None:
        """Schedule the XQ command to be sent periodically."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(SDUINO_INIT_WAIT_XQ)
                await self.send_command("XQ", expect_response=False)
            except Exception as e:
                self.logger.error(f"XQ scheduling error: {e}")
                break

    async def _start_heartbeat_task(self) -> None:
        """Start the heartbeat task if not already running."""
        if not self._heartbeat_task or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Periodically publish status heartbeat messages."""
        while not self._stop_event.is_set():
            try:
                await self._publish_status_heartbeat()
                await asyncio.sleep(SDUINO_STATUS_HEARTBEAT_INTERVAL)
            except Exception as e:
                self.logger.error(f"Heartbeat loop error: {e}")
                break

    async def _publish_status_heartbeat(self) -> None:
        """Publish a status heartbeat message via MQTT."""
        if self.mqtt_publisher:
            status = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": self.init_version_response,
                "connected": not self.transport.closed()
            }
            await self.mqtt_publisher.publish_simple("status/heartbeat", json.dumps(status))