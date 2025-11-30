import logging
import queue
import re
import threading
import os # NEU: Import für Umgebungsvariablen
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Literal, Optional, Pattern

from .constants import SDUINO_CMD_TIMEOUT
from .exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError
from .mqtt import MqttPublisher # NEU: MQTT-Import
from .parser import SignalParser
from .transport import BaseTransport
from .types import DecodedMessage, PendingResponse, QueuedCommand


class SignalduinoController:
    """Orchestrates the connection, command queue and message parsing."""

    def __init__(
        self,
        transport: BaseTransport,
        parser: Optional[SignalParser] = None,
        message_callback: Optional[Callable[[DecodedMessage], None]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.transport = transport
        self.parser = parser or SignalParser()
        self.message_callback = message_callback
        self.logger = logger or logging.getLogger(__name__)

        # NEU: MQTT Publisher initialisieren
        self.mqtt_publisher: Optional[MqttPublisher] = None
        if os.environ.get("MQTT_HOST"):
            # Nur initialisieren, wenn MQTT-Host konfiguriert ist
            self.mqtt_publisher = MqttPublisher(logger=self.logger)
            self.mqtt_publisher.register_command_callback(self._handle_mqtt_command)

        self._reader_thread: Optional[threading.Thread] = None
        self._parser_thread: Optional[threading.Thread] = None
        self._writer_thread: Optional[threading.Thread] = None

        self._stop_event = threading.Event()
        self._raw_message_queue: queue.Queue[str] = queue.Queue()
        self._write_queue: queue.Queue[QueuedCommand] = queue.Queue()
        self._pending_responses: List[PendingResponse] = []
        self._pending_responses_lock = threading.Lock()

    def connect(self) -> None:
        """Opens the transport and starts the worker threads."""
        if self.transport.is_open:
            self.logger.warning("connect() called but transport is already open.")
            return

        try:
            self.transport.open()
            self.logger.info("Transport opened successfully.")
        except SignalduinoConnectionError as e:
            self.logger.error("Failed to open transport: %s", e)
            raise

        self._stop_event.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, name="sd-reader")
        self._reader_thread.start()

        self._parser_thread = threading.Thread(target=self._parser_loop, name="sd-parser")
        self._parser_thread.start()

        self._writer_thread = threading.Thread(target=self._writer_loop, name="sd-writer")
        self._writer_thread.start()

    def disconnect(self) -> None:
        """Stops the worker threads and closes the transport."""
        if not self.transport.is_open:
            self.logger.warning("disconnect() called but transport is not open.")
            return

        self.logger.info("Disconnecting...")
        self._stop_event.set()

        # NEU: MQTT Publisher stoppen
        if self.mqtt_publisher:
            self.mqtt_publisher.stop()

        # Wake up threads that might be waiting on queues
        self._raw_message_queue.put("")
        self._write_queue.put(QueuedCommand("", 0))

        if self._reader_thread:
            self._reader_thread.join(timeout=2)
        if self._parser_thread:
            self._parser_thread.join(timeout=1)
        if self._writer_thread:
            self._writer_thread.join(timeout=1)

        self.transport.close()
        self.logger.info("Transport closed.")

    def _reader_loop(self) -> None:
        """Continuously reads from the transport and puts lines into a queue."""
        self.logger.debug("Reader loop started.")
        while not self._stop_event.is_set():
            try:
                line = self.transport.readline()
                if line:
                    self.logger.debug("RX RAW: %r", line)
                    self._raw_message_queue.put(line)
            except SignalduinoConnectionError as e:
                self.logger.error("Connection error in reader loop: %s", e)
                self._stop_event.set()
            except Exception:
                if not self._stop_event.is_set():
                    self.logger.exception("Unhandled exception in reader loop")
                self._stop_event.wait(0.1)
        self.logger.debug("Reader loop finished.")

    def _parser_loop(self) -> None:
        """Continuously processes raw messages from the queue."""
        self.logger.debug("Parser loop started.")
        while not self._stop_event.is_set():
            try:
                raw_line = self._raw_message_queue.get(timeout=0.1)
                if not raw_line or self._stop_event.is_set():
                    continue

                if self._handle_as_command_response(raw_line.strip()):
                    continue

                decoded_messages = self.parser.parse_line(raw_line)
                for message in decoded_messages:
                    if self.mqtt_publisher:
                        try:
                            self.mqtt_publisher.publish(message)
                        except Exception:
                            self.logger.exception("Error in MQTT publish")

                    if self.message_callback:
                        try:
                            self.message_callback(message)
                        except Exception:
                            self.logger.exception("Error in message callback")
            except queue.Empty:
                continue
            except Exception:
                if not self._stop_event.is_set():
                    self.logger.exception("Unhandled exception in parser loop")
        self.logger.debug("Parser loop finished.")

    def _writer_loop(self) -> None:
        """Continuously processes the write queue."""
        self.logger.debug("Writer loop started.")
        while not self._stop_event.is_set():
            try:
                command = self._write_queue.get(timeout=0.1)
                if not command.payload or self._stop_event.is_set():
                    continue

                self._send_and_wait(command)
            except queue.Empty:
                continue
            except SignalduinoCommandTimeout as e:
                self.logger.warning("Writer loop: %s", e)
            except Exception:
                if not self._stop_event.is_set():
                    self.logger.exception("Unhandled exception in writer loop")
        self.logger.debug("Writer loop finished.")

    def _send_and_wait(self, command: QueuedCommand) -> None:
        """Sends a command and waits for a response if required."""
        if not command.expect_response:
            self.logger.debug("Sending command (fire-and-forget): %s", command.payload)
            self.transport.write_line(command.payload)
            return

        pending = PendingResponse(
            command=command,
            deadline=datetime.now(timezone.utc) + timedelta(seconds=command.timeout),
        )
        with self._pending_responses_lock:
            self._pending_responses.append(pending)

        self.logger.debug("Sending command (expect response): %s", command.payload)
        self.transport.write_line(command.payload)

        try:
            if not pending.event.wait(timeout=command.timeout):
                raise SignalduinoCommandTimeout(
                    f"Command '{command.description or command.payload}' timed out"
                )

            if command.on_response and pending.response:
                command.on_response(pending.response)

        finally:
            with self._pending_responses_lock:
                if pending in self._pending_responses:
                    self._pending_responses.remove(pending)

    def _handle_as_command_response(self, line: str) -> bool:
        """Checks if a line matches any pending command response."""
        with self._pending_responses_lock:
            # Iterate backwards to allow safe removal
            for i in range(len(self._pending_responses) - 1, -1, -1):
                pending = self._pending_responses[i]

                if datetime.now(timezone.utc) > pending.deadline:
                    self.logger.warning("Pending response for '%s' expired.", pending.command.payload)
                    del self._pending_responses[i]
                    continue

                if pending.command.response_pattern and pending.command.response_pattern.search(line):
                    self.logger.debug("Matched response for '%s': %s", pending.command.payload, line)
                    pending.response = line
                    pending.event.set()
                    del self._pending_responses[i]
                    return True
        return False

    def send_raw_command(self, command: str, expect_response: bool = False, timeout: float = 2.0) -> Optional[str]:
        """Queues a raw command and optionally waits for a specific response."""
        return self.send_command(payload=command, expect_response=expect_response, timeout=timeout)

    def set_message_type_enabled(
        self, message_type: Literal["MS", "MU", "MC"], enabled: bool
    ) -> None:
        """Enables or disables a specific message type in the firmware."""
        if message_type not in {"MS", "MU", "MC"}:
            raise ValueError(f"Invalid message type: {message_type}")

        verb = "E" if enabled else "D"
        noun = message_type  # S, U, or C
        command = f"C{verb}{noun}"
        self.send_command(command)

    def _send_cc1101_command(self, command: str, value: Any) -> None:
        """Helper to send a CC1101-specific command."""
        full_command = f"{command}{value}"
        self.send_command(full_command)

    def set_bwidth(self, bwidth: int) -> None:
        """Set the CC1101 bandwidth."""
        self._send_cc1101_command("C10", bwidth)

    def set_rampl(self, rampl: int) -> None:
        """Set the CC1101 rAmpl."""
        self._send_cc1101_command("W1D", rampl)

    def set_sens(self, sens: int) -> None:
        """Set the CC1101 sensitivity."""
        self._send_cc1101_command("W1F", sens)

    def set_patable(self, patable: str) -> None:
        """Set the CC1101 PA table."""
        self._send_cc1101_command("x", patable)

    def set_freq(self, freq: float) -> None:
        """Set the CC1101 frequency."""
        # This is a simplified version. The Perl code has complex logic here.
        command = f"W0F{int(freq):02X}"  # Example, not fully correct
        self.send_command(command)

    def send_message(self, message: str) -> None:
        """Sends a pre-encoded message string."""
        self.send_command(message)

    def send_command(
        self,
        payload: str,
        expect_response: bool = False,
        timeout: float = 2.0,
        response_pattern: Optional[Pattern[str]] = None,
    ) -> Optional[str]:
        """Queues a command and optionally waits for a specific response."""
        if not self.transport.is_open:
            raise SignalduinoConnectionError("Transport is not open.")

        if not expect_response:
            self._write_queue.put(QueuedCommand(payload=payload, timeout=0))
            return None

        response_queue: queue.Queue[str] = queue.Queue()

        def on_response(response: str):
            response_queue.put(response)

        if response_pattern is None:
            response_pattern = re.compile(
                f".*{re.escape(payload)}.*|.*OK.*", re.IGNORECASE
            )

        command = QueuedCommand(
            payload=payload,
            timeout=timeout,
            expect_response=True,
            response_pattern=response_pattern,
            on_response=on_response,
            description=payload,
        )

        self._write_queue.put(command)

        try:
            return response_queue.get(timeout=timeout)
        except queue.Empty:
            # Code Refactor: Distinguish between timeout (slow device) and dead connection.
            # The reader loop will set _stop_event and close the transport on SignalduinoConnectionError
            if self._stop_event.is_set() or not self.transport.is_open:
                self.logger.error(
                    "Command '%s' timed out. Connection appears to be dead (transport closed or worker threads stopping).", payload
                )
                raise SignalduinoConnectionError(
                    f"Command '{payload}' failed: Connection dropped."
                ) from None
            
            # If transport is still open and not stopping, assume it's a slow device/no response
            self.logger.warning(
                "Command '%s' timed out. Transport still appears open. Treating as no response from device.", payload
            )
            raise SignalduinoCommandTimeout(f"Command '{payload}' timed out") from None

    def _handle_mqtt_command(self, command: str, payload: str) -> None:
        """Handles commands received via MQTT."""
        self.logger.info("Handling MQTT command: %s (payload: %s)", command, payload)
        
        if command == "version":
            try:
                # Send 'V' command and wait for response matching version pattern
                # Perl: 'V\s.*SIGNAL(?:duino|ESP|STM).*(?:\s\d\d:\d\d:\d\d)'
                version_pattern = re.compile(
                    r"V\s.*SIGNAL(?:duino|ESP|STM).*", re.IGNORECASE
                )

                try:
                    response = self.send_command(
                        payload="V",
                        expect_response=True,
                        timeout=SDUINO_CMD_TIMEOUT,
                        response_pattern=version_pattern,
                    )
                    self.logger.info("Got version response: %s", response)
                    # Publish result back to MQTT
                    # Topic: signalduino/messages/result/version
                    # We need access to the client to publish ad-hoc messages or add a method to publisher
                    if (
                        self.mqtt_publisher
                        and self.mqtt_publisher.client.is_connected()
                    ):
                        result_topic = (
                            f"{self.mqtt_publisher.mqtt_topic}/result/{command}"
                        )
                        self.mqtt_publisher.client.publish(result_topic, response)

                except SignalduinoCommandTimeout:
                    self.logger.error("Timeout waiting for version response")
                    if (
                        self.mqtt_publisher
                        and self.mqtt_publisher.client.is_connected()
                    ):
                        result_topic = (
                            f"{self.mqtt_publisher.mqtt_topic}/error/{command}"
                        )
                        self.mqtt_publisher.client.publish(result_topic, "Timeout")

            except Exception as e:
                self.logger.error("Error executing version command: %s", e)
        else:
            self.logger.warning("Unknown MQTT command: %s", command)