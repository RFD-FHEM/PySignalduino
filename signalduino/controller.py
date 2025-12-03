import json # NEU: Import für JSON-Serialisierung
import logging
import queue
import re
import threading
import os # NEU: Import für Umgebungsvariablen
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Optional, Pattern

from .commands import SignalduinoCommands # NEU: Import für Befehle
from .constants import (
    SDUINO_CMD_TIMEOUT,
    SDUINO_INIT_MAXRETRY,
    SDUINO_INIT_WAIT,
    SDUINO_INIT_WAIT_XQ,
    SDUINO_STATUS_HEARTBEAT_INTERVAL, # NEU: Heartbeat-Konstante
)
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
        self.commands = SignalduinoCommands(self.send_command) # NEU: Befehlsklasse initialisieren
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

        self._heartbeat_timer: Optional[threading.Timer] = None # NEU: Heartbeat Timer initialisieren

        self._stop_event = threading.Event()
        self._raw_message_queue: queue.Queue[str] = queue.Queue()
        self._write_queue: queue.Queue[QueuedCommand] = queue.Queue()
        self._pending_responses: List[PendingResponse] = []
        self._pending_responses_lock = threading.Lock()

        self.init_retry_count = 0
        self.init_reset_flag = False

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
            
        if self._heartbeat_timer: # NEU: Heartbeat Timer stoppen
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None

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

    def initialize(self) -> None:
        """Starts the initialization process."""
        self.logger.info("Initializing device...")
        self.init_retry_count = 0
        self.init_reset_flag = False

        # Schedule Disable Receiver (XQ) and wait briefly
        threading.Timer(SDUINO_INIT_WAIT_XQ, self._send_xq).start()
        
        # Schedule StartInit (Get Version)
        threading.Timer(SDUINO_INIT_WAIT, self._start_init).start()

    def _send_xq(self) -> None:
        try:
            self.logger.debug("Sending XQ to disable receiver during init")
            self.commands.disable_receiver()
        except Exception as e:
            self.logger.warning("Failed to send XQ: %s", e)

    def _start_init(self) -> None:
        self.logger.info("StartInit, get version, retry = %d", self.init_retry_count)

        if self.init_retry_count == 0:
            # First attempt: XQ is sent via a separate timer in initialize(), no blocking wait here.
            pass

        if self.init_retry_count >= SDUINO_INIT_MAXRETRY:
            if not self.init_reset_flag:
                self.logger.warning("StartInit, retry count reached. Resetting device.")
                self.init_reset_flag = True
                self._reset_device()
            else:
                self.logger.error("StartInit, retry count reached after reset. Closing device.")
                self.disconnect()
            return

        response = None
        try:
            # Use commands class for version check
            response = self.commands.get_version(timeout=2.0) # Shorter timeout for retries
        except Exception as e:
            self.logger.debug("StartInit: Exception during version check: %s", e)

        self._check_version_resp(response)

    def _check_version_resp(self, msg: Optional[str]) -> None:
        if msg:
            self.logger.info("Initialized %s", msg.strip())
            self.init_reset_flag = False
            self.init_retry_count = 0
            self.init_version_response = msg # Speichern der Version

            # NEU: Versionsmeldung per MQTT veröffentlichen (Schritt 5)
            if self.mqtt_publisher:
                # Topic: <mqtt_topic>/status/version
                self.mqtt_publisher.publish_simple("status/version", msg.strip(), retain=True)

            # Enable Receiver XE
            try:
                self.logger.info("Enabling receiver (XE)")
                self.commands.enable_receiver()
            except Exception as e:
                self.logger.warning("Failed to enable receiver: %s", e)

            # Check for CC1101
            if "cc1101" in msg.lower():
                self.logger.info("CC1101 detected")
                # Here we could query ccconf and ccpatable like in Perl
            
            # NEU: Starte Heartbeat-Timer
            self._start_heartbeat_timer()

        else:
            self.logger.warning("StartInit: No valid version response.")
            self.init_retry_count += 1
            # Retry initialization
            self._start_init()

    def _reset_device(self) -> None:
        self.logger.info("Resetting device...")
        try:
            self.disconnect()
            # Wait briefly to ensure port is released/device resets
            threading.Event().wait(2.0)
            self.connect()
            self.initialize()
        except Exception as e:
            self.logger.error("Failed to reset device: %s", e)

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

                line_data = raw_line.strip()
                
                if self._handle_as_command_response(line_data):
                    continue

                if line_data.startswith("XQ") or line_data.startswith("XR"):
                    # Abfangen der Receiver-Statusmeldungen XQ/XR (wie in Perl /^XQ/ und /^XR/)
                    self.logger.debug("Found receiver status: %s", line_data)
                    continue

                decoded_messages = self.parser.parse_line(line_data)
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

    def _start_heartbeat_timer(self) -> None:
        """Schedules the periodic status heartbeat."""
        if not self.mqtt_publisher:
            return

        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
        
        self._heartbeat_timer = threading.Timer(
            SDUINO_STATUS_HEARTBEAT_INTERVAL,
            self._publish_status_heartbeat
        )
        self._heartbeat_timer.name = "sd-heartbeat"
        self._heartbeat_timer.start()
        self.logger.info("Heartbeat timer started, interval: %d seconds.", SDUINO_STATUS_HEARTBEAT_INTERVAL)

    def _publish_status_heartbeat(self) -> None:
        """Publishes the current device status."""
        if not self.mqtt_publisher or not self.mqtt_publisher.is_connected():
            self.logger.warning("Cannot publish heartbeat; publisher not connected.")
            self._start_heartbeat_timer() # Try again later
            return
            
        try:
            # 1. Heartbeat/Alive message (Retain: True)
            self.mqtt_publisher.publish_simple("status/alive", "online", retain=True)
            self.logger.debug("Published heartbeat status.")

            # 2. Status data (version, ram, uptime)
            # Fetch data from device (non-blocking call, runs in timer thread)
            status_data = {}
            
            # Version (if not already known from init)
            if self.init_version_response:
                status_data["version"] = self.init_version_response.strip()
            
            # Free RAM
            try:
                ram_resp = self.commands.get_free_ram()
                # Format: R: 1234
                if ":" in ram_resp:
                    status_data["free_ram"] = ram_resp.split(":")[-1].strip()
                else:
                    status_data["free_ram"] = ram_resp.strip()
            except Exception as e:
                self.logger.warning("Could not get free RAM for heartbeat: %s", e)
                status_data["free_ram"] = "error"
                
            # Uptime
            try:
                uptime_resp = self.commands.get_uptime()
                # Format: t: 1234
                if ":" in uptime_resp:
                    status_data["uptime"] = uptime_resp.split(":")[-1].strip()
                else:
                    status_data["uptime"] = uptime_resp.strip()
            except Exception as e:
                self.logger.warning("Could not get uptime for heartbeat: %s", e)
                status_data["uptime"] = "error"
            
            # Publish all collected data to a single status/data topic
            if status_data:
                # Publish as JSON for structured data
                payload = json.dumps(status_data)
                self.mqtt_publisher.publish_simple("status/data", payload)
            
        except Exception as e:
            self.logger.error("Error during status heartbeat: %s", e)

        # Reschedule for next run
        self._start_heartbeat_timer()

    def _handle_mqtt_command(self, command: str, payload: str) -> None:
        """Handles commands received via MQTT."""
        self.logger.info("Handling MQTT command: %s (payload: %s)", command, payload)

        if not self.mqtt_publisher or not self.mqtt_publisher.is_connected():
            self.logger.warning("Cannot handle MQTT command; publisher not connected.")
            return

        command_mapping = {
            "version": self.commands.get_version,
            "help": self.commands.get_help,
            "free_ram": self.commands.get_free_ram,
            "uptime": self.commands.get_uptime,
        }

        if command in command_mapping:
            try:
                # Execute the corresponding command method
                response = command_mapping[command]()
                
                self.logger.info("Got response for %s: %s", command, response)
                
                # Publish result back to MQTT
                # Topic: <mqtt_topic>/result/<command>
                self.mqtt_publisher.publish_simple(f"result/{command}", response)

            except SignalduinoCommandTimeout:
                self.logger.error("Timeout waiting for command response: %s", command)
                self.mqtt_publisher.publish_simple(f"error/{command}", "Timeout")
                
            except Exception as e:
                self.logger.error("Error executing command %s: %s", command, e)
                self.mqtt_publisher.publish_simple(f"error/{command}", f"Error: {e}")

        else:
            self.logger.warning("Unknown MQTT command: %s", command)
            self.mqtt_publisher.publish_simple(f"error/{command}", "Unknown command")