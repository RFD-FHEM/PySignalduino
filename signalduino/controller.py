import asyncio
import logging
from typing import Callable, Optional

from signalduino.constants import (
    SDUINO_RETRY_INTERVAL,
    SDUINO_INIT_MAXRETRY,
    DEFAULT_FREQUENCY,
    STX,
)
from signalduino.commands import Command
from signalduino.exceptions import SerialConnectionClosedError, SignalduinoCommandTimeout
from signalduino.types import SerialInterface, DecodedMessage
from signalduino.parser import SignalParser

logger = logging.getLogger(__name__)


class InitError(Exception):
    """Custom error for initialization failures."""


class CommandError(Exception):
    """Custom error for command failures."""


class SignalduinoController:
    """
    Manages the connection, communication, and message parsing for a Signalduino
    device.
    """

    def __init__(
        self,
        serial_interface: SerialInterface,
        parser: SignalParser,
        message_callback: Optional[Callable[[DecodedMessage], None]] = None,
    ):
        """
        Initialize the controller.

        :param serial_interface: An instance of SerialInterface for communication.
        :param parser: An instance of SignalParser for handling asynchronous
                       messages.
        :param message_callback: Optional callback function for decoded messages.
        """
        self._serial = serial_interface
        self.parser = parser
        self.message_callback = message_callback
        self._reader_task_handle: asyncio.Task | None = None
        self._command_response_queue: asyncio.Queue = asyncio.Queue()
        self._pending_command_waiter: asyncio.Future | None = None
        self._is_closing = False

    @property
    def is_alive(self) -> bool:
        """Check if the connection is active and the reader task is running."""
        return self._serial.is_connected and not self._is_closing

    async def connect(self):
        """Establish the serial connection and start the reader task."""
        if not self._serial.is_connected:
            await self._serial.connect()

        if self._reader_task_handle is None:
            self._reader_task_handle = asyncio.create_task(self._reader_task())

        # Perform initialization handshake (baud rate, version, frequency)
        await self.initialize()

    async def close(self):
        """Close the serial connection and stop the reader task."""
        if self._is_closing:
            return

        self._is_closing = True
        logger.info("Closing SignalduinoController")

        # Stop reader task
        if self._reader_task_handle:
            self._reader_task_handle.cancel()
            try:
                await self._reader_task_handle
            except asyncio.CancelledError:
                pass
            self._reader_task_handle = None

        # Close serial connection
        await self._serial.close()

    async def initialize(self):
        """
        Perform the initial setup and handshake with the Signalduino device.
        This includes setting the baud rate, retrieving the version, and setting
        the frequency. This method retries on failure.
        """
        max_retry = SDUINO_INIT_MAXRETRY
        retry_count = 0

        while True:
            retry_count += 1
            logger.info("Initializing Signalduino (attempt %d/%d)", retry_count, max_retry)

            try:
                # Set baud rate and retrieve version
                # This also implicitly validates the connection
                version_info = await self.send_command(Command.VERSION())

                # Set initial frequency
                await self.send_command(Command.SET_FREQUENCY(DEFAULT_FREQUENCY))

                # If we reach here, initialization was successful
                logger.info("Signalduino initialized successfully: %s", version_info)
                return version_info

            except TimeoutError as e:
                logger.warning("Signalduino initialization failed (attempt %d/%d): %s",
                               retry_count, max_retry, e)
                if retry_count >= max_retry:
                    logger.error("Maximum initialization retries reached (%d). Aborting.", max_retry)
                    raise InitError(f"Failed to initialize Signalduino after {max_retry} attempts.") from e

            except Exception as e:
                logger.error("Fatal error during Signalduino initialization: %s", e, exc_info=True)
                raise InitError(f"Fatal error during initialization: {e}") from e

            await asyncio.sleep(SDUINO_RETRY_INTERVAL)

    async def _reader_task(self):
        """
        Task that continuously reads lines from the serial port and processes them.
        """
        logger.debug("Starting _reader_task")
        while self.is_alive:
            try:
                line = await self.read_line()
                
                if line is None:
                    # If read_line returns None, it means no data is available right now.
                    # We should wait a bit to avoid tight looping if the transport returns None immediately.
                    await asyncio.sleep(0.001)
                    continue

                line = line.strip()

                if not line:
                    continue

                logger.debug("Received line: %s", line)

                # Check if we are currently waiting for a command response
                # Asynchronous messages start with STX, and must bypass the command response logic.
                if self._pending_command_waiter and not line.startswith(STX):
                    # Signalduino responses are not raw messages, so we put them
                    # into the command response queue.
                    await self._command_response_queue.put(line)
                    continue

                # If not waiting for a command response, this must be an
                # asynchronous message (e.g., sensor data).
                decoded_messages = self.parser.parse_line(line)

                if self.message_callback and decoded_messages:
                    for message in decoded_messages:
                        self.message_callback(message)

            except SerialConnectionClosedError:
                logger.info("_reader_task exiting because connection was closed.")
                break
            except Exception as e:
                logger.error("Error in _reader_task: %s", e, exc_info=True)
                # Add a small sleep to prevent tight looping on continuous errors
                await asyncio.sleep(0.1)
        logger.debug("_reader_task stopped")

    async def read_line(self) -> str | None:
        """Read a single line from the serial port."""
        return await self._serial.read_line()

    async def send_command(self, command: Command) -> str:
        """
        Send a command to the Signalduino and wait for a response.
        """
        if self._pending_command_waiter:
            raise CommandError("A command response is already pending.")

        logger.debug("Sending command: %s", command.name)
        await self._serial.write_line(command.raw_command)

        # Set up a waiter for the response
        self._pending_command_waiter = asyncio.Future()

        try:
            # Wait for a response to arrive in the queue
            response_line = await asyncio.wait_for(
                self._command_response_queue.get(),
                timeout=command.timeout
            )

            # Check for expected success response or explicit error
            if not command.is_success_response(response_line):
                # For commands like 'V', which return version info, the
                # success check is simply that a response was received.
                # For commands like 'XQ', which echo 'XQ' on success, we check.
                if command.expected_response is not None:
                    # If we expected a specific response and got something else,
                    # it's a command failure.
                    logger.error("Command failed: %s. Response: %s", command.name, response_line)
                    raise CommandError(f"Command '{command.name}' failed. Response: {response_line}")

            return response_line

        except asyncio.TimeoutError as e:
            logger.error("Command timeout for %s after %s seconds",
                         command.name, command.timeout)
            raise SignalduinoCommandTimeout(f"Command '{command.name}' timed out") from e

        finally:
            # The command is complete, clear the waiter
            self._pending_command_waiter = None


    async def __aenter__(self):
        """Asynchronous context manager entry method."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Asynchronous context manager exit method."""
        await self.close()