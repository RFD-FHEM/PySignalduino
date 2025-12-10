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
)

# threading, queue, time entfernt
from .commands import SignalduinoCommands
from .constants import (
    SDUINO_CMD_TIMEOUT,
    SDUINO_INIT_MAXRETRY,
    SDUINO_INIT_WAIT,
    SDUINO_INIT_WAIT_XQ,
    SDUINO_STATUS_HEARTBEAT_INTERVAL,
)
from .exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError
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
        # send_command muss jetzt async sein
        self.commands = SignalduinoCommands(self.send_command)
        self.parser = parser or SignalParser()
        self.message_callback = message_callback
        self.logger = logger or logging.getLogger(__name__)

        self.mqtt_publisher: Optional[MqttPublisher] = None
        if os.environ.get("MQTT_HOST"):
            self.mqtt_publisher = MqttPublisher(logger=self.logger)
            # handle_mqtt_command muss jetzt async sein
            self.mqtt_publisher.register_command_callback(self._handle_mqtt_command)

        # Ersetze threading-Objekte durch asyncio-Äquivalente
        self._stop_event = asyncio.Event()
        self._raw_message_queue: asyncio.Queue[str] = asyncio.Queue()
        self._write_queue: asyncio.Queue[QueuedCommand] = asyncio.Queue()
        self._pending_responses: List[PendingResponse] = []
        self._pending_responses_lock = asyncio.Lock()

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
        self.logger.info("Entering SignalduinoController async context.")
        
        # 1. Transport öffnen (Nutzt den aenter des Transports)
        # NEU: Transport muss als Kontextmanager verwendet werden
        if self.transport:
            await self.transport.__aenter__()

        # 2. MQTT starten
        if self.mqtt_publisher:
            # Nutzt den aenter des MqttPublishers
            await self.mqtt_publisher.__aenter__()
            self.logger.info("MQTT publisher started.")
            
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        """Stops all tasks, closes transport and MQTT connection."""
        self.logger.info("Exiting SignalduinoController async context.")
        
        # 1. Stopp-Event setzen und alle Tasks abbrechen
        self._stop_event.set()
        
        # Tasks abbrechen (Heartbeat, Init-Tasks, etc.)
        tasks_to_cancel = [
            self._heartbeat_task,
            self._init_task_xq,
            self._init_task_start,
        ]
        
        # Haupt-Tasks abbrechen (Reader, Parser, Writer)
        # Wir warten nicht auf den Parser/Writer, da sie mit der Queue arbeiten.
        # Wir müssen nur die Task-Handles abbrechen, da run() bereits auf die kritischen gewartet hat.
        tasks_to_cancel.extend(self._main_tasks)

        for task in tasks_to_cancel:
            if task and not task.done():
                self.logger.debug("Cancelling task: %s", task.get_name())
                task.cancel()

        # Warte auf das Ende aller Tasks, ignoriere CancelledError
        # Füge einen kurzen Timeout hinzu, um zu verhindern, dass es unbegrenzt blockiert
        # Wir sammeln die Futures und warten darauf mit einem Timeout
        tasks = [t for t in tasks_to_cancel if t is not None and not t.done()]
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2.0)
            except asyncio.TimeoutError:
                self.logger.warning("Timeout waiting for controller tasks to finish.")
            
        self.logger.debug("All controller tasks cancelled.")

        # 2. Transport und MQTT schließen (Nutzt die aexit der Komponenten)
        if self.transport:
            # transport.__aexit__ aufrufen
            await self.transport.__aexit__(exc_type, exc_val, exc_tb)
            
        if self.mqtt_publisher:
            # mqtt_publisher.__aexit__ aufrufen
            await self.mqtt_publisher.__aexit__(exc_type, exc_val, exc_tb)

        # Lasse nur CancelledError und ConnectionError zu
        if exc_type and not issubclass(exc_type, (asyncio.CancelledError, SignalduinoConnectionError)):
            self.logger.error("Exception occurred in async context: %s: %s", exc_type.__name__, exc_val)
            # Rückgabe False, um die Exception weiterzuleiten
            return False 
        
        return None # Unterdrücke die Exception (CancelledError/ConnectionError sind erwartet/ok)


    async def initialize(self) -> None:
        """Starts the initialization process."""
        self.logger.info("Initializing device...")
        self.init_retry_count = 0
        self.init_reset_flag = False

        if self._stop_event.is_set():
            self.logger.warning("initialize called but stop event is set.")
            return

        # Plane Disable Receiver (XQ) und warte kurz
        if self._init_task_xq and not self._init_task_xq.done():
            self._init_task_xq.cancel()
        # Verwende asyncio.create_task für verzögerte Ausführung
        self._init_task_xq = asyncio.create_task(self._delay_and_send_xq())
        self._init_task_xq.set_name("sd-init-xq")
        
        # Plane StartInit (Get Version)
        if self._init_task_start and not self._init_task_start.done():
            self._init_task_start.cancel()
        self._init_task_start = asyncio.create_task(self._delay_and_start_init())
        self._init_task_start.set_name("sd-init-start")
        
    async def _delay_and_send_xq(self) -> None:
        """Helper to delay before sending XQ."""
        try:
            await asyncio.sleep(SDUINO_INIT_WAIT_XQ)
            await self._send_xq()
        except asyncio.CancelledError:
            self.logger.debug("_delay_and_send_xq cancelled.")
        except Exception as e:
            self.logger.exception("Error in _delay_and_send_xq: %s", e)

    async def _delay_and_start_init(self) -> None:
        """Helper to delay before starting init."""
        try:
            await asyncio.sleep(SDUINO_INIT_WAIT)
            await self._start_init()
        except asyncio.CancelledError:
            self.logger.debug("_delay_and_start_init cancelled.")
        except Exception as e:
            self.logger.exception("Error in _delay_and_start_init: %s", e)

    async def _send_xq(self) -> None:
        """Sends XQ command."""
        if self._stop_event.is_set():
            return
        try:
            self.logger.debug("Sending XQ to disable receiver during init")
            # commands.disable_receiver ist jetzt ein awaitable
            await self.commands.disable_receiver()
        except Exception as e:
            self.logger.warning("Failed to send XQ: %s", e)

    async def _start_init(self) -> None:
        """Attempts to get the device version to confirm initialization."""
        if self._stop_event.is_set():
            return

        self.logger.info("StartInit, get version, retry = %d", self.init_retry_count)

        if self.init_retry_count >= SDUINO_INIT_MAXRETRY:
            if not self.init_reset_flag:
                self.logger.warning("StartInit, retry count reached. Resetting device.")
                self.init_reset_flag = True
                await self._reset_device()
            else:
                self.logger.error("StartInit, retry count reached after reset. Stopping controller.")
                self._stop_event.set() # Setze Stopp-Event, aexit wird das Schließen übernehmen
            return

        response: Optional[str] = None
        try:
            # commands.get_version ist jetzt ein awaitable
            response = await self.commands.get_version(timeout=2.0)
        except Exception as e:
            self.logger.debug("StartInit: Exception during version check: %s", e)

        await self._check_version_resp(response)

    async def _check_version_resp(self, msg: Optional[str]) -> None:
        """Handles the response from the version command."""
        if self._stop_event.is_set():
            return

        if msg:
            self.logger.info("Initialized %s", msg.strip())
            self.init_reset_flag = False
            self.init_retry_count = 0
            self.init_version_response = msg

            # NEU: Versionsmeldung per MQTT veröffentlichen
            if self.mqtt_publisher:
                # publish_simple ist jetzt awaitable
                await self.mqtt_publisher.publish_simple("status/version", msg.strip(), retain=True)

            # Enable Receiver XE
            try:
                self.logger.info("Enabling receiver (XE)")
                # commands.enable_receiver ist jetzt ein awaitable
                await self.commands.enable_receiver()
            except Exception as e:
                self.logger.warning("Failed to enable receiver: %s", e)

            # Check for CC1101
            if "cc1101" in msg.lower():
                self.logger.info("CC1101 detected")
            
            # NEU: Starte Heartbeat-Task
            await self._start_heartbeat_task()

        else:
            self.logger.warning("StartInit: No valid version response.")
            self.init_retry_count += 1
            # Initialisierung wiederholen
            # Verzögere den Aufruf, um eine Busy-Loop bei Verbindungsfehlern zu vermeiden
            await asyncio.sleep(1.0) 
            await self._start_init()

    async def _reset_device(self) -> None:
        """Resets the device by closing and reopening the transport."""
        self.logger.info("Resetting device...")
        # Nutze aexit/aenter Logik, um die Verbindung zu schließen/wiederherzustellen
        await self.__aexit__(None, None, None) # Schließt Transport und stoppt Tasks/Publisher
        # Kurze Pause für den Reset
        await asyncio.sleep(2.0)
        # NEU: Der Controller ist neu gestartet und muss wieder in den async Kontext eintreten
        await self.__aenter__()

        # Manuell die Initialisierung starten
        try:
            await self._send_xq()
            await self._start_init()
        except Exception as e:
            self.logger.error("Failed to re-initialize device after reset: %s", e)
            self._stop_event.set()

    async def _reader_task(self) -> None:
        """Continuously reads from the transport and puts lines into a queue."""
        self.logger.debug("Reader task started.")
        while not self._stop_event.is_set():
            try:
                # Nutze await für die asynchrone Transport-Leseoperation
                # Setze ein Timeout, um CancelledError zu erhalten, falls nötig, und um andere Events zu ermöglichen
                line = await asyncio.wait_for(self.transport.readline(), timeout=0.1)
                
                if line:
                    self.logger.debug("RX RAW: %r", line)
                    await self._raw_message_queue.put(line)
            except asyncio.TimeoutError:
                continue # Queue ist leer, Schleife fortsetzen
            except SignalduinoConnectionError as e:
                # Im Falle eines Verbindungsfehlers das Stopp-Event setzen und die Schleife beenden.
                self.logger.error("Connection error in reader task: %s", e)
                self._stop_event.set()
                break # Schleife verlassen
            except asyncio.CancelledError:
                break # Bei Abbruch beenden
            except Exception:
                if not self._stop_event.is_set():
                    self.logger.exception("Unhandled exception in reader task")
                # Kurze Pause, um eine Endlosschleife zu vermeiden
                await asyncio.sleep(0.1) 
        self.logger.debug("Reader task finished.")

    async def _parser_task(self) -> None:
        """Continuously processes raw messages from the queue."""
        self.logger.debug("Parser task started.")
        while not self._stop_event.is_set():
            try:
                # Nutze await für das asynchrone Lesen aus der Queue
                raw_line = await asyncio.wait_for(self._raw_message_queue.get(), timeout=0.1)
                self._raw_message_queue.task_done() # Wichtig für asyncio.Queue
                
                if self._stop_event.is_set():
                    continue

                line_data = raw_line.strip()
                
                # Nachrichten, die mit \x02 (STX) beginnen, sind Sensordaten und sollten nie als Kommandoantworten behandelt werden.
                if line_data.startswith("\x02"):
                    pass # Gehe direkt zum Parsen
                elif await self._handle_as_command_response(line_data): # _handle_as_command_response muss async sein
                    continue

                if line_data.startswith("XQ") or line_data.startswith("XR"):
                    # Abfangen der Receiver-Statusmeldungen XQ/XR
                    self.logger.debug("Found receiver status: %s", line_data)
                    continue

                decoded_messages = self.parser.parse_line(line_data)
                for message in decoded_messages:
                    if self.mqtt_publisher:
                        try:
                            # publish ist jetzt awaitable
                            await self.mqtt_publisher.publish(message)
                        except Exception:
                            self.logger.exception("Error in MQTT publish")

                    if self.message_callback:
                        try:
                            # message_callback ist jetzt awaitable
                            await self.message_callback(message)
                        except Exception:
                            self.logger.exception("Error in message callback")

            except asyncio.TimeoutError:
                continue # Queue ist leer, Schleife fortsetzen
            except asyncio.CancelledError:
                break # Bei Abbruch beenden
            except Exception:
                if not self._stop_event.is_set():
                    self.logger.exception("Unhandled exception in parser task")
        self.logger.debug("Parser task finished.")

    async def _writer_task(self) -> None:
        """Continuously processes the write queue."""
        self.logger.debug("Writer task started.")
        while not self._stop_event.is_set():
            try:
                # Nutze await für das asynchrone Lesen aus der Queue
                command = await asyncio.wait_for(self._write_queue.get(), timeout=0.1)
                self._write_queue.task_done()
                
                if not command.payload or self._stop_event.is_set():
                    continue

                await self._send_and_wait(command)
            except asyncio.TimeoutError:
                continue # Queue ist leer, Schleife fortsetzen
            except asyncio.CancelledError:
                break # Bei Abbruch beenden
            except SignalduinoCommandTimeout as e:
                self.logger.warning("Writer task: %s", e)
            except Exception:
                if not self._stop_event.is_set():
                    self.logger.exception("Unhandled exception in writer task")
        self.logger.debug("Writer task finished.")

    async def _send_and_wait(self, command: QueuedCommand) -> None:
        """Sends a command and waits for a response if required."""
        if not command.expect_response:
            self.logger.debug("Sending command (fire-and-forget): %s", command.payload)
            # transport.write_line ist jetzt awaitable
            await self.transport.write_line(command.payload)
            return

        pending = PendingResponse(
            command=command,
            event=asyncio.Event(), # Füge ein asyncio.Event hinzu
            deadline=datetime.now(timezone.utc) + timedelta(seconds=command.timeout),
            response=None
        )
        # Nutze asyncio.Lock für asynchrone Sperren
        async with self._pending_responses_lock:
            self._pending_responses.append(pending)

        self.logger.debug("Sending command (expect response): %s", command.payload)
        await self.transport.write_line(command.payload)

        try:
            # Warte auf das Event mit Timeout
            await asyncio.wait_for(pending.event.wait(), timeout=command.timeout)

            if command.on_response and pending.response:
                # on_response ist ein synchrones Callable und kann direkt aufgerufen werden
                command.on_response(pending.response)

        except asyncio.TimeoutError:
            raise SignalduinoCommandTimeout(
                f"Command '{command.description or command.payload}' timed out"
            ) from None
        finally:
            async with self._pending_responses_lock:
                if pending in self._pending_responses:
                    self._pending_responses.remove(pending)

    async def _handle_as_command_response(self, line: str) -> bool:
        """Checks if a line matches any pending command response."""
        # Nutze asyncio.Lock
        async with self._pending_responses_lock:
            # Iteriere rückwärts, um sicheres Entfernen zu ermöglichen
            for i in range(len(self._pending_responses) - 1, -1, -1):
                pending = self._pending_responses[i]

                if datetime.now(timezone.utc) > pending.deadline:
                    self.logger.warning("Pending response for '%s' expired.", pending.command.payload)
                    del self._pending_responses[i]
                    continue

                if pending.command.response_pattern and pending.command.response_pattern.search(line):
                    self.logger.debug("Matched response for '%s': %s", pending.command.payload, line)
                    pending.response = line
                    # Setze das asyncio.Event
                    pending.event.set()
                    del self._pending_responses[i]
                    return True
        return False

    async def send_raw_command(self, command: str, expect_response: bool = False, timeout: float = 2.0) -> Optional[str]:
        """Queues a raw command and optionally waits for a specific response."""
        # send_command ist jetzt awaitable
        return await self.send_command(payload=command, expect_response=expect_response, timeout=timeout)

    async def send_command(
        self,
        payload: str,
        expect_response: bool = False,
        timeout: float = 2.0,
        response_pattern: Optional[Pattern[str]] = None,
    ) -> Optional[str]:
        """Queues a command and optionally waits for a specific response."""
        
        if not expect_response:
            # Nutze await für asynchrone Queue-Operation
            await self._write_queue.put(QueuedCommand(payload=payload, timeout=0))
            return None

        # NEU: Verwende asyncio.Future anstelle einer threading.Queue
        response_future: asyncio.Future[str] = asyncio.Future()

        def on_response(response: str):
            # Prüfe, ob das Future nicht bereits abgeschlossen ist (z.B. durch Timeout im Caller)
            if not response_future.done():
                response_future.set_result(response)

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

        await self._write_queue.put(command)

        try:
            # Warte auf das Future mit Timeout
            return await asyncio.wait_for(response_future, timeout=timeout)
        except asyncio.TimeoutError:
            # Code Refactor: Timeout vs. dead connection
            if self._stop_event.is_set():
                self.logger.error(
                    "Command '%s' timed out. Connection appears to be dead (controller stopping).", payload
                )
                raise SignalduinoConnectionError(
                    f"Command '{payload}' failed: Connection dropped."
                ) from None
            
            # Annahme: Transport-API wirft SignalduinoConnectionError bei Trennung.
            # Wenn dies nicht der Fall ist, wird ein Timeout angenommen.
            self.logger.warning(
                "Command '%s' timed out. Treating as no response from device.", payload
            )
            raise SignalduinoCommandTimeout(f"Command '{payload}' timed out") from None

    async def _start_heartbeat_task(self) -> None:
        """Schedules the periodic status heartbeat task."""
        if not self.mqtt_publisher:
            return

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._heartbeat_task.set_name("sd-heartbeat")
        self.logger.info("Heartbeat task started, interval: %d seconds.", SDUINO_STATUS_HEARTBEAT_INTERVAL)

    async def _heartbeat_loop(self) -> None:
        """The main loop for the periodic status heartbeat."""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(SDUINO_STATUS_HEARTBEAT_INTERVAL)
                await self._publish_status_heartbeat()
        except asyncio.CancelledError:
            self.logger.debug("Heartbeat loop cancelled.")
        except Exception as e:
            self.logger.exception("Unhandled exception in heartbeat loop: %s", e)
            
    async def _publish_status_heartbeat(self) -> None:
        """Publishes the current device status."""
        if not self.mqtt_publisher or not await self.mqtt_publisher.is_connected():
            self.logger.warning("Cannot publish heartbeat; publisher not connected.")
            return
            
        try:
            # 1. Heartbeat/Alive message (Retain: True)
            await self.mqtt_publisher.publish_simple("status/alive", "online", retain=True)
            self.logger.info("Heartbeat executed. Status: alive")

            # 2. Status data (version, ram, uptime)
            status_data = {}
            
            # Version
            if self.init_version_response:
                status_data["version"] = self.init_version_response.strip()
            
            # Free RAM
            try:
                # commands.get_free_ram ist awaitable
                ram_resp = await self.commands.get_free_ram()
                # Format: R: 1234
                if ":" in ram_resp:
                    status_data["free_ram"] = ram_resp.split(":")[-1].strip()
                else:
                    status_data["free_ram"] = ram_resp.strip()
            except SignalduinoConnectionError:
                 # Bei Verbindungsfehler: Controller anweisen zu stoppen/neu zu verbinden
                self.logger.error(
                    "Heartbeat failed: Connection dropped during get_free_ram. Triggering stop."
                )
                self._stop_event.set() # Stopp-Event setzen, aexit wird das Schließen übernehmen
                return
            except Exception as e:
                self.logger.warning("Could not get free RAM for heartbeat: %s", e)
                status_data["free_ram"] = "error"
                
            # Uptime
            try:
                # commands.get_uptime ist awaitable
                uptime_resp = await self.commands.get_uptime()
                # Format: t: 1234
                if ":" in uptime_resp:
                    status_data["uptime"] = uptime_resp.split(":")[-1].strip()
                else:
                    status_data["uptime"] = uptime_resp.strip()
            except SignalduinoConnectionError:
                self.logger.error(
                    "Heartbeat failed: Connection dropped during get_uptime. Triggering stop."
                )
                self._stop_event.set() # Stopp-Event setzen, aexit wird das Schließen übernehmen
                return
            except Exception as e:
                self.logger.warning("Could not get uptime for heartbeat: %s", e)
                status_data["uptime"] = "error"
            
            # Publish all collected data
            if status_data:
                payload = json.dumps(status_data)
                await self.mqtt_publisher.publish_simple("status/data", payload)
            
        except Exception as e:
            self.logger.error("Error during status heartbeat: %s", e)

    async def _handle_mqtt_command(self, command: str, payload: str) -> None:
        """Handles commands received via MQTT."""
        self.logger.info("Handling MQTT command: %s (payload: %s)", command, payload)

        if not self.mqtt_publisher or not await self.mqtt_publisher.is_connected():
            self.logger.warning("Cannot handle MQTT command; publisher not connected.")
            return

        # Mapping von MQTT-Befehl zu einer async-Methode (ohne Args) oder einer Lambda-Funktion (mit Args)
        # Alle Methoden sind jetzt awaitables
        command_mapping = {
            "version": self.commands.get_version,
            "freeram": self.commands.get_free_ram,
            "uptime": self.commands.get_uptime,
            "cmds": self.commands.get_cmds,
            "ping": self.commands.ping,
            "config": self.commands.get_config,
            "ccconf": self.commands.get_ccconf,
            "ccpatable": self.commands.get_ccpatable,
            # lambda muss jetzt awaitables zurückgeben
            "ccreg": lambda p: self.commands.read_cc1101_register(int(p, 16)),
            "rawmsg": lambda p: self.commands.send_raw_message(p),
        }

        if command == "help":
            self.logger.warning("Ignoring deprecated 'help' MQTT command (use 'cmds').")
            await self.mqtt_publisher.publish_simple(f"error/{command}", "Deprecated command. Use 'cmds'.")
            return
        
        if command in command_mapping:
            response: Optional[str] = None
            try:
                # Execute the corresponding command method
                cmd_func = command_mapping[command]
                if command in ["ccreg", "rawmsg"]:
                    if not payload:
                        self.logger.error("Command '%s' requires a payload argument.", command)
                        await self.mqtt_publisher.publish_simple(f"error/{command}", "Missing payload argument.")
                        return
                    
                    # Die lambda-Funktion gibt ein awaitable zurück, das ausgeführt werden muss
                    awaitable_response = cmd_func(payload)
                    response = await awaitable_response
                else:
                    # Die Methode ist ein awaitable, das ausgeführt werden muss
                    response = await cmd_func()
                
                self.logger.info("Got response for %s: %s", command, response)
                
                # Publish result back to MQTT
                # Wir stellen sicher, dass die Antwort ein String ist, da die Befehlsmethoden str zurückgeben sollen.
                # Sollte nur ein Problem sein, wenn die Command-Methode None zurückgibt (was sie nicht sollte).
                response_str = str(response) if response is not None else "OK"
                await self.mqtt_publisher.publish_simple(f"result/{command}", response_str)

            except SignalduinoCommandTimeout:
                self.logger.error("Timeout waiting for command response: %s", command)
                await self.mqtt_publisher.publish_simple(f"error/{command}", "Timeout")
                
            except Exception as e:
                self.logger.error("Error executing command %s: %s", command, e)
                await self.mqtt_publisher.publish_simple(f"error/{command}", f"Error: {e}")

        else:
            self.logger.warning("Unknown MQTT command: %s", command)
            await self.mqtt_publisher.publish_simple(f"error/{command}", "Unknown command")


    async def run(self, timeout: Optional[float] = None) -> None:
        """
        Starts the main asynchronous tasks (reader, parser, writer) 
        and waits for them to complete or for a connection loss.
        """
        self.logger.info("Starting main controller tasks...")

        # 1. Initialisierung starten (führt Versionsprüfung durch und startet Heartbeat)
        await self.initialize()

        # 2. Haupt-Tasks erstellen und starten
        reader_task = asyncio.create_task(self._reader_task(), name="sd-reader")
        parser_task = asyncio.create_task(self._parser_task(), name="sd-parser")
        writer_task = asyncio.create_task(self._writer_task(), name="sd-writer")
        
        self._main_tasks = [reader_task, parser_task, writer_task]

        # 3. Auf eine der Haupt-Tasks warten (Reader/Writer werden bei Verbindungsabbruch beendet)
        # Parser sollte weiterlaufen, bis die Queue leer ist. Reader/Writer sind die kritischen Tasks.
        critical_tasks = [reader_task, writer_task]

        # Führe ein Wait mit optionalem Timeout aus, das mit `asyncio.wait_for` implementiert wird
        if timeout is not None:
            try:
                # Warten auf die kritischen Tasks, bis sie fertig sind oder ein Timeout eintritt
                done, pending = await asyncio.wait_for(
                    asyncio.wait(critical_tasks, return_when=asyncio.FIRST_COMPLETED),
                    timeout=timeout
                )
                self.logger.info("Run finished due to timeout or task completion.")

            except asyncio.TimeoutError:
                self.logger.info("Run finished due to timeout (%s seconds).", timeout)
                # Das aexit wird sich um das Aufräumen kümmern
            
        else:
            # Warten, bis eine der kritischen Tasks abgeschlossen ist
            done, pending = await asyncio.wait(
                critical_tasks,
                return_when=asyncio.FIRST_COMPLETED
            )
            # Wenn ein Task unerwartet beendet wird (z.B. durch Fehler), sollte er in `done` sein.
            # Wenn das Stopp-Event nicht gesetzt ist, war es ein Fehler.
            if any(t.exception() for t in done) and not self._stop_event.is_set():
                self.logger.error("A critical controller task finished with an exception.")

        # Das aexit im async with Block wird sich um das Aufräumen kümmern
        # (Schließen des Transports, Abbrechen aller Tasks).